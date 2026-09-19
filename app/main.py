import asyncio
import contextlib
import logging
import random
import time
import uuid as uuid_module
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from . import cache, carparks, dashboard, refresher, request_log
from .config import MAX_N, OPS_REFRESH_SECONDS, USER_CACHE_TTL_SECONDS
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



@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if OPS_REFRESH_SECONDS > 0:
        task = asyncio.create_task(refresher.run_forever())
    else:
        logger.info("Ops refresher disabled (SMARTPARK_OPS_REFRESH_SECONDS=0)")
    logger.info(
        "Started: %d car parks, user_cache_ttl=%ss, ops_refresh=%ss",
        len(carparks.list_carpark_ids()), USER_CACHE_TTL_SECONDS, OPS_REFRESH_SECONDS,
    )
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await carparks.close_client()


app = FastAPI(title="SmartPark API", version="0.2.0", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    OPS-REQ: comprehensive application logging. Every request, on every
    endpoint, gets one structured log line with a timestamp (from
    logging's own formatter), severity level, service name ("smartpark",
    set in the formatter below), and a unique id for tracing this specific
    request through the logs.

    Uses the caller-supplied `uuid` query param when present (so a
    find-carparks call's log line matches the user's own uuid, useful for
    correlating a specific user's activity), otherwise generates one, so
    every request is traceable even on endpoints that don't take a uuid
    (annotate-carpark, ops endpoints, healthz).
    """
    request_id = request.query_params.get("uuid") or str(uuid_module.uuid4())
    start = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.exception(
            "request_id=%s method=%s path=%s status=500 duration_ms=%.1f (unhandled exception)",
            request_id, request.method, request.url.path, elapsed_ms,
        )
        raise

    elapsed_ms = (time.perf_counter() - start) * 1000
    log_fn = logger.info if response.status_code < 400 else logger.warning
    log_fn(
        "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
        request_id, request.method, request.url.path, response.status_code, elapsed_ms,
    )
    return response


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
        logger.warning("request_id=%s requested n=%s > MAX_N=%s, clamping", uuid, n, MAX_N)
        n = MAX_N

    # Repeat requests from the same user (same uuid and n) within the TTL
    # are answered from cache. Off by default (TTL 0), see config.py.
    cached = cache.user_get(uuid, n)
    if cached is not None:
        logger.info("request_id=%s find-carparks served from user cache", uuid)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return FindCarparksResponse(
            uuid=uuid, status="success", msg="success",
            speed_inference=f"{elapsed_ms:.1f} ms", requested_n=n,
            results=[CarparkResult(**r) for r in cached],
        )

    all_ids = carparks.list_carpark_ids()
    if not all_ids:
        raise HTTPException(status_code=503, detail="No carparks configured")

    # Spec requirement: query at least 2*n random carparks before returning
    # the top n.
    sample_size = min(len(all_ids), 2 * n)
    sampled_ids = random.sample(all_ids, sample_size)

    # For each sampled carpark: HTTP GET to its camera (async), then YOLO
    # inference in a worker thread (CPU-bound, so it must stay off the event
    # loop). gather() runs all sampled carparks concurrently. annotate=False
    # because this endpoint never returns the annotated image.
    outcomes = await asyncio.gather(
        *[carparks.infer_carpark(cid, annotate=False) for cid in sampled_ids],
        return_exceptions=True,
    )

    inference_results = []
    for cid, outcome in zip(sampled_ids, outcomes):
        if isinstance(outcome, Exception):
            logger.error("request_id=%s carpark_id=%s inference failed: %s", uuid, cid, outcome)
        else:
            inference_results.append(outcome)

    if not inference_results:
        elapsed_ms = (time.perf_counter() - start) * 1000
        body = FindCarparksResponse(
            uuid=uuid, status="error",
            msg="All sampled car park cameras failed, please retry",
            speed_inference=f"{elapsed_ms:.1f} ms", requested_n=n, results=[],
        )
        return JSONResponse(status_code=503, content=body.model_dump())

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
    cache.user_put(uuid, n, [r.model_dump() for r in top_n])

    failed = len(sampled_ids) - len(inference_results)
    msg = "success" if not failed else f"partial: {failed} of {len(sampled_ids)} cameras failed"
    elapsed_ms = (time.perf_counter() - start) * 1000

    return FindCarparksResponse(
        uuid=uuid,
        status="success",
        msg=msg,
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

    try:
        result = await carparks.infer_carpark(carpark_id, annotate=True)
    except carparks.CameraError as exc:
        logger.error("request_id=annotate carpark_id=%s camera failed: %s", carpark_id, exc)
        body = AnnotateCarparkResponse(
            carpark_id=carpark_id, status="error",
            msg=f"Camera unavailable: {exc}", image_base64="",
        )
        return JSONResponse(status_code=502, content=body.model_dump())

    return AnnotateCarparkResponse(
        carpark_id=carpark_id,
        status="success",
        msg="success",
        image_base64=carparks.image_to_base64(result["annotated_image_bytes"]),
    )


@app.get("/api/takephoto", response_model=TakePhotoResponse)
def takephoto(carpark_id: str = Query(..., description="Which car park's camera to read")):
    """
    Simulated car park camera: GET /api/takephoto returns a base64 image
    picked at random from the dataset. The platform reaches it with a real
    HTTP GET using each car park's camera_url (see carparks.py). By default
    that URL points back at this route, but it can point at any host.
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
    OPS-API-1: all carparks with their latest available-spaces reading.

    Reads the per-pod ops cache, which is filled by real YOLO inference:
    from user traffic (find-carparks / annotate-carpark) and from a
    background refresher (refresher.py) that re-checks any car park whose
    reading is older than SMARTPARK_OPS_REFRESH_SECONDS. This endpoint never
    runs inference itself, so it stays cheap however many car parks exist.
    A car park with no reading yet shows available_spaces null.
    """
    readings = cache.snapshot()
    results = []
    for cid in carparks.list_carpark_ids():
        carpark = carparks.get_carpark(cid)
        reading = readings.get(cid)
        if reading is None:
            results.append(OpsCarpark(carpark_id=cid, name=carpark.name))
        else:
            results.append(
                OpsCarpark(
                    carpark_id=cid,
                    name=carpark.name,
                    available_spaces=reading["available_spaces"],
                    confidence_score=reading["confidence_score"],
                    last_updated=cache.iso(reading["updated_at"]),
                    source=reading["source"],
                )
            )
    return OpsCarparksResponse(status="success", carparks=results)


@app.get("/ops/dashboard")
def ops_dashboard():
    """
    Renders the operations dashboard as a PNG. Reload the page/URL to
    regenerate with current numbers. Uses the same cached readings as
    OPS-API-1, see the note on that endpoint for how they are kept fresh.
    """
    png_bytes = dashboard.build_dashboard_png()
    return Response(content=png_bytes, media_type="image/png")


@app.get("/api/ops/active-users", response_model=OpsActiveUsersResponse)
def ops_active_users():
    """OPS-API-2: distinct users seen in the last N seconds, from the request log."""
    from .config import ACTIVE_USER_WINDOW_SECONDS

    count = request_log.active_user_count()
    return OpsActiveUsersResponse(
        status="success",
        window_seconds=ACTIVE_USER_WINDOW_SECONDS,
        active_user_count=count,
    )
