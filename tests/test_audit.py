import importlib.util
import itertools
import os
import random
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from routelab import store
from routelab.evaluator import evaluate
from routelab.experiments import run_experiment, run_once
from routelab.matrices import build_matrix
from routelab.models import ExperimentRequest, Fleet, ReplanRequest, RunOptions, Scenario, Stop
from routelab.presets import get_scenario
from routelab.replan import run_replan
from routelab.solvers import Search

HAS_ORTOOLS = importlib.util.find_spec("ortools") is not None


def generated(seed, count=4):
    rng = random.Random(seed)
    nodes = [Stop(id="depot", demand=0, service_minutes=0, window_end=80)]
    nodes += [
        Stop(
            id=str(i),
            demand=rng.randint(1, 4),
            service_minutes=rng.randint(0, 5),
            window_start=rng.randint(0, 10),
            window_end=rng.randint(25, 70),
        )
        for i in range(count)
    ]
    distance = [
        [0 if i == j else rng.randint(0, 12) for j in range(len(nodes))] for i in range(len(nodes))
    ]
    duration = [
        [0 if i == j else rng.randint(1, 15) for j in range(len(nodes))] for i in range(len(nodes))
    ]
    return Scenario(
        nodes=nodes,
        fleet=Fleet(count=3, capacity=6, end_time=80),
        matrix={"distances_km": distance, "durations_minutes": duration},
    )


def brute_objective(problem):
    """Independent permutations + cuts; never calls either production checker."""
    matrix = problem.matrix
    indices = {node.id: i for i, node in enumerate(problem.nodes)}
    depot = indices[problem.depot_id]
    customers = [i for i in range(len(problem.nodes)) if i != depot]
    best = None
    for permutation in itertools.permutations(customers):
        for cuts in range(1 << (len(customers) - 1)):
            routes, route = [], []
            for offset, index in enumerate(permutation):
                route.append(index)
                if offset == len(customers) - 1 or cuts & (1 << offset):
                    routes.append(route)
                    route = []
            if len(routes) > problem.fleet.count:
                continue
            feasible, distance = True, 0
            for route in routes:
                if sum(problem.nodes[i].demand for i in route) > problem.fleet.capacity + 1e-7:
                    feasible = False
                    break
                now = max(problem.fleet.start_time, problem.nodes[depot].window_start)
                previous, route_distance = depot, 0
                for index in route + [depot]:
                    travel, length = (
                        matrix.durations_minutes[previous][index],
                        matrix.distances_km[previous][index],
                    )
                    if travel is None or length is None:
                        feasible = False
                        break
                    now += travel
                    route_distance += length
                    node = problem.nodes[index]
                    if index == depot:
                        feasible &= now <= min(node.window_end, problem.fleet.end_time) + 1e-7
                    else:
                        now = max(now, node.window_start)
                        feasible &= now <= node.window_end + 1e-7
                        now += node.service_minutes
                    previous = index
                if problem.fleet.max_distance_km is not None:
                    feasible &= route_distance <= problem.fleet.max_distance_km + 1e-7
                distance += route_distance
            objective = (len(routes), distance)
            if feasible and (best is None or objective < best):
                best = objective
    return best


