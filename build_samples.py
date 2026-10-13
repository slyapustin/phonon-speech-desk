"""Generate paired synthetic speech samples with reproducible audio degradation."""
from pathlib import Path
import subprocess
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], check=True)


def noisy(audio, snr_db, seed):
    rng = np.random.default_rng(seed)
    # Low-pass random noise approximates steady room/ventilation noise.
    noise = np.convolve(rng.normal(size=len(audio)), np.ones(5) / 5, mode="same")
    speech_rms = np.sqrt(np.mean(audio ** 2))
    noise *= speech_rms / (10 ** (snr_db / 20) * np.sqrt(np.mean(noise ** 2)))
    mixed = audio + noise
    return mixed / max(1, np.max(np.abs(mixed)) / 0.95)


subprocess.run(["say", "-v", "Samantha", "-r", "165", "-f", str(SAMPLES / "long-expected.txt"),
                "-o", str(SAMPLES / "long-clean.aiff")], check=True)
ffmpeg("-i", SAMPLES / "long-clean.aiff", "-ar", "16000", "-ac", "1", SAMPLES / "long-clean.wav")
speech, sr = sf.read(SAMPLES / "long-clean.wav")
if len(speech) / sr < 60:
    raise RuntimeError("Long speech generation failed; run outside the sandbox in Terminal.")
sf.write(SAMPLES / "long-noisy.wav", noisy(speech, 12, 42), sr, subtype="PCM_16")
ffmpeg("-i", SAMPLES / "long-clean.wav", "-af", "highpass=f=300,lowpass=f=2800,aecho=0.8:0.8:75:0.18",
       "-ar", "8000", SAMPLES / "phone-filtered.wav")
phone, phone_sr = sf.read(SAMPLES / "phone-filtered.wav")
sf.write(SAMPLES / "phone-filtered.wav", noisy(phone, 8, 43), phone_sr, subtype="PCM_16")
ffmpeg("-i", SAMPLES / "phone-filtered.wav", "-ar", "16000", "-c:a", "pcm_s16le", SAMPLES / "long-phone.wav")
for name in ("long-clean", "long-noisy", "long-phone"):
    info = sf.info(SAMPLES / f"{name}.wav")
    print(f"{name}: {info.duration:.1f}s, {info.samplerate} Hz, {info.channels} channel")
