import io
import wave
import struct

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

import app


@pytest.fixture
def client(monkeypatch):
    # Exercise HTTP validation without loading a GPU model.
    monkeypatch.setattr(app.engine, "status", "ready")
    monkeypatch.setattr(app.engine, "busy", False)
    return TestClient(app.app)


def test_empty_upload(client):
    response = client.post("/api/transcribe", files={"file": ("empty.wav", b"")})
    assert response.status_code == 422
    assert not app.engine.busy


def test_invalid_audio_releases_worker(client):
    response = client.post("/api/transcribe", files={"file": ("bad.mp3", b"not audio")})
    assert response.status_code == 422
    assert not app.engine.busy


def test_hotword_limit(client):
    response = client.post("/api/transcribe", files={"file": ("a.wav", b"a")},
                           data={"hotwords": ",".join(str(i) for i in range(26))})
    assert response.status_code == 422


def test_busy_and_loading(client, monkeypatch):
    monkeypatch.setattr(app.engine, "busy", True)
    assert client.post("/api/transcribe", files={"file": ("a.wav", b"a")}).status_code == 409
    monkeypatch.setattr(app.engine, "status", "loading")
    assert client.post("/api/transcribe", files={"file": ("a.wav", b"a")}).status_code == 503


def test_cross_origin_rejected(client):
    response = client.post("/api/transcribe", headers={"Origin": "https://example.com"},
                           files={"file": ("a.wav", b"a")})
    assert response.status_code == 403


def test_sample_selection_rejects_unknown_paths(client):
    assert client.get("/api/sample", params={"sample_id": "../README"}).status_code == 404


def test_sample_library_metadata_and_playback(client, monkeypatch, tmp_path):
    sample_dir = tmp_path / "samples"
    sample_dir.mkdir()
    with wave.open(str(sample_dir / "demo.wav"), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 16000)
    (sample_dir / "expected.txt").write_text("Example speech.")
    monkeypatch.setattr(app, "ROOT", tmp_path)
    items = client.get("/api/samples").json()
    assert len(items) == 1
    assert items[0]["duration"] == 1
    assert items[0]["reference"] == "Example speech."
    response = client.get("/api/sample?sample_id=demo", headers={"Range": "bytes=0-43"})
    assert response.status_code == 206
    assert response.content[:4] == b"RIFF"


def test_large_upload_rejected(client, monkeypatch):
    monkeypatch.setattr(app, "MAX_BYTES", 10)
    response = client.post("/api/transcribe", files={"file": ("a.wav", b"a" * 11)})
    assert response.status_code == 413
    assert not app.engine.busy


def test_duration_limit_before_inference(client, monkeypatch):
    monkeypatch.setattr(app, "MAX_SECONDS", 1)
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 32000)
    response = client.post("/api/transcribe", files={"file": ("long.wav", audio.getvalue())})
    assert response.status_code == 413


def test_file_cleanup_and_per_request_hotwords(client, monkeypatch):
    paths = []
    def transcribe(path, terms):
        assert path.read_bytes() == b"sample"
        assert terms == ["Ada", "Fermion"]
        paths.append(path)
        return {"text": "example", "words": []}
    monkeypatch.setattr(app.engine, "transcribe", transcribe)
    response = client.post("/api/transcribe", files={"file": ("../../a.wav", b"sample")},
                           data={"hotwords": " Ada, Fermion, "})
    assert response.status_code == 200
    assert response.json()["text"] == "example"
    assert all(not path.exists() for path in paths)
    assert not app.engine.busy


def test_live_origin_rejected(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/live", headers={"origin": "https://example.com"}):
            pass


def test_live_bad_config_releases_worker(client):
    with client.websocket_connect("/api/live") as socket:
        socket.send_json({"type": "start", "sample_rate": 48000})
        assert socket.receive_json()["type"] == "error"
    assert not app.engine.busy


def test_live_updates_finish_and_exclusive_access(client, monkeypatch):
    class FakeLive:
        def __init__(self, model, hotwords):
            assert hotwords == ["Ada"]
        def feed(self, audio):
            assert len(audio) == 3200
            return [{"type": "partial", "final_text": "", "text": "hello"}]
        def finish(self):
            return {"type": "complete", "text": "hello"}
    monkeypatch.setattr(app, "LiveTranscriber", FakeLive)
    with client.websocket_connect("/api/live") as socket:
        socket.send_json({"type": "start", "sample_rate": 16000, "hotwords": ["Ada"]})
        assert socket.receive_json() == {"type": "ready"}
        assert client.post("/api/transcribe", files={"file": ("a.wav", b"a")}).status_code == 409
        socket.send_bytes(struct.pack("<800f", *([0.1] * 800)))
        assert socket.receive_json()["text"] == "hello"
        socket.send_json({"type": "stop"})
        assert socket.receive_json()["type"] == "complete"
    assert not app.engine.busy


def test_live_invalid_frame_and_disconnect_release_worker(client, monkeypatch):
    monkeypatch.setattr(app, "LiveTranscriber", lambda *_: None)
    with client.websocket_connect("/api/live") as socket:
        socket.send_json({"type": "start", "sample_rate": 16000})
        assert socket.receive_json()["type"] == "ready"
        socket.send_bytes(b"abc")
        assert socket.receive_json()["type"] == "error"
    assert not app.engine.busy
    with client.websocket_connect("/api/live") as socket:
        socket.send_json({"type": "start", "sample_rate": 16000})
        assert socket.receive_json()["type"] == "ready"
    assert not app.engine.busy
