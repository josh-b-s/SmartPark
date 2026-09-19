# SmartPark: FastAPI + YOLO car park availability service

A REST API that samples simulated car park cameras, runs YOLO to count empty spaces, and returns the best `n` car parks. Runs locally, in Docker, or on GKE.

## Not included in the zip

- **`images/`** (~200 MB, teaching-team photos): put the `.jpg`/`.png` files directly in `images/` at the project root. The Dockerfile copies this folder, so it must exist to build (an empty folder works; `/api/takephoto` then serves generated placeholders).
- **`model/model.pt`** (~3 GB, YOLO weights): for local and Docker runs, place it at `model/model.pt`. On GKE, upload it to the model bucket (`gcp/commands.md` step 3); an init container downloads it at pod start. Without weights the app still starts but returns random fallback numbers (log: `YOLO weights not found`).

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Keep port 8000: cameras are reached at `SMARTPARK_CAMERA_BASE_URL` (default `http://127.0.0.1:8000`). If you change the port, set that variable to match. API docs: http://127.0.0.1:8000/docs

```bash
curl "http://127.0.0.1:8000/api/find-carparks?uuid=abc-123&n=3"
curl "http://127.0.0.1:8000/api/annotate-carpark?carpark_id=CBD_001"
curl "http://127.0.0.1:8000/api/ops/carparks"
curl "http://127.0.0.1:8000/api/ops/active-users"
python view_annotated.py CBD_001      # saves annotated_CBD_001.png
```

## Endpoints

| Endpoint | Spec | Behaviour |
|---|---|---|
| `GET /api/find-carparks?uuid=&n=` | CORE-API-1 | Samples `2*n` random car parks, fetches each image over HTTP, runs YOLO concurrently, returns the top `n` by available spaces. `n` is clamped to `MAX_N` (answer to "what if n > 100?"). Partial camera failures are answered from the rest (`msg` reports the count); if all fail, HTTP 503. |
| `GET /api/annotate-carpark?carpark_id=` | CORE-API-2 | Base64 PNG with YOLO boxes drawn (HTTP 502 if the camera is unreachable). |
| `GET /api/takephoto?carpark_id=` | Camera | Simulated camera: random image from the image folder, or a generated placeholder. Called over HTTP via each car park's `camera_url`. |
| `GET /api/ops/carparks` | OPS-API-1 | Latest reading per car park: `available_spaces`, `confidence_score`, `last_updated`, `source` (`yolo` or `fallback_random`). `available_spaces` is `null` until the first reading. |
| `GET /api/ops/active-users` | OPS-API-2 | Users in the last 30 s, from the in-memory request log (`app/request_log.py`, OPS-REQ-1). |
| `GET /ops/dashboard` | OPS-REQ-2 | Server-rendered matplotlib PNG: available spaces per car park plus active-user and total request counts. Reload to refresh. |
| `GET /healthz` | Probe | Kubernetes liveness/readiness target. |

## Configuration

All settings are environment variables. On Kubernetes they come from the `smartpark-config` ConfigMap; after editing, run `kubectl apply -f k8s/configmap.yaml && kubectl rollout restart deployment smartpark-api`.

| Variable | Default | Meaning |
|---|---|---|
| `SMARTPARK_NUM_CARPARKS` | 20 | Car parks to generate (10-99, otherwise the app refuses to start). |
| `SMARTPARK_CARPARK_CONFIG` | unset | Path to a JSON file defining car parks explicitly. |
| `SMARTPARK_CAMERA_BASE_URL` | `http://127.0.0.1:8000` | Base URL for generated cameras. |
| `SMARTPARK_MAX_N` | 20 | Largest `n` accepted by `find-carparks`. |
| `SMARTPARK_USER_CACHE_TTL` | 0 (off) | Seconds to cache a `find-carparks` answer per (`uuid`, `n`). |
| `SMARTPARK_OPS_REFRESH_SECONDS` | 60 | Background refresh interval for OPS-API-1 and the dashboard (0 disables). |
| `SMARTPARK_LOG_RETENTION` | 300 | Seconds of request-log history kept in memory. |
| `SMARTPARK_EMPTY_CLASS_ID` | 0 | YOLO class id meaning "empty space" (0 = empty, 1 = occupied, per the PKLot label conversion in the notebook). |

