"""
Runs a sweep of short Locust tests at increasing concurrency levels
against a FIXED replica count (you set the replica count with `kubectl
scale` yourself before running this), then prints a summary table.

This produces the data the spec's benchmark report actually asks for:
"maximum users and average response time" per replica count, and enough
points to plot concurrent users vs. average latency as a curve, one curve
per replica count.

Usage:
    python locust/run_sweep.py --host http://EXTERNAL_IP --label replicas_1 --users 5 10 15 20 25 30

Each concurrency level runs for RUN_SECONDS with a short ramp, then the
next level starts. Results for each level are saved to
locust/results/<label>_u<N>_stats.csv, and a combined summary CSV is
written to locust/results/<label>_summary.csv.

"Max users" (for the report's Results Table) is defined here as the
highest tested concurrency level where the failure rate stayed under
FAILURE_THRESHOLD. Pick the threshold to match what you consider
"acceptable" service, the default (5%) is a reasonable, defensible
starting point, adjust it and note your reasoning in the report if you
change it.
"""

import argparse
import csv
import os
import subprocess
import sys

RUN_SECONDS = 45
SPAWN_RATE = 5
FAILURE_THRESHOLD = 0.05  # 5%


def run_one_level(host: str, label: str, users: int) -> dict:
    csv_prefix = f"locust/results/{label}_u{users}"
    cmd = [
        sys.executable, "-m", "locust",
        "-f", "locust/locustfile.py",
        "--host", host,
        "-u", str(users),
        "-r", str(SPAWN_RATE),
        "--run-time", f"{RUN_SECONDS}s",
        "--headless",
        "--csv", csv_prefix,
    ]
    print(f"\n=== Running u={users} for {RUN_SECONDS}s ===")
    subprocess.run(cmd, check=False)  # non-zero exit on failures is expected, not an error here

    stats_path = f"{csv_prefix}_stats.csv"
    with open(stats_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    agg = next(r for r in rows if r["Name"] == "Aggregated")

    request_count = int(agg["Request Count"])
    failure_count = int(agg["Failure Count"])
    failure_rate = (failure_count / request_count) if request_count else 1.0

    return {
        "users": users,
        "request_count": request_count,
        "failure_count": failure_count,
        "failure_rate": failure_rate,
        "avg_response_ms": float(agg["Average Response Time"]),
        "median_response_ms": float(agg["Median Response Time"]),
        "p95_ms": float(agg["95%"]),
        "p99_ms": float(agg["99%"]),
        "requests_per_sec": float(agg["Requests/s"]),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True, help="e.g. http://34.116.100.152")
    parser.add_argument("--label", required=True, help="e.g. replicas_1")
    parser.add_argument("--users", nargs="+", type=int, required=True, help="concurrency levels to test, e.g. 5 10 20 30")
    args = parser.parse_args()

    os.makedirs("locust/results", exist_ok=True)

    results = []
    for u in args.users:
        results.append(run_one_level(args.host, args.label, u))

    summary_path = f"locust/results/{args.label}_summary.csv"
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    print(f"\n=== Summary for {args.label} ===")
    print(f"{'Users':>6} {'Fail%':>7} {'Avg ms':>9} {'Median ms':>10} {'p95 ms':>8} {'p99 ms':>8} {'req/s':>7}")
    max_users_under_threshold = None
    for r in results:
        print(
            f"{r['users']:>6} {r['failure_rate']*100:>6.1f}% {r['avg_response_ms']:>9.0f} "
            f"{r['median_response_ms']:>10.0f} {r['p95_ms']:>8.0f} {r['p99_ms']:>8.0f} {r['requests_per_sec']:>7.2f}"
        )
        if r["failure_rate"] < FAILURE_THRESHOLD:
            max_users_under_threshold = r["users"]

    print(f"\nMax users under {FAILURE_THRESHOLD*100:.0f}% failure rate: {max_users_under_threshold}")
    print(f"Full summary saved to {summary_path}")


if __name__ == "__main__":
    main()
