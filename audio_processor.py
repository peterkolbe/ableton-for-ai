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
import config

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


def _process_spectrogram(magnitude, sr, hop_length, audio_path, output_png):
  """Internal helper to create spectrogram from magnitude."""
  db = librosa.amplitude_to_db(magnitude, ref=np.max, top_db=80)

  with matplotlib_lock:
    # Use object-oriented matplotlib for thread-safety
    fig = Figure(figsize=(16, 8))
    canvas = FigureCanvasAgg(fig)
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
    fig.savefig(output_png, dpi=200, bbox_inches="tight")

    # Cleanup
    fig.clf()
    del fig

  return output_png


def _process_band_energy(magnitude, sr, n_fft, hop_length, audio_path, output_json):
  """Internal helper to compute band energy from magnitude."""
  power = magnitude ** 2
  freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
  times = librosa.frames_to_time(np.arange(power.shape[1]), sr=sr, hop_length=hop_length)

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
    row = {"time": float(t)}
    for band_name, mask in masks.items():
      band_power = power[mask, t_idx].sum()
      band_db = 10 * np.log10(max(band_power, 1e-12))
      row[f"{band_name}_db"] = float(band_db)
    frames.append(row)

  payload = {
    "stem": audio_path.name,
    "sample_rate": int(sr),
    "n_fft": n_fft,
    "hop_length": hop_length,
    "bands": bands,
    "frames": frames,
  }

  with open(output_json, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)
  return output_json


def create_spectrogram(
    audio_path: str,
    output_png: str | None = None,
    sr: int | None = None,
    n_fft: int = 4096,
    hop_length: int = 512,
    top_db: int = 80,
    fmax: int = 20000,
) -> str:
  """
  Create a log-frequency spectrogram PNG from an audio file.
  """
  audio_path = Path(audio_path)
  if output_png is None:
    output_png = str(audio_path.with_suffix(".spectrogram.png"))

  # Load audio, preserve original sample rate if sr=None
  y, sr_loaded = librosa.load(audio_path, sr=sr, mono=False)

  # Convert stereo to mono for a simpler overview spectrogram
  y_mono = librosa.to_mono(y) if y.ndim > 1 else y

  # STFT -> magnitude
  stft = librosa.stft(y_mono, n_fft=n_fft, hop_length=hop_length, window="hann")
  magnitude = np.abs(stft)

  return _process_spectrogram(magnitude, sr_loaded, hop_length, audio_path, output_png)


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
    output_json = str(audio_path.with_suffix(".analysis.json"))

  y, sr_loaded = librosa.load(audio_path, sr=sr, mono=False)
  y_mono = librosa.to_mono(y) if y.ndim > 1 else y

  stft = librosa.stft(y_mono, n_fft=n_fft, hop_length=hop_length, window="hann")
  magnitude = np.abs(stft)

  return _process_band_energy(magnitude, sr_loaded, n_fft, hop_length, audio_path, output_json)


def process_audio_file(file_path: str):
  """
  Processes a single audio file: creates spectrogram and analysis JSON.
  """
  try:
    audio_path = Path(file_path)
    log_info(f"Analyzing {audio_path.name}...")

    n_fft = 4096
    hop_length = 512

    y, sr = librosa.load(audio_path, sr=None, mono=False)
    y_mono = librosa.to_mono(y) if y.ndim > 1 else y

    # Compute STFT once (heavy operation)
    stft = librosa.stft(y_mono, n_fft=n_fft, hop_length=hop_length, window="hann")
    magnitude = np.abs(stft)

    output_png = str(audio_path.with_suffix(".spectrogram.png"))
    output_json = str(audio_path.with_suffix(".analysis.json"))

    # We don't need another ThreadPoolExecutor here as files are already
    # processed in parallel on a higher level. Sequential inside the file
    # avoids excessive resource usage and potential Matplotlib deadlocks.
    _process_spectrogram(magnitude, sr, hop_length, audio_path, output_png)
    _process_band_energy(magnitude, sr, n_fft, hop_length, audio_path, output_json)

    return True
  except Exception as e:
    log_error(f"Error analyzing {file_path}: {e}")
    return False
