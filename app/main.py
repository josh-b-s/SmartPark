import asyncio
import logging
import random
import time

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response

from . import carparks, dashboard, request_log
from .config import MAX_N
from .schemas import (
    AnnotateCarparkResponse,
    CarparkResult,
    FindCarparksResponse,
    OpsActiveUsersResponse,
    OpsCarpark,
    OpsCarparksResponse,
    TakePhotoResponse,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s smartpark %(message)s",
)
logger = logging.getLogger("smartpark")

app = FastAPI(title="SmartPark API", version="0.1.0")


@app.get("/healthz")
def healthz():
    """Liveness/readiness probe target for Kubernetes (added now so it's not forgotten later)."""
    return {"status": "ok"}


@app.get("/api/find-carparks", response_model=FindCarparksResponse)
async def find_carparks(
    uuid: str = Query(..., description="Unique id for the requesting user/session"),
    n: int = Query(..., ge=1, description="Number of top carparks to return"),
):
    start = time.perf_counter()
    request_log.log_request(uuid=uuid, endpoint="find-carparks")

    if n > MAX_N:
        # "what if n > 100?" - the spec explicitly asks us to think about
        # this. We clamp rather than error, so well-behaved clients still
        # get a usable (if smaller) response instead of a hard failure.
        logger.warning("uuid=%s requested n=%s > MAX_N=%s, clamping", uuid, n, MAX_N)
        n = MAX_N

    all_ids = carparks.list_carpark_ids()
    if not all_ids:
        raise HTTPException(status_code=503, detail="No carparks configured")

    # Spec requirement: query at least 2*n random carparks before returning
    # the top n.
    sample_size = min(len(all_ids), 2 * n)
    sampled_ids = random.sample(all_ids, sample_size)

    # Run YOLO inference for each sampled carpark concurrently in worker
    # threads. carparks.infer_carpark() is a blocking, CPU-bound call.
    # asyncio.to_thread keeps it off the event loop so other requests
    # (including other users' find-carparks calls) aren't stalled while
    # this one's inference runs. gather() also lets the sampled carparks'
    # inference happen in parallel rather than one-by-one.
    inference_results = await asyncio.gather(
        *[asyncio.to_thread(carparks.infer_carpark, cid) for cid in sampled_ids]
    )

    scored = [
        CarparkResult(
            carpark_id=r["carpark_id"],
            name=carparks.get_carpark(r["carpark_id"]).name,
            available_spaces=r["available_spaces"],
            confidence_score=r["confidence_score"],
        )
        for r in inference_results
    ]

    top_n = sorted(scored, key=lambda r: r.available_spaces, reverse=True)[:n]
    elapsed_ms = (time.perf_counter() - start) * 1000

    return FindCarparksResponse(
        uuid=uuid,
        status="success",
        msg="success",
        speed_inference=f"{elapsed_ms:.1f} ms",
        requested_n=n,
        results=top_n,
    )


@app.get("/api/annotate-carpark", response_model=AnnotateCarparkResponse)
async def annotate_carpark(carpark_id: str = Query(...)):
    carpark = carparks.get_carpark(carpark_id)
    if carpark is None:
        return AnnotateCarparkResponse(
            carpark_id=carpark_id,
            status="error",
            msg=f"Unknown carpark_id '{carpark_id}'",
            image_base64="",
        )

    # Off the event loop, same reasoning as find_carparks above.
    result = await asyncio.to_thread(carparks.infer_carpark, carpark_id)
    return AnnotateCarparkResponse(
        carpark_id=carpark_id,
        status="success",
        msg="success",
        image_base64=carparks.image_to_base64(result["annotated_image_bytes"]),
    )


@app.get("/api/carparks/{carpark_id}/takephoto", response_model=TakePhotoResponse)
def takephoto(carpark_id: str):
    """
    Simulates a car park's own camera endpoint. In the architecture diagram
    this is a separate device the platform polls; here it's just a route on
    the same app for simplicity (see docstring in carparks.py).
    """
    carpark = carparks.get_carpark(carpark_id)
    if carpark is None:
        raise HTTPException(status_code=404, detail=f"Unknown carpark_id '{carpark_id}'")

    image_bytes = carparks.take_photo(carpark_id)
    return TakePhotoResponse(
        carpark_id=carpark_id,
        image_base64=carparks.image_to_base64(image_bytes),
    )


@app.get("/api/ops/carparks", response_model=OpsCarparksResponse)
def ops_carparks():
    """
    OPS-API-1: all carparks + current available spots.

    Deliberately uses fake_inference() here rather than running real YOLO
    inference on every carpark on every ops call. With up to 99 carparks
    configured, that would mean up to 99 blocking model.predict() calls per
    dashboard refresh, which doesn't scale. A real version of this should
    read from a periodically-refreshed cache (e.g. a background task that
    re-runs inference on each carpark every N seconds and stores the
    result) rather than doing it live. Worth implementing as the
    "repeated requests can be cached" optimisation the spec asks about.
    """
    results = []
    for cid in carparks.list_carpark_ids():
        carpark = carparks.get_carpark(cid)
        available, _ = carparks.fake_inference(carpark)
        results.append(
            OpsCarpark(carpark_id=cid, name=carpark.name, available_spaces=available)
        )
    return OpsCarparksResponse(status="success", carparks=results)


@app.get("/ops/dashboard")
def ops_dashboard():
    """
    Renders the operations dashboard as a PNG. Reload the page/URL to
    regenerate with current numbers. Uses the same fake_inference() data
    source as OPS-API-1, see the note on that endpoint above for why real
    per-carpark inference isn't run live here.
    """
    png_bytes = dashboard.build_dashboard_png()
    return Response(content=png_bytes, media_type="image/png")
def ops_active_users():
    """OPS-API-2: distinct users seen in the last N seconds, from the request log."""
    from .config import ACTIVE_USER_WINDOW_SECONDS

    count = request_log.active_user_count()
    return OpsActiveUsersResponse(
        status="success",
        window_seconds=ACTIVE_USER_WINDOW_SECONDS,
        active_user_count=count,
    )
