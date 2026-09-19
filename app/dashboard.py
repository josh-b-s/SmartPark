"""
Operations dashboard, rendered server-side as a single PNG.

Kept deliberately simple: a bar chart of the latest available-spaces reading
per carpark (same cache as OPS-API-1), plus a small text panel showing
the OPS-API-2 active user count and total request count. Refresh the page
to regenerate it with current numbers, no client-side JS or extra
framework needed.
"""

import io

import matplotlib

matplotlib.use("Agg")  # headless backend, no display available in the container
import matplotlib.pyplot as plt

from . import cache, carparks, request_log


def build_dashboard_png() -> bytes:
    ids = carparks.list_carpark_ids()
    readings = cache.snapshot()

    labels = []
    available = []
    for cid in ids:
        reading = readings.get(cid)
        if reading is None:
            continue  # not measured yet (background refresher still warming up)
        labels.append(cid.replace("CBD_", ""))
        available.append(reading["available_spaces"])

    using_fallback = any(r["source"] != "yolo" for r in readings.values())
    active_users = request_log.active_user_count()
    total_requests = request_log.total_request_count()

    fig, (ax_bar, ax_text) = plt.subplots(
        2, 1, figsize=(10, 7), gridspec_kw={"height_ratios": [4, 1]}
    )

    # Plot on numeric positions and label them ourselves. Passing the
    # "001"-style strings directly makes matplotlib guess they are numbers.
    positions = list(range(len(labels)))
    ax_bar.bar(positions, available, color="#3b82f6")
    ax_bar.set_xticks(positions)
    ax_bar.set_xticklabels(labels, rotation=45)
    title = "Available spaces per carpark (OPS-API-1, latest YOLO reading)"
    if using_fallback:
        title = "Available spaces per carpark (RANDOM FALLBACK DATA: no model loaded)"
    if not labels:
        title = "No readings yet, background refresher is still warming up"
    ax_bar.set_title(title)
    ax_bar.set_xlabel("Carpark ID (suffix)")
    ax_bar.set_ylabel("Available spaces")

    ax_text.axis("off")
    ax_text.text(
        0.0,
        0.5,
        f"Active users (last 30s, this pod): {active_users}    |    "
        f"Total requests logged: {total_requests}    |    "
        f"Carparks with readings: {len(labels)}/{len(ids)}",
        fontsize=12,
        va="center",
    )

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120)
    plt.close(fig)
    return buf.getvalue()
