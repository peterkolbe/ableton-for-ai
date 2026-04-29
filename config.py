# =============================================================================
# DEFAULTS (FALLBACK VALUES)
# =============================================================================

DEFAULT_STEMS_SOURCE_DIR = "./stems"
DEFAULT_PREFERRED_AUDIO_FORMAT = "wav"  # wav | mp3
DEFAULT_RELEVANT_DEVICE_NAMES = {"Pro-Q 4", "Decapitator", "Raum", "Ozone Imager 2", "Massive", "Fresh Air", "SubBoomBass2"}
DEFAULT_RELEVANT_DEVICE_CLASSES = {
  "Eq8", "EqEight", "ChannelEq", "Compressor", "Compressor2", "GlueCompressor", "Limiter", "Gate",
  "AutoFilter", "AutoFilter2", "MultibandDynamics", "Saturator", "Utility", "Delay", "SimpleDelay", "PingPongDelay", "DrumBuss", "Echo",
  "Utility", "LFO"
}

DEFAULT_LOG_LEVEL = "INFO"  # INFO | DEBUG
DEFAULT_BASE_OUT_DIR = "out"
DEFAULT_PROJECT_JSON_FILENAME = "ableton-project-for-ai.json"
DEFAULT_ANALYSIS_FRAME_DURATION_MS = 10
DEFAULT_SPECTROGRAM_QUALITY = 90
DEFAULT_SUMMARY_MAX_SIZE_KB = 500
