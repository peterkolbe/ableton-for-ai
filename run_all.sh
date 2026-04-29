#!/bin/bash
# Stop any existing osc_daemon.py process to ensure a clean start
echo "Stopping existing osc_daemon..."
pkill -f "python.*osc_daemon.py" || true

# Start the osc_daemon.py and redirect output to osc_daemon.log (overwrite)
echo "Starting osc_daemon.py (logging to osc_daemon.log)..."
uv run osc_daemon.py > osc_daemon.log 2>&1 &
DAEMON_PID=$!

# Give the daemon a moment to initialize and bind ports
sleep 2

# Run the combined extraction and analysis pipeline using uv
echo "Executing FULL PIPELINE (Extraction & Audio Analysis)..."
uv run ableton_client.py analyze_stems_and_extract_ableton_project_data

# Optional: Kill the daemon after completion?
# The user didn't explicitly ask to stop it, so we leave it running in the background
# as it is a persistent service, consistent with previous manual steps.
echo "Full pipeline finished. osc_daemon.py is still running with PID $DAEMON_PID."
