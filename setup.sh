#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo 'This POC targets Apple silicon Macs.' >&2
  exit 1
fi
command -v ffmpeg >/dev/null || { echo 'Install ffmpeg first: brew install ffmpeg'; exit 1; }
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required; this lock was tested with 3.11"'
[[ -x .venv/bin/python ]] || "$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
echo 'Ready. Run ./run.sh and open http://127.0.0.1:8765'
