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

## Render connectivity

For the existing Render service, set these values in **Render → Environment**, then redeploy. Editing `.env.example` does not configure the running service; RouteLab reads process environment variables.

```text
ROUTELAB_ALLOWED_HOSTS=delivery-backend-22c4.onrender.com,localhost,127.0.0.1
APP_CORS_ORIGINS=["https://droptimizer.netlify.app"]
ROUTELAB_EMBEDDED_WORKER=1
```

Without an explicit host override, RouteLab accepts loopback hosts and Render's exact `RENDER_EXTERNAL_HOSTNAME`. Explicit `ROUTELAB_ALLOWED_HOSTS` replaces those defaults; include any custom domain used by Render health checks. A missing allowed host returns `400 Invalid host header`; an incorrect frontend origin blocks browser requests.

Use this start command with one API process and its embedded worker:

```sh
python -m uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1
```

Check `https://delivery-backend-22c4.onrender.com/ready` after deployment. A `200` response confirms a fresh worker heartbeat; `503` means the worker is unavailable. `/health` checks storage and can succeed without a worker. Keep `ROUTELAB_DB` on a writable path; retaining SQLite history across restarts requires persistent storage. The app uses shared scenarios and job history without sign-in.
