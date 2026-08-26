"""
YOLO model loading and inference.

Adapted from the teaching team's reference `main.py` snippet: load once at
import time, call `model.predict(...)` on an image, read boxes/classes/
confidence off the result, and use `result.plot()` for the annotated image.

The key change from the reference script: this is written to be called
from a thread pool (see main.py's use of `asyncio.to_thread`), since
`model.predict()` is a blocking, CPU-bound call and must never run directly
inside an `async def` route. That would stall the event loop for every
other concurrent request while inference runs.
"""

import io
import logging
import os

from PIL import Image

from .config import DETECTION_CONF_THRESHOLD, EMPTY_CLASS_ID, MODEL_PATH

logger = logging.getLogger("smartpark")

_model = None
_model_load_attempted = False


def _get_model():
    """
    Lazily load the model on first use (not at import time), so importing
    this module never fails just because the weights file isn't present
    yet. Callers fall back to a stub instead. Cached after first success.
    """
    global _model, _model_load_attempted
    if _model is not None or _model_load_attempted:
        return _model

    _model_load_attempted = True
    if not os.path.isfile(MODEL_PATH):
        logger.warning(
            "YOLO weights not found at %s, inference will use the random "
            "fallback until a model file is mounted there.",
            MODEL_PATH,
        )
        return None

    try:
        from ultralytics import YOLO  # imported lazily: heavy + optional until weights exist

        _model = YOLO(MODEL_PATH)
        logger.info("Loaded YOLO model from %s", MODEL_PATH)
    except Exception:
        logger.exception("Failed to load YOLO model from %s", MODEL_PATH)
        _model = None
    return _model


def model_available() -> bool:
    return _get_model() is not None


def run_inference(image_bytes: bytes) -> dict:
    """
    Blocking call. Run in a thread pool by the caller.

    Returns:
        {
            "available_spaces": int,
            "occupied_spaces": int,
            "confidence_score": float,       # mean confidence over empty-space detections
            "annotated_image_bytes": bytes,  # PNG, boxes drawn
        }
    """
    model = _get_model()
    if model is None:
        raise RuntimeError("YOLO model is not loaded")

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    results = model.predict(image, conf=DETECTION_CONF_THRESHOLD, verbose=False)
    result = results[0]

    empty_confidences = []
    occupied_count = 0

    for box in result.boxes:
        class_id = int(box.cls[0].item())
        conf = float(box.conf[0].item())
        if class_id == EMPTY_CLASS_ID:
            empty_confidences.append(conf)
        else:
            occupied_count += 1

    available_spaces = len(empty_confidences)
    confidence_score = round(sum(empty_confidences) / len(empty_confidences), 4) if empty_confidences else 0.0

    # result.plot() returns an RGB numpy array (BGR->RGB already handled the
    # way the reference script does it: result.plot()[:, :, ::-1])
    annotated_array = result.plot()[:, :, ::-1]
    annotated_image = Image.fromarray(annotated_array)
    buf = io.BytesIO()
    annotated_image.save(buf, format="PNG")

    return {
        "available_spaces": available_spaces,
        "occupied_spaces": occupied_count,
        "confidence_score": confidence_score,
        "annotated_image_bytes": buf.getvalue(),
    }
