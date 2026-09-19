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

# Optional JSON file describing the car parks (id, name, camera_url,
# total_spaces). When set and present, it replaces the generated registry.
# In Kubernetes, mount it from a ConfigMap (see k8s/configmap.yaml). Leave
# unset to generate NUM_CARPARKS car parks instead.
CARPARK_CONFIG_PATH = os.environ.get("SMARTPARK_CARPARK_CONFIG", "")

# The spec requires the number of car parks to be configurable in 10-99.
MIN_CARPARKS = 10
MAX_CARPARKS = 99

# Base URL of the (simulated) car park cameras. Each generated car park's
# camera_url is <base>/api/takephoto?carpark_id=<id>. The platform makes a
# real HTTP GET to it. The default points at this same app's simulator route
# on port 8000, which is correct in Docker and GKE. Running uvicorn on a
# different port locally means setting this to match.
CAMERA_BASE_URL = os.environ.get("SMARTPARK_CAMERA_BASE_URL", "http://127.0.0.1:8000")
CAMERA_TIMEOUT_SECONDS = float(os.environ.get("SMARTPARK_CAMERA_TIMEOUT", "10"))

# Per-user response cache for /api/find-carparks, keyed on (uuid, n). 0 turns
# it off. It is off by default so benchmark runs stay comparable, since
# Locust users repeat their uuid and would otherwise hit the cache.
USER_CACHE_TTL_SECONDS = float(os.environ.get("SMARTPARK_USER_CACHE_TTL", "0"))
USER_CACHE_MAX_ENTRIES = int(os.environ.get("SMARTPARK_USER_CACHE_MAX", "10000"))

# Background refresher for OPS-API-1 / the dashboard: every N seconds it
# re-runs inference on car parks whose cached reading is older than N seconds.
# Readings produced by find-carparks also feed this cache, so under load the
# refresher has almost nothing to do. 0 disables it.
OPS_REFRESH_SECONDS = float(os.environ.get("SMARTPARK_OPS_REFRESH_SECONDS", "60"))

# How long request-log entries are kept (seconds). Must be >= the active
# user window. Older entries are pruned, so memory stays bounded.
REQUEST_LOG_RETENTION_SECONDS = int(os.environ.get("SMARTPARK_LOG_RETENTION", "300"))

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
