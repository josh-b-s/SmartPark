## Empirical Benchmark Report

**System bottlenecks.** Profiling showed the service is entirely CPU-bound,
not I/O- or network-bound. A single `find-carparks` call runs `2*n` YOLO
inferences concurrently via `asyncio.to_thread`; on a pod capped at 1 CPU,
this produced ~10.9s latency, since six threads were forced to share one
core. Raising the pod's CPU limit alone (no other change) cut this to
7.6s, and switching from `e2-medium`'s shared/burstable vCPUs to
`e2-standard-4`'s dedicated cores cut it further to 4.4s, a 60% reduction
achieved purely through resource allocation. A second, code-level
bottleneck was found: `run_inference()` always renders and PNG-encodes an
annotated image, even when `find-carparks` discards it and only needs the
detection counts. This wastes compute on every call and is a clear
optimisation target we deliberately left unfixed mid-benchmark, to keep
replica comparisons valid.

**Horizontal scaling characteristics.** Locust testing (30 concurrent
users, 2-minute runs, fixed 2-node/8-vCPU cluster) across 1/2/4/8 replicas
produced a non-monotonic result that is the most important finding in
this report:

| Replicas | Failure rate | Throughput | Median | p99 |
|---|---|---|---|---|
| 1 | 64.6% | 0.41 req/s | 32.0s | 78.0s |
| 2 | 0% | 0.67 req/s | 37.0s | 58.0s |
| 4 | 0% | 0.75 req/s | 29.0s | 75.0s |
| 8 | 0% | 0.75 req/s | 29.0s | 70.0s |

Going from 1 to 2 replicas was the single most impactful change measured
anywhere in this project: it eliminated all request failures and lifted
throughput 63%. Beyond that, however, throughput plateaus flat at ~0.75
req/s from 4 to 8 replicas, and p99 latency actually *worsens* from 2 to 4
replicas before partially recovering at 8. This is because node count was
held fixed at 2 nodes throughout: adding pod replicas past that point
does not add CPU, it only adds more processes contending for the same
8 vCPUs, so scheduling overhead grows while real capacity does not. This
demonstrates that Kubernetes' horizontal pod scaling is not free
throughput; it is bounded by, and can be actively undermined by, the
underlying node pool's capacity.

**Cost.** Development and testing across `e2-medium` and `e2-standard-4`
node pools, plus a LoadBalancer Service and Artifact Registry storage,
stayed under $10 total. Discipline mattered more than instance choice:
the LoadBalancer alone runs ~$0.025/hr and a 2-node `e2-standard-4` pool
~$0.38/hr regardless of utilisation, so the largest cost risk was always
an idle cluster left running, not compute intensity during active tests.

**Processing efficiency and recommendations.** For a production
deployment, three changes would materially improve both cost and
performance: (1) skip annotation rendering in `find-carparks`, since it
is pure waste there; (2) cache `/api/ops/carparks` results on a short
refresh interval rather than running inference live, since it currently
does not scale past a handful of carparks; and (3) size the node pool to
the expected replica count *before* relying on horizontal scaling,
since our data shows extra replicas on a fixed node pool can worsen tail
latency rather than improve it. The clearest actionable insight from this
benchmarking exercise is that node capacity, not replica count, was the
true limiting resource once the system moved past a single point of
failure.

(≈500 words)
