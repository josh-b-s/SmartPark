"""
Carpark "discovery" and simulated camera access.

Design decision (documented for the report/interview): rather than running
each carpark as a genuinely separate microservice, we simulate each carpark
as an entry in an in-memory registry, and its camera as a function that
returns a random image. This keeps the system simple for a single FastAPI
deployment while still satisfying "each car park exposes /api/takephoto":
that route exists below, parameterised by carpark_id, and could be split
into real per-carpark services later without changing the public API.

Nothing here calls YOLO directly, see model.py and infer_carpark() below
for that. fake_inference() is the fallback used when no model is loaded.
"""

import base64
import glob
import io
import os
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from PIL import Image

from .config import IMAGE_DATASET_DIR, NUM_CARPARKS


@dataclass
class Carpark:
    carpark_id: str
    name: str
    total_spaces: int = field(default_factory=lambda: random.randint(50, 200))


def _generate_carparks(n: int) -> Dict[str, Carpark]:
    carparks = {}
    for i in range(1, n + 1):
        cid = f"CBD_{i:03d}"
        carparks[cid] = Carpark(carpark_id=cid, name=f"Carpark {i}")
    return carparks


# Module-level registry, built once at startup. In a real deployment this
# could instead be loaded from a config file / database, see config.py.
CARPARKS: Dict[str, Carpark] = _generate_carparks(NUM_CARPARKS)


def list_carpark_ids() -> List[str]:
    return list(CARPARKS.keys())


def get_carpark(carpark_id: str) -> Optional[Carpark]:
    return CARPARKS.get(carpark_id)


def _placeholder_image_bytes() -> bytes:
    """A tiny solid-colour PNG, used only if no sample images are on disk yet."""
    img = Image.new("RGB", (64, 64), color=(random.randint(0, 255),) * 3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _dataset_image_paths() -> List[str]:
    if not os.path.isdir(IMAGE_DATASET_DIR):
        return []
    return glob.glob(os.path.join(IMAGE_DATASET_DIR, "*.jpg")) + glob.glob(
        os.path.join(IMAGE_DATASET_DIR, "*.png")
    )


def take_photo(carpark_id: str) -> bytes:
    """
    Simulates GET /api/takephoto on a carpark's camera: returns raw image
    bytes for a randomly chosen frame. Falls back to a generated placeholder
    if no sample images have been dropped into IMAGE_DATASET_DIR yet.
    """
    paths = _dataset_image_paths()
    if paths:
        with open(random.choice(paths), "rb") as f:
            return f.read()
    return _placeholder_image_bytes()


def image_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


def fake_inference(carpark: Carpark) -> tuple[int, float]:
    """
    Fallback used when no YOLO weights are available (see model.py) so the
    API keeps working end-to-end during local dev/testing without the
    (large) model file. Returns (available_spaces, confidence_score).
    """
    available = random.randint(0, carpark.total_spaces)
    confidence = round(random.uniform(0.85, 0.99), 3)
    return available, confidence


def infer_carpark(carpark_id: str) -> dict:
    """
    Blocking: takes a photo of the given carpark and runs real YOLO
    inference on it if a model is loaded, otherwise falls back to
    fake_inference(). Callers (main.py) MUST run this via
    `asyncio.to_thread` / a thread pool. Never call it directly inside an
    async route, since model.predict() is CPU-bound and blocks the event
    loop.

    Returns a dict shaped like model.run_inference()'s output, plus
    carpark_id, so callers don't need to branch on which path was taken.
    """
    from . import model as model_module  # local import avoids a hard dependency at module load time

    image_bytes = take_photo(carpark_id)

    if model_module.model_available():
        result = model_module.run_inference(image_bytes)
        result["carpark_id"] = carpark_id
        result["source"] = "yolo"
        return result

    carpark = get_carpark(carpark_id)
    available, confidence = fake_inference(carpark)
    return {
        "carpark_id": carpark_id,
        "available_spaces": available,
        "occupied_spaces": max(carpark.total_spaces - available, 0),
        "confidence_score": confidence,
        "annotated_image_bytes": image_bytes,  # raw frame, not actually annotated
        "source": "fallback_random",
    }
