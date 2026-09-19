# Locust load testing: 1 / 2 / 4 / 8 replicas

Setup (once): `pip install -r locust/requirements.txt`

## 1. Cluster

Keep the node count fixed at 2 for all four replica counts, so replica count is the only variable. `gcp/commands.md` creates the cluster with 2 nodes; confirm with `kubectl get nodes` (2 nodes, both `Ready`). If you have only 1 node, resize:

```bash
gcloud container clusters resize smartpark-cluster --node-pool default-pool --num-nodes=2 --zone australia-southeast1-a --quiet
```

Two `e2-standard-4` nodes cost about $0.38/hr: use for a focused session, then tear down (`gcp/teardown.md`). Delete the HPA first if applied (`kubectl delete -f k8s/hpa.yaml`), or it will change replica counts mid-test.

## 2. Per replica count (1, 2, 4, 8)

**a. Scale and wait.** Pods take a few minutes to become ready at higher counts (init container downloads the model, then the image pulls). Ctrl+C once every pod shows `1/1 Running`.

```bash
kubectl scale deployment smartpark-api --replicas=1
kubectl get pods -w
```

**b. Warm up.** Each pod pays a one-time YOLO model load (~10 s+) on its first request. An unwarmed pod would push that cost into the timed run and skew tail latency; at 4 replicas, 20 warm-up requests missed a pod and made max latency look worse than at 2 replicas. Send at least 10x the replica count in requests (1 → 10, 2 → 20, 4 → 40, 8 → 80). Load balancing is not perfectly even, so this makes it very likely, not certain, that every pod is hit. Use fresh uuids each time in case the user cache is on. If a result looks worse than a lower replica count, re-warm and re-run.

```bash
for i in $(seq 1 10); do curl -s -o /dev/null "http://EXTERNAL_IP/api/find-carparks?uuid=warmup-$i&n=2"; done            # bash
1..10 | ForEach-Object { curl.exe -s -o NUL "http://EXTERNAL_IP/api/find-carparks?uuid=warmup-$_&n=2" }                    # PowerShell
for /L %i in (1,1,10) do curl -s -o NUL "http://EXTERNAL_IP/api/find-carparks?uuid=warmup-%i&n=2"                          # cmd (use %%i in .bat)
```

Get the IP with `kubectl get service smartpark-api`. Change `10` to match the replica count.

**c. Run a test.** Two methods were used in the report:

- **Method B, concurrency sweep** (produced the report's table and plots): 90 s at each of 5, 10, 20 and 30 users, then a summary table and `locust/results/<label>_summary.csv`.

  ```bash
  python locust/run_sweep.py --host http://EXTERNAL_IP --label replicas_1 --users 5 10 20 30
  ```

- **Method A, fixed load** (showed the replicas=1 collapse at 30 users, 64.6% failures): one 2-minute run, 5 users/s ramp-up.

  ```bash
  locust -f locust/locustfile.py --host=http://EXTERNAL_IP -u 30 -r 5 --run-time 2m --headless --csv=locust/results/replicas_1
  ```

  This writes `*_stats.csv`, `*_stats_history.csv` and `*_failures.csv` (per-endpoint rows plus an `Aggregated` row with counts, median/p95/p99 and req/s). Change the `--csv` suffix for each replica count.

**Read req/s, not just failures.** Locust does not count requests still in flight at the end of a run as failures, so "0% failures" at high concurrency on a struggling config can mean almost nothing completed (`replicas=1`, 30 users: 0.03 req/s). `run_sweep.py` warns when a level completes zero requests. So "max sustainable users" is defined by a latency ceiling: the highest tested concurrency where average response stayed under 30 s and requests completed (`--latency-ceiling SECONDS` to change). This is the definition the report uses.

## 3. After all runs

1. Copy each run's `Max sustainable users` line and its average latency at that level into the report's results table.
2. From the project root, run `python locust/plot_results.py`. It writes `report/figure1_latency_vs_users.png` (average), `report/figure2_p95_latency_vs_users.png` (p95) and `report/figure3_throughput_vs_users.png`, one line per replica count with gaps where a level completed no requests.
3. Keep the CSVs in `locust/results/` so every report number traces to raw data.
4. Tear down: `gcp/teardown.md`, or scale the pool back to 1 node with `--num-nodes=1` in the resize command above.
