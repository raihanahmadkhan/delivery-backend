"""Road snapshot identity, geometry fidelity, and external-service boundaries."""

import io
import os
import tempfile
import unittest
from copy import deepcopy
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

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

    def test_equivalent_public_urls_preserve_community_limits(self):
        with patch.dict(
            os.environ,
            {
                "ROUTELAB_OSRM_URL": "HTTPS://ROUTER.PROJECT-OSRM.ORG:443/",
                "ROUTELAB_OSRM_DATA_VERSION": "",
                "ROUTELAB_PHOTON_URL": "HTTPS://PHOTON.KOMOOT.IO:443/",
            },
        ):
            self.assertEqual(road.configuration(), (road.PUBLIC_ENGINE, "community-unversioned"))
            self.assertTrue(geography.map_configuration()["search_public"])
            scenario = example().model_dump()
            scenario["nodes"] = [scenario["nodes"][0]] + [
                {**scenario["nodes"][1], "id": f"customer-{index}"} for index in range(26)
            ]
            with (
                patch("routelab.road.fetch_json") as fetch,
                self.assertRaisesRegex(ValueError, "at most 25"),
            ):
                road.snapshot(Scenario.model_validate(scenario))
            fetch.assert_not_called()

    def test_service_normalization_preserves_local_ports_and_ipv6(self):
        for supplied, expected in [
            ("http://LOCALHOST:5000", "http://localhost:5000"),
            ("http://[::1]:5000", "http://[::1]:5000"),
            ("http://osrm:80", "http://osrm"),
        ]:
            with self.subTest(url=supplied):
                self.assertEqual(
                    geography.service_url(supplied, "router.project-osrm.org", "osrm"), expected
                )

    def test_tile_configuration_rejects_invalid_ports(self):
        for url in [
            "https://tiles.example.com:bad/{z}/{x}/{y}.png",
            "https://tiles.example.com:99999/{z}/{x}/{y}.png",
            "http://[::1/{z}/{x}/{y}.png",
        ]:
            with (
                self.subTest(url=url),
                patch.dict(os.environ, {"ROUTELAB_TILE_URL": url}),
                self.assertRaisesRegex(ValueError, "invalid host or port"),
            ):
                geography.map_configuration()

    def test_http_tiles_match_browser_csp_loopback_hosts(self):
        for host in ("localhost", "127.0.0.1"):
            template = f"http://{host}:8088/tiles/{{z}}/{{x}}/{{y}}.png"
            with self.subTest(host=host), patch.dict(os.environ, {"ROUTELAB_TILE_URL": template}):
                self.assertEqual(geography.map_configuration()["tile_url"], template)
        with (
            patch.dict(os.environ, {"ROUTELAB_TILE_URL": "http://[::1]:8088/{z}/{x}/{y}.png"}),
            self.assertRaisesRegex(ValueError, "localhost or 127.0.0.1"),
        ):
            geography.map_configuration()

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

    def test_search_bias_uses_stable_nearby_cache_without_sharing_distant_results(self):
        payload = {
            "features": [
                {"geometry": {"coordinates": [73.85, 18.52]}, "properties": {"name": "Pharmacy"}}
            ]
        }
        with patch("routelab.geography.fetch_json", return_value=payload) as fetch:
            first = geography.search("pharmacy", latitude=18.521, longitude=73.856)
            self.assertEqual(
                first, geography.search(" PHARMACY ", latitude=18.522, longitude=73.857)
            )
            fetch.assert_called_once()
            params = parse_qs(urlsplit(fetch.call_args.args[1]).query)
            self.assertEqual(params["lat"], ["18.52"])
            self.assertEqual(params["lon"], ["73.86"])
            self.assertEqual(params["limit"], ["6"])
            self.assertNotIn("bbox", params)
            geography.search("pharmacy", latitude=19.53, longitude=72.99)
            geography.search("pharmacy")
            self.assertEqual(fetch.call_count, 3)

    def test_search_labels_include_address_and_deduplicate_location_names(self):
        payload = {
            "features": [
                {
                    "geometry": {"coordinates": [73.85, 18.52]},
                    "properties": {
                        "name": "Apte Pharmacy",
                        "housenumber": "14",
                        "street": " FC  Road ",
                        "locality": "Shivajinagar",
                        "city": "Pune",
                        "county": "PUNE",
                        "state": "Maharashtra",
                        "postcode": "411005",
                        "country": "India",
                    },
                }
            ]
        }
        with patch("routelab.geography.fetch_json", return_value=payload):
            self.assertEqual(
                geography.search("apte")[0]["name"],
                "Apte Pharmacy, 14 FC Road, Shivajinagar, Pune, Maharashtra, 411005, India",
            )

    def test_search_skips_malformed_features_but_rejects_invalid_response(self):
        valid = {"geometry": {"coordinates": [73.85, 18.52]}, "properties": {"name": "Pune"}}
        payload = {"features": [None, {"geometry": None}, {**valid, "properties": None}, valid]}
        with patch("routelab.geography.fetch_json", return_value=payload):
            self.assertEqual(len(geography.search("Pune")), 1)
        for index, invalid in enumerate(
            [
                None,
                {},
                {"features": {}},
                {"features": [None]},
                {"features": [{**valid, "geometry": {"coordinates": [True, 18.52]}}]},
            ]
        ):
            with (
                self.subTest(payload=invalid),
                patch("routelab.geography.fetch_json", return_value=invalid),
                self.assertRaisesRegex(ValueError, "invalid data"),
            ):
                geography.search(f"invalid {index}")

    def test_search_rejects_invalid_focus_before_provider_request(self):
        for latitude, longitude in [
            (18.52, None),
            (None, 73.85),
            (float("nan"), 73.85),
            (18.52, float("inf")),
            (86, 73.85),
            (18.52, 181),
            (True, 73.85),
        ]:
            with (
                self.subTest(latitude=latitude, longitude=longitude),
                patch("routelab.geography.fetch_json") as fetch,
                self.assertRaises(ValueError),
            ):
                geography.search("pharmacy", latitude=latitude, longitude=longitude)
            fetch.assert_not_called()

    def test_places_endpoint_validates_optional_coordinate_pair(self):
        with (
            TestClient(app, base_url="http://localhost") as client,
            patch("routelab.geography.search", return_value=[]) as search,
        ):
            response = client.get(
                "/api/places", params={"q": "pharmacy", "latitude": 18.52, "longitude": 73.85}
            )
            self.assertEqual(response.status_code, 200)
            search.assert_called_once_with("pharmacy", latitude=18.52, longitude=73.85)
            for extra in [
                {"latitude": 18.52},
                {"longitude": 73.85},
                {"latitude": "nan", "longitude": 73.85},
                {"latitude": 18.52, "longitude": 181},
                {"latitude": 86, "longitude": 73.85},
            ]:
                with self.subTest(params=extra):
                    self.assertEqual(
                        client.get("/api/places", params={"q": "pharmacy", **extra}).status_code,
                        422,
                    )
            self.assertEqual(search.call_count, 1)
            self.assertEqual(client.get("/api/places", params={"q": "Pune"}).status_code, 200)
            search.assert_called_with("Pune", latitude=None, longitude=None)

    def test_provider_json_rejects_nonstandard_numbers_bad_encoding_and_truncation(self):
        for raw in [b"\xff", b"{", b'{"value":NaN}', b"[" * 1100]:
            opener = Mock()
            opener.open.return_value = io.BytesIO(raw)
            with (
                self.subTest(body=raw[:30]),
                patch("routelab.geography.build_opener", return_value=opener),
                patch("routelab.store.reserve_network_slot"),
                self.assertRaisesRegex(ValueError, "invalid JSON"),
            ):
                geography.fetch_json("https://photon.komoot.io", "/api/?q=Pune")
        opener = Mock()
        opener.open.side_effect = IncompleteRead(b"{")
        with (
            patch("routelab.geography.build_opener", return_value=opener),
            patch("routelab.store.reserve_network_slot"),
            self.assertRaisesRegex(ValueError, "unavailable"),
        ):
            geography.fetch_json("https://photon.komoot.io", "/api/?q=Pune")

    def test_provider_response_bound_is_enforced_before_json_parsing(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(b"x" * 17)
        with (
            patch("routelab.geography.build_opener", return_value=opener),
            patch("routelab.store.reserve_network_slot"),
            self.assertRaisesRegex(ValueError, "too large"),
        ):
            geography.fetch_json("https://photon.komoot.io", "/api/?q=Pune", limit=16)

    def test_road_snapshot_rejects_boolean_metrics_and_malformed_snaps(self):
        for mutation in ["metric", "coordinate", "snap_shape", "matrix_shape"]:
            payload = deepcopy(table())
            if mutation == "metric":
                payload["distances"][0][1] = True
            elif mutation == "coordinate":
                payload["sources"][0]["location"][0] = True
            elif mutation == "snap_shape":
                payload["sources"][0]["location"].append(1)
            else:
                payload["durations"][0].pop()
            with (
                self.subTest(mutation=mutation),
                patch("routelab.road.fetch_json", return_value=payload),
                self.assertRaises(ValueError),
            ):
                road.snapshot(example())

    def test_road_geometry_rejects_boolean_metrics_and_malformed_coordinate_shape(self):
        frozen = self.freeze()
        for mutation in ["metric", "coordinate", "coordinate_shape"]:
            payload = {
                "code": "Ok",
                "routes": [
                    {
                        "legs": [
                            {"distance": 1200, "duration": 240},
                            {"distance": 1800, "duration": 300},
                        ],
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[73.85, 18.52], [73.86, 18.53]],
                        },
                    }
                ],
            }
            if mutation == "metric":
                payload["routes"][0]["legs"][0]["duration"] = True
            elif mutation == "coordinate":
                payload["routes"][0]["geometry"]["coordinates"][0][0] = True
            else:
                payload["routes"][0]["geometry"]["coordinates"][0].append(1)
            with (
                self.subTest(mutation=mutation),
                patch("routelab.road.fetch_json", return_value=payload),
                self.assertRaises(ValueError),
            ):
                road.geometry(frozen, ["a"])


if __name__ == "__main__":
    unittest.main()
