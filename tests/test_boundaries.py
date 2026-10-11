import asyncio
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from routelab import road, store
from routelab.experiments import run_experiment
from routelab.http_safety import MAX_BODY_BYTES, RequestSafety
from routelab.importers import import_file
from routelab.models import ExperimentRequest
from routelab.presets import get_scenario


class BoundaryTests(unittest.TestCase):
    def test_csv_rejects_ambiguous_columns(self):
        for content in [b"x,x,y\n0,1,2", b"x,y\n0,1,2", b"x,y\n0"]:
            with self.subTest(content=content), self.assertRaises(ValueError):
                import_file("test.csv", content)

    def test_streamed_size_limit_without_content_length(self):
        async def check():
            messages = []
            invoked = False

            async def app(scope, receive, send):
                nonlocal invoked
                invoked = True

            async def receive():
                return {"type": "http.request", "body": b"x" * (1024 * 1024), "more_body": True}

            async def send(message):
                messages.append(message)

            await RequestSafety(app, [])(
                {"type": "http", "method": "POST", "headers": []}, receive, send
            )
            self.assertEqual(messages[0]["status"], 413)
            self.assertFalse(invoked)
            self.assertEqual(MAX_BODY_BYTES, 3 * 1024 * 1024)

        asyncio.run(check())

    def test_road_url_allowlist(self):
        for url in [
            "https://router.project-osrm.org.evil.example",
            "http://example.com",
            "http://127.0.0.1/path",
            "http://user@localhost",
            "http://localhost?url=x",
            "http://localhost#x",
        ]:
            with (
                self.subTest(url=url),
                patch.dict(
                    os.environ, {"ROUTELAB_OSRM_URL": url, "ROUTELAB_OSRM_DATA_VERSION": "test"}
                ),
            ):
                self.assertFalse(road.configured())

    def test_road_snapshot_units_directed_nulls_and_cache(self):
        scenario = get_scenario("pune")
        count = len(scenario.nodes)
        distances = [
            [0 if i == j else 1000 + 10 * i + j for j in range(count)] for i in range(count)
        ]
        durations = [[0 if i == j else 60 + i + j for j in range(count)] for i in range(count)]
        distances[1][2] = durations[1][2] = None
        payload = json.dumps(
            {
                "code": "Ok",
                "distances": distances,
                "durations": durations,
                "sources": [
                    {"location": [n.longitude, n.latitude], "hint": "test"} for n in scenario.nodes
                ],
            }
        ).encode()
        opener = Mock()
        opener.open.return_value = io.BytesIO(payload)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {
                    "ROUTELAB_DB": str(Path(directory) / "road.sqlite3"),
                    "ROUTELAB_OSRM_URL": "http://localhost:5000",
                    "ROUTELAB_OSRM_DATA_VERSION": "test",
                },
            ),
            patch("routelab.geography.build_opener", return_value=opener),
        ):
            store.initialize()
            snapshot = road.snapshot(scenario)
            self.assertEqual(snapshot.matrix.distances_km[0][1], 1.001)
            self.assertEqual(snapshot.matrix.durations_minutes[0][1], 61 / 60)
            self.assertIsNone(snapshot.matrix.distances_km[1][2])
            self.assertIsNotNone(snapshot.matrix.distances_km[2][1])
            self.assertEqual(road.snapshot(scenario), snapshot)
            opener.open.assert_called_once()
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 15)

    def test_cancelled_experiment_retains_all_planned_pairs(self):
        result = run_experiment(
            ExperimentRequest(
                scenario=get_scenario("tiny"), algorithms=["greedy", "alns"], seeds=[1, 2, 3]
            ),
            cancelled=lambda: True,
        )
        self.assertEqual(result["completed_trials"], 0)
        self.assertEqual(result["paired_comparisons"][0]["missing_or_error"], 3)
        self.assertEqual(len(result["scenario_hash"]), 64)

    def test_failed_trials_retain_provenance(self):
        with patch("routelab.experiments.run_once", side_effect=RuntimeError("test failure")):
            result = run_experiment(
                ExperimentRequest(scenario=get_scenario("tiny"), algorithms=["greedy"], seeds=[42])
            )
        trial = result["trials"][0]
        self.assertEqual(trial["status"], "error")
        self.assertEqual(trial["scenario_hash"], result["scenario_hash"])
        self.assertEqual(len(trial["environment"]["source_sha256"]), 64)
