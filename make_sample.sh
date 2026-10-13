#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p samples
say -v Samantha -r 165 -o samples/demo.aiff 'This is a local speech recognition test on my Mac. The audio stays on this computer. Please schedule a meeting for tomorrow morning at ten, and remind me to bring the project notes.'
ffmpeg -nostdin -hide_banner -loglevel error -y -i samples/demo.aiff -ar 16000 -ac 1 samples/demo.wav
python3 -c 'import wave; w = wave.open("samples/demo.wav"); assert w.getnframes() > 1600, "Speech synthesis produced no audio. Run this script in Terminal outside a sandbox."'
echo 'Sample ready: samples/demo.wav'
.venv/bin/python build_samples.py
