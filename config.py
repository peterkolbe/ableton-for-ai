import os
import sys
from pathlib import Path
from typing import Set

# =============================================================================
# DEFAULTS (FALLBACK VALUES)
# =============================================================================

DEFAULT_LOG_LEVEL = "INFO"  # INFO | DEBUG
DEFAULT_BASE_OUT_DIR = "out"
DEFAULT_STEMS_SOURCE_DIR = "/Users/peterkolbe/Library/CloudStorage/OneDrive-PeterKolbe/ai-stem-exchange"
DEFAULT_SNAPSHOT_JSON_FILENAME = "ableton-project-for-ai.json"
DEFAULT_PREFERRED_AUDIO_FORMAT = "mp3"  # mp3 | wav

DEFAULT_RELEVANT_DEVICE_CLASSES = {
  "Eq8", "EqEight", "ChannelEq", "Compressor", "Compressor2", "GlueCompressor", "Limiter", "Gate",
  "AutoFilter", "AutoFilter2", "MultibandDynamics", "Saturator", "Utility", "Delay", "SimpleDelay", "PingPongDelay", "DrumBuss", "Echo"
}
DEFAULT_RELEVANT_DEVICE_NAMES = {"Pro-Q 4"}


# =============================================================================
# CONFIGURATION CLASS
# =============================================================================

class Configuration:
  """
  Centralized configuration management with validation and environment support.
  """

  def __init__(self):
    # Read from environment or use defaults
    self._log_level = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    self._base_out_dir = os.getenv("BASE_OUT_DIR", DEFAULT_BASE_OUT_DIR)
    self._stems_source_dir = os.getenv("STEMS_SOURCE_DIR", DEFAULT_STEMS_SOURCE_DIR)
    self._snapshot_json_filename = os.getenv("SNAPSHOT_JSON_FILENAME", DEFAULT_SNAPSHOT_JSON_FILENAME)
    self._preferred_audio_format = os.getenv("PREFERRED_AUDIO_FORMAT", DEFAULT_PREFERRED_AUDIO_FORMAT).lower()

    # Lists and Sets (support comma-separated environment variables)
    env_classes = os.getenv("RELEVANT_DEVICE_CLASSES")
    self.RELEVANT_DEVICE_CLASSES: Set[str] = {c.strip() for c in env_classes.split(",")} if env_classes else DEFAULT_RELEVANT_DEVICE_CLASSES

    env_names = os.getenv("RELEVANT_DEVICE_NAMES")
    self.RELEVANT_DEVICE_NAMES: Set[str] = {n.strip() for n in env_names.split(",")} if env_names else DEFAULT_RELEVANT_DEVICE_NAMES

    self._validate()

  def _validate(self):
    """Internal validation of settings."""
    if self._log_level not in ["INFO", "DEBUG"]:
      print(f"[WARNING] Invalid LOG_LEVEL '{self._log_level}'. Using DEFAULT: {DEFAULT_LOG_LEVEL}", file=sys.stderr)
      self._log_level = DEFAULT_LOG_LEVEL

    if self._preferred_audio_format not in ["mp3", "wav"]:
      print(f"[WARNING] Invalid PREFERRED_AUDIO_FORMAT '{self._preferred_audio_format}'. Using DEFAULT: {DEFAULT_PREFERRED_AUDIO_FORMAT}",
            file=sys.stderr)
      self._preferred_audio_format = DEFAULT_PREFERRED_AUDIO_FORMAT

    # Path validation
    source_path = Path(self._stems_source_dir)
    if not source_path.exists():
      print(f"[WARNING] STEMS_SOURCE_DIR does not exist: {self._stems_source_dir}", file=sys.stderr)
      print("[WARNING] Audio analysis will be skipped for non-existent stems.", file=sys.stderr)

  @property
  def LOG_LEVEL(self) -> str:
    return self._log_level

  @property
  def BASE_OUT_DIR(self) -> str:
    return self._base_out_dir

  @property
  def STEMS_SOURCE_DIR(self) -> str:
    return self._stems_source_dir

  @property
  def SNAPSHOT_JSON_FILENAME(self) -> str:
    return self._snapshot_json_filename

  @property
  def PREFERRED_AUDIO_FORMAT(self) -> str:
    return self._preferred_audio_format

  def get_snapshot_json_path(self) -> str:
    """Constructs the full path to the snapshot JSON file."""
    return os.path.join(self.BASE_OUT_DIR, self.SNAPSHOT_JSON_FILENAME)


# =============================================================================
# EXPORTS (FOR BACKWARDS COMPATIBILITY)
# =============================================================================

# Create a singleton instance
_config = Configuration()

# Map instance properties to module-level variables
LOG_LEVEL = _config.LOG_LEVEL
BASE_OUT_DIR = _config.BASE_OUT_DIR
STEMS_SOURCE_DIR = _config.STEMS_SOURCE_DIR
SNAPSHOT_JSON_FILENAME = _config.SNAPSHOT_JSON_FILENAME
PREFERRED_AUDIO_FORMAT = _config.PREFERRED_AUDIO_FORMAT
RELEVANT_DEVICE_CLASSES = _config.RELEVANT_DEVICE_CLASSES
RELEVANT_DEVICE_NAMES = _config.RELEVANT_DEVICE_NAMES


def get_snapshot_json_path():
  return _config.get_snapshot_json_path()
