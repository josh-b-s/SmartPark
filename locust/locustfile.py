"""
Load test for the SmartPark API, per the spec's Performance Benchmarking
requirement: simulate high-concurrency traffic and measure latency,
throughput, and failure rates.

Run against the cluster's external IP, not localhost, see
locust/README.md for the exact commands used for the 1/2/4/8 replica
comparison.

Task weights: find-carparks is the primary user-facing endpoint (the
"search for a carpark" flow), so it's weighted much higher than
annotate-carpark (a secondary "show me the detail image" flow a user
might occasionally follow up with).
"""

import random
import uuid

from locust import HttpUser, between, task

# Must match the deployed SMARTPARK_NUM_CARPARKS (default 20), or some ids will not exist.
CARPARK_IDS = [f"CBD_{i:03d}" for i in range(1, 21)]


class SmartParkUser(HttpUser):
    # Simulates a real user pausing between actions, e.g. glancing at
    # results before searching again, rather than hammering the API in a
    # tight loop. Keeps the load profile realistic rather than
    # artificially worst-case.
    wait_time = between(1, 3)

    def on_start(self):
        # One stable uuid per simulated user for the duration of the test,
        # mirroring how a real client would identify itself across
        # requests rather than generating a new id every call.
        self.user_uuid = str(uuid.uuid4())

    @task(5)
    def find_carparks(self):
        n = random.randint(1, 5)
        self.client.get(
            f"/api/find-carparks?uuid={self.user_uuid}&n={n}",
            name="/api/find-carparks",
        )

    @task(1)
    def annotate_carpark(self):
        carpark_id = random.choice(CARPARK_IDS)
        self.client.get(
            f"/api/annotate-carpark?carpark_id={carpark_id}",
            name="/api/annotate-carpark",
        )
