"""
Car park registry, simulated cameras, and the inference pipeline.

Discovery / configuration: the registry is built once at startup from either
  1. a JSON file (SMARTPARK_CARPARK_CONFIG), a list of objects with
     carpark_id, and optionally name, camera_url and total_spaces, or
  2. SMARTPARK_NUM_CARPARKS generated entries (default 20).
In Kubernetes both come from a ConfigMap (k8s/configmap.yaml). The number of
car parks must be within 10-99 (spec), or the app refuses to start.

Cameras: every car park has a camera_url, and the platform fetches the
image with a real HTTP GET, as in the architecture diagram. By default
camera_url points at this app's own simulator route (GET /api/takephoto in
main.py), which returns a random image from the dataset. Pointing
camera_url at another host needs no code change.

The pipeline is: fetch_photo() (async HTTP) -> infer_image() (blocking, run
in a worker thread via asyncio.to_thread) -> result also written to the ops
cache so OPS-API-1 and the dashboard reflect real detections.
"""

import asyncio
import base64
import glob
import io
import json
import logging
import os
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx
from PIL import Image

from . import cache
from .config import (
    CAMERA_BASE_URL,
    CAMERA_TIMEOUT_SECONDS,
    CARPARK_CONFIG_PATH,
    IMAGE_DATASET_DIR,
    MAX_CARPARKS,
    MIN_CARPARKS,
    NUM_CARPARKS,
)

logger = logging.getLogger("smartpark")


class CameraError(Exception):
    """The car park's camera could not be reached or returned bad data."""


@dataclass
class Carpark:
    carpark_id: str
    name: str
    camera_url: str
    total_spaces: int = field(default_factory=lambda: random.randint(50, 200))


def _default_camera_url(carpark_id: str) -> str:
    return f"{CAMERA_BASE_URL.rstrip('/')}/api/takephoto?carpark_id={carpark_id}"


def _generate_carparks(n: int) -> Dict[str, Carpark]:
    carparks = {}
    for i in range(1, n + 1):
        cid = f"CBD_{i:03d}"
        carparks[cid] = Carpark(
            carpark_id=cid, name=f"Carpark {i}", camera_url=_default_camera_url(cid)
        )
    return carparks


def _load_carparks_from_file(path: str) -> Dict[str, Carpark]:
    with open(path, encoding="utf-8") as f:
        entries = json.load(f)
    if not isinstance(entries, list):
        raise ValueError(f"{path} must contain a JSON list of car park objects")
    carparks: Dict[str, Carpark] = {}
    for entry in entries:
        cid = entry["carpark_id"]
        if cid in carparks:
            raise ValueError(f"Duplicate carpark_id '{cid}' in {path}")
        kwargs = {}
        if "total_spaces" in entry:
            kwargs["total_spaces"] = int(entry["total_spaces"])
        carparks[cid] = Carpark(
            carpark_id=cid,
            name=entry.get("name", cid),
            camera_url=entry.get("camera_url") or _default_camera_url(cid),
            **kwargs,
        )
    return carparks


def _build_registry() -> Dict[str, Carpark]:
    if CARPARK_CONFIG_PATH and os.path.isfile(CARPARK_CONFIG_PATH):
        registry = _load_carparks_from_file(CARPARK_CONFIG_PATH)
        logger.info("Loaded %d car parks from %s", len(registry), CARPARK_CONFIG_PATH)
    else:
        if CARPARK_CONFIG_PATH:
            logger.warning(
                "SMARTPARK_CARPARK_CONFIG=%s not found, generating %d car parks instead",
                CARPARK_CONFIG_PATH, NUM_CARPARKS,
            )
        registry = _generate_carparks(NUM_CARPARKS)

    if not (MIN_CARPARKS <= len(registry) <= MAX_CARPARKS):
        raise ValueError(
            f"Number of car parks must be between {MIN_CARPARKS} and {MAX_CARPARKS}, "
            f"got {len(registry)}"
        )
    return registry


# Built once at startup.
CARPARKS: Dict[str, Carpark] = _build_registry()


def list_carpark_ids() -> List[str]:
    return list(CARPARKS.keys())


def get_carpark(carpark_id: str) -> Optional[Carpark]:
    return CARPARKS.get(carpark_id)


# --- camera simulator (backs GET /api/takephoto in main.py) -----------------

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
    What a car park's camera does when it receives GET /api/takephoto:
    return a randomly chosen frame from the dataset (a placeholder if the
    dataset folder is empty). Only the camera simulator route calls this.
    """
    paths = _dataset_image_paths()
    if paths:
        with open(random.choice(paths), "rb") as f:
            return f.read()
    return _placeholder_image_bytes()


def image_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


# --- platform side: HTTP GET to the camera ----------------------------------

_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=CAMERA_TIMEOUT_SECONDS)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def fetch_photo(carpark_id: str) -> bytes:
    """HTTP GET to the car park's camera; returns the decoded image bytes."""
    carpark = get_carpark(carpark_id)
    if carpark is None:
        raise CameraError(f"Unknown carpark_id '{carpark_id}'")
    try:
        resp = await _get_client().get(carpark.camera_url)
        resp.raise_for_status()
        return base64.b64decode(resp.json()["image_base64"])
    except Exception as exc:  # network error, bad status, bad JSON, bad base64
        raise CameraError(f"camera for {carpark_id} failed: {exc!r}") from exc


# --- inference ---------------------------------------------------------------

def fake_inference(carpark: Carpark) -> tuple[int, float]:
    """
    Fallback used when no YOLO weights are available (see model.py) so the
    API keeps working end-to-end during local dev/testing without the
    (large) weights file. Returns (available_spaces, confidence_score).
    """
    available = random.randint(0, carpark.total_spaces)
    confidence = round(random.uniform(0.85, 0.99), 3)
    return available, confidence


def infer_image(carpark_id: str, image_bytes: bytes, annotate: bool = False) -> dict:
    """
    Blocking: runs real YOLO inference on the image if a model is loaded,
    otherwise falls back to fake_inference(). MUST be run in a worker thread
    (asyncio.to_thread), because model.predict() is CPU-bound.

    annotate=False skips drawing/encoding the annotated image, which
    find-carparks never uses (only annotate-carpark does).

    The reading is also stored in the ops cache.
    """
    from . import model as model_module  # local import avoids a hard dependency at module load time

    if model_module.model_available():
        result = model_module.run_inference(image_bytes, annotate=annotate)
        result["source"] = "yolo"
    else:
        carpark = get_carpark(carpark_id)
        available, confidence = fake_inference(carpark)
        result = {
            "available_spaces": available,
            "occupied_spaces": max(carpark.total_spaces - available, 0),
            "confidence_score": confidence,
            "annotated_image_bytes": image_bytes if annotate else None,  # raw frame, not annotated
            "source": "fallback_random",
        }

    result["carpark_id"] = carpark_id
    cache.store_reading(
        carpark_id, result["available_spaces"], result["confidence_score"], result["source"]
    )
    return result


async def infer_carpark(carpark_id: str, annotate: bool = False) -> dict:
    """Fetch a photo over HTTP, then run inference in a worker thread."""
    image_bytes = await fetch_photo(carpark_id)
    return await asyncio.to_thread(infer_image, carpark_id, image_bytes, annotate)