**Car park discovery.** At startup, car parks are either generated (`CBD_001`...`CBD_0NN`, camera URL `<CAMERA_BASE_URL>/api/takephoto?carpark_id=<id>`) or loaded from a JSON list of 10-99 objects where only `carpark_id` is required:

```json
[{"carpark_id": "MEL_01", "name": "Melbourne Central", "camera_url": "http://cam-01.internal/api/takephoto", "total_spaces": 120}]
```

On Kubernetes, put the JSON under a `carparks.json: |` key in `k8s/configmap.yaml`, mount it in `k8s/deployment.yaml` (a `configMap` volume at `/app/config`, merged into the existing `volumes` and `volumeMounts`), and set `SMARTPARK_CARPARK_CONFIG=/app/config/carparks.json`. Locally, just set the variable to the file path. Pointing a `camera_url` at another host needs no code change.

## Caching and performance

- **Ops cache** (`app/cache.py`): every inference result updates the latest reading per car park. OPS-API-1 and the dashboard only read this cache, so they never run YOLO. A background refresher re-checks only readings older than `SMARTPARK_OPS_REFRESH_SECONDS`, one at a time, so it does almost nothing under user load.
- **User cache**: with `SMARTPARK_USER_CACHE_TTL` > 0, a repeat `find-carparks` with the same `uuid` and `n` skips fetching and inference. It is off by default so Locust runs (one uuid per simulated user) stay comparable. To demo it, set the ConfigMap value to e.g. `"10"`, restart, and call the same URL twice: `speed_inference` drops below a millisecond.
- **Non-blocking inference**: `carparks.infer_carpark()` fetches the photo with async HTTP, then runs blocking YOLO in a worker thread via `asyncio.to_thread`. `find-carparks` uses `asyncio.gather` across the `2*n` sampled car parks. This avoids blocking the event loop, as the spec warns.
- **`annotate=False`**: `find-carparks` skips drawing and PNG-encoding the annotated image, since it is never returned there; only `annotate-carpark` pays that cost.
- **Model loading**: `app/model.py` loads weights lazily on first use from `model/model.pt` (`SMARTPARK_MODEL_PATH`). Without weights it falls back to `carparks.fake_inference()`.

## Logging

