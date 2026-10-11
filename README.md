# RouteLab engine

Read [the engineering guide](docs/ROUTELAB.md) for the precise model, architecture, benchmark protocol, and audit checklist.

```sh
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

The API starts a separate local worker and persists immutable jobs in `data/routelab.sqlite3`. Open `/docs` for the API contract. All optimization on frozen matrices and built-in scenarios works offline after installation. Real-place search and new road snapshots use Photon/OSRM (free community defaults, or self-hosted instances). No credentials are required. Read [geographic routing](docs/GEOGRAPHIC_ROUTING.md) for privacy, service limits, and local OSRM setup.

```sh
python -m routelab.cli --preset tiny --algorithm exact --seconds 3
python -m routelab.cli --preset harbor --experiment --output artifacts/harbor.json
python -m routelab.benchmark --output artifacts/suite-01 --ablations
```

The audit retains a multi-instance, multi-seed ablation run, not a statistical performance claim. See [release evidence](docs/RELEASE_AUDIT.md).

Release checks (activate a virtualenv first):

```sh
python -m pip install -r requirements-bootstrap.txt
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python scripts/smoke_worker.py
python scripts/check_lifecycle.py
```

Optional OR-Tools: `python -m pip install -r requirements-reference.txt`. The full release script requires it and frontend dependencies: `python scripts/verify_release.py --output artifacts/release-check-01`.
