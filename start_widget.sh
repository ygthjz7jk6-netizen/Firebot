#!/bin/bash
# Script to start only the Firebot Desktop Widget (assuming the main app/server is already running)

cd "$(dirname "$0")"

# Check if server is running on port 8899
if ! lsof -i :8899 > /dev/null; then
  echo "⚠️ Firebot server is not running. Please start Firebot first."
  exit 1
fi

echo "🚀 Starting Firebot Desktop Widget..."
python3 widget_window.py
