"""
Utility to ensure the OSC daemon is running before the MCP server or CLI tools start.
Automatically starts the daemon as a background subprocess if it's not already available.
"""

import os
import socket
import subprocess
import sys
import time

import config_utils as config


def is_daemon_running(host=None, port=None) -> bool:
    """Check if the OSC daemon is already running by attempting a TCP connection."""
    host = host or config.DAEMON_HOST
    port = port or config.DAEMON_PORT
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def start_daemon() -> subprocess.Popen | None:
    """
    Start the OSC daemon as a background subprocess.
    Returns the Popen process object, or None if the daemon was already running.
    """
    if is_daemon_running():
        _log("[INFO] OSC daemon already running.")
        return None

    # Find the osc_daemon module - it could be installed as entry point or as a file
    daemon_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "osc_daemon.py")

    if os.path.exists(daemon_script):
        cmd = [sys.executable, daemon_script]
    else:
        # Fallback: use the installed entry point
        cmd = ["ableton-osc-daemon"]

    _log("[INFO] Starting OSC daemon in background...")
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # Detach from parent process
    )

    # Wait briefly for daemon to become available
    for _ in range(20):  # Max 2 seconds
        time.sleep(0.1)
        if is_daemon_running():
            _log(f"[INFO] OSC daemon started successfully (PID: {process.pid}).")
            return process

    _log("[ERROR] OSC daemon did not become available within 2 seconds. Is Ableton Live running with AbletonOSC?")
    return process


def stop_daemon(process: subprocess.Popen | None):
    """Gracefully stop a daemon subprocess that was started by start_daemon()."""
    if process is None:
        return
    _log("[INFO] Stopping OSC daemon...")
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()


def ensure_daemon() -> subprocess.Popen | None:
    """
    Convenience function: ensures the daemon is running.
    Returns the process if we started it (caller should stop it on exit), or None if it was already running.
    """
    return start_daemon()


def _log(message: str):
    """Print to stderr (same as the rest of the project's logging)."""
    print(message, file=sys.stderr, flush=True)
