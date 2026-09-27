"""Storage and CPU ceilings, measured without HTTP in the way.

Answers two questions the HTTP probe cannot separate:
  1. How many write commits per second can this database actually sustain?
  2. Is the heavy read path bound by the GIL (one core) or by the database?

Run against a copy of the real database; it only ever inserts and rolls back.
"""

import argparse
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "tabiko.db"


def copy_db() -> Path:
    # NamedTemporaryFile(delete=False) so the copy can be reopened by name, then
    # the placeholder is removed: copy() would otherwise write into a live handle
    # and the workers would open a different file than the one written.
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        path = Path(handle.name)
    shutil.copy(SOURCE, path)
    return path


def measure_writes(
    path: Path, journal: str, synchronous: str, threads: int, seconds: float
):
    # journal_mode is persistent and needs a brief exclusive lock, so it is set
    # once up front. Setting it from every thread deadlocks on its own lock.
    setup = sqlite3.connect(path, timeout=30.0)
    setup.execute(f"PRAGMA journal_mode={journal}")
    setup.execute(
        "CREATE TABLE IF NOT EXISTS probe (id INTEGER PRIMARY KEY, payload TEXT)"
    )
    setup.commit()
    setup.close()

    barrier = threading.Barrier(threads)
    stop = time.perf_counter() + seconds
    counts = [0] * threads
    errors = [0] * threads

    def worker(slot: int) -> None:
        conn = sqlite3.connect(path, timeout=5.0, check_same_thread=False)
        # synchronous is per connection and takes no database lock.
        conn.execute(f"PRAGMA synchronous={synchronous}")
        conn.execute("PRAGMA busy_timeout=5000")
        barrier.wait()
        index = 0
        while time.perf_counter() < stop:
            index += 1
            try:
                conn.execute(
                    "INSERT INTO probe (payload) VALUES (?)", (f"x{index}" * 40,)
                )
                conn.commit()
                counts[slot] += 1
            except sqlite3.OperationalError:
                errors[slot] += 1
                # A locked database means back off, exactly as a real writer must.
                time.sleep(0.005)
        conn.close()

    workers = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
    began = time.perf_counter()
    for thread in workers:
        thread.start()
    for thread in workers:
        thread.join()
    wall = time.perf_counter() - began
    return sum(counts) / wall, sum(errors)


def measure_gil() -> None:
    """Does the heavy read path use more than one core?

    Two threads each run the same pure-Python work the proximity sort does. If
    the GIL is the constraint, two threads take roughly twice as long as one.
    """

    def haversine_sort(n: int) -> float:
        rows = [(12.9 + i / 100_000, 77.5 + i / 100_000) for i in range(n)]
        origin = (12.9915, 77.5520)
        for lat, lon in rows:
            phi1, phi2 = 0.2269, lat * 0.01745
            d_phi = (lat - origin[0]) * 0.01745
            d_lam = (lon - origin[1]) * 0.01745
            a = (
                __import__("math").sin(d_phi / 2) ** 2
                + __import__("math").cos(phi1)
                * __import__("math").cos(phi2)
                * __import__("math").sin(d_lam / 2) ** 2
            )
            __import__("math").asin(min(1.0, a**0.5))
        return float(len(rows))

    for threads in (1, 2, 4):
        began = time.perf_counter()
        workers = [
            threading.Thread(target=haversine_sort, args=(7728,))
            for _ in range(threads)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        elapsed = time.perf_counter() - began
        print(
            f"  {threads} thread(s) x 7,728 distance computations: "
            f"{elapsed * 1000:7.1f} ms  "
            f"({threads / elapsed:5.1f} x throughput vs 1 thread)"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--seconds", type=float, default=4.0)
    args = parser.parse_args()

    print(f"source database: {SOURCE.name}")
    print()
    print("write commits per second (the storage ceiling):")
    for journal in ("delete", "wal"):
        for synchronous in ("FULL", "NORMAL"):
            path = copy_db()
            try:
                rate, errors = measure_writes(
                    path, journal, synchronous, args.threads, args.seconds
                )
                print(
                    f"  journal={journal:6} synchronous={synchronous:6} "
                    f"writers={args.threads:3}  {rate:8.0f} writes/s  "
                    f"({errors} lock errors)"
                )
            finally:
                os.unlink(path)

    print()
    print("CPU scaling of the proximity sort (is the GIL the limit?):")
    measure_gil()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
