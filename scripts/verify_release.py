"""Run the release gates once and retain command output, including blocked gates.

Run with the project virtualenv after installing dev and reference requirements.
Stop local servers on 8000/8080 first. No source files or existing data are deleted.
"""

import argparse
import datetime
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    backend = Path(__file__).resolve().parents[1]
    workspace = backend.parent
    python = sys.executable
    npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
    checks = []

    def run(name, command, cwd=backend, timeout=300):
        started = time.monotonic()
        print(f"CHECK: {name}", flush=True)
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            log = result.stdout + result.stderr
            status = "passed" if result.returncode == 0 else "failed"
            code = result.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            log, status, code = str(exc), "blocked", None
        (output / f"{name}.log").write_text(log, encoding="utf-8")
        checks.append(
            {
                "name": name,
                "command": command,
                "cwd": str(cwd),
                "status": status,
                "exit_code": code,
                "seconds": round(time.monotonic() - started, 2),
            }
        )
        print(f"{status.upper()}: {name}", flush=True)
        return status == "passed"

    run("backend-tests", [python, "-m", "unittest", "discover", "-s", "tests", "-v"])
    run("backend-lint", [python, "-m", "ruff", "check", "."])
    run("backend-format", [python, "-m", "ruff", "format", "--check", "."])
    run("api-worker", [python, "scripts/smoke_worker.py"])
    run("worker-lifecycle", [python, "scripts/check_lifecycle.py"])
    run("frontend-check", [npm, "run", "check"], workspace / "frontend")
    run("python-dependencies", [python, "-m", "pip", "check"])
    run(
        "python-audit",
        [python, "-m", "pip_audit", "--local", "--timeout", "15", "--progress-spinner", "off"],
    )
    run("npm-audit", [npm, "audit", "--audit-level=low"], workspace / "frontend")
    run(
        "benchmark",
        [
            python,
            "-m",
            "routelab.benchmark",
            "--output",
            str(output / "benchmark"),
            "--seeds",
            "11,22,33",
            "--seconds",
            "0.5",
            "--iterations",
            "100",
            "--ablations",
            "--ortools",
        ],
    )
    try:
        sys.path.insert(0, str(backend))
        from routelab.evaluator import evaluate
        from routelab.matrices import build_matrix, digest
        from routelab.models import Scenario

        manifest = json.loads(
            (output / "benchmark" / "manifest-complete.json").read_text(encoding="utf-8")
        )
        verified = 0
        for filename in manifest["artifacts"]:
            experiment = json.loads((output / "benchmark" / filename).read_text(encoding="utf-8"))
            assert experiment["completed_trials"] == experiment["planned_trials"]
            for trial in experiment["trials"]:
                assert trial["status"] != "error", trial
                scenario = Scenario.model_validate(trial["scenario"])
                matrix = build_matrix(scenario)
                assert trial["scenario_hash"] == digest(scenario.model_dump())
                assert trial["matrix_hash"] == matrix.hash
                assert trial["evaluation"] == evaluate(scenario, matrix, trial["routes"])
                if trial.get("exact_reference"):
                    assert trial["exact_reference"]["vehicles_gap"] >= 0
                    gap = trial["exact_reference"]["distance_gap_percent"]
                    assert gap is None or gap >= -1e-7
                verified += 1
        assert verified == manifest["trials"] == 75
        checks.append(
            {"name": "benchmark-artifacts", "status": "passed", "trials_revalidated": verified}
        )
    except Exception as exc:
        checks.append({"name": "benchmark-artifacts", "status": "failed", "error": str(exc)})
    compose = ["docker", "compose", "-p", "routelab-release-check"]
    run("compose-config", compose + ["config", "--quiet"], workspace, 30)
    if run("container-engine", ["docker", "info"], workspace, 30):
        if run("container-build", compose + ["build"], workspace, 900):
            try:
                if run(
                    "container-start",
                    compose + ["up", "-d", "--wait", "--wait-timeout", "120"],
                    workspace,
                    150,
                ):
                    started = time.monotonic()

                    def request(path, body=None):
                        data = None if body is None else json.dumps(body).encode()
                        req = urllib.request.Request(
                            "http://127.0.0.1:8080" + path,
                            data=data,
                            headers={"Content-Type": "application/json"},
                        )
                        with urllib.request.urlopen(req, timeout=10) as response:
                            return json.load(response)

                    try:
                        assert request("/ready")["worker_alive"]
                        scenario = request("/api/presets/tiny")
                        job = request(
                            "/api/runs",
                            {
                                "scenario": scenario,
                                "options": {"algorithm": "exact", "time_limit_seconds": 1},
                            },
                        )
                        deadline = time.monotonic() + 30
                        while time.monotonic() < deadline:
                            result = request(f"/api/runs/{job['id']}")
                            if result["status"] not in ("queued", "running"):
                                break
                            time.sleep(0.2)
                        assert (
                            result["status"] == "completed" and result["result"]["proven_optimal"]
                        )
                        with urllib.request.urlopen(
                            "http://127.0.0.1:8080/", timeout=10
                        ) as response:
                            assert response.headers.get("Content-Security-Policy")
                            assert b'<div id="root"></div>' in response.read()
                        checks.append(
                            {
                                "name": "container-http",
                                "status": "passed",
                                "seconds": time.monotonic() - started,
                            }
                        )
                    except Exception as exc:
                        checks.append(
                            {"name": "container-http", "status": "failed", "error": str(exc)}
                        )
            finally:
                run("container-stop", compose + ["down"], workspace, 60)
    else:
        checks.append(
            {
                "name": "container-build-run",
                "status": "blocked",
                "error": "No reachable container engine; Compose validation is not a build/run test.",
            }
        )
    report = {
        "created_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "checks": checks,
        "release_ready": all(check["status"] == "passed" for check in checks),
    }
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Evidence: {output}\nRelease ready: {report['release_ready']}")
    return 0 if report["release_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
