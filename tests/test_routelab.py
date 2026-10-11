import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from routelab import store
from routelab.evaluator import evaluate
from routelab.experiments import run_once
from routelab.matrices import build_matrix
from routelab.models import Fleet, RunOptions, Scenario, Stop
from routelab.presets import get_scenario


def scenario():
    return Scenario(
        nodes=[
            Stop(id="depot", demand=0, service_minutes=0),
            Stop(id="a", x=1, demand=4, service_minutes=10),
            Stop(id="b", x=2, demand=4, service_minutes=10),
        ],
        fleet=Fleet(count=2, capacity=5),
        speed_kph=60,
    )


class ContractTests(unittest.TestCase):
    def test_capacity_and_coverage_are_hard(self):
        problem = scenario()
        matrix = build_matrix(problem)
        self.assertTrue(evaluate(problem, matrix, [["a"], ["b"]])["feasible"])
        self.assertIn(
            "capacity", [v["kind"] for v in evaluate(problem, matrix, [["a", "b"]])["violations"]]
        )
        report = evaluate(problem, matrix, [["a", "a"]])
        self.assertEqual(report["unserved"], ["b"])
        self.assertIn("duplicate", [v["kind"] for v in report["violations"]])

    def test_time_is_not_distance_and_waiting_is_explicit(self):
        problem = scenario()
        problem.speed_kph = 30
        problem.nodes[1].window_start = 20
        report = evaluate(problem, build_matrix(problem), [["a"], ["b"]])
        visit = report["vehicles"][0]["schedule"][1]
        self.assertEqual(visit["arrival"], 2)
        self.assertEqual(visit["waiting"], 18)
        self.assertEqual(visit["departure"], 30)
        self.assertEqual(report["vehicles"][0]["return_time"], 32)

    def test_directed_and_unreachable_arcs(self):
        problem = scenario()
        body = problem.model_dump()
        body["matrix"] = {
            "distances_km": [[0, 2, None], [8, 0, 1], [None, 4, 0]],
            "durations_minutes": [[0, 3, None], [9, 0, 2], [None, 5, 0]],
        }
        problem = Scenario.model_validate(body)
        report = evaluate(problem, build_matrix(problem), [["a"], ["b"]])
        self.assertEqual(report["vehicles"][0]["distance_km"], 10)
        self.assertFalse(report["feasible"])
        self.assertIn("unreachable", [v["kind"] for v in report["violations"]])

    def test_tiny_exact_certifies_only_a_complete_solution(self):
        problem = get_scenario("tiny")
        result = run_once(problem, RunOptions(algorithm="exact", time_limit_seconds=3))
        self.assertTrue(result["proven_optimal"])
        self.assertTrue(evaluate(problem, build_matrix(problem), result["routes"])["feasible"])
        self.assertEqual(result["status"], "optimal")


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="routelab-tests-")
        self.environment = patch.dict(
            os.environ, {"ROUTELAB_DB": str(Path(self.directory.name) / "test.sqlite3")}
        )
        self.environment.start()
        store.initialize()

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def test_idempotency_and_fencing(self):
        identity = store.enqueue("run", {"value": 1}, "same-key")
        self.assertEqual(store.enqueue("run", {"value": 1}, "same-key"), identity)
        with self.assertRaises(ValueError):
            store.enqueue("run", {"value": 2}, "same-key")
        claimed = store.claim()
        store.complete(identity, "stale-token", result={"bad": True})
        self.assertEqual(store.get_job(identity)["status"], "running")
        store.complete(identity, claimed["lease_token"], result={"good": True})
        self.assertEqual(store.get_job(identity)["result"], {"good": True})

    def test_queued_cancellation_is_terminal(self):
        identity = store.enqueue("run", {})
        store.cancel(identity)
        self.assertIsNone(store.claim())
        self.assertEqual(store.get_job(identity)["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
