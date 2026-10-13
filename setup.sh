#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo 'This POC targets Apple silicon Macs.' >&2
  exit 1
fi
command -v ffmpeg >/dev/null || { echo 'Install ffmpeg first: brew install ffmpeg'; exit 1; }
PYTHON_BIN="${PYTHON_BIN:-python3.13}"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info[:2] == (3, 13), "Use Python 3.13 for this project"'
if [[ -x .venv/bin/python ]] && ! .venv/bin/python -c 'import sys; sys.exit(sys.version_info[:2] != (3, 13))'; then
  echo 'Existing .venv uses a different Python. Rename it first (for example: mv .venv .venv.previous), then rerun ./setup.sh.' >&2
  exit 1
fi
[[ -x .venv/bin/python ]] || "$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
echo 'Ready. Run ./run.sh and open http://127.0.0.1:8765'
