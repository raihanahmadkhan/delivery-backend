"""Road snapshot identity, geometry fidelity, and external-service boundaries."""

import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from routelab import geography, road, store
from routelab.experiments import run_experiment, run_once
from routelab.matrices import build_matrix
from routelab.models import ExperimentRequest, RunOptions, Scenario


def example():
    return Scenario(
        name="City deliveries",
        coordinate_mode="geographic",
        travel_model="road",
        nodes=[
            {
                "id": "depot",
                "name": "Depot",
                "longitude": 73.8545,
                "latitude": 18.5214,
                "demand": 0,
                "service_minutes": 0,
            },
            {"id": "a", "name": "Delivery", "longitude": 73.856, "latitude": 18.522},
        ],
    )


def table():
    return {
        "code": "Ok",
        "distances": [[0, 1200], [1800, 0]],
        "durations": [[0, 240], [300, 0]],
        "sources": [
            {"location": [73.8545, 18.5214], "hint": "a"},
            {"location": [73.856, 18.522], "hint": "b"},
        ],
    }


class GeographicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "ROUTELAB_DB": str(Path(self.temp.name) / "geo.sqlite3"),
                "ROUTELAB_OSRM_URL": "http://localhost:5000",
                "ROUTELAB_OSRM_DATA_VERSION": "test-map",
                "ROUTELAB_EMBEDDED_WORKER": "0",
            },
        )
        self.env.start()
        store.initialize()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def freeze(self):
        with patch("routelab.road.fetch_json", return_value=table()):
            return road.snapshot(example())

    def test_road_mode_never_falls_back_to_haversine(self):
        with self.assertRaisesRegex(ValueError, "road matrix"):
            build_matrix(example())
        with TestClient(app, base_url="http://localhost") as client:
            for path, body in [
                ("/api/runs", {"scenario": example().model_dump()}),
                ("/api/experiments", {"scenario": example().model_dump()}),
                ("/api/evaluate", {"scenario": example().model_dump(), "routes": [["a"]]}),
            ]:
                self.assertEqual(client.post(path, json=body).status_code, 422)

    def test_real_matrices_use_existing_solver_and_validator(self):
        frozen = self.freeze()
        result = run_once(frozen, RunOptions(algorithm="exact", time_limit_seconds=1))
        self.assertTrue(result["evaluation"]["feasible"])
        self.assertEqual(result["evaluation"]["distance_km"], 3)
        self.assertEqual(result["evaluation"]["driving_minutes"], 9)
        self.assertEqual(result["matrix_provenance"]["kind"], "road")
        frozen.nodes[1].longitude += 0.1
        with self.assertRaisesRegex(ValueError, "Locations changed"):
            road.assert_ready(frozen)
        with self.assertRaisesRegex(ValueError, "Locations changed"):
            build_matrix(frozen)

    def test_road_experiment_reuses_one_matrix_offline_across_vehicles_and_seeds(self):
        raw = example().model_dump()
        raw["nodes"] += [
            {**raw["nodes"][1], "id": "b", "longitude": 73.857},
            {**raw["nodes"][1], "id": "c", "longitude": 73.858},
        ]
        raw["fleet"]["count"], raw["fleet"]["capacity"] = 2, 2
        scenario = Scenario.model_validate(raw)
        payload = {
            "code": "Ok",
            "distances": [
                [0, 1200, 1500, 2200],
                [1800, 0, 700, 1700],
                [1600, 900, 0, 800],
                [2400, 1500, 1000, 0],
            ],
            "durations": [
                [0, 240, 300, 440],
                [360, 0, 140, 340],
                [320, 180, 0, 160],
                [480, 300, 200, 0],
            ],
            "sources": [
                {"location": [n.longitude, n.latitude], "hint": n.id} for n in scenario.nodes
            ],
        }
        with patch("routelab.road.fetch_json", return_value=payload):
            frozen = road.snapshot(scenario)
        with patch(
            "routelab.road.fetch_json", side_effect=AssertionError("Solver must not request roads")
        ):
            study = run_experiment(
                ExperimentRequest(
                    scenario=frozen,
                    algorithms=["greedy", "local_search", "alns", "exact"],
                    seeds=[11, 22],
                    time_limit_seconds=1,
                    iterations=20,
                )
            )
        self.assertEqual(len(study["trials"]), 8)
        self.assertEqual(len({t["matrix_hash"] for t in study["trials"]}), 1)
        self.assertTrue(
            all(
                t["evaluation"]["feasible"] and t["evaluation"]["vehicles_used"] == 2
                for t in study["trials"]
            )
        )
        self.assertTrue(all(t["matrix_provenance"]["kind"] == "road" for t in study["trials"]))

    def test_geometry_matches_directed_legs_and_survives_service_outage(self):
        frozen = self.freeze()
        shape = {
            "type": "LineString",
            "coordinates": [[73.8545, 18.5214], [73.856, 18.522], [73.8545, 18.5214]],
        }
        response = {
            "code": "Ok",
            "routes": [
                {
                    "legs": [
                        {"distance": 1200, "duration": 240},
                        {"distance": 1800, "duration": 300},
                    ],
                    "geometry": shape,
                }
            ],
        }
        with patch("routelab.road.fetch_json", return_value=response) as fetch:
            self.assertEqual(road.geometry(frozen, ["a"])["geometry"], shape)
            self.assertEqual(road.geometry(frozen, ["a"])["geometry"], shape)
            fetch.assert_called_once()
            self.assertIn("continue_straight=false", fetch.call_args.args[1])
        with patch("routelab.road.fetch_json", side_effect=ValueError("offline")):
            self.assertEqual(road.geometry(frozen, ["a"])["geometry"], shape)

    def test_geometry_rejects_changed_network_and_malformed_shape(self):
        frozen = self.freeze()
        response = {
            "code": "Ok",
            "routes": [
                {
                    "legs": [
                        {"distance": 9200, "duration": 240},
                        {"distance": 1800, "duration": 300},
                    ],
                    "geometry": {"type": "LineString", "coordinates": [[73, 18], [74, 19]]},
                }
            ],
        }
        with (
            patch("routelab.road.fetch_json", return_value=response),
            self.assertRaisesRegex(ValueError, "no longer matches"),
        ):
            road.geometry(frozen, ["a"])
        with self.assertRaises(ValueError):
            road.geometry(frozen, ["a", "a"])

    def test_no_road_fallback_and_strict_service_urls(self):
        payload = deepcopy(table())
        payload["fallback_speed_cells"] = [[0, 1]]
        with (
            patch("routelab.road.fetch_json", return_value=payload),
            self.assertRaisesRegex(ValueError, "fallback"),
        ):
            road.snapshot(example())
        for url in [
            "http://169.254.169.254",
            "https://evil.test",
            "https://photon.komoot.io@evil.test",
            "https://photon.komoot.io/path",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                geography.service_url(url, "photon.komoot.io", "photon")

    def test_search_normalizes_bounded_plain_text_results_and_caches(self):
        payload = {
            "features": [
                {
                    "geometry": {"coordinates": [73.85, 18.52]},
                    "properties": {"name": "<img src=x>", "city": "Pune", "country": "India"},
                }
            ]
        }
        with patch("routelab.geography.fetch_json", return_value=payload) as fetch:
            first = geography.search(" Pune ")
            self.assertEqual(first, geography.search("pune"))
            self.assertIn("<img src=x>", first[0]["name"])
            self.assertEqual(first[0]["latitude"], 18.52)
            fetch.assert_called_once()

    def test_rate_gate_is_shared_in_database_and_cache_expires(self):
        with patch("routelab.store.time.sleep") as sleep:
            store.reserve_network_slot("test-service")
            store.reserve_network_slot("test-service")
            self.assertGreater(sleep.call_args.args[0], 0.9)
        store.cache_geo("search", [1], -1)
        self.assertIsNone(store.geo_cached("search"))

    def test_road_metadata_counts_and_empty_tile_environment(self):
        frozen = self.freeze().model_dump()
        frozen["matrix"]["road"]["hints"] = []
        with self.assertRaisesRegex(ValueError, "match the node order"):
            Scenario.model_validate(frozen)
        with patch.dict(os.environ, {"ROUTELAB_TILE_URL": ""}):
            self.assertEqual(
                geography.map_configuration()["tile_url"],
                "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            )

    def test_search_deduplicates_and_skips_invalid_coordinates(self):
        item = {"geometry": {"coordinates": [73.85, 18.52]}, "properties": {"name": "Pune"}}
        with patch(
            "routelab.geography.fetch_json",
            return_value={
                "features": [item, item, {**item, "geometry": {"coordinates": [181, 90]}}]
            },
        ):
            self.assertEqual(len(geography.search("Pune")), 1)


if __name__ == "__main__":
    unittest.main()
