#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export HF_HOME="$PWD/.cache/huggingface"
export FERMION_CACHE_DIR="$PWD/.cache/fermion"
export FERMION_DEVICE=mlx
export HF_HUB_DISABLE_TELEMETRY=1
export DO_NOT_TRACK=1
if [[ ! -x .venv/bin/python ]]; then
  echo 'Run ./setup.sh first.' >&2
  exit 1
fi
exec .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port "${PORT:-8765}"
