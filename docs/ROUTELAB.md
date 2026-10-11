# RouteLab engineering guide

## Status and scope

RouteLab is a local-first routing workbench built on Python/FastAPI and React/Vite. See [the release audit](RELEASE_AUDIT.md) for completed checks and unresolved deployment gates. It is a technical laboratory, not a courier dispatch service. No superiority over established solvers is claimed.

## Mathematical contract

Each customer is served exactly once by a homogeneous vehicle, starting and ending at one depot. Initial route demand must not exceed capacity; deliveries reduce the onboard load. Demand is nonnegative: pickups, split deliveries, reloads, breaks, heterogeneous vehicles, and multiple depots are outside the model.

Travel distance is in kilometres and duration is in minutes. Arrival is previous departure plus the supplied duration; service starts at `max(arrival, window_start)`, and departure adds service duration. A customer's hard window constrains **service start**, not completion. Return must meet both the depot closing time and fleet shift end. An optional maximum route distance is also hard.

Feasible solutions are ordered lexicographically by `(vehicles_used, total_distance_km)`. A shorter invalid route never beats a feasible solution. Incomplete search candidates have an explicit diagnostic ordering—missing customers, violation count, excess, fleet, distance—which is not a physical cost or the published objective. Every published route is independently re-evaluated.

The primary geographic workflow uses a frozen OSRM distance/duration matrix. Road drafts without a matrix are rejected by the engine, never approximated silently. Cartesian presets use Euclidean kilometres and explicit constant speed; legacy geographic benchmark presets use great-circle distance and constant speed, **not road travel or traffic**. Imported matrices may be asymmetric and use paired `null` values for unreachable arcs. Matrix row order must match node order; diagonals are zero. Geographic views use Leaflet and checked road geometry where available; Cartesian benchmark views remain schematic SVG.

## Architecture and ownership

```text
React/TypeScript workbench
  -> FastAPI: validate inputs, freeze requests, return job IDs
  -> SQLite WAL: scenarios + jobs + progress + result artifacts
  -> worker supervisor: claim a fenced lease, spawn one CPU child
  -> routing engine: matrix -> construction/search -> independent evaluator
  -> SQLite result -> SSE/polling -> linked visualizations and exports
```

SQLite is intentional: one workstation does not need a broker and a database service. Transactions serialize claims. Lease tokens reject stale completion writes, heartbeats allow interrupted attempts to retry, and cancellation has cooperative and hard-stop paths. Execution is at least once; only a valid lease can publish completion. Queue size, customer count, search time, trace size, and experiment budgets are bounded. Multiple machines, network-mounted databases, autoscaling, and public tenancy are not supported deployment promises.

API and worker share model/evaluator code, not mutable optimizer state. `models.py` owns input contracts, `matrices.py` travel semantics, `evaluator.py` the independent schedule oracle, `solvers.py` educational algorithms, `reference.py` the optional OR-Tools adapter, `experiments.py` evidence, `store.py` persistence, `worker.py` execution, and `replan.py` disruption semantics.

## Solvers and what can be claimed

1. **Cheapest insertion:** feasible insertion placements, with new routes ordered after placements into an existing route. Transparent baseline; it can get stuck and does not prove infeasibility.
2. **Local search:** construction followed by first-improvement relocate, swap, and full-route 2-opt checks. Reversal is evaluated explicitly, so asymmetric arcs do not use a symmetric shortcut.
3. **ALNS:** random, related, costly-customer, and whole-route removal; cheapest/regret repair; optional local improvement; adaptive operator weights and distance annealing at the same fleet/feasibility level. Both components can be disabled for ablation.
4. **Exact reference:** enumerate feasible ordered customer subsets, then dynamic-program a disjoint route partition. Only completed enumeration certifies the lexicographic optimum or infeasibility, limited to eight customers. Timeout retains an incumbent without claiming a proof.
5. **OR-Tools reference:** optional open-source local dependency (`pip install -r requirements-reference.txt`). Integer scaling conservatively rounds travel/service/demand upward and limits downward. The original floating-point evaluator checks returned routes. Rounding can exclude borderline-feasible routes. This is a heuristic reference, not an optimality certificate.

Each solver receives an explicit wall-time cap. Construction counts against that budget. Deterministic methods may finish early. An iteration cap and seed improve control but do not make a time-limited result bitwise reproducible across hardware. Candidate-check counters are implementation-specific and are not equal-effort budgets across fundamentally different solvers.

## Experiments and evidence

Experiments retain all trials, including errors, incomplete and infeasible results. Algorithm order rotates between seeds. Report feasibility first, then vehicle counts, then distance. Distance summaries are conditional on a solver's minimum feasible fleet count; comparing those medians across different fleet counts is invalid. Standard deviation is descriptive, not evidence of statistical significance.

Each successful trial stores the complete normalized scenario and options, matrix/source provenance, scenario/matrix hashes, package/platform information, solver version, source SHA-256, timings, evaluations, trace, and independent schedules. Failed trials retain options and provenance too; unattempted seed pairs count as missing. JSON exports are the canonical evidence; CSV exports are convenience summaries. Preserve original datasets, provenance, licenses, and units before publishing benchmark claims. Solomon imports preserve raw numerical distance/time conventions; their displayed km-equivalent units must not be confused with real geography.

From `backend/`:

```sh
python -m routelab.cli --preset tiny --algorithm exact --seconds 3 --output artifacts/tiny.json
python -m routelab.cli --preset harbor --experiment --seconds 2 --seeds 11,22,33 --output artifacts/harbor.json
python -m routelab.cli --preset harbor --experiment --no-adaptive --output artifacts/no-adaptation.json
python -m routelab.cli --preset harbor --experiment --no-local-search --output artifacts/no-local.json
```

