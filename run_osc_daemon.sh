#!/bin/bash
# Stop any existing osc_daemon.py process to ensure a clean start
echo "Stopping existing osc_daemon..."
pkill -f "python.*osc_daemon.py" || true

# Start the osc_daemon.py and redirect output to osc_daemon.log (overwrite)
echo "Starting osc_daemon.py (logging to osc_daemon.log)..."
uv run osc_daemon.py > osc_daemon.log 2>&1 &
