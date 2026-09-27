"""Concurrency probe against a running API.

Not a benchmark suite, just enough to find where the ceiling is: closed-loop
load at a fixed concurrency, reporting latency percentiles and error counts per
endpoint. Run against a live server, not the test client.
"""

import argparse
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict

BASE = "http://127.0.0.1:8010"

SCENARIOS = {
    # What a browsing user hits on load.
    "browse": ["/restaurants?limit=48", "/stats", "/filter-options"],
    # The heaviest read: origin present, so every match is scored in Python.
    "nearby": [
        "/restaurants?origin_lat=12.9915&origin_lon=77.552&sort=distance&limit=48"
    ],
    # The whole-city map payload, for comparison with the viewport one.
    "map": ["/restaurants/points?sort=name"],
    # What the map actually asks for now: only the visible area.
    "map-view": [
        "/restaurants/points?sort=name&south=12.97&west=77.53&north=13.02&east=77.58"
    ],
    # Text search on the cached index.
    "craving": ["/search/craving?q=biryani"],
    # A write, which is what SQLite serialises.
    "write": ["/auth/login"],
}


def call(path: str, timeout: float = 30.0):
    started = time.perf_counter()
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=b'{"email":"asha@example.com","password":"password123"}'
        if path == "/auth/login"
        else None,
        headers={"Content-Type": "application/json"} if path == "/auth/login" else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        exc.read()
        status = exc.code
    except Exception as exc:  # noqa: BLE001 - the point is to record the failure
        status = f"ERR {type(exc).__name__}"
    return (time.perf_counter() - started) * 1000, status


def run(scenario: str, workers: int, seconds: float) -> dict:
    paths = SCENARIOS[scenario]
    samples: list[float] = []
    statuses: dict[str, int] = defaultdict(int)
    lock = threading.Lock()
    stop = time.perf_counter() + seconds
    counter = {"n": 0}

    def worker(seed: int) -> None:
        index = seed
        while time.perf_counter() < stop:
            path = paths[index % len(paths)]
            index += 1
            elapsed, status = call(path)
            with lock:
                samples.append(elapsed)
                statuses[str(status)] += 1
                counter["n"] += 1

    threads = [
        threading.Thread(target=worker, args=(i,), daemon=True) for i in range(workers)
    ]
    began = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    wall = time.perf_counter() - began

    ordered = sorted(samples)
    return {
        "scenario": scenario,
        "workers": workers,
        "requests": counter["n"],
        "rps": round(counter["n"] / wall, 1),
        "p50": round(statistics.median(ordered), 1),
        "p95": round(ordered[int(len(ordered) * 0.95)], 1),
        "p99": round(ordered[int(len(ordered) * 0.99)], 1),
        "max": round(ordered[-1], 1),
        "statuses": dict(sorted(statuses.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("scenarios", nargs="*", default=["browse"])
    args = parser.parse_args()

    print(
        f"{'scenario':10} {'workers':>7} {'reqs':>6} {'rps':>7} {'p50':>8} {'p95':>8} {'p99':>8} {'max':>8}  statuses"
    )
    for scenario in args.scenarios:
        result = run(scenario, args.workers, args.seconds)
        print(
            f"{result['scenario']:10} {result['workers']:7d} {result['requests']:6d} "
            f"{result['rps']:7.1f} {result['p50']:8.1f} {result['p95']:8.1f} "
            f"{result['p99']:8.1f} {result['max']:8.1f}  {result['statuses']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
