"""
Utility to ensure the OSC daemon is running before the MCP server or CLI tools start.
Automatically starts the daemon as a background subprocess if it's not already available.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time

import config_utils as config

# How long to wait for the daemon to become responsive after starting it.
DAEMON_STARTUP_TIMEOUT_SEC = 10.0
DAEMON_POLL_INTERVAL_SEC = 0.1


def is_daemon_running(host=None, port=None) -> bool:
    """Check if the OSC daemon is already running by attempting a TCP connection."""
    host = host or config.DAEMON_HOST
    port = port or config.DAEMON_PORT
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def _is_our_daemon(host=None, port=None) -> bool:
    """
    Verify that the process listening on the daemon port is actually our OSC daemon
    by sending a 'get_status' JSON-RPC request.
    """
    host = host or config.DAEMON_HOST
    port = port or config.DAEMON_PORT
    try:
        with socket.create_connection((host, port), timeout=1.0) as s:
            req = json.dumps({"jsonrpc": "2.0", "id": "probe", "method": "get_status"}) + "\n"
            s.sendall(req.encode())
            s.settimeout(1.0)
            data = s.recv(4096).decode()
            if not data:
                return False
            resp = json.loads(data.strip().split("\n")[0])
            result = resp.get("result", {})
            return isinstance(result, dict) and result.get("status") == "ok"
    except Exception:
        return False


def _pids_on_port(port: int) -> list[int]:
    """Return PIDs of processes listening on the given TCP port (using lsof)."""
    try:
        out = subprocess.check_output(
            ["lsof", "-ti", f"tcp:{port}"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
        )
        return [int(p) for p in out.split() if p.strip().isdigit()]
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return []


def _kill_stale_daemon(port: int) -> bool:
    """Kill the process listening on the given port. Returns True if something was killed."""
    pids = _pids_on_port(port)
    if not pids:
        return False
    for pid in pids:
        try:
            _log(f"[INFO] Killing stale daemon process (PID: {pid}) on port {port}.")
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    # Give it a moment to release the port
    for _ in range(20):  # up to 2s
        time.sleep(0.1)
        if not _pids_on_port(port):
            return True
    # Hard kill if still hanging
    for pid in _pids_on_port(port):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            continue
    time.sleep(0.3)
    return True


def _build_daemon_command() -> list[str]:
    """
    Build the command to launch the OSC daemon.
    Strategy:
    1. Prefer the installed entry point 'ableton-for-ai-daemon' (works for pip/uvx installs).
    2. Fall back to invoking osc_daemon.py directly via the current Python interpreter.
    3. Last resort: run as module.
    """
    entry_point = shutil.which("ableton-for-ai-daemon")
    if entry_point:
        return [entry_point]

    daemon_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "osc_daemon.py")
    if os.path.exists(daemon_script):
        return [sys.executable, daemon_script]

    return [sys.executable, "-m", "osc_daemon"]


def start_daemon() -> subprocess.Popen | None:
    """
    Start the OSC daemon as a background subprocess.

    - If a healthy daemon is already running, returns None.
    - If a stale/dead daemon is squatting on the port, it gets killed and restarted.
    - If a foreign process holds the port, an error is logged and we abort.
    - Waits up to DAEMON_STARTUP_TIMEOUT_SEC for the new daemon to become responsive.
    """
    port = config.DAEMON_PORT

    if is_daemon_running():
        if _is_our_daemon():
            _log("[INFO] OSC daemon already running.")
            return None
        # Port is taken but it's not our daemon - check if it's *anything* we can identify
        pids = _pids_on_port(port)
        if pids:
            _log(
                f"[WARN] Port {port} is held by an unresponsive process (PID(s): {pids}). "
                f"Assuming it's a stale OSC daemon and killing it..."
            )
            _kill_stale_daemon(port)
        else:
            _log(f"[ERROR] Port {port} is in use but no PID found. Cannot start daemon.")
            return None

    cmd = _build_daemon_command()
    _log(f"[INFO] Starting OSC daemon in background: {' '.join(cmd)}")

    # Forward daemon stderr to our stderr so issues are visible.
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=sys.stderr,
        start_new_session=True,  # Detach from parent process
    )

    # Wait for daemon to become available
    max_iterations = int(DAEMON_STARTUP_TIMEOUT_SEC / DAEMON_POLL_INTERVAL_SEC)
    for _ in range(max_iterations):
        time.sleep(DAEMON_POLL_INTERVAL_SEC)
        if is_daemon_running():
            _log(f"[INFO] OSC daemon started successfully (PID: {process.pid}).")
            return process
        if process.poll() is not None:
            _log(
                f"[ERROR] OSC daemon process exited immediately (code {process.returncode}). "
                f"Command was: {' '.join(cmd)}"
            )
            return process

    _log(
        f"[ERROR] OSC daemon did not become available within {DAEMON_STARTUP_TIMEOUT_SEC:.0f} seconds. "
        f"Is Ableton Live running with AbletonOSC enabled?"
    )
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
