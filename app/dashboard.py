"""
Operations dashboard, rendered server-side as a single PNG.

Kept deliberately simple: a bar chart of current available spaces per
carpark (same data source as OPS-API-1), plus a small text panel showing
the OPS-API-2 active user count and total request count. Refresh the page
to regenerate it with current numbers, no client-side JS or extra
framework needed.
"""

import io

import matplotlib

matplotlib.use("Agg")  # headless backend, no display available in the container
import matplotlib.pyplot as plt

from . import carparks, request_log


def build_dashboard_png() -> bytes:
    ids = carparks.list_carpark_ids()
    names = []
    available = []
    for cid in ids:
        carpark = carparks.get_carpark(cid)
        spaces, _ = carparks.fake_inference(carpark)
        names.append(cid.replace("CBD_", ""))
        available.append(spaces)

    active_users = request_log.active_user_count()
    total_requests = request_log.total_request_count()

    fig, (ax_bar, ax_text) = plt.subplots(
        2, 1, figsize=(10, 7), gridspec_kw={"height_ratios": [4, 1]}
    )

    ax_bar.bar(names, available, color="#3b82f6")
    ax_bar.set_title("Available spaces per carpark (OPS-API-1)")
    ax_bar.set_xlabel("Carpark ID (suffix)")
    ax_bar.set_ylabel("Available spaces")
    ax_bar.tick_params(axis="x", rotation=45)

    ax_text.axis("off")
    ax_text.text(
        0.0,
        0.5,
        f"Active users (last 30s): {active_users}    |    "
        f"Total requests logged: {total_requests}    |    "
        f"Carparks tracked: {len(ids)}",
        fontsize=12,
        va="center",
    )

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120)
    plt.close(fig)
    return buf.getvalue()
