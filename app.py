"""A loopback-only, single-user Phonon-2 recording desk."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict
import logging
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import wave

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from streaming import LiveTranscriber

ROOT = Path(__file__).resolve().parent
MAX_BYTES = 32 * 1024 * 1024
MAX_SECONDS = 600
SAMPLES = {
    "demo": ("Short introduction", "Clean synthetic speech, Samantha voice.", "expected.txt"),
    "long-clean": ("Project briefing — clean", "Synthetic speech in a quiet setting. Compare with the two degraded versions.", "long-expected.txt"),
    "long-noisy": ("Project briefing — room noise", "Same synthetic speech with steady background noise at 12 dB signal-to-noise ratio.", "long-expected.txt"),
    "long-phone": ("Project briefing — muffled call", "Same synthetic speech, narrow telephone bandwidth, a little echo and stronger noise at 8 dB SNR.", "long-expected.txt"),
}
os.environ.setdefault("HF_HOME", str(ROOT / ".cache/huggingface"))
os.environ.setdefault("FERMION_CACHE_DIR", str(ROOT / ".cache/fermion"))
os.environ["FERMION_DEVICE"] = "mlx"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
logger = logging.getLogger("phonon-poc")


class Engine:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="phonon")
        self.model = None
        self.status = "loading"
        self.error = None
        self.info = {}
        self.load_seconds = None
        self.busy = False

    def load(self):
        started = time.perf_counter()
        try:
            import fermion
            import mlx.core as mx

            self.model = fermion.load_speech(os.environ.get("CALL_NOTE_MODEL", "phonon-2"), quiet=False)
            self.info = self.model.describe()
            self.info["device"] = mx.device_info()
            from fermion._speech.live import warm_up
            self.info["warmup_seconds"] = warm_up(self.model)
            self.load_seconds = time.perf_counter() - started
            self.status = "ready"
        except (Exception, SystemExit) as exc:
            logger.exception("Model startup failed")
            self.error = str(exc)
            self.status = "error"

    def transcribe_wav(self, source: Path, hotwords: list[str]):
        """Transcribe a known WAV fixture without an external decoder."""
        started = time.perf_counter()
        result = asdict(self.model.transcribe_detailed(str(source), hotwords=hotwords))
        processing = time.perf_counter() - started
        duration = result["audio_seconds"]
        result.update(model="phonon-2", backend="mlx", processing_seconds=processing,
                      conversion_seconds=0, model_load_seconds=self.load_seconds,
                      realtime_factor=processing / duration, speed_x=duration / processing)
        return result

    def transcribe(self, source: Path, hotwords: list[str]):
        if not shutil.which("ffmpeg"):
            raise HTTPException(503, "File import requires FFmpeg. Live recording and the bundled sample do not.")
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="phonon-convert-") as directory:
            target = Path(directory) / "audio.wav"
            try:
                subprocess.run(
                    ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                     "-protocol_whitelist", "file,pipe", "-i", str(source),
                     "-map", "0:a:0", "-vn", "-t", str(MAX_SECONDS + 1),
                     "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target)],
                    check=True, capture_output=True, timeout=90,
                )
            except subprocess.CalledProcessError as exc:
                raise HTTPException(422, "Cannot decode this audio. Try a WAV, MP3, M4A, FLAC or WebM file.") from exc
            except subprocess.TimeoutExpired as exc:
                raise HTTPException(422, "Audio conversion timed out. Try a shorter file.") from exc
            with wave.open(str(target), "rb") as audio:
                duration = audio.getnframes() / audio.getframerate()
            if duration > MAX_SECONDS:
                raise HTTPException(413, "Audio is longer than 10 minutes. Split it into shorter files.")
            if duration < 0.1:
                raise HTTPException(422, "Audio is empty or shorter than 0.1 seconds.")
            conversion_seconds = time.perf_counter() - started
            try:
                result = asdict(self.model.transcribe_detailed(str(target), hotwords=hotwords))
            except (ValueError, SystemExit) as exc:
                raise HTTPException(422, str(exc)) from exc
            processing = time.perf_counter() - started
            result.update(
                model="phonon-2", backend="mlx", processing_seconds=processing,
                conversion_seconds=conversion_seconds, model_load_seconds=self.load_seconds,
                realtime_factor=processing / duration, speed_x=duration / processing,
            )
            return result


engine = Engine()


@asynccontextmanager
async def lifespan(app):
    loading = asyncio.get_running_loop().run_in_executor(engine.pool, engine.load)
    yield
    await loading
    engine.pool.shutdown(wait=True)


app = FastAPI(title="Phonon local speech desk", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])


@app.middleware("http")
async def local_requests(request: Request, call_next):
    # No CORS: other websites cannot read or submit recordings through this app.
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        expected = f"{request.url.scheme}://{request.headers.get('host')}"
        if origin and origin != expected:
            return JSONResponse({"detail": "Cross-origin requests are not allowed."}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
        try:
            if int(request.headers.get("content-length", "0")) > MAX_BYTES + 64 * 1024:
                return JSONResponse({"detail": "File is larger than 32 MB."}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    return response


@app.get("/")
def index():
    return FileResponse(ROOT / "static/index.html")


@app.get("/api/status")
def status():
    return dict(status=engine.status, error=engine.error, busy=engine.busy,
                model="phonon-2", backend="mlx", load_seconds=engine.load_seconds,
                engine=engine.info, max_bytes=MAX_BYTES, max_seconds=MAX_SECONDS)


@app.get("/api/sample")
def sample(sample_id: str = "demo"):
    if sample_id not in SAMPLES:
        raise HTTPException(404, "Unknown sample.")
    path = ROOT / "samples" / f"{sample_id}.wav"
    if not path.exists():
        raise HTTPException(404, "Generate the sample first: ./make_sample.sh")
    return FileResponse(path, media_type="audio/wav", filename=path.name)


@app.get("/api/samples")
def samples():
    items = []
    for sample_id, (title, description, reference) in SAMPLES.items():
        path = ROOT / "samples" / f"{sample_id}.wav"
        if path.exists():
            with wave.open(str(path), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()
            items.append(dict(id=sample_id, title=title, description=description,
                              duration=duration, reference=(ROOT / "samples" / reference).read_text()))
    return items


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...), hotwords: str = Form("")):
    try:
        if engine.status != "ready":
            raise HTTPException(503, engine.error or "The model is still loading. Please wait.")
        if engine.busy:
            raise HTTPException(409, "Another recording is being transcribed. Please wait.")
        terms = [term.strip() for term in hotwords.split(",") if term.strip()]
        if len(terms) > 25 or len(hotwords) > 1000:
            raise HTTPException(422, "Use at most 25 hotwords and 1,000 characters.")
        # All inference uses the same worker as model load; MLX calls never overlap.
        engine.busy = True
        try:
            with tempfile.TemporaryDirectory(prefix="phonon-upload-") as directory:
                source = Path(directory) / "upload"
                size = 0
                with source.open("wb") as output:
                    while chunk := await file.read(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise HTTPException(413, "File is larger than 32 MB.")
                        output.write(chunk)
                if not size:
                    raise HTTPException(422, "The audio file is empty.")
                job = asyncio.get_running_loop().run_in_executor(engine.pool, engine.transcribe, source, terms)
                try:
                    return await asyncio.shield(job)
                except asyncio.CancelledError:
                    # A disconnected client must not delete a file still in use.
                    await job
                    raise
                except HTTPException:
                    raise
                except Exception as exc:
                    logger.exception("Transcription failed")
                    raise HTTPException(500, "Transcription failed. Check the server terminal and try again.") from exc
        finally:
            engine.busy = False
    finally:
        await file.close()


async def engine_call(fn, *args):
    job = asyncio.get_running_loop().run_in_executor(engine.pool, fn, *args)
    try:
        return await asyncio.shield(job)
    except asyncio.CancelledError:
        await job
        raise


@app.websocket("/api/live")
async def live_transcription(socket: WebSocket):
    origin = socket.headers.get("origin")
    scheme = "https" if socket.url.scheme == "wss" else "http"
    if origin and origin != f"{scheme}://{socket.headers.get('host')}":
        await socket.close(code=1008)
        return
    await socket.accept()
    if engine.status != "ready" or engine.busy:
        await socket.send_json({"type": "error", "message": "The engine is loading or busy. Try again shortly."})
        await socket.close(code=1013)
        return
    engine.busy = True
    try:
        config = await asyncio.wait_for(socket.receive_json(), timeout=10)
        if not isinstance(config, dict) or config.get("type") != "start" or config.get("sample_rate") != 16000:
            raise ValueError("Start with type=start and sample_rate=16000; send mono float32 little-endian audio.")
        hotwords = config.get("hotwords", [])
        if (not isinstance(hotwords, list) or len(hotwords) > 25
                or any(not isinstance(term, str) for term in hotwords)
                or sum(len(term) for term in hotwords) > 1000):
            raise ValueError("Use at most 25 hotwords and 1,000 characters.")
        session = await engine_call(LiveTranscriber, engine.model, hotwords)
        await socket.send_json({"type": "ready"})
        samples_received = 0
        while True:
            message = await asyncio.wait_for(socket.receive(), timeout=30)
            if message["type"] == "websocket.disconnect":
                break
            data = message.get("bytes")
            if data is not None:
                if not data or len(data) % 4 or len(data) > 3200:
                    raise ValueError("Send audio blocks of 1–800 float32 samples.")
                samples_received += len(data) // 4
                if samples_received > MAX_SECONDS * 16000:
                    raise ValueError("Live recordings are limited to 10 minutes.")
                for event in await engine_call(session.feed, data):
                    await socket.send_json(event)
            elif json.loads(message.get("text", "{}")) == {"type": "stop"}:
                result = await engine_call(session.finish)
                result["model_load_seconds"] = engine.load_seconds
                await socket.send_json(result)
                await socket.close()
                break
            else:
                raise ValueError("Unknown live message. Send audio or type=stop.")
    except WebSocketDisconnect:
        pass
    except (ValueError, asyncio.TimeoutError) as exc:
        try:
            await socket.send_json({"type": "error", "message": str(exc) or "Live session timed out."})
            await socket.close(code=1008)
        except (RuntimeError, WebSocketDisconnect):
            pass
    except Exception:
        logger.exception("Live transcription failed")
        try:
            await socket.send_json({"type": "error", "message": "Live transcription failed. The recording can still be transcribed after stopping."})
            await socket.close(code=1011)
        except (RuntimeError, WebSocketDisconnect):
            pass
    finally:
        engine.busy = False


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
