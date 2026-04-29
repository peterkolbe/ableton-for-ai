# =============================================================================
# DEFAULTS (FALLBACK VALUES)
# =============================================================================

# --- Network / Ports ---
DEFAULT_DAEMON_HOST = "127.0.0.1"
DEFAULT_DAEMON_PORT = 65432
DEFAULT_ABLETON_OSC_HOST = "127.0.0.1"
DEFAULT_ABLETON_OSC_SEND_PORT = 11000
DEFAULT_ABLETON_OSC_RECEIVE_PORT = 11001

# --- Paths & Formats ---
DEFAULT_STEMS_SOURCE_DIR = "./stems"
DEFAULT_PREFERRED_AUDIO_FORMAT = "wav"  # wav | mp3
DEFAULT_RELEVANT_DEVICE_NAMES = {
    "Pro-Q 4",
    "Decapitator",
    "Raum",
    "Ozone Imager 2",
    "Massive",
    "Fresh Air",
    "SubBoomBass2",
}
DEFAULT_RELEVANT_DEVICE_CLASSES = {
    "Eq8",
    "EqEight",
    "ChannelEq",
    "Compressor",
    "Compressor2",
    "GlueCompressor",
    "Limiter",
    "Gate",
    "AutoFilter",
    "AutoFilter2",
    "MultibandDynamics",
    "Saturator",
    "Utility",
    "Delay",
    "SimpleDelay",
    "PingPongDelay",
    "DrumBuss",
    "Echo",
    "LFO",
}

DEFAULT_LOG_LEVEL = "INFO"  # INFO | DEBUG
DEFAULT_BASE_OUT_DIR = "out"
DEFAULT_PROJECT_JSON_FILENAME = "ableton-project-for-ai.json"
DEFAULT_ANALYSIS_FRAME_DURATION_MS = 10
DEFAULT_SPECTROGRAM_QUALITY = 90
DEFAULT_SUMMARY_MAX_SIZE_KB = 500
