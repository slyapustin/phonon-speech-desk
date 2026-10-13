"""Pace the known sample through the actual local WebSocket and check partials."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time

import numpy as np
import soundfile as sf
from websockets.sync.client import connect

audio, rate = sf.read("samples/demo.wav", dtype="float32")
assert rate == 16000
audio = np.concatenate([audio, np.zeros(16000, dtype=np.float32)])
events = []
with connect("ws://127.0.0.1:8765/api/live", origin="http://127.0.0.1:8765") as socket:
    socket.send(json.dumps({"type": "start", "sample_rate": 16000, "hotwords": []}))
    assert json.loads(socket.recv(timeout=30))["type"] == "ready"
    started = time.perf_counter()
    def send_audio():
        for offset in range(0, len(audio), 800):
            socket.send(audio[offset:offset + 800].astype("<f4").tobytes())
            delay = started + min(offset + 800, len(audio)) / rate - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
        socket.send(json.dumps({"type": "stop"}))
    with ThreadPoolExecutor(max_workers=1) as pool:
        sender = pool.submit(send_audio)
        while True:
            event = json.loads(socket.recv(timeout=30))
            event["received_seconds"] = time.perf_counter() - started
            events.append(event)
            print(f"{event['received_seconds']:.2f}s {event['type']}: {event.get('text', event.get('message', ''))}", flush=True)
            assert event["type"] != "error", event
            if event["type"] == "complete":
                break
        sender.result()
partials = [event for event in events if event["type"] == "partial"]
assert partials and partials[0]["received_seconds"] < len(audio) / rate
assert any(event["type"] == "final" for event in events)
assert "local speech recognition test" in events[-1]["text"].lower()
output = Path("test-results/live-stream.json")
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(events, indent=2) + "\n")
print(f"Verified {len(partials)} partials; first at {partials[0]['received_seconds']:.2f}s. Saved {output}.")
