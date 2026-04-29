import asyncio
import base64
import json
import os
from typing import List, Optional

from fastmcp import FastMCP
from fastmcp.server.middleware.tool_injection import ResourceToolMiddleware

import config_utils as config
from ableton_client import AbletonClient, log_info, log_error

# Initialize the MCP server
# Configure this in your MCP settings (e.g. Claude Desktop or IDE) as:
# IMPORTANT: Command must be ONLY 'uv'. Flags go into 'args'.
# command: uv (or absolute path to uv)
# args: ["--directory", "/absolute/path/to/project", "run", "mcp_server_ableton.py"]
mcp = FastMCP("Ableton Live Controller")

# for compatibility with nearly all AI agents, we inject the ResourceToolMiddleware which allows tools to update resources and notify clients of changes.
# TODO this should become deprecated in a few weeks / months ...
mcp.add_middleware(ResourceToolMiddleware())

# Create Ableton client
ableton_client = AbletonClient()


# ----- MCP RESOURCES -----

@mcp.resource("ableton://stems/{track_name}/summary")
async def get_stem_summary_resource(track_name: str) -> str:
  """
  Returns a compact audio analysis summary for a specific track.
  If the summary was split into multiple chunks, this returns the first chunk (01).
  """
  return await _get_summary_by_chunk(track_name, 1)


@mcp.resource("ableton://stems/{track_name}/summary/chunk/{chunk_id}")
async def get_stem_summary_chunk_resource(track_name: str, chunk_id: int) -> str:
  """
  Returns a specific chunk of a compact audio analysis summary.
  Use this when 'total_chunks' in the first summary indicates multiple parts.
  """
  return await _get_summary_by_chunk(track_name, chunk_id)


async def _get_summary_by_chunk(track_name: str, chunk_id: int) -> str:
  # 1. Try with chunk suffix if chunk_id > 0
  suffix = f".{chunk_id:02d}.summary.json"
  path = await _find_stem_file(track_name, suffix)

  # 2. If not found and chunk_id is 1, try without chunk suffix (backward compatibility / small files)
  if not path and chunk_id == 1:
    path = await _find_stem_file(track_name, ".summary.json")

  if not path or not os.path.exists(path):
    return json.dumps({"error": f"Summary chunk {chunk_id} not found for track: {track_name}"})

  with open(path, "r") as f:
    data = json.load(f)

    # Add local paths for reference
    data["local_summary_path"] = os.path.abspath(path)
    data["local_spectrogram_path"] = os.path.abspath(
      path.replace(suffix if f".{chunk_id:02d}.summary.json" in path else ".summary.json", ".spectrogram.webp")
    )

    # If it's chunked, provide URI templates for other chunks
    if "total_chunks" in data and data["total_chunks"] > 1:
      data["chunk_uris"] = [
        f"ableton://stems/{track_name}/summary/chunk/{i}"
        for i in range(1, data["total_chunks"] + 1)
      ]

    return json.dumps(data)


@mcp.resource("ableton://stems/{track_name}/spectrogram")
async def get_stem_spectrogram_resource(track_name: str) -> str:
  """Provides the spectrogram as a Data URI string (base64 encoded WebP)."""
  path = await _find_stem_file(track_name, ".spectrogram.webp")
  if not path or not os.path.exists(path):
    return f"Error: Spectrogram not found for track: {track_name}"
  with open(path, "rb") as f:
    data = f.read()
    base64_data = base64.b64encode(data).decode("utf-8")
    return f"data:image/webp;base64,{base64_data}"


@mcp.resource("ableton://stems/available/summaries")
async def get_available_stem_summaries_resource() -> str:
  """
  Returns a list of all tracks that have an available '.summary.json' analysis file.
  Use this to discover which tracks can be inspected via 'ableton://stems/{track_name}/summary'.
  """
  stems = await ableton_client.get_available_stem_summaries()
  return json.dumps(stems)


@mcp.resource("ableton://stems/available/spectrograms")
async def get_available_stem_spectrograms_resource() -> str:
  """
  Returns a list of all tracks that have an available '.spectrogram.webp' image.
  Use this to discover which tracks have visual representations available.
  """
  spectrograms = await ableton_client.get_available_stem_spectrograms()
  return json.dumps(spectrograms)


@mcp.tool()
async def analyze_stems() -> str:
  """
  DEEP AUDIO ANALYSIS: Triggers the generation of summaries and spectrograms for all tracks.

  This is a heavy operation that:
  1. Generates '.summary.json' (Frames, Transients, LUFS) for AI consumption.
  2. Generates '.spectrogram.webp' (Log-frequency visualizations).
  3. Generates '.analysis.json' (Full resolution data for internal use).

  ACTION: Use this when you need fresh audio data (e.g., after the user recorded new parts 
  or changed audio effects that significantly alter the sound).
  """
  if not await ableton_client.connect():
    return "Error: Could not connect to AbletonOSC daemon."
  try:
    await ableton_client.analyze_stems()
    return "Full stem analysis and summary generation completed. Results are available in out/summaries/, out/spectrograms/ and via resources."
  finally:
    await ableton_client.close()


