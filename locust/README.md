# Locust load testing: 1 / 2 / 4 / 8 replica comparison

## Setup (once)

```bash
pip install -r locust/requirements.txt
```

## 1. Add a second node before testing

Keeping node count fixed across all four replica counts means replica
count is the only thing changing between runs, so the comparison is
actually meaningful, one node's worth of CPU is shared across whatever
number of replicas are scheduled on it.

```bash
gcloud container clusters resize smartpark-cluster --node-pool default-pool --num-nodes=2 --zone australia-southeast1-a --quiet
```

Wait for it to finish, then confirm:

```bash
kubectl get nodes
```

Should show 2 nodes, both `Ready`.

Note the cost bump: 2x `e2-standard-4` is about $0.38/hr combined. Fine
for a focused test session, don't leave it running afterward, see
`gcp/teardown.md`.

## 2. Two testing methods, both used in this project's final report

**Method A (fixed load)** below shows the dramatic replicas=1 failure
collapse under a constant 30-user load (64.6% failure rate), the
clearest way to see a single replica overwhelmed.

**Method B (concurrency sweep, below)** using `run_sweep.py` is what
actually produced the report's required results table and the two
latency/throughput plots, since those need data across multiple
concurrency levels per replica count, not one fixed point.

## Method A: fixed load, one point per replica count

Repeat this block four times, once each for `--replicas=1`, `2`, `4`,
`8`. Get your service's external IP first if you don't have it handy:

```bash
kubectl get service smartpark-api
```

### a. Scale to the target replica count

```bash
kubectl scale deployment smartpark-api --replicas=1
```

### b. Wait for all pods to be Running and Ready

```bash
kubectl get pods -w
```

Ctrl+C once every pod for this replica count shows `1/1 Running`. This
can take a few minutes at higher replica counts, each pod's init
container has to download the model from GCS, and each main container
has to pull the image, before it's ready.

### c. Send warm-up requests, enough to statistically cover every pod

Each pod pays a one-time cold-start cost the first time it loads the
YOLO model (see the ~10s+ first-request latency we saw earlier, worse
under concurrent load). Left unaddressed, a pod that never gets a
warm-up hit will eat that cold-start cost during the timed run instead,
badly skewing your tail latency numbers, this is exactly what happened
during initial testing at replicas=4: 20 warm-up requests weren't enough
to statistically guarantee all 4 pods got hit at least once (GKE's Service
load-balancing across pods isn't perfectly even), and the result was a
worse max latency at 4 replicas than at 2, which doesn't reflect a real
capacity problem, just an under-warmed pod.

Rule of thumb: send at least 10x the replica count in warm-up requests
to make it very likely every pod's been hit at least once.

Pick the loop for your shell, and change `10` to the request count for
your replica count (see the table below). Use a fresh set of uuids each
time, or the user cache (if you have turned it on) would answer repeats
without touching the model.

bash / zsh / Git Bash:

```bash
for i in $(seq 1 10); do curl -s -o /dev/null "http://EXTERNAL_IP/api/find-carparks?uuid=warmup-$i&n=2"; done
```

PowerShell:

```powershell
1..10 | ForEach-Object { curl.exe -s -o NUL "http://EXTERNAL_IP/api/find-carparks?uuid=warmup-$_&n=2" }
```

Windows cmd.exe:

```bat
for /L %i in (1,1,10) do curl -s -o NUL "http://EXTERNAL_IP/api/find-carparks?uuid=warmup-%i&n=2"
```

(In a `.bat` file, write `%%i` instead of `%i`.)

Replica count -> suggested warm-up request count:
- 1 replica: 10 requests
- 2 replicas: 20 requests
- 4 replicas: 40 requests
- 8 replicas: 80 requests

Since the Service load-balances across all Ready pods, this gives a
statistically good (not guaranteed) chance every pod's been warmed. Not
strictly guaranteed, LoadBalancer routing isn't perfectly round-robin,
but close enough for this purpose. If a replica count's results look
anomalously worse than a lower replica count's, re-warm with more
requests and rerun before trusting the number.

### d. Run the timed load test

```bash
locust -f locust/locustfile.py --host=http://EXTERNAL_IP -u 30 -r 5 --run-time 2m --headless --csv=locust/results/replicas_1
```

- `-u 30`: 30 simulated concurrent users
- `-r 5`: ramp up 5 users/second
- `--run-time 2m`: run for 2 minutes
- `--csv=locust/results/replicas_1`: writes
  `replicas_1_stats.csv`, `replicas_1_stats_history.csv`, and
  `replicas_1_failures.csv`

Change the `--csv` suffix (`replicas_2`, `replicas_4`, `replicas_8`) each
time so results don't overwrite each other.

Each `*_stats.csv` has a row per endpoint plus an `Aggregated` row with
request count, failure count, median/p95/p99 latency, and requests/second.

## Method B: concurrency sweep (produces the report's table and plots)

After warming up a given replica count (same warm-up step as Method A
above), run one command instead of a single fixed Locust invocation:

```bash
python locust/run_sweep.py --host http://EXTERNAL_IP --label replicas_1 --users 5 10 20 30
```

This runs 90-second tests at each concurrency level in sequence (5, 10,
20, 30 users), and prints a summary table plus saves
`locust/results/replicas_1_summary.csv`. Repeat for `replicas_2`,
`replicas_4`, `replicas_8` (with the matching warm-up request count
first each time).

Watch the `req/s` column, not just failure rate, alongside average
latency: Locust doesn't count a request still in-flight when the test
ends as a failure, so at very high concurrency on a struggling
configuration, `0% failures` can mean "almost nothing completed at all"
rather than genuine success, `run_sweep.py` prints a warning when a
level completes zero requests. "Max sustainable users" is therefore defined
by a latency ceiling: the highest tested concurrency where the average
response time stayed under 30s and requests actually completed. That is the
`Max sustainable users` line the script prints (change the ceiling with
`--latency-ceiling SECONDS`), and it is the definition the report uses.

## 3. After all runs

Once `replicas_1`, `replicas_2`, `replicas_4` and `replicas_8` each have a
`*_summary.csv` in `locust/results/`:

1. Copy the `Max sustainable users` line and the average-latency figure at
   that level from each run into the report's results table.
2. Generate the figures (run from the project root):

   ```bash
   python locust/plot_results.py
   ```

   This writes `report/figure1_latency_vs_users.png` (average latency),
   `report/figure2_p95_latency_vs_users.png` (p95 latency) and
   `report/figure3_throughput_vs_users.png` (throughput), one line per replica
   count, with gaps where a level completed no requests.
3. Keep the CSVs in `locust/results/` so the report numbers can be traced to
   the raw data.
4. Tear down (next section) so the cluster stops billing.

## 4. Teardown

```bash
gcloud container clusters resize smartpark-cluster --node-pool default-pool --num-nodes=1 --zone australia-southeast1-a --quiet
```

or delete the whole cluster if you're done for the day, see
`gcp/teardown.md`.
