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

## 2. For each replica count: scale, warm up, run

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

### c. Send one warm-up request per pod

Each pod pays a one-time cold-start cost the first time it loads the
YOLO model (see the ~10s first-request latency we saw earlier).
Left unaddressed, this would make low-replica-count runs look
artificially slower than they really are, since a bigger fraction of
their pods would still be "cold" when the timed run starts. Fire off a
few requests per replica count to warm every pod before starting the
timed run:

```bash
for /L %i in (1,1,10) do curl "http://EXTERNAL_IP/api/find-carparks?uuid=warmup-%i&n=2"
```

(That's a Windows cmd.exe loop; in PowerShell use
`1..10 | ForEach-Object { curl "http://EXTERNAL_IP/api/find-carparks?uuid=warmup-$_&n=2" }`)

Since the Service load-balances across all Ready pods, sending 10
requests gives a good chance every pod has been hit at least once even
at replicas=8. Not guaranteed, LoadBalancer routing isn't strictly
round-robin, but close enough for this purpose.

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

## 3. After all four runs

Each `*_stats.csv` has a row per endpoint plus an `Aggregated` row with
request count, failure count, median/p95/p99 latency, and requests/second,
exactly what the spec's benchmark report asks for (latency, throughput,
failure rates). Pull the `Aggregated` row from each of the four files to
build your comparison chart.

## 4. Teardown

```bash
gcloud container clusters resize smartpark-cluster --node-pool default-pool --num-nodes=1 --zone australia-southeast1-a --quiet
```

or delete the whole cluster if you're done for the day, see
`gcp/teardown.md`.
