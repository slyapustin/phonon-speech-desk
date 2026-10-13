"""Download/load the official model and report the actual runtime, without audio."""
import json
import os
from pathlib import Path

root = Path(__file__).resolve().parent
os.environ.setdefault("HF_HOME", str(root / ".cache/huggingface"))
os.environ.setdefault("FERMION_CACHE_DIR", str(root / ".cache/fermion"))
os.environ["FERMION_DEVICE"] = "mlx"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import fermion
import mlx.core as mx

speech = fermion.load_speech("phonon-2", quiet=False)
print(json.dumps({"engine": speech.describe(), "device": mx.device_info()}, indent=2))