class OptimizationAudit(unittest.TestCase):
    def test_already_cancelled_solvers_stop_before_construction(self):
        for algorithm in ("greedy", "local_search", "alns", "exact", "ortools"):
            with self.subTest(algorithm=algorithm):
                result = run_once(
                    get_scenario("tiny"),
                    RunOptions(algorithm=algorithm),
                    cancelled=lambda: True,
                )
                self.assertEqual(result["termination_reason"], "cancelled")
                self.assertFalse(result["proven_optimal"])
                self.assertEqual(result["routes"], [])

    @unittest.skipUnless(HAS_ORTOOLS, "Optional OR-Tools reference is not installed")
    def test_reference_retains_callback_cancellation_reason(self):
        polls = 0

        def cancelled():
            nonlocal polls
            polls += 1
            return polls >= 2

        result = run_once(
            get_scenario("tiny"),
            RunOptions(algorithm="ortools", time_limit_seconds=3),
            cancelled=cancelled,
        )
        self.assertEqual(result["termination_reason"], "cancelled")
        self.assertTrue(result["evaluation"]["feasible"])

    def test_exact_matches_independent_permutations_and_partitions(self):
        for seed in range(25):
            problem = generated(seed)
            expected = brute_objective(problem)
            result = run_once(problem, RunOptions(algorithm="exact", time_limit_seconds=3))
            with self.subTest(seed=seed):
                self.assertEqual(result["status"], "optimal" if expected else "proven_infeasible")
                if expected:
                    self.assertEqual(tuple(result["evaluation"]["objective"]), expected)

    def test_fast_screen_and_validator_agree_for_all_ordered_subsets(self):
        for seed in range(8):
            problem = generated(seed)
            matrix = build_matrix(problem)
            search = Search(problem, matrix, RunOptions(time_limit_seconds=30))
            for size in range(1, 5):
                for route in itertools.permutations(search.customers, size):
                    report = evaluate(problem, matrix, [list(route)])
                    feasible_except_missing = all(
                        v["kind"] == "unserved" for v in report["violations"]
                    )
                    self.assertEqual(search.admissible(route), feasible_except_missing)

    def test_heuristic_results_are_checked_and_never_beat_exact(self):
        algorithms = ("greedy", "local_search", "alns") + (("ortools",) if HAS_ORTOOLS else ())
        for seed in range(12):
            problem = generated(seed)
            optimum = brute_objective(problem)
            for algorithm in algorithms:
                result = run_once(
                    problem, RunOptions(algorithm=algorithm, time_limit_seconds=0.15, iterations=12)
                )
                report = evaluate(problem, build_matrix(problem), result["routes"])
                with self.subTest(seed=seed, algorithm=algorithm):
                    self.assertEqual(report, result["evaluation"])
                    if report["feasible"]:
                        self.assertIsNotNone(optimum)
                        self.assertGreaterEqual(tuple(report["objective"]), optimum)

    def test_nonmetric_removal_does_not_make_unreachable_arc_free(self):
        problem = generated(2)
        problem.matrix.distances_km[0][2] = None
        problem.matrix.durations_minutes[0][2] = None
        search = Search(problem, build_matrix(problem), RunOptions(time_limit_seconds=3))
        self.assertEqual(search.route_distance(["1"]), float("inf"))
        self.assertFalse(search.admissible(["1"]))

    def test_zero_distance_and_depot_not_first(self):
        problem = generated(5)
        problem.matrix.distances_km = [[0] * 5 for _ in range(5)]
        problem.matrix.durations_minutes = [[0] * 5 for _ in range(5)]
        problem.nodes[1].demand = 0
        result = run_once(problem, RunOptions(algorithm="exact", time_limit_seconds=3))
        self.assertEqual(result["evaluation"]["distance_km"], 0)
        order = [2, 0, 1, 3, 4]
        body = problem.model_dump()
        body["nodes"] = [body["nodes"][i] for i in order]
        for field in ("distances_km", "durations_minutes"):
            body["matrix"][field] = [[body["matrix"][field][i][j] for j in order] for i in order]
        moved = run_once(
            Scenario.model_validate(body), RunOptions(algorithm="exact", time_limit_seconds=3)
        )
        self.assertEqual(moved["evaluation"]["objective"], result["evaluation"]["objective"])

    def test_service_start_window_not_completion_and_hard_return(self):
        problem = Scenario(
            nodes=[
                Stop(id="depot", demand=0, service_minutes=0),
                Stop(id="a", x=1, service_minutes=10, window_end=1),
            ],
            speed_kph=60,
        )
        self.assertTrue(evaluate(problem, build_matrix(problem), [["a"]])["feasible"])
        problem.fleet.end_time = 11
        report = evaluate(problem, build_matrix(problem), [["a"]])
        self.assertIn("return_deadline", [v["kind"] for v in report["violations"]])
        problem.fleet.end_time = 100
        problem.fleet.max_distance_km = 1
        self.assertFalse(evaluate(problem, build_matrix(problem), [["a"]])["feasible"])

    def test_seed_reproducibility_with_nonbinding_time_cap(self):
        problem = generated(9)
        options = RunOptions(algorithm="alns", seed=77, iterations=12, time_limit_seconds=30)
        a, b = run_once(problem, options), run_once(problem, options)
        self.assertEqual(a["routes"], b["routes"])
        self.assertEqual(a["operator_stats"], b["operator_stats"])
        self.assertEqual(a["matrix_hash"], b["matrix_hash"])
        self.assertEqual(a["termination_reason"], "iteration_limit")

    @unittest.skipUnless(HAS_ORTOOLS, "Optional OR-Tools reference is not installed")
    def test_reference_empty_integer_domain_is_not_crash_or_proof(self):
        problem = generated(1)
        problem.nodes[1].window_start = 0.0001
        problem.nodes[1].window_end = 0.0002
        result = run_once(problem, RunOptions(algorithm="ortools", time_limit_seconds=0.2))
        self.assertFalse(result["proven_optimal"])

    def test_experiment_preserves_options_and_all_trials(self):
        result = run_experiment(
            ExperimentRequest(
                scenario=get_scenario("tiny"),
                algorithms=["exact", "alns"],
                seeds=[11, 22],
                time_limit_seconds=0.5,
                iterations=3,
                removal_fraction=0.5,
            )
        )
        self.assertEqual(len(result["trials"]), 4)
        self.assertTrue(all(t["options"]["removal_fraction"] == 0.5 for t in result["trials"]))
        self.assertTrue(all("exact_reference" in t for t in result["trials"]))
        comparison = result["paired_comparisons"][0]
        self.assertEqual(
            sum(
                comparison[k]
                for k in ("wins", "ties", "losses", "both_infeasible", "missing_or_error")
            ),
            2,
        )

    def test_replan_locks_prefix_assignment_and_zero_change_budget(self):
        problem = get_scenario("harbor")
        parent = run_once(problem, RunOptions(algorithm="greedy", time_limit_seconds=3))
        self.assertTrue(parent["evaluation"]["feasible"])
        request = ReplanRequest(
            parent_job_id="a" * 32,
            completed_stops=1,
            delay_minutes=30,
            change_budget=0,
            options=RunOptions(iterations=40, time_limit_seconds=1),
        )
        result = run_replan(parent, request)
        self.assertEqual(result["routes"], parent["routes"])
        continued = result["disruption"]["continued"]
        self.assertEqual(result["evaluation"], continued)
        for index in range(1, len(parent["routes"])):
            self.assertEqual(
                continued["vehicles"][index]["schedule"],
                parent["evaluation"]["vehicles"][index]["schedule"],
            )
        shifted = [r[:] for r in parent["routes"]]
        shifted[0][0], shifted[1][0] = shifted[1][0], shifted[0][0]
        scenario = Scenario.model_validate(result["scenario"])
        self.assertFalse(evaluate(scenario, build_matrix(scenario), shifted)["feasible"])


