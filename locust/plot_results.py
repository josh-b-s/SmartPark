"""
Builds the report's figures from the sweep summaries written by run_sweep.py
(locust/results/replicas_<N>_summary.csv), one line per replica count:

    figure1_latency_vs_users.png       average response time vs concurrent users
    figure2_p95_latency_vs_users.png   95th percentile response time vs users
    figure3_throughput_vs_users.png    requests/second vs concurrent users

Levels where nothing completed have no latency (NaN) and are left as gaps
rather than drawn as zero.

Usage (from the project root):
    python locust/plot_results.py
    python locust/plot_results.py --results-dir locust/results --out-dir report
"""

import argparse
import csv
import glob
import math
import os
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def load_summaries(results_dir):
    """Returns {replica_count: [row dicts sorted by users]}."""
    data = {}
    for path in glob.glob(os.path.join(results_dir, "replicas_*_summary.csv")):
        match = re.search(r"replicas_(\d+)_summary\.csv$", path)
        if not match:
            continue
        with open(path, newline="", encoding="utf-8") as f:
            rows = [
                {
                    "users": int(r["users"]),
                    "avg_s": _num(r["avg_response_ms"]) / 1000,
                    "p95_s": _num(r["p95_ms"]) / 1000,
                    "rps": _num(r["requests_per_sec"]),
                }
                for r in csv.DictReader(f)
            ]
        data[int(match.group(1))] = sorted(rows, key=lambda r: r["users"])
    return dict(sorted(data.items()))


def plot(data, key, title, ylabel, out_path):
    fig, ax = plt.subplots(figsize=(7, 4.5))
    users_seen = set()
    for replicas, rows in data.items():
        xs = [r["users"] for r in rows]
        users_seen.update(xs)
        label = f"{replicas} replica" + ("" if replicas == 1 else "s")
        ax.plot(xs, [r[key] for r in rows], marker="o", label=label)
    ax.set_xticks(sorted(users_seen))
    ax.set_title(title)
    ax.set_xlabel("Concurrent users")
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"wrote {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default="locust/results")
    parser.add_argument("--out-dir", default="report")
    args = parser.parse_args()

    data = load_summaries(args.results_dir)
    if not data:
        raise SystemExit(
            f"No replicas_<N>_summary.csv files found in {args.results_dir}. "
            "Run locust/run_sweep.py for each replica count first."
        )
    os.makedirs(args.out_dir, exist_ok=True)
    plot(data, "avg_s", "Figure 1: Average response time vs concurrent users",
         "Average response time (s)", os.path.join(args.out_dir, "figure1_latency_vs_users.png"))
    plot(data, "p95_s", "Figure 2: p95 response time vs concurrent users",
         "95th percentile response time (s)", os.path.join(args.out_dir, "figure2_p95_latency_vs_users.png"))
    plot(data, "rps", "Figure 3: Throughput vs concurrent users",
         "Throughput (requests/second)", os.path.join(args.out_dir, "figure3_throughput_vs_users.png"))


if __name__ == "__main__":
    main()
