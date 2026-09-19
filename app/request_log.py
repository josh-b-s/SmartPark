"""
In-memory request log, satisfying OPS-REQ-1 (log core-API requests) and
backing OPS-API-2 (active users in the last N seconds).

Entries older than REQUEST_LOG_RETENTION_SECONDS are pruned on every write
and read, so memory stays bounded however long the pod runs. A separate
counter keeps the lifetime total, since pruned entries no longer count.

NOTE: this is per pod. With replicas > 1 each pod has its own view of
"recent users", because the Service load-balances requests across pods. A
shared store (e.g. Redis) would be the real fix and is out of scope.
"""

import time
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Deque

from .config import ACTIVE_USER_WINDOW_SECONDS, REQUEST_LOG_RETENTION_SECONDS


@dataclass
class RequestLogEntry:
    timestamp: float
    uuid: str
    endpoint: str


_log: Deque[RequestLogEntry] = deque()
_total = 0
_lock = Lock()


def _prune(now: float) -> None:
    # Caller must hold _lock. Entries are appended in time order, so the
    # oldest are always at the left.
    retention = max(REQUEST_LOG_RETENTION_SECONDS, ACTIVE_USER_WINDOW_SECONDS)
    cutoff = now - retention
    while _log and _log[0].timestamp < cutoff:
        _log.popleft()


def log_request(uuid: str, endpoint: str) -> None:
    global _total
    now = time.time()
    with _lock:
        _log.append(RequestLogEntry(timestamp=now, uuid=uuid, endpoint=endpoint))
        _total += 1
        _prune(now)


def active_user_count(window_seconds: int = ACTIVE_USER_WINDOW_SECONDS) -> int:
    now = time.time()
    cutoff = now - window_seconds
    with _lock:
        _prune(now)
        recent_uuids = {e.uuid for e in _log if e.timestamp >= cutoff}
    return len(recent_uuids)


def total_request_count() -> int:
    """Lifetime number of logged requests (not reduced by pruning)."""
    with _lock:
        return _total


def retained_entry_count() -> int:
    with _lock:
        return len(_log)
