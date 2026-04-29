import re
import unicodedata
import os
import sys
from pathlib import Path
from typing import Set

# Import defaults from config.py
from config import (
    DEFAULT_STEMS_SOURCE_DIR,
    DEFAULT_PREFERRED_AUDIO_FORMAT,
    DEFAULT_RELEVANT_DEVICE_NAMES,
    DEFAULT_RELEVANT_DEVICE_CLASSES,
    DEFAULT_LOG_LEVEL,
    DEFAULT_BASE_OUT_DIR,
    DEFAULT_PROJECT_JSON_FILENAME,
    DEFAULT_ANALYSIS_FRAME_DURATION_MS,
    DEFAULT_SPECTROGRAM_QUALITY,
    DEFAULT_SUMMARY_MAX_SIZE_KB
)

def sanitize_filename(name: str) -> str:
    """
    Sanitizes a string to be used as a filename:
    - Lowercase
    - Replace spaces and invalid characters with '-'
    - Remove accents/umlauts (ä -> a, etc.)
    - Keep only standard characters (a-z, 0-9, -, .)
    """
    # Convert to lowercase
    name = name.lower()
    # Normalize unicode to decompose characters (e.g., 'ä' to 'a' + 'umlaut')
    name = unicodedata.normalize('NFKD', name)
    # Encode to ascii, ignoring non-ascii characters
    name = name.encode('ascii', 'ignore').decode('ascii')
    # Replace anything that isn't a-z, 0-9, '-', '.' with '-'
    name = re.sub(r'[^a-z0-9\-.]', '-', name)
    # Replace multiple dashes with a single dash
    name = re.sub(r'-+', '-', name)
    # Strip leading/trailing dashes
    name = name.strip('-')
    return name

class Configuration:
  """
  Centralized configuration management with validation and environment support.
  """

  def __init__(self):
    # Read from environment or use defaults
    self._log_level = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    self._base_out_dir = os.getenv("BASE_OUT_DIR", DEFAULT_BASE_OUT_DIR)
    self._stems_source_dir = os.getenv("STEMS_SOURCE_DIR", DEFAULT_STEMS_SOURCE_DIR)
    self._project_json_filename = sanitize_filename(os.getenv("PROJECT_JSON_FILENAME", os.getenv("SNAPSHOT_JSON_FILENAME", DEFAULT_PROJECT_JSON_FILENAME)))
    self._preferred_audio_format = os.getenv("PREFERRED_AUDIO_FORMAT", DEFAULT_PREFERRED_AUDIO_FORMAT).lower()
    self._spectrogram_quality = int(os.getenv("SPECTROGRAM_QUALITY", DEFAULT_SPECTROGRAM_QUALITY))
    self._summary_max_size_kb = int(os.getenv("SUMMARY_MAX_SIZE_KB", DEFAULT_SUMMARY_MAX_SIZE_KB))
    self._analysis_frame_duration_ms = int(os.getenv("ANALYSIS_FRAME_DURATION_MS", DEFAULT_ANALYSIS_FRAME_DURATION_MS))
    self._analyses_dir = os.getenv("ANALYSES_DIR", "analyses")
    self._spectrograms_dir = os.getenv("SPECTROGRAMS_DIR", "spectrograms")
    self._summaries_dir = os.getenv("SUMMARIES_DIR", "summaries")
    self._project_dir = os.getenv("PROJECT_DIR", "project")

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

    if not (1 <= self._spectrogram_quality <= 100):
      print(f"[WARNING] Invalid SPECTROGRAM_QUALITY '{self._spectrogram_quality}'. Must be 1-100. Using DEFAULT: {DEFAULT_SPECTROGRAM_QUALITY}",
            file=sys.stderr)
      self._spectrogram_quality = DEFAULT_SPECTROGRAM_QUALITY

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
  def PROJECT_JSON_FILENAME(self) -> str:
    return self._project_json_filename

  @property
  def PREFERRED_AUDIO_FORMAT(self) -> str:
    return self._preferred_audio_format

  @property
  def SPECTROGRAM_QUALITY(self) -> int:
    return self._spectrogram_quality

  @property
  def SUMMARY_MAX_SIZE_KB(self) -> int:
    return self._summary_max_size_kb

  @property
  def ANALYSIS_FRAME_DURATION_MS(self) -> int:
    return self._analysis_frame_duration_ms

  @property
  def ANALYSES_DIR(self) -> str:
    return self._analyses_dir

  @property
  def SPECTROGRAMS_DIR(self) -> str:
    return self._spectrograms_dir

  @property
  def SUMMARIES_DIR(self) -> str:
    return self._summaries_dir

  @property
  def PROJECT_DIR(self) -> str:
    return self._project_dir

  def get_project_json_path(self) -> str:
    """Constructs the full path to the project JSON file."""
    return os.path.join(self.BASE_OUT_DIR, self.PROJECT_DIR, self.PROJECT_JSON_FILENAME)

  def get_analyses_path(self) -> str:
    return os.path.join(self.BASE_OUT_DIR, self.ANALYSES_DIR)

  def get_spectrograms_path(self) -> str:
    return os.path.join(self.BASE_OUT_DIR, self.SPECTROGRAMS_DIR)

  def get_summaries_path(self) -> str:
    return os.path.join(self.BASE_OUT_DIR, self.SUMMARIES_DIR)

  def get_project_path(self) -> str:
    return os.path.join(self.BASE_OUT_DIR, self.PROJECT_DIR)


# =============================================================================
# EXPORTS (FOR BACKWARDS COMPATIBILITY)
# =============================================================================

# Create a singleton instance
_config = Configuration()

# Map instance properties to module-level variables
LOG_LEVEL = _config.LOG_LEVEL
BASE_OUT_DIR = _config.BASE_OUT_DIR
STEMS_SOURCE_DIR = _config.STEMS_SOURCE_DIR
PROJECT_JSON_FILENAME = _config.PROJECT_JSON_FILENAME
PREFERRED_AUDIO_FORMAT = _config.PREFERRED_AUDIO_FORMAT
SPECTROGRAM_QUALITY = _config.SPECTROGRAM_QUALITY
ANALYSIS_FRAME_DURATION_MS = _config.ANALYSIS_FRAME_DURATION_MS
ANALYSES_DIR = _config.ANALYSES_DIR
SPECTROGRAMS_DIR = _config.SPECTROGRAMS_DIR
SUMMARIES_DIR = _config.SUMMARIES_DIR
PROJECT_DIR = _config.PROJECT_DIR
SUMMARY_MAX_SIZE_KB = _config.SUMMARY_MAX_SIZE_KB
RELEVANT_DEVICE_CLASSES = _config.RELEVANT_DEVICE_CLASSES
RELEVANT_DEVICE_NAMES = _config.RELEVANT_DEVICE_NAMES


def get_project_json_path():
  return _config.get_project_json_path()


def get_analyses_path():
  return _config.get_analyses_path()


def get_spectrograms_path():
  return _config.get_spectrograms_path()


def get_summaries_path():
  return _config.get_summaries_path()


def get_project_path():
  return _config.get_project_path()
