# RouteLab release audit — 2026-09-22

## Outcome

The code hardening pass is complete for the defects identified below. The consolidated run has **12 passing checks**, one failed engine-availability check, and one blocked container build/run gate. **Container release certification is not complete.** The application remains a trusted local research workbench, not an authenticated public service.

Authoritative machine evidence: `backend/artifacts/release-final-20260922-r2/report.json` and adjacent command logs. The directory also contains the final raw benchmark artifacts. The earlier `release-final-20260922` report is retained transparently: it caught an invalid Testing Library option in a new test's TypeScript types. That test was corrected before the complete r2 run. Artifacts are Git-ignored; retain/publish selected evidence explicitly.

## Fixed

- Routing: unreachable arcs no longer become zero-cost edges in removal scoring; nonmetric partial-route repair avoids infinite-delta arithmetic; candidate screening rejects invalid/duplicate customers; ALNS reports iteration-limit termination accurately.
- Reference/evidence: OR-Tools rejects empty conservatively scaled integer domains without crashing or claiming infeasibility of the original model. Experiment removal settings are retained; exact gaps require matching scenario/matrix identities; failed trials retain provenance; cancelled experiments count all missing planned seed pairs.
- Durable execution: expired leases cannot renew, publish progress, or complete even before another claimant arrives. Retried jobs clear previous progress. Shutdown releases only its own claim. CPU children detect dead supervisors; hard termination has a kill fallback. Cancellation remains terminal; stale tokens cannot overwrite a newer attempt.
- Storage: explicit version-1 initialization, preservation of original unversioned RouteLab data, refusal to downgrade newer schemas, tested integrity and SQLite backup/restore. API readiness distinguishes an available database from a live worker.
- HTTP/imports: pre-parser streamed/body-size and timeout limits; origin and Host restrictions; malformed/nonfinite JSON handling; bounded evaluation/matrix/execution inputs; sanitized validation/storage errors; literal export formats; finite integer Solomon IDs/fleet counts; CSV duplicate headers and malformed row widths rejected.
- UI: corrupted persisted drafts and malicious hash IDs are rejected; delayed preset/import/snapshot responses cannot overwrite newer edits; saved-run loading cannot display unrelated draft geometry; duplicate submission and late progress races guarded; move reports clear after settings change; JSON dialog focus trapping/Escape/restoration; accessible mobile navigation and keyboard-selectable schematic stops; upload size and non-JSON gateway errors handled.
- Deployment/dependencies: nonroot API image, explicit copied runtime source, process/resource limits, readiness proxy, preserved Nginx security-header inheritance with caching, CSP, loopback bindings, and documented environment settings. Compatible security updates replace vulnerable dependency versions and old venv bootstrap tooling. Retired tour algorithms/UI screens, mapping/chart/client dependencies, and Render/Netlify/Tailwind configs were removed; Git history preserves the original work.
- Repeatable verification: `scripts/verify_release.py` retains each command's output, all benchmark artifacts, and a machine-readable gate result. No commits, pushes, or public deployment were performed.

## Verified on the final tree

| Gate | Result |
| --- | --- |
| Backend tests | 28 passed; generated directed/capacitated/windowed cases, independent exhaustive oracle, solver/evaluator differential checks, edge cases, imports, HTTP boundaries, transactions, migration/backup |
| Backend lint/format | Ruff check and format check passed |
| API → spawned worker | Exact run, experiment, replan, CSV export passed against an isolated temporary database |
| Real processes | Queued/running cancellation, graceful restart, abrupt supervisor death/orphan detection, two-worker exclusive claiming and database integrity passed |
| Frontend tests | 11 passed; identity, input, injection-as-text, keyboard selection, modal focus, delayed loads, mobile names, API errors |
| Frontend checks | Strict TypeScript, ESLint and Vite production build passed; JS 246.41 kB / 76.28 kB gzip |
| Clean setup | Fresh Python virtualenv/runtime/dev/reference install; `npm ci --ignore-scripts` succeeded after stopping Vite's Windows native-module lock |
| Python dependencies | `pip check` passed; `pip-audit --local` found no known vulnerabilities, including optional reference/dev/bootstrap packages |
| JavaScript dependencies | `npm audit --audit-level=low` reported zero vulnerabilities |
| Benchmarks | 75 retained trials, four instances, three seeds, baseline/reference solvers and ALNS ablations; all artifacts reloaded, hashes recomputed and routes independently re-evaluated |
| Compose | `docker compose config --quiet` passed |
| Containers | Build/run, image/OS-package audit and runtime Nginx checks blocked by the unavailable engine; static inspection is not a substitute |