class DatabaseAudit(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="routelab-audit-")
        self.env = patch.dict(
            os.environ,
            {
                "ROUTELAB_DB": str(Path(self.directory.name) / "test.sqlite3"),
                "ROUTELAB_EMBEDDED_WORKER": "0",
            },
        )
        self.env.start()
        store.initialize()

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    def test_concurrent_claims_are_unique(self):
        identities = {store.enqueue("run", {"i": i}) for i in range(12)}
        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs = list(pool.map(lambda _: store.claim(), range(16)))
        claimed = [j["id"] for j in jobs if j]
        self.assertEqual(set(claimed), identities)
        self.assertEqual(len(claimed), len(set(claimed)))

    def test_expired_worker_cannot_renew_publish_or_complete(self):
        identity = store.enqueue("run", {})
        first = store.claim()
        with store.connection() as conn:
            conn.execute("UPDATE jobs SET heartbeat=? WHERE id=?", (time.time() - 21, identity))
        self.assertTrue(store.pulse(identity, first["lease_token"]))
        store.progress(identity, first["lease_token"], {"wrong": True})
        store.complete(identity, first["lease_token"], {"wrong": True})
        second = store.claim()
        self.assertNotEqual(first["lease_token"], second["lease_token"])
        store.complete(identity, first["lease_token"], {"wrong": True})
        store.complete(identity, second["lease_token"], {"right": True})
        self.assertEqual(store.get_job(identity)["result"], {"right": True})

    def test_retry_limit_cancellation_and_release(self):
        identity = store.enqueue("run", {})
        for _ in range(3):
            job = store.claim()
            store.abandon(identity, job["lease_token"])
        self.assertEqual(store.get_job(identity)["status"], "failed")
        other = store.enqueue("run", {"other": True})
        job = store.claim()
        store.cancel(other)
        store.complete(other, job["lease_token"], {"partial": True})
        self.assertEqual(store.get_job(other)["status"], "cancelled")

    def test_atomic_idempotency(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(lambda _: store.enqueue("run", {"same": True}, "key"), range(20)))
        self.assertEqual(len(set(ids)), 1)

    def test_schema_upgrade_integrity_backup_and_downgrade_guard(self):
        identity = store.enqueue("run", {})
        with store.connection() as conn:
            conn.execute("PRAGMA user_version=0")
        store.initialize()
        self.assertIsNotNone(store.get_job(identity))
        with store.connection() as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            with closing(sqlite3.connect(Path(self.directory.name) / "backup.sqlite3")) as backup:
                conn.backup(backup)
                self.assertEqual(backup.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
            conn.execute("PRAGMA user_version=999")
        with self.assertRaises(RuntimeError):
            store.initialize()

    def test_api_malformed_requests_and_origin_bounds(self):
        with TestClient(app, base_url="http://127.0.0.1") as client:
            body = {"scenario": get_scenario("tiny").model_dump()}
            self.assertEqual(
                client.post(
                    "/api/runs", json=body, headers={"Origin": "https://evil.example"}
                ).status_code,
                403,
            )
            self.assertEqual(
                client.post(
                    "/api/runs",
                    content='{"scenario":NaN}',
                    headers={"Content-Type": "application/json"},
                ).status_code,
                400,
            )
            body["scenario"]["speed_kph"] = "NaN"
            self.assertEqual(client.post("/api/runs", json=body).status_code, 422)
            self.assertEqual(
                client.post("/api/import", content=b"x" * (3 * 1024 * 1024 + 1)).status_code, 413
            )
            self.assertEqual(
                client.get("/health", headers={"Host": "evil.example"}).status_code, 400
            )
            self.assertEqual(client.get("/ready").status_code, 503)
            self.assertEqual(
                client.post("/api/import", files={"file": ("bad.json", b"[]")}).status_code, 422
            )
            self.assertEqual(
                client.post(
                    "/api/import",
                    files={"file": ("bad.txt", b"VEHICLE\ninf 10\nCUSTOMER\n0 0 0 0 0 10 0")},
                ).status_code,
                422,
            )


if __name__ == "__main__":
    unittest.main()
