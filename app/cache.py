"""
Two small in-memory caches (per pod).

1. Ops cache: the latest inference reading per car park. Every inference
   (find-carparks, annotate-carpark, background refresher) writes here, and
   OPS-API-1 plus the dashboard read from it, so they show real detections
   instead of running YOLO on every car park per request.

2. User cache: a short-TTL cache of find-carparks responses keyed on
   (uuid, n), for the "repeated requests from the same user can be cached"
   optimisation. Disabled when the TTL is 0.
"""

import time
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, List, Optional, Tuple

from .config import USER_CACHE_MAX_ENTRIES, USER_CACHE_TTL_SECONDS

_ops: Dict[str, dict] = {}
_ops_lock = Lock()


def store_reading(carpark_id: str, available_spaces: int, confidence_score: float, source: str) -> None:
    with _ops_lock:
        _ops[carpark_id] = {
            "available_spaces": available_spaces,
            "confidence_score": confidence_score,
            "source": source,
            "updated_at": time.time(),
        }


def get_reading(carpark_id: str) -> Optional[dict]:
    with _ops_lock:
        entry = _ops.get(carpark_id)
        return dict(entry) if entry else None


def snapshot() -> Dict[str, dict]:
    with _ops_lock:
        return {k: dict(v) for k, v in _ops.items()}


def is_stale(entry: Optional[dict], max_age_seconds: float) -> bool:
    return entry is None or (time.time() - entry["updated_at"]) > max_age_seconds


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


# --- per-user find-carparks cache -------------------------------------------

_user: Dict[Tuple[str, int], Tuple[float, List[dict]]] = {}
_user_lock = Lock()


def user_get(uuid: str, n: int) -> Optional[List[dict]]:
    if USER_CACHE_TTL_SECONDS <= 0:
        return None
    with _user_lock:
        item = _user.get((uuid, n))
        if item is None:
            return None
        expires_at, results = item
        if expires_at < time.time():
            del _user[(uuid, n)]
            return None
        return results


def user_put(uuid: str, n: int, results: List[dict]) -> None:
    if USER_CACHE_TTL_SECONDS <= 0:
        return
    now = time.time()
    with _user_lock:
        if len(_user) >= USER_CACHE_MAX_ENTRIES:
            # Drop expired entries first; if still full, evict the oldest.
            for key in [k for k, (exp, _) in _user.items() if exp < now]:
                del _user[key]
            while len(_user) >= USER_CACHE_MAX_ENTRIES:
                _user.pop(next(iter(_user)))
        _user[(uuid, n)] = (now + USER_CACHE_TTL_SECONDS, results)
