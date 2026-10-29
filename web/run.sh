#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if [ ! -f .venv/installed-requirements.txt ] || ! cmp -s requirements.txt .venv/installed-requirements.txt; then
  .venv/bin/python -m pip install -r requirements.txt
  cp requirements.txt .venv/installed-requirements.txt
fi
exec .venv/bin/python -m uvicorn mauve_web.app:create_app --factory --host "${MAUVE_HOST:-127.0.0.1}" --port "${PORT:-8765}"
