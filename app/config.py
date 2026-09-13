"""
Central configuration for the SmartPark service.

Keeping this in one place makes it easy to override via environment
variables later (e.g. when we containerise / deploy to Kubernetes) without
touching business logic.
"""

import os

# How many simulated car parks exist in this deployment. The spec requires
# this to be configurable in the range 10-99.
NUM_CARPARKS = int(os.environ.get("SMARTPARK_NUM_CARPARKS", "20"))

# Where the sample car-park images live. Each file here is treated as a
# possible "camera frame" that a carpark's /takephoto endpoint can return.
# Defaults to the top-level images/ folder from the teaching team's
# reference project (release/images), since that's already populated.
# Override with SMARTPARK_IMAGE_DIR if you keep images somewhere else.
IMAGE_DATASET_DIR = os.environ.get(
    "SMARTPARK_IMAGE_DIR",
    os.path.join(os.path.dirname(__file__), "..", "images"),
)

# Safety cap so a malicious/huge `n` in /api/find-carparks can't force the
# service to iterate over an absurd number of "carparks" per request.
MAX_N = int(os.environ.get("SMARTPARK_MAX_N", "20"))

# How far back (seconds) OPS-API-2 looks when counting "active" users.
ACTIVE_USER_WINDOW_SECONDS = int(os.environ.get("SMARTPARK_ACTIVE_WINDOW", "30"))

# Path to the trained YOLO weights (.pt). Deliberately NOT baked into the
# Docker image later, this gets mounted/downloaded at container startup,
# per the assignment's "updatable model" requirement. If the file doesn't
# exist, the app falls back to fake_inference() so you can still run/test
# everything locally without the (large) weights file.
MODEL_PATH = os.environ.get(
    "SMARTPARK_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "..", "model", "model.pt"),
)

# Per the PKLot label conversion used to train this model (see notebook):
# class 0 = empty/available space, class 1 = occupied.
EMPTY_CLASS_ID = int(os.environ.get("SMARTPARK_EMPTY_CLASS_ID", "0"))

# Minimum confidence for a detected box to be counted at all.
DETECTION_CONF_THRESHOLD = float(os.environ.get("SMARTPARK_CONF_THRESHOLD", "0.25"))
