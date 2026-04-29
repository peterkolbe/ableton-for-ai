import json
import sys
from pathlib import Path

import librosa
import librosa.display
import matplotlib

matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
import numpy as np
import threading
import pyloudnorm as pyln
import config_utils as config

# Global lock for Matplotlib as it's not thread-safe even with the OO-API 
# if librosa.display calls internal pyplot state functions.
matplotlib_lock = threading.Lock()


def log_debug(message: str):
  """Prints debug messages to stderr if LOG_LEVEL is DEBUG."""
  if config.LOG_LEVEL == "DEBUG":
    print(f"[DEBUG] {message}", file=sys.stderr, flush=True)


def log_info(message: str):
  """Prints info messages to stderr."""
  print(f"[INFO] {message}", file=sys.stderr, flush=True)


def log_error(message: str):
  """Prints error messages to stderr."""
  print(f"[ERROR] {message}", file=sys.stderr, flush=True)


def _detect_transients(y, sr):
  """Internal helper to detect transients (onsets) and their peak level."""
  # Use librosa's onset detection
  onset_frames = librosa.onset.onset_detect(y=y, sr=sr, hop_length=512)
  onsets_time = librosa.frames_to_time(onset_frames, sr=sr, hop_length=512)
  
  transients = []
  for t in onsets_time:
    start_sample = int(t * sr)
    # Search peak in a 50ms window
    end_sample = min(len(y), start_sample + int(0.05 * sr))
    if start_sample < len(y):
      window = y[start_sample:end_sample]
      if len(window) > 0:
        peak = np.max(np.abs(window))
        peak_db = 20 * np.log10(peak + 1e-12)
        transients.append({
          "t": round(float(t), 3),
          "d": 0.05, # Fixed duration for now
          "p": round(float(peak_db), 1)
        })
  return transients


def _process_spectrogram(magnitude, sr, hop_length, audio_path, output_path):
  """Internal helper to create spectrogram from magnitude."""
  db = librosa.amplitude_to_db(magnitude, ref=np.max, top_db=80)

  with matplotlib_lock:
    # Use object-oriented matplotlib for thread-safety
    # figsize=(13.33, 6.66) with dpi=120 gives 1600x800, good for LLM consumption
    fig = Figure(figsize=(13.33, 6.66))
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)

    img = librosa.display.specshow(
      db,
      sr=sr,
      hop_length=hop_length,
      x_axis="time",
      y_axis="log",
      fmax=20000,
      ax=ax
    )
    fig.colorbar(img, ax=ax, format="%+2.0f dB")
    ax.set_title(f"Spectrogram: {audio_path.name}")
    fig.tight_layout()
    
    # Save as WebP for efficiency (stays under 1MB for MCP)
    if str(output_path).endswith(".png"):
        output_path = str(output_path).replace(".png", ".webp")
        
    fig.savefig(output_path, format="webp", dpi=120, bbox_inches="tight", pil_kwargs={'quality': config.SPECTROGRAM_QUALITY, 'optimize': True})

    # Cleanup
    fig.clf()
    del fig

  return str(output_path)


