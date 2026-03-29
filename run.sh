#!/bin/bash
cd "$(dirname "$0")"

# Auto-backup data on launch
./backup.sh 2>/dev/null &

source venv/bin/activate

# Start Flask in background
python app.py &
PID=$!

# Wait for server to be ready
sleep 1

# Open browser
xdg-open http://localhost:5000 2>/dev/null

# Wait for Flask to exit (Ctrl+C in terminal kills it)
echo "Polar AI Coach running at http://localhost:5000 (PID $PID)"
echo "Press Ctrl+C to stop."
wait $PID
