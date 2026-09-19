"""
Background task that keeps the ops cache (OPS-API-1 and the dashboard) fresh.

Every OPS_REFRESH_SECONDS it looks for car parks whose cached reading is
missing or older than that, and re-runs inference on them one at a time
(sequentially, so it never adds more than one worker thread of CPU load).
Readings produced by user traffic also update the cache, so under load
there is almost nothing left for this task to do.
"""

import asyncio
import logging

from . import cache, carparks
from .config import OPS_REFRESH_SECONDS

logger = logging.getLogger("smartpark")


async def refresh_stale_once() -> int:
    """One pass. Returns how many car parks were refreshed."""
    refreshed = 0
    for cid in carparks.list_carpark_ids():
        if not cache.is_stale(cache.get_reading(cid), OPS_REFRESH_SECONDS):
            continue
        try:
            await carparks.infer_carpark(cid, annotate=False)
            refreshed += 1
        except Exception:
            logger.exception("request_id=ops-refresher carpark_id=%s refresh failed", cid)
    return refreshed


async def run_forever() -> None:
    logger.info("request_id=ops-refresher started, interval=%ss", OPS_REFRESH_SECONDS)
    # Startup runs before uvicorn has bound its port, and the default camera
    # URL points back at this same server, so give it a moment first.
    await asyncio.sleep(3)
    while True:
        try:
            count = await refresh_stale_once()
            if count:
                logger.info("request_id=ops-refresher refreshed %d car parks", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("request_id=ops-refresher pass failed")
        await asyncio.sleep(OPS_REFRESH_SECONDS)
