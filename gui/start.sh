#!/usr/bin/env bash
# Start the Clericus GUI server
# Usage: ./gui/start.sh [port]
set -e
PORT=${1:-8765}
cd "$(dirname "$0")/.."
echo "Starting Clericus GUI on http://localhost:${PORT}"
uvicorn gui.api.server:app --host 0.0.0.0 --port "$PORT" --reload