@mcp.tool()
async def get_overview() -> dict:
  """
  SESSION DISCOVERY: Returns a high-level overview of the current Live set.

  Includes:
  - Tempo and Locators (Song structure).
  - Simplified Track list with mixer states (Index, Name, Volume, Panning, Mute, Solo).

  Use this for initial navigation and to identify track indices for further 'get_track' calls.
  """
  return await ableton_client.get_overview()


@mcp.tool()
async def get_track(track_index: int) -> dict:
  """
  TRACK INSPECTION: Returns comprehensive data for a single track.

  Includes:
  - Mixer state (Volume, Panning, etc.).
  - Complete Device Chain.
  - All Device Parameters (including UI-readable strings like "-12.0 dB" or "1500 Hz").

  Use this when you need to understand exactly how a specific track is processed
  or which parameters are available for manipulation.
  """
  return await ableton_client.get_track(track_index)


@mcp.tool()
async def get_tracks(index_min: int, index_max: int) -> dict:
  """
  BULK TRACK INSPECTION: Query full data for multiple tracks in a single call.
  
  Parameters:
  - index_min: Starting track index.
  - index_max: Ending track index.
  
  Returns an array of track objects, identical in structure to 'get_track'.
  Highly efficient for analyzing groups of tracks (e.g., all drum tracks).
  """
  if not await ableton_client.connect():
    return {"ok": False, "error": "Could not connect to AbletonOSC daemon."}
  return await ableton_client.get_tracks(index_min, index_max, None)


@mcp.tool()
async def set_device_parameter(
    track_index: int, device_index: int, parameter_index: int, value: float
) -> dict:
  """
  REMOTE CONTROL: Sets a specific device parameter.

  Parameters:
  - track_index: The index of the track.
  - device_index: The index of the device in the chain.
  - parameter_index: The index of the parameter to change.
  - value: The new normalized value (0.0 to 1.0).

  Note: For UI-readable values (like dB or Hz), check 'get_track' output first,
  but always send the normalized 0.0-1.0 value for the actual change.
  """
  return await ableton_client.set_device_parameter(
    track_index, device_index, parameter_index, value
  )


@mcp.tool()
async def set_device_parameters(
    track_index: int, device_index: int, values: List[float]
) -> dict:
  """
  BULK REMOTE CONTROL: Sets multiple parameters for a device at once.

  Parameters:
  - values: A list of floats representing the new values for ALL parameters of the device.

  Recommended for loading 'presets' or making simultaneous multi-parameter adjustments.
  """
  return await ableton_client.set_device_parameters(track_index, device_index, values)


@mcp.tool()
async def set_track_volume(track_index: int, value: float) -> dict:
  """
  MIXER CONTROL: Sets the volume of a track.
  - value: 0.0 to 1.0 (corresponds to Ableton's internal fader scaling).
  """
  return await ableton_client.set_track_volume(track_index, value)


@mcp.tool()
async def set_track_panning(track_index: int, value: float) -> dict:
  """
  MIXER CONTROL: Sets the panning of a track.
  - value: -1.0 (Left) to 1.0 (Right), 0.0 is Center.
  """
  return await ableton_client.set_track_panning(track_index, value)


@mcp.tool()
async def set_track_mute(track_index: int, mute: bool) -> dict:
  """
  Toggles the mute status of a track (True=Muted, False=Active).
  """
  return await ableton_client.set_track_mute(track_index, mute)


@mcp.tool()
async def set_track_solo(track_index: int, solo: bool) -> dict:
  """
  Toggles the solo status of a track (True=Solo, False=Normal).
  """
  return await ableton_client.set_track_solo(track_index, solo)


async def _find_stem_file(track_name: str, suffix: str) -> Optional[str]:
  """
  Helper to find a stem file in the output directory.
  Matches exact name, or name with prefix (like project name).
  """
  # Determine sub-directory based on suffix
  sub_dir = ""
  if suffix.endswith(".summary.json"):
    sub_dir = config.SUMMARIES_DIR
  elif suffix.endswith(".spectrogram.webp"):
    sub_dir = config.SPECTROGRAMS_DIR
  elif suffix.endswith(".analysis.json"):
    sub_dir = config.ANALYSES_DIR
  else:
    # Fallback/Default
    sub_dir = ""

  base_dir = os.path.join(config.BASE_OUT_DIR, sub_dir)
  if not os.path.exists(base_dir):
    return None

  sanitized_track_name = config.sanitize_filename(track_name)

  # 1. Try exact match with sanitized name
  exact_path = os.path.join(base_dir, f"{sanitized_track_name}{suffix}")
  if os.path.exists(exact_path):
    return exact_path

  # 2. Try matching files that contain the sanitized track_name and end with suffix
  files = os.listdir(base_dir)
  for f in files:
    f_lower = f.lower()
    if f_lower.endswith(suffix.lower()) and sanitized_track_name in f_lower:
      return os.path.join(base_dir, f)

  return None


# ----- CLI RUNNER -----

if __name__ == "__main__":
  try:
    log_info("Starting Ableton Live MCP server...")
    mcp.run()
  finally:
    asyncio.run(ableton_client.close())