The separate browser smoke exercised scenario selection, completed exact-run schedules, four-trial experiment submission/results, and mobile layout/navigation. The observed 390px viewport had no horizontal page overflow. Browser smoke and jsdom interaction tests are not a comprehensive cross-browser or screen-reader certification. Temporary viewport overrides were reset and test API/dev processes were stopped.

Benchmark settings: seeds 11/22/33, 0.5-second per-trial cap, 100 iterations, presets tiny/harbor/tight/scattered, full algorithms plus no-adaptation/no-local-search variants. 72 trials were feasible (including three certified exact optima); three local-search trials on the tight-window scenario correctly reported no feasible solution found. No trial errored. This is correctness/representative-run evidence, **not** a statistical superiority or hardware-neutral performance claim. Time-capped trajectories may vary between runs. The manifests retain platform, source fingerprint, solver configuration and input hashes.

Test host: Windows, Python 3.11.5, Node 20.20.0, Vite 8.0.16, optional OR-Tools 9.15.6755. Prefer a maintained Python patch and Node 22 for new deployments; the actual Linux image build remains a release gate.

## Blocking container gate

The installed Docker CLI cannot connect to `dockerDesktopLinuxEngine`. Starting Desktop fails while initializing its internal ingest socket (`sailor-ingest.sock`: file cannot be accessed). A read-only WSL check found no independent engine socket or Podman alternative. No factory reset, Docker-state deletion, system installation, paid service, or infrastructure migration was attempted.

Repair/start an available local OCI engine before rerunning the gate. Container base-image contents, Linux installation, live Nginx headers/proxying, and actual container shutdown cannot be certified until that succeeds.

## Non-blocking scope limitations

- Single-machine SQLite, trusted local access, no auth/multi-tenancy/TLS termination or automatic retention purge. Do not expose this configuration publicly. The notebook displays the newest 100 entries, retaining older rows.
- Exact proof is limited to eight customers; heuristic failure is not an infeasibility proof. OR-Tools rounding can exclude borderline-feasible floating-point routes.
- Optional OSRM was tested with mocked responses and cache/unit/reachability checks, not a downloaded regional graph. The offline SVG is schematic; no road geometry or traffic claims.
- Time-limited runs are not bitwise reproducible across hardware. More datasets/seeds and isolated timing are needed for comparative performance claims.
- Upstream test/reference deprecation warnings remain (Starlette's httpx test adapter, SWIG types, jsdom's transitive encoding package). These are not suppressed; tests/builds and vulnerability audits pass.
- Backend/frontend remain separate Git repositories. Root Compose and deployment documentation are outside both; publishing them needs an explicit repository decision.

## Commands to reproduce / finish

Activate the backend virtualenv, install manifests, and install the frontend lockfile before running. Stop local servers on 8000/8080; keep the container engine running. From `backend`:

```sh
python -m pip install -r requirements-bootstrap.txt
python -m pip install -r requirements-dev.txt -r requirements-reference.txt
python scripts/verify_release.py --output artifacts/release-check-next
```

Run `npm ci` from `frontend` before the script on a clean checkout. The output directory must be new. Expected completion: every check `passed`, process exit code 0, `report.json` has `release_ready: true`. The script builds/starts a separate `routelab-release-check` Compose project, checks proxied readiness/optimization/static security headers, then stops it without deleting its volume.

Current r2 exit code is **1**, solely because engine availability failed and container build/run was blocked. Do not label the container release ready until the final gate passes.
