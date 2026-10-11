import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routelab import store
from routelab.models import RunOptions, RunRequest
from routelab.presets import get_scenario


def until(predicate, seconds=35):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError("Lifecycle condition did not become true before its deadline")


def main():
    workers = []
    with tempfile.TemporaryDirectory(prefix="routelab-lifecycle-") as directory:
        root = Path(directory)
        with patch.dict(os.environ, {"ROUTELAB_DB": str(root / "jobs.sqlite3")}):
            store.initialize()

            def start():
                stop = root / f"stop-{len(workers)}"
                env = {
                    **os.environ,
                    "ROUTELAB_PARENT_PID": str(os.getpid()),
                    "ROUTELAB_STOP_FILE": str(stop),
                }
                process = subprocess.Popen(
                    [sys.executable, "-B", "-m", "routelab.worker"],
                    cwd=Path(__file__).resolve().parents[1],
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                workers.append((process, stop))
                return process, stop

            def enqueue(slow=False):
                body = RunRequest(
                    scenario=get_scenario("scattered" if slow else "tiny"),
                    options=RunOptions(
                        algorithm="alns" if slow else "exact",
                        time_limit_seconds=8 if slow else 1,
                        iterations=10000,
                    ),
                ).model_dump()
                return store.enqueue("run", body)

            def active(identity):
                job = store.get_job(identity)
                return job["status"] == "running" and job["progress"] is not None

            def complete(identity):
                job = store.get_job(identity)
                if job["status"] in ("failed", "cancelled"):
                    raise AssertionError(job)
                return job if job["status"] == "completed" else None

            try:
                queued = enqueue()
                store.cancel(queued)
                assert store.claim() is None
                worker, stop = start()
                running = enqueue(True)
                until(lambda: active(running))
                store.cancel(running)
                until(lambda: store.get_job(running)["status"] == "cancelled", 8)
                print("PASS: queued and running cancellation", flush=True)

                interrupted = enqueue(True)
                until(lambda: active(interrupted))
                stop.touch()
                worker.wait(timeout=8)
                assert store.get_job(interrupted)["status"] == "queued"
                worker, stop = start()
                restored = until(lambda: complete(interrupted))
                assert restored["attempts"] == 2
                print("PASS: graceful shutdown releases claim and restart completes it", flush=True)

                crashed = enqueue(True)
                until(lambda: active(crashed))
                worker.kill()  # Only the supervisor spawned by this test.
                worker.wait(timeout=5)
                # Its CPU child detects the dead supervisor and releases the lease;
                # expiry is the fallback if the child was also abruptly terminated.
                until(lambda: store.get_job(crashed)["status"] == "queued", 25)
                worker, stop = start()
                recovered = until(lambda: complete(crashed))
                assert recovered["attempts"] == 2
                print("PASS: abrupt supervisor death and orphan-child recovery", flush=True)

                start()
                identities = [enqueue() for _ in range(6)]
                results = [
                    until(lambda identity=identity: complete(identity)) for identity in identities
                ]
                assert all(
                    job["attempts"] == 1 and job["result"]["proven_optimal"] for job in results
                )
                assert store.get_job(queued)["status"] == "cancelled"
                with store.connection() as connection:
                    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                print(
                    "PASS: two real workers, six exclusive claims, certified results, database integrity",
                    flush=True,
                )
            finally:
                for process, marker in workers:
                    marker.touch()
                    if process.poll() is None:
                        try:
                            process.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)


if __name__ == "__main__":
    main()