A FastAPI middleware in `main.py` logs every request as one structured line: timestamp and severity (Python logging formatter), service name `smartpark`, `request_id` (the caller's `uuid` when present, otherwise generated), method, path, status and duration in ms. Unhandled exceptions are logged with a traceback via `logger.exception`. On GKE, stdout is collected by Cloud Logging automatically.

## Design notes (interview prep)

- **Cameras are simulated inside the same app.** Each car park has a `camera_url`, served by the app's own `/api/takephoto`, but reached with a real HTTP GET, so the code path is identical to a separate camera. Because they are in-process, loopback camera calls share pod CPU with inference.
- **Request log, ops cache and user cache are per pod.** With several replicas, OPS-API-2 and the ops readings only reflect requests that pod handled. The log is pruned to `SMARTPARK_LOG_RETENTION` seconds (plus a separate lifetime counter). A shared store such as Redis is the real fix, out of scope here.
- **OPS-API-1 never runs inference.** It stays cheap with up to 99 car parks; the trade-off is readings up to about `SMARTPARK_OPS_REFRESH_SECONDS` old, or missing briefly after startup.

## Run with Docker

Build from the project root (the folder containing `Dockerfile`, `app/`, `images/`):

```bash
docker build -t smartpark-api .
```

Mount the weights at run time so they are not baked into the image (swap the file and restart; no rebuild):

```bash
docker run -p 8000:8000 -v "$(pwd)/model:/app/model" smartpark-api            # bash
docker run -p 8000:8000 -v "${PWD}\model:/app/model" smartpark-api            # PowerShell
docker run -p 8000:8000 -v "%cd%\model:/app/model" smartpark-api              # cmd
```

Without a mounted model the container runs with random fallback numbers. The `HEALTHCHECK` hits `/healthz`; `docker ps` should show "healthy" after ~10 s. The image is large because `ultralytics` pulls in `torch` (a few hundred MB to a couple of GB), which matters for push and pull time.

## Deploy to GKE

**Substitute your own values first.** The files contain the author's project ID (`smartpark-fit3184-508304`), region (`australia-southeast1`) and bucket (`smartpark-fit3184-508304-smartpark-model`). Bucket names are globally unique. Replace the bucket first, since it contains the project ID:

```bash
grep -rl "smartpark-fit3184-508304" k8s gcp README.md | xargs sed -i \
  -e 's/smartpark-fit3184-508304-smartpark-model/YOUR_BUCKET_NAME/g' \
  -e 's/smartpark-fit3184-508304/YOUR_PROJECT_ID/g'
```

- `gcp/commands.md`: full copy-paste sequence (project setup, image push, cluster, deploy). Region and zone are defined at its top.
- `gcp/teardown.md`: run at the end of every session; the cluster and load balancer bill hourly.
- **Updatable model**: `model.pt` is not in the image. An init container in `k8s/deployment.yaml` downloads it from GCS into a shared volume before the app starts. To swap models, re-upload to the bucket and run `kubectl rollout restart deployment smartpark-api`.
- **Resources**: each pod requests 250m CPU / 1Gi memory and is limited to 4 CPU / 2Gi, so many pods schedule while one can burst to a whole node under load.
- **Autoscaling**: `k8s/hpa.yaml` (CPU-based) was tested: under load it scaled 1 → 4 → 8 replicas in about 20 s. It is not applied by default because it fights manual `kubectl scale` during benchmarks. Use `kubectl apply -f k8s/hpa.yaml` for the demo; before benchmarking run `kubectl delete -f k8s/hpa.yaml && kubectl scale deployment smartpark-api --replicas=1`.

## Load testing (Locust)

`locust/locustfile.py` simulates users calling `find-carparks` (weight 5) and `annotate-carpark` (weight 1). `locust/run_sweep.py` runs several concurrency levels against one fixed replica count:

```bash
python locust/run_sweep.py --host http://EXTERNAL_IP --label replicas_1 --users 5 10 20 30
```

Full procedure, including per-replica warm-up, is in `locust/README.md`. "Max sustainable users" is the highest tested concurrency where average response time stayed under 30 s (`--latency-ceiling`); raw results are in `locust/results/`.

## Benchmark report

The submitted PDF report uses two plots, included in `report/`: `figure1_latency_vs_users.png` (average latency) and `figure2_p95_latency_vs_users.png` (p95 latency). `python locust/plot_results.py` regenerates both from `locust/results/`, plus a throughput plot (`figure3_throughput_vs_users.png`, not included).

Headline findings: 1 → 2 replicas removed the failure collapse seen at 1 replica under load but did not raise max sustainable concurrency (both 10); 2 → 4 doubled it (10 → 20); 4 → 8 did not move it further. That plateau points to the fixed 2-node, 8-vCPU cluster, not replica count, as the ceiling.

## Known limitations

- Request log, ops cache and user cache are per pod (see design notes).
- **The benchmarks predate three changes present in this code:** `annotate=False` in `find-carparks`, the background ops refresher, and fetching camera images over HTTP. To measure the current code, re-run the sweep with `SMARTPARK_USER_CACHE_TTL` at 0.
