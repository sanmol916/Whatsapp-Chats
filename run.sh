#!/usr/bin/env bash
# Start the WhatsApp Export Viewer panel.
#
# Usage:
#   ./run.sh                 # http://127.0.0.1:8000
#   HOST=0.0.0.0 PORT=9000 ./run.sh
#
# The panel is served at the root URL; the JSON API lives under /api/*.
set -euo pipefail
cd "$(dirname "$0")/backend"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python -m venv .venv
fi

# Always ensure dependencies are present/up to date (fast when already satisfied).
# This also repairs an existing .venv after a requirements change (e.g. the
# SQLAlchemy upgrade needed for Python 3.13/3.14).
./.venv/bin/pip install --upgrade pip >/dev/null
./.venv/bin/pip install -r requirements.txt

# Timeouts kept high so multi-GB uploads over slow links don't get cut off.
exec ./.venv/bin/python -m uvicorn app.main:app \
  --host "$HOST" --port "$PORT" \
  --timeout-keep-alive 300 \
  --limit-max-requests 100000