def _process_band_energy(magnitude, sr, n_fft, hop_length, audio_path, output_json, global_metrics=None, y=None, summary_only=False):
  """Internal helper to compute band energy from magnitude and other frame-level metrics."""
  power = magnitude ** 2
  freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
  times = librosa.frames_to_time(np.arange(power.shape[1]), sr=sr, hop_length=hop_length)

  # Prepare additional frame-level metrics if y is provided
  rms_frames = None
  peak_frames = None
  corr_frames = None
  lufs_mom_frames = None
  lufs_st_frames = None

  if y is not None:
    # Convert stereo to mono for RMS/Peak if needed, or use overall max/mean
    y_mono = librosa.to_mono(y) if y.ndim > 1 else y
    
    # RMS (dB)
    rms = librosa.feature.rms(y=y_mono, frame_length=n_fft, hop_length=hop_length)[0]
    rms_frames = 20 * np.log10(rms + 1e-12)
    
    # Peak (dB)
    # Using librosa.util.frame to get windows for peak calculation
    y_padded = np.pad(y_mono, n_fft // 2, mode='reflect')
    peak_windows = librosa.util.frame(y_padded, frame_length=n_fft, hop_length=hop_length)
    peak_frames = 20 * np.log10(np.max(np.abs(peak_windows), axis=0) + 1e-12)

    # Stereo Correlation
    if y.ndim > 1 and y.shape[0] == 2:
      y_padded_l = np.pad(y[0], n_fft // 2, mode='reflect')
      y_padded_r = np.pad(y[1], n_fft // 2, mode='reflect')
      frames_l = librosa.util.frame(y_padded_l, frame_length=n_fft, hop_length=hop_length)
      frames_r = librosa.util.frame(y_padded_r, frame_length=n_fft, hop_length=hop_length)
      
      corr_frames = np.ones(frames_l.shape[1])
      # Compute correlation for each frame
      for i in range(frames_l.shape[1]):
        if np.max(np.abs(frames_l[:, i])) > 1e-8 or np.max(np.abs(frames_r[:, i])) > 1e-8:
          c = np.corrcoef(frames_l[:, i], frames_r[:, i])[0, 1]
          if not np.isnan(c):
            corr_frames[i] = c

    # Momentary and Short-term LUFS
    try:
      meter_mom = pyln.Meter(sr, block_size=0.4) # Momentary
      meter_st = pyln.Meter(sr, block_size=3.0) # Short-term
      
      y_ln = y.T if y.ndim > 1 else y[:, np.newaxis]
      
      # For Momentary
      _ = meter_mom.integrated_loudness(y_ln)
      block_lufs_mom = np.array(meter_mom.blockwise_loudness)
      if len(block_lufs_mom) > 0:
        block_times_mom = np.arange(len(block_lufs_mom)) * 0.1 + 0.2
        lufs_mom_frames = np.interp(times, block_times_mom, block_lufs_mom, left=block_lufs_mom[0], right=block_lufs_mom[-1])
        
      # For Short-term
      _ = meter_st.integrated_loudness(y_ln)
      block_lufs_st = np.array(meter_st.blockwise_loudness)
      if len(block_lufs_st) > 0:
        # Step size for short-term is also 0.1s in pyloudnorm, but window is 3s
        # Window center is at 1.5s
        block_times_st = np.arange(len(block_lufs_st)) * 0.1 + 1.5
        lufs_st_frames = np.interp(times, block_times_st, block_lufs_st, left=block_lufs_st[0], right=block_lufs_st[-1])
    except Exception:
      pass

  bands = {
    "sub": (20, 60),
    "bass": (60, 120),
    "low_mid": (120, 400),
    "mid": (400, 2000),
    "presence": (2000, 6000),
    "high": (6000, 12000),
    "air": (12000, 20000),
  }

  def band_mask(lo, hi):
    return (freqs >= lo) & (freqs < hi)

  masks = {name: band_mask(lo, hi) for name, (lo, hi) in bands.items()}

  frames = []
  for t_idx, t in enumerate(times):
    if summary_only:
      # Ultra-compact representation for summary
      # Round time to 3 decimals, values to 1 decimal
      row = {
        "t": round(float(t), 3),
        # Band energy as a list to save keys: sub, bass, low_mid, mid, presence, high, air
        "e": [round(float(10 * np.log10(max(power[masks[name], t_idx].sum(), 1e-12))), 1) for name in bands],
        "r": round(float(rms_frames[t_idx]), 1) if rms_frames is not None else None,
        "p": round(float(peak_frames[t_idx]), 1) if peak_frames is not None else None,
        "lm": round(float(lufs_mom_frames[t_idx]), 1) if lufs_mom_frames is not None else None,
        "ls": round(float(lufs_st_frames[t_idx]), 1) if lufs_st_frames is not None else None,
        "sc": round(float(corr_frames[t_idx]), 2) if corr_frames is not None else None
      }
    else:
      row = {"time": float(t)}
      # Add band energy
      for band_name, mask in masks.items():
        band_power = power[mask, t_idx].sum()
        band_db = 10 * np.log10(max(band_power, 1e-12))
        row[f"{band_name}_db"] = float(band_db)
      
      # Add additional metrics if available
      if rms_frames is not None:
        row["rms_db"] = float(rms_frames[t_idx])
      if peak_frames is not None:
        row["peak_db"] = float(peak_frames[t_idx])
      if corr_frames is not None:
        row["stereo_correlation"] = float(corr_frames[t_idx])
      if lufs_mom_frames is not None:
        row["lufs_momentary"] = float(lufs_mom_frames[t_idx])
      if lufs_st_frames is not None:
        row["lufs_shortterm"] = float(lufs_st_frames[t_idx])
      if rms_frames is not None and peak_frames is not None:
        row["crest_factor"] = float(peak_frames[t_idx] - rms_frames[t_idx])

    frames.append(row)

  transients = []
  if y is not None:
    transients = _detect_transients(y_mono if y.ndim > 1 else y, sr)

  payload = {
    "stem": audio_path.name,
    "sample_rate": int(sr),
    "n_fft": n_fft,
    "hop_length": hop_length,
    "global_metrics": global_metrics,
    "bands": bands if not summary_only else list(bands.keys()),
    "transients": transients,
    "frames": frames,
  }

  if summary_only:
    payload["legend"] = {
      "t": "time (seconds)",
      "e": "band energy list (sub, bass, low_mid, mid, presence, high, air)",
      "r": "RMS (dB)",
      "p": "Peak (dB)",
      "lm": "LUFS momentary",
      "ls": "LUFS short-term",
      "sc": "Stereo correlation"
    }
    # Check if we need to split based on size
    json_str = json.dumps(payload, separators=(',', ':'))
    limit_bytes = config.SUMMARY_MAX_SIZE_KB * 1024
    
    if len(json_str) > limit_bytes and len(frames) > 0:
      # We need to split
      num_frames = len(frames)
      # Roughly estimate number of chunks needed (add 10% safety margin for metadata repetition)
      num_chunks = int(np.ceil(len(json_str) / (limit_bytes * 0.9)))
      frames_per_chunk = int(np.ceil(num_frames / num_chunks))
      
      log_info(f"Summary size ({len(json_str)//1024}KB) exceeds limit ({config.SUMMARY_MAX_SIZE_KB}KB). Splitting into multiple chunks.")
      
      base_path = output_json.replace(".summary.json", "")
      chunks = []
      for start_idx in range(0, num_frames, frames_per_chunk):
          end_idx = min(start_idx + frames_per_chunk, num_frames)
          chunks.append(frames[start_idx:end_idx])
      
      num_chunks_actual = len(chunks)
      
      for i, chunk_frames in enumerate(chunks):
        # Determine time range for transients
        start_time = chunk_frames[0]["t"]
        end_time = chunk_frames[-1]["t"]
        
        chunk_transients = [t for t in transients if start_time <= t["t"] <= end_time]
        
        chunk_payload = payload.copy()
        chunk_payload["frames"] = chunk_frames
        chunk_payload["transients"] = chunk_transients
        chunk_payload["chunk"] = i + 1
        chunk_payload["total_chunks"] = num_chunks_actual
        
        chunk_filename = f"{base_path}.{i+1:02d}.summary.json"
        with open(chunk_filename, "w", encoding="utf-8") as f:
          json.dump(chunk_payload, f, separators=(',', ':'))
      
      # Also delete the original unsplit path if it was passed as output_json and we just created chunks
      # Actually we haven't written the original one yet.
      return transients
    else:
      # No splitting needed or not summary_only
      with open(output_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(',', ':'))
      return transients
  else:
    # Regular full analysis
    with open(output_json, "w", encoding="utf-8") as f:
      json.dump(payload, f, indent=2)
    return output_json


def create_spectrogram(
    audio_path: str,
    output_path: str | None = None,
    sr: int | None = None,
    n_fft: int = 4096,
    hop_length: int = 512,
    top_db: int = 80,
    fmax: int = 20000,
) -> str:
  """
  Create a log-frequency spectrogram (WebP) from an audio file.
  """
  audio_path = Path(audio_path)
  if output_path is None:
    sanitized_stem = config.sanitize_filename(audio_path.stem)
    output_path = str(audio_path.parent / (sanitized_stem + ".spectrogram.webp"))

  # Load audio, preserve original sample rate if sr=None
  y, sr_loaded = librosa.load(audio_path, sr=sr, mono=False)

  # Convert stereo to mono for a simpler overview spectrogram
  y_mono = librosa.to_mono(y) if y.ndim > 1 else y

  # STFT -> magnitude
  stft = librosa.stft(y_mono, n_fft=n_fft, hop_length=hop_length, window="hann")
  magnitude = np.abs(stft)

  return _process_spectrogram(magnitude, sr_loaded, hop_length, audio_path, output_path)


def band_energy_analysis(
    audio_path: str,
    output_json: str | None = None,
    sr: int | None = None,
    n_fft: int = 4096,
    hop_length: int = 512,
) -> str:
  """
  Compute time-resolved band energy analysis and save as JSON.
  """
  audio_path = Path(audio_path)
  if output_json is None:
    sanitized_stem = config.sanitize_filename(audio_path.stem)
    output_json = str(audio_path.parent / (sanitized_stem + ".analysis.json"))

  y, sr_loaded = librosa.load(audio_path, sr=sr, mono=False)
  y_mono = librosa.to_mono(y) if y.ndim > 1 else y

  stft = librosa.stft(y_mono, n_fft=n_fft, hop_length=hop_length, window="hann")
  magnitude = np.abs(stft)

  return _process_band_energy(magnitude, sr_loaded, n_fft, hop_length, audio_path, output_json, y=y)


def process_audio_file(file_path: str, output_dir: str, summary_only: bool = False) -> bool:
  """
  Processes a single audio file: creates spectrogram and analysis JSON.
  If output_dir is provided, results are saved there instead of next to the source file.
  
  :param summary_only: If True, only generates the .summary.json (fast).
  """
  try:
    audio_path = Path(file_path)
    log_info(f"Analyzing {audio_path.name} (summary_only={summary_only})...")

    n_fft = 4096

    # Load audio, mono=False to get stereo info if available, sr=None to keep original rate
    y, sr = librosa.load(audio_path, sr=None, mono=False)
    
    # 10ms hop length as requested
    hop_length = int(sr * (config.ANALYSIS_FRAME_DURATION_MS / 1000.0))
    
    # Calculate global metrics
    peak_db = 20 * np.log10(np.max(np.abs(y)) + 1e-12)
    rms_db = 20 * np.log10(np.sqrt(np.mean(y**2)) + 1e-12)
    
    # LUFS calculation
    y_ln = y.T if y.ndim > 1 else y[:, np.newaxis]
    meter = pyln.Meter(sr)
    try:
      loudness = meter.integrated_loudness(y_ln)
    except Exception:
      loudness = -100.0 # Error fallback
      
    # Stereo Correlation
    corr = 1.0
    if y.ndim > 1 and y.shape[0] == 2:
      # Some stems might be silence, avoid correlation errors
      if np.max(np.abs(y)) > 1e-8:
          c_matrix = np.corrcoef(y[0], y[1])
          if not np.isnan(c_matrix[0, 1]):
              corr = c_matrix[0, 1]

    global_metrics = {
      "integrated_loudness_lufs": float(loudness),
      "peak_db": float(peak_db),
      "rms_db": float(rms_db),
      "crest_factor_db": float(peak_db - rms_db),
      "stereo_correlation": float(corr)
    }

    # Convert to mono for spectrogram and band analysis
    y_mono = librosa.to_mono(y) if y.ndim > 1 else y

    # Compute STFT once (heavy operation)
    stft = librosa.stft(y_mono, n_fft=n_fft, hop_length=hop_length, window="hann")
    magnitude = np.abs(stft)

    # Determine output paths
    analyses_dir = Path(config.get_analyses_path())
    spectrograms_dir = Path(config.get_spectrograms_path())
    summaries_dir = Path(config.get_summaries_path())

    analyses_dir.mkdir(parents=True, exist_ok=True)
    spectrograms_dir.mkdir(parents=True, exist_ok=True)
    summaries_dir.mkdir(parents=True, exist_ok=True)

    sanitized_stem = config.sanitize_filename(audio_path.stem)
    output_summary_json = str(summaries_dir / (sanitized_stem + ".summary.json"))
    
    # Always create summary
    _process_band_energy(magnitude, sr, n_fft, hop_length, audio_path, output_summary_json, global_metrics, y=y, summary_only=True)

    if not summary_only:
      output_spectrogram = str(spectrograms_dir / (sanitized_stem + ".spectrogram.webp"))
      output_full_json = str(analyses_dir / (sanitized_stem + ".analysis.json"))
      
      _process_spectrogram(magnitude, sr, hop_length, audio_path, output_spectrogram)
      _process_band_energy(magnitude, sr, n_fft, hop_length, audio_path, output_full_json, global_metrics, y=y, summary_only=False)

    return True
  except Exception as e:
    log_error(f"Error analyzing {file_path}: {e}")
    return False
