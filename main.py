import asyncio
import os
import sqlite3
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from config import get_allowed_hosts, get_cors_origins
from routelab import VERSION, store
from routelab.api import router
from routelab.http_safety import RequestSafety


@asynccontextmanager
async def lifespan(app):
    store.initialize()
    worker = None
    stop_file = store.db_path().parent / f"worker-{uuid.uuid4().hex}.stop"
    if os.environ.get("ROUTELAB_EMBEDDED_WORKER", "1") == "1":
        env = {
            **os.environ,
            "ROUTELAB_DB": str(store.db_path()),
            "ROUTELAB_PARENT_PID": str(os.getpid()),
            "ROUTELAB_STOP_FILE": str(stop_file),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        worker = subprocess.Popen(
            [sys.executable, "-B", "-m", "routelab.worker"],
            cwd=Path(__file__).parent,
            env=env,
            creationflags=flags,
        )
    try:
        yield
    finally:
        if worker:
            stop_file.touch()
            try:
                await asyncio.to_thread(worker.wait, timeout=5)
            except subprocess.TimeoutExpired:
                worker.terminate()
                try:
                    await asyncio.to_thread(worker.wait, timeout=3)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    await asyncio.to_thread(worker.wait, timeout=3)
            stop_file.unlink(missing_ok=True)


app = FastAPI(
    title="RouteLab",
    version=VERSION,
    description="Geographic route planning with validated, reproducible optimization experiments.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Idempotency-Key"],
)
app.include_router(router)
app.add_middleware(RequestSafety, allowed_origins=get_cors_origins())
app.add_middleware(TrustedHostMiddleware, allowed_hosts=get_allowed_hosts())


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"loc": error["loc"], "msg": str(error["msg"])[:500], "type": error["type"]}
                for error in exc.errors()[:25]
            ]
        },
    )


@app.exception_handler(sqlite3.OperationalError)
async def storage_unavailable(request, exc):
    return JSONResponse(
        status_code=503,
        content={"detail": "Storage temporarily unavailable"},
        headers={"Retry-After": "1"},
    )


@app.get("/ready")
def ready():
    state = store.health()
    return JSONResponse(status_code=200 if state["worker_alive"] else 503, content=state)


@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION, **store.health()}


@app.get("/")
def root():
    return {"name": "RouteLab", "docs": "/docs", "version": VERSION}
