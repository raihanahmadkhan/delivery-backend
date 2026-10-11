import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient

from main import app


def wait(client, identity):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        job = client.get(f"/api/runs/{identity}").json()
        if job["status"] not in ("queued", "running"):
            assert job["status"] == "completed", job
            return job
        time.sleep(0.2)
    raise AssertionError("Worker did not complete within the smoke-test deadline")


def main():
    with (
        tempfile.TemporaryDirectory(prefix="routelab-smoke-") as directory,
        patch.dict(
            os.environ,
            {
                "ROUTELAB_DB": str(Path(directory) / "smoke.sqlite3"),
                "ROUTELAB_EMBEDDED_WORKER": "1",
            },
        ),
        TestClient(app, base_url="http://127.0.0.1") as client,
    ):
        scenario = client.get("/api/presets/tiny").json()
        response = client.post(
            "/api/runs",
            json={
                "scenario": scenario,
                "options": {"algorithm": "exact", "time_limit_seconds": 1},
            },
        )
        assert response.status_code == 202, response.text
        run = wait(client, response.json()["id"])
        assert run["result"]["evaluation"]["feasible"] and run["result"]["proven_optimal"]
        experiment = client.post(
            "/api/experiments",
            json={
                "scenario": scenario,
                "algorithms": ["greedy", "alns"],
                "seeds": [11],
                "time_limit_seconds": 0.2,
                "iterations": 10,
            },
        )
        assert experiment.status_code == 202, experiment.text
        batch = wait(client, experiment.json()["id"])
        assert len(batch["result"]["trials"]) == 2
        replan = client.post(
            "/api/replans",
            json={
                "parent_job_id": run["id"],
                "delay_minutes": 5,
                "options": {"time_limit_seconds": 0.2, "iterations": 10},
            },
        )
        assert replan.status_code == 202, replan.text
        repaired = wait(client, replan.json()["id"])
        assert repaired["result"]["disruption"]["delay_minutes"] == 5
        assert client.get(f"/api/runs/{run['id']}/export?format=csv").status_code == 200
        print("PASS: API -> SQLite -> spawned worker -> exact run, experiment, replan, and export")


if __name__ == "__main__":
    main()
