#!/bin/bash
# Script to start the Firebot Menu Bar App

cd "$(dirname "$0")"

# Check if server is running on port 8899
if ! lsof -i :8899 > /dev/null; then
  echo "⚠️ Firebot server is not running. Please start Firebot first."
  exit 1
fi

echo "🚀 Starting Firebot Menu Bar App..."
./venv/bin/python3 menubar_app.py
