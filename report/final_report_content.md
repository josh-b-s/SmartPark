## Empirical Benchmark Report

### 1. Results Table

Max sustainable concurrent users per replica count, defined as the
highest tested concurrency where average response stayed under 30s:

| Replicas | Max sustainable users | Avg response at that level |
|---|---|---|
| 1 | 10 | 25.8s |
| 2 | 10 | 15.7s |
| 4 | 20 | 28.4s |
| 8 | 20 | 25.3s |

All four configs showed 0% failures even at 30 users, but that's
misleading: at replicas=1, u=30, throughput collapsed to 0.03 req/s,
almost nothing completed. Failure rate alone doesn't capture a stalled
system, so the table uses a latency ceiling instead.

### 2. Graphical Plots

**Figure 1** (avg response time vs. concurrent users) and **Figure 2**
(throughput vs. concurrent users) attached, one line per replica count.

### 3. Performance Analysis

The service is CPU-bound: each `find-carparks` call runs `2*n` YOLO
inferences via `asyncio.to_thread`. A pod capped at 1 CPU took ~10.9s
per request; raising the CPU limit alone cut this to 7.6s, and moving
from `e2-medium`'s shared vCPUs to `e2-standard-4`'s dedicated cores cut
it to 4.4s, a 60% reduction from resource allocation alone, no code
changes.

Replica scaling showed three distinct effects. 1 to 2 replicas didn't
raise max concurrency (both cap at 10) but nearly halved latency (25.8s
to 15.7s) and eliminated the failure collapse seen at replicas=1 under
sustained load (64.6% failure rate). 2 to 4 doubled sustainable
concurrency (10 to 20). 4 to 8 didn't move it further, only a modest
latency gain.

This plateau reflects fixed node capacity: all tests ran on a 2-node,
8-vCPU cluster. HPA testing confirmed this: under load it scaled 1 to 4
to 8 replicas within 20 seconds, yet CPU utilisation stayed
150-1000%+ of target even at the ceiling, since 8 pods still share 8
physical cores. Horizontal scaling is bounded by node capacity, not a
substitute for provisioning adequate compute.

A code-level inefficiency was found: `run_inference()` always renders
and encodes an annotated image, even when `find-carparks` discards it,
pure wasted compute, left unfixed mid-benchmark to keep comparisons
valid.

### 4. Cost Analysis

**Cost to date:** GCP Billing confirms **$3.54** total, well under the
$20 guideline. Compute Engine $2.11, GKE management fee $0.77,
Persistent Disk $0.26, Load Balancing $0.21, small auto-enabled extras
$0.19, Storage ~$0.00. Compute and cluster management are over 80% of
spend, confirming node/cluster uptime, not storage or networking, is
the real cost driver, and that GKE has several small peripheral charges
beyond raw compute worth accounting for upfront.

**Estimated 20-minute demo cost**, same config ($0.191/hr/node,
~$0.025/hr LoadBalancer):

(2 x $0.191 + $0.025) x (20/60) ≈ **$0.14**
