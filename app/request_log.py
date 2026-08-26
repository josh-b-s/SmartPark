"""
Very simple in-memory request log, satisfying OPS-REQ-1 (log core-API
requests) and backing OPS-API-2 (active users in the last N seconds).

NOTE: in-memory is fine for a single-pod demo, but it means each pod has
its own view of "recent users" once you scale replicas > 1. Worth calling
out as a limitation in the benchmark report. A shared store (Redis) would
be the real fix, but is out of scope for this iteration.
"""

import time
from dataclasses import dataclass
from threading import Lock
from typing import List

from .config import ACTIVE_USER_WINDOW_SECONDS


@dataclass
class RequestLogEntry:
    timestamp: float
    uuid: str
    endpoint: str


_log: List[RequestLogEntry] = []
_lock = Lock()


def log_request(uuid: str, endpoint: str) -> None:
    with _lock:
        _log.append(RequestLogEntry(timestamp=time.time(), uuid=uuid, endpoint=endpoint))


def active_user_count(window_seconds: int = ACTIVE_USER_WINDOW_SECONDS) -> int:
    cutoff = time.time() - window_seconds
    with _lock:
        recent_uuids = {entry.uuid for entry in _log if entry.timestamp >= cutoff}
    return len(recent_uuids)


def total_request_count() -> int:
    with _lock:
        return len(_log)
