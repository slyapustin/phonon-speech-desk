"""Small reproducible smoke benchmark; run with the server already running."""
import argparse
import json
from pathlib import Path
import statistics

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("audio", nargs="?", default="samples/demo.wav")
parser.add_argument("--runs", type=int, default=3)
parser.add_argument("--url", default="http://127.0.0.1:8765")
parser.add_argument("--output", default="test-results/benchmark.json")
args = parser.parse_args()
results = []
with httpx.Client(base_url=args.url, timeout=180, trust_env=False) as client:
    status = client.get("/api/status").json()
    if status["status"] != "ready":
        raise SystemExit(f"Engine is {status['status']}; wait for startup, then retry.")
    for i in range(args.runs):
        with open(args.audio, "rb") as audio:
            response = client.post("/api/transcribe", files={"file": (Path(args.audio).name, audio)})
        response.raise_for_status()
        result = response.json()
        results.append(result)
        print(f"Run {i + 1}: {result['audio_seconds']:.2f}s audio / {result['processing_seconds']:.3f}s processing = {result['speed_x']:.1f}x realtime")
        print(result["text"])
report = {"status": status, "audio": args.audio, "runs": results,
          "median_processing_seconds": statistics.median(r["processing_seconds"] for r in results)}
output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, indent=2) + "\n")
print(f"Saved {output}")
