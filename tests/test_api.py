import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from routelab import store
from routelab.presets import get_scenario


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="routelab-api-")
        self.environment = patch.dict(
            os.environ,
            {
                "ROUTELAB_DB": str(Path(self.directory.name) / "test.sqlite3"),
                "ROUTELAB_EMBEDDED_WORKER": "0",
            },
        )
        self.environment.start()
        store.initialize()

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def test_blank_idempotency_header_can_submit_multiple_runs(self):
        with TestClient(app, base_url="http://localhost") as client:
            body = {"scenario": get_scenario("tiny").model_dump()}
            responses = [
                client.post("/api/runs", json=body, headers={"Idempotency-Key": ""})
                for _ in range(2)
            ]
            self.assertEqual([response.status_code for response in responses], [202, 202])
            self.assertNotEqual(responses[0].json()["id"], responses[1].json()["id"])

    def test_idempotent_retry_reuses_job_and_conflicting_request_is_rejected(self):
        with TestClient(app, base_url="http://localhost") as client:
            body = {"scenario": get_scenario("tiny").model_dump()}
            headers = {"Idempotency-Key": "retry-this-run"}
            first = client.post("/api/runs", json=body, headers=headers)
            self.assertEqual(first.status_code, 202)
            retry = client.post("/api/runs", json=body, headers=headers)
            self.assertEqual(retry.status_code, 202)
            self.assertEqual(first.json()["id"], retry.json()["id"])
            body["scenario"]["name"] = "Changed request"
            self.assertEqual(client.post("/api/runs", json=body, headers=headers).status_code, 409)