Artifacts contain inputs, but not the entire Python environment; use the source fingerprint and retain dependency manifests when comparing runs. Do not rename a scenario or alter its matrix mid-comparison and treat it as the same instance.

## Geographic planning and road snapshots

New drafts start in the geographic workspace: place search or map selection, fleet, hard constraints, then solve. The API obtains a directed road matrix before submitting a durable job. The adapter follows the [OSRM Table API](https://project-osrm.org/docs/v5.24.0/api/#table-service): seconds become minutes, metres become kilometres, and unreachable pairs stay null. Distances follow **fastest paths**, not necessarily shortest-distance paths. No straight-line fallback is requested or accepted.

Default internet providers are OSM tiles, Photon place search, and the community OSRM service. Public road requests are limited to 25 deliveries and scheduled no faster than one request per 1.1 seconds per configured service through SQLite. They are for light use, with no SLA. Self-hosted OSRM supports up to 100 deliveries and requires a declared data/profile version. Callers cannot choose arbitrary service URLs. See [the complete geographic/self-hosting guide](GEOGRAPHIC_ROUTING.md).

Matrices are cached by ordered coordinates, profile, engine, and data version (daily acquisition buckets for the unversioned public service). Saved run inputs embed them, so later optimization and experiments use identical travel costs offline. A coordinate identity hash rejects stale matrices. Final road geometry uses stored snap hints and must match every directed matrix leg within 10 metres/1 second. Changed or unavailable road data produces an explicit geometry warning, not invented roads. Search replay uses labelled dashed stop-order lines, not a new network call per iteration.

CLI equivalent: `python -m routelab.cli --preset pune --road --output artifacts/pune-road.json`. The same solver and independent evaluator consume geographic, synthetic, and benchmark matrices.

## Replanning is bounded and physical

A delay is applied after a chosen completed visit (or before departure for zero completed stops). Completed prefixes are frozen. Other vehicles finish any already-started leg/visit before changing their remaining sequence. All deliveries stay on the vehicle that loaded them; there is no unexplained parcel transfer or teleportation.

The experiment compares continuation of the old sequence with within-vehicle sequence repair. A change budget bounds altered outgoing successors, including route starts. This is an educational one-event simulation, not online traffic prediction. New orders, transfers, continuous vehicle location, and chained disruptions are intentionally not implied.

## Persistence and local deployment

The API starts an embedded **separate process** supervisor by default. For explicit separation, set `ROUTELAB_EMBEDDED_WORKER=0` and run `python -m routelab.worker` with the same absolute `ROUTELAB_DB` in another terminal. Use one supervisor for benchmark comparability. Do not run multiple development reloaders against shared data while timing trials.

The workspace Compose recipe mounts a persistent volume into API and worker and binds ports only on loopback. The frontend proxies API and progress streams without buffering. `GET /health` reports database reachability and worker freshness; `/ready` returns 503 without a fresh worker heartbeat. The optional OR-Tools dependency is not installed in the default container.

Back up SQLite with its backup API or stop both processes before copying the database and its WAL state. Do not copy just a live `.sqlite3` file and assume every committed write is included. Saved artifacts remain on disk; the notebook lists the latest 100 entries. The disposable search/geometry cache alone is bounded to 1,000 entries/32 MB, with expiry and oldest-entry eviction.

This build uses a **shared workspace without authentication**. Saved scenarios, job history, and job controls are shared by every visitor. CORS is not access control. Body/time/queue limits, origin and Host checks are implemented; Netlify and Render terminate TLS. Private workspaces would require authentication and authorization. Swagger documentation uses upstream CDN assets; the geographic UI requests visible tiles, place suggestions, and routing data from the configured providers.

## Verification and completion gate

The portable batch runner is available as `python -m routelab.benchmark --output artifacts/suite-01 --ablations`. It retains a start manifest, one complete JSON per instance/variant, raw-trial CSV, and a completion manifest. It refuses to overwrite a nonempty directory. An interrupted study leaves the start manifest and completed artifacts, not a false completion claim. Add `--ortools` only after installing the optional reference. Matched-seed counts are descriptive; exact gaps are only defined when a reference proved an optimum on the same input, and distance gaps require matching fleet counts.

The current audit covers the following areas; consult [its evidence and limitations](RELEASE_AUDIT.md) rather than treating this list as a certification:

- Property/metamorphic tests for coverage, capacity, waits, service starts, return deadlines, unreachable/directed arcs, zero-distance stops, and numerical tolerances.
- Exact-oracle comparisons on generated tiny cases; differential schedule checks against a separately formulated model; OR-Tools integration and scaling edge cases.
- Crash/retry fencing, simultaneous claims, idempotency collisions, cancellation races, restart recovery, persistence corruption/backup tests, and storage quotas.
- Multi-instance, multiple-seed benchmark suite with declared machine, warmup/order controls, raw results, paired comparisons, and ablations. No cherry-picked winning seed.
- Browser flows and accessibility across desktop/mobile: edits, imports, cancellation, reconnection, history, replay, exports, and failed runs.
- Dependency/security cleanup (the implementation install reported existing npm advisories), HTTP bounds, container build/run verification, deployment shutdown, and resource measurements.

The interview story is the invariant chain: **a precise problem contract, independently checked solutions, measured algorithm tradeoffs, durable computation, and an interface that lets another person challenge the result.**
