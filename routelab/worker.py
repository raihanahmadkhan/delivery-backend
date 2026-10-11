import multiprocessing
import os
import signal
import time
import traceback
from pathlib import Path

from . import store
from .experiments import run_experiment, run_once
from .models import ExperimentRequest, ReplanRequest, RunRequest
from .replan import run_replan


def parent_alive(pid):
    if not pid:
        return True
    if os.name == "nt":
        # Windows os.kill(pid, 0) is not a safe liveness probe. A read-only
        # process handle lets the supervisor notice abrupt API shutdown too.
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied is not proof of exit.
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def stop(child):
    child.terminate()
    child.join(timeout=3)
    if child.is_alive():
        child.kill()
        child.join(timeout=3)


def execute(job):
    identity, token = job["id"], job["lease_token"]
    supervisor_pid = os.getppid()

    def cancelled():
        return not parent_alive(supervisor_pid) or store.pulse(identity, token)

    def progress(value):
        if parent_alive(supervisor_pid):
            store.progress(identity, token, value)

    try:
        if job["kind"] == "run":
            request = RunRequest.model_validate(job["request"])
            result = run_once(request.scenario, request.options, progress, cancelled)
        elif job["kind"] == "experiment":
            result = run_experiment(
                ExperimentRequest.model_validate(job["request"]), progress, cancelled
            )
        else:
            request = ReplanRequest.model_validate(job["request"])
            parent = store.get_job(request.parent_job_id)
            if not parent or not parent["result"]:
                raise ValueError("Parent result is unavailable")
            result = run_replan(parent["result"], request, progress, cancelled)
        if parent_alive(supervisor_pid):
            store.complete(identity, token, result=result)
        else:
            store.abandon(identity, token)
    except Exception as exc:
        traceback.print_exc()
        store.complete(identity, token, error=f"{type(exc).__name__}: {str(exc)[:700]}")


def main():
    store.initialize()
    context = multiprocessing.get_context("spawn")
    parent_pid = int(os.environ.get("ROUTELAB_PARENT_PID", "0"))
    stop_file = os.environ.get("ROUTELAB_STOP_FILE")
    child = None
    job = None
    stopping = False

    def request_stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)

    def should_stop():
        return stopping or (stop_file and Path(stop_file).exists()) or not parent_alive(parent_pid)

    try:
        while True:
            if should_stop():
                return
            store.worker_heartbeat()
            job = store.claim()
            if job is None:
                time.sleep(0.5)
                continue
            body = job["request"]
            if job["kind"] == "experiment":
                budget = (
                    len(body["algorithms"]) * len(body["seeds"]) * (body["time_limit_seconds"] + 2)
                    + 10
                )
            else:
                budget = body.get("options", {}).get("time_limit_seconds", 3) + 10
            child = context.Process(target=execute, args=(job,))
            child.start()
            start, cancellation_since = time.monotonic(), None
            while child.is_alive():
                if should_stop():
                    return
                store.worker_heartbeat()
                cancelled = store.pulse(job["id"], job["lease_token"])
                if cancelled and cancellation_since is None:
                    cancellation_since = time.monotonic()
                if (
                    cancellation_since is not None and time.monotonic() - cancellation_since > 2
                ) or time.monotonic() - start > budget:
                    stop(child)
                    store.complete(
                        job["id"],
                        job["lease_token"],
                        error="Execution cancelled"
                        if cancelled
                        else "Worker hard deadline exceeded",
                    )
                    break
                child.join(timeout=0.4)
            current = store.get_job(job["id"])
            if current and current["status"] == "running":
                store.complete(
                    job["id"], job["lease_token"], error="Worker process exited without a result"
                )
            child = None
    except KeyboardInterrupt:
        pass
    finally:
        if child and child.is_alive():
            stop(child)
        if job:
            store.abandon(job["id"], job["lease_token"])


if __name__ == "__main__":
    main()
