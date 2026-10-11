# RouteLab final review — 12 October 2026

The final cleanup preserves the existing architecture and useful capstone features. Native tests, builds, worker lifecycle checks, dependency audits, and retained benchmark validation pass. **Container build/run verification remains blocked by the unavailable local Docker engine.** RouteLab remains a shared workbench without authentication; this review does not certify a private or untrusted public dispatch service.

## Scope and decisions

Reviewed the frontend components, controls, persisted drafts, API client, map/schedule/replay/comparison views, backend endpoints, input models, imports, matrices, all solvers, independent evaluator, replanning, experiments, CLI/benchmark tools, SQLite store, worker, HTTP safety, dependencies, configuration, deployment recipes, and documentation.

The independent evaluator, frozen matrices, background worker with recovery leases, solver comparisons, bounded exact oracle, optional OR-Tools reference, exports, and onboard disruption repair all have useful, explainable roles. They were retained. No new features, state frameworks, brokers, services, authentication system, or project restructuring were introduced. Existing uncommitted work was preserved. No unused runtime dependency requiring removal was found.

## Targeted changes

- Hide ALNS-only controls for methods that ignore them; prevent oversized exact solves and invalid comparison submissions.
- Clear obsolete Undo state after scenario replacement, recover from missing bookmarked runs, and reject malformed persisted matrix data before rendering.
- Display synthetic geographic route order with an explicit straight-line caption; keep imported matrices without road provenance location-only.
- Correct multi-day schedule labels, unavailable experiment timing, and the replanning method shown in History. Remove confirmed unused icons, selectors, and a redundant class.
- Check cancellation before fast solver construction and preserve cancellation caught by the OR-Tools callback.
- Reject half-provided CSV latitude/longitude pairs; retain Cartesian CSV compatibility when both geographic columns are blank.
- Normalize empty idempotency keys to avoid duplicate-key server errors. Canonicalize equivalent provider URLs so community-service limits remain enforced.
- Reject invalid tile hosts/ports and HTTP tile hosts blocked by deployment CSP. Remove the ineffective IPv6 literal from default allowed hosts; retain supported outbound IPv6 provider URLs.
- Select the maintained Python 3.11 series instead of pinning an old patch. Add focused regressions and skip only optional reference checks when OR-Tools is absent.

## Verified

| Check | Result |
| --- | --- |
| Backend suite | 66 tests passed, including input/security boundaries, solver/evaluator agreement, API idempotency, geographic providers, persistence and lease races |
| Frontend suite | 47 interaction tests passed |
| Static/build checks | Ruff lint and format, strict TypeScript, ESLint, and Vite production build passed |
| Runtime dependencies | `pip check` passed; `pip-audit --local` and `npm audit --audit-level=low` reported no known vulnerabilities |
| API and spawned worker | Exact solve, experiment, replan, and CSV export passed using temporary databases |
| Real process lifecycle | Queued/running cancellation, graceful restart, abrupt supervisor death, orphan recovery, exclusive concurrent claims, and SQLite integrity passed |
| Benchmark artifacts | 75 trials across four presets, three seeds, reference methods, and ALNS ablations; every scenario/matrix hash recomputed and result independently re-evaluated |
| Additional correctness check | 100 constrained directed/unreachable tiny instances matched independent exhaustive enumeration |
| Optional-free core tests | Only two reference-specific tests skipped with OR-Tools unavailable; remaining checks passed |
| Browser | Exact solution and schedule, bounded delay repair, three-trial comparison, History reload, meaningful solver controls, and mobile navigation checked; no observed console errors or horizontal overflow at the 390px test viewport |
| Live geographic smoke | Photon returned five Pune suggestions; public OSRM supplied a directed two-point snapshot and matching 55-point geometry (0.4027 km / 1.125 min outbound leg) |
| Compose | Base and optional road override configurations validated |
| Containers | Engine unavailable; Linux image build, image/OS-package audit, runtime Nginx proxy/headers, and container shutdown remain unverified |

Machine evidence: `backend/artifacts/final-review-20261012-r2/report.json` and adjacent logs/benchmark artifacts. The initial `final-review-20261012` report is retained: it found one test-format issue, which was corrected before the final run. The final report intentionally returns `release_ready: false` and exit code 1 when the engine check fails. Native validation is not a substitute for container execution.

The live-service smoke is retained in `backend/artifacts/final-review-live-services.json`; browser evidence in `backend/artifacts/final-review-browser.jpg`. Artifacts are Git-ignored. Earlier audit evidence remains in its original artifact directories. The source tests and this review are tracked.

The verified host used Windows, Python 3.11.5, Node 20.20.0, and the installed optional OR-Tools reference. Use maintained Python patches and Node 22 for deployment. Windows sandbox socket/temp restrictions required native validation outside the sandbox; they were not worked around in application code. Test processes used isolated databases; the user's notebook was preserved.

## Genuine limitations

- Saved scenarios, history, and job controls are shared by every visitor. CORS and allowed hosts are not authorization. Keep access trusted; private/untrusted deployment requires a separate access-control design.
- SQLite and worker coordination target one machine. Persistent hosting storage is needed to retain history; saved artifacts are not automatically purged.
- Public tiles/search/routing need internet and offer no SLA or live traffic. The lightweight live smoke confirms current connectivity, not provider availability or full road-network coverage. No regional OSRM dataset or complete cross-browser/accessibility certification was performed.
- Exact proofs stop at eight customers. Heuristic failure is not infeasibility proof; OR-Tools integer rounding and time caps retain their documented limitations. Replanning repairs one disruption with fixed onboard assignments.
- Container deployment remains an external verification gate. No deployment, commit, or push was performed.
- Backend and frontend are separate Git repositories. Root Compose files and deployment documentation are outside both and are not included by pushing either repository.

To repeat the complete gate after an engine is available, run from `backend` with installed development/reference requirements and frontend dependencies:

```sh
python scripts/verify_release.py --output artifacts/release-check-next
```

Use a new output directory. The runner retains all evidence and reports success only when every gate passes.
