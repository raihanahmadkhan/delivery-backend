"""Single-machine durable queue. SQLite transactions serialize worker claims.

Lease tokens fence late completions.
"""

import contextlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

from .matrices import digest

LEASE_SECONDS = 20
SCHEMA_VERSION = 2


def db_path():
    return Path(
        os.environ.get(
            "ROUTELAB_DB", str(Path(__file__).resolve().parents[1] / "data" / "routelab.sqlite3")
        )
    ).resolve()


@contextlib.contextmanager
def connection():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize():
    with connection() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError("Database is newer than this RouteLab build; refusing a downgrade")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
          CREATE TABLE IF NOT EXISTS scenarios (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL
          );
          CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
            request TEXT NOT NULL, result TEXT, progress TEXT, error TEXT,
            created REAL NOT NULL, started REAL, finished REAL,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            lease_token TEXT, heartbeat REAL, attempts INTEGER NOT NULL DEFAULT 0,
            idempotency_key TEXT UNIQUE, request_hash TEXT NOT NULL
          );
          CREATE INDEX IF NOT EXISTS jobs_status_created ON jobs(status, created);
          CREATE TABLE IF NOT EXISTS worker_status (id INTEGER PRIMARY KEY, heartbeat REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS matrix_snapshots (id TEXT PRIMARY KEY, body TEXT NOT NULL, created REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS geo_cache (id TEXT PRIMARY KEY, body TEXT NOT NULL, expires REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS network_slots (id TEXT PRIMARY KEY, next_request REAL NOT NULL);
        """)
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def save_scenario(body):
    identity = digest(body)
    with connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO scenarios VALUES (?, ?, ?, ?)",
            (identity, body["name"], json.dumps(body), time.time()),
        )
    return identity


def get_matrix_snapshot(identity):
    with connection() as conn:
        row = conn.execute("SELECT body FROM matrix_snapshots WHERE id=?", (identity,)).fetchone()
        return json.loads(row["body"]) if row else None


def save_matrix_snapshot(identity, body):
    with connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO matrix_snapshots VALUES (?,?,?)",
            (identity, json.dumps(body, allow_nan=False), time.time()),
        )


def geo_cached(identity):
    with connection() as conn:
        row = conn.execute(
            "SELECT body FROM geo_cache WHERE id=? AND expires>?", (identity, time.time())
        ).fetchone()
        return json.loads(row["body"]) if row else None


def cache_geo(identity, body, seconds=86400):
    encoded = json.dumps(body, allow_nan=False)
    if len(encoded) > 4 * 1024 * 1024:
        raise ValueError("Geographic response exceeded the storage limit")
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM geo_cache WHERE expires<=?", (time.time(),))
        while (
            conn.execute("SELECT coalesce(sum(length(body)),0) FROM geo_cache").fetchone()[0]
            + len(encoded)
            > 32 * 1024 * 1024
            or conn.execute("SELECT count(*) FROM geo_cache").fetchone()[0] >= 1000
        ):
            conn.execute(
                "DELETE FROM geo_cache WHERE id=(SELECT id FROM geo_cache ORDER BY expires LIMIT 1)"
            )
        conn.execute(
            "INSERT OR REPLACE INTO geo_cache VALUES (?,?,?)",
            (identity, encoded, time.time() + seconds),
        )


def reserve_network_slot(service):
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        now = time.time()
        row = conn.execute(
            "SELECT next_request FROM network_slots WHERE id=?", (service,)
        ).fetchone()
        start = max(now, row[0] if row else now)
        if start - now > 3:
            raise ValueError("Map service is busy. Please retry in a few seconds.")
        conn.execute("INSERT OR REPLACE INTO network_slots VALUES (?,?)", (service, start + 1.1))
    if start > now:
        time.sleep(start - now)


def list_scenarios():
    with connection() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT id,name,created FROM scenarios ORDER BY created DESC LIMIT 100"
            )
        ]


def get_scenario(identity):
    with connection() as conn:
        row = conn.execute("SELECT body FROM scenarios WHERE id=?", (identity,)).fetchone()
        return json.loads(row["body"]) if row else None


def enqueue(kind, body, key=None):
    request_hash = digest({"kind": kind, "body": body})
    identity = uuid.uuid4().hex
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if key:
            row = conn.execute(
                "SELECT id,request_hash FROM jobs WHERE idempotency_key=?", (key,)
            ).fetchone()
            if row:
                if row["request_hash"] != request_hash:
                    raise ValueError("Idempotency key was already used for a different request")
                return row["id"]
        active = conn.execute(
            "SELECT count(*) FROM jobs WHERE status IN ('queued','running')"
        ).fetchone()[0]
        if active >= 12:
            raise OverflowError("Queue is full (12 active jobs); wait for a run to finish")
        conn.execute(
            "INSERT INTO jobs(id,kind,status,request,created,idempotency_key,request_hash) VALUES (?,?,?,?,?,?,?)",
            (identity, kind, "queued", json.dumps(body), time.time(), key, request_hash),
        )
    return identity


def decode(row, full=True):
    if row is None:
        return None
    item = dict(row)
    for field in ["request", "result", "progress"]:
        if field in item and item[field]:
            item[field] = json.loads(item[field])
    item.pop("lease_token", None)
    item.pop("idempotency_key", None)
    if not full:
        request = item.pop("request", {})
        item["name"] = request.get("scenario", {}).get("name", "Replanning experiment")
        item["algorithm"] = request.get("options", {}).get("algorithm", item["kind"])
    return item


def get_job(identity):
    with connection() as conn:
        return decode(conn.execute("SELECT * FROM jobs WHERE id=?", (identity,)).fetchone())


def list_jobs():
    with connection() as conn:
        rows = conn.execute(
            "SELECT id,kind,status,request,progress,error,created,started,finished,attempts FROM jobs ORDER BY created DESC LIMIT 100"
        )
        return [decode(row, full=False) for row in rows]


def cancel(identity):
    with connection() as conn:
        conn.execute(
            "UPDATE jobs SET cancel_requested=1, status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END, finished=CASE WHEN status='queued' THEN ? ELSE finished END WHERE id=? AND status IN ('queued','running')",
            (time.time(), identity),
        )
    return get_job(identity)


def worker_heartbeat():
    with connection() as conn:
        conn.execute("INSERT OR REPLACE INTO worker_status VALUES (1,?)", (time.time(),))


def health():
    with connection() as conn:
        row = conn.execute("SELECT heartbeat FROM worker_status WHERE id=1").fetchone()
        return {
            "storage": "sqlite",
            "worker_alive": bool(row and time.time() - row["heartbeat"] < 12),
            "active_jobs": conn.execute(
                "SELECT count(*) FROM jobs WHERE status IN ('queued','running')"
            ).fetchone()[0],
        }


def claim():
    now = time.time()
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE jobs SET status=CASE WHEN cancel_requested=1 THEN 'cancelled' WHEN attempts>=3 THEN 'failed' ELSE 'queued' END, error='Worker lease expired; interrupted attempt', lease_token=NULL, finished=CASE WHEN attempts>=3 OR cancel_requested=1 THEN ? ELSE NULL END WHERE status='running' AND (heartbeat IS NULL OR heartbeat < ?)",
            (now, now - LEASE_SECONDS),
        )
        row = conn.execute(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        token = uuid.uuid4().hex
        conn.execute(
            "UPDATE jobs SET status='running',started=?,finished=NULL,error=NULL,progress=NULL,result=NULL,heartbeat=?,lease_token=?,attempts=attempts+1 WHERE id=?",
            (now, now, token, row["id"]),
        )
        job = decode(row)
        job["lease_token"] = token
        return job


def pulse(identity, token):
    with connection() as conn:
        now = time.time()
        conn.execute(
            "UPDATE jobs SET heartbeat=? WHERE id=? AND lease_token=? AND status='running' AND heartbeat>=?",
            (now, identity, token, now - LEASE_SECONDS),
        )
        row = conn.execute(
            "SELECT cancel_requested,lease_token,status,heartbeat FROM jobs WHERE id=?", (identity,)
        ).fetchone()
        return (
            row is None
            or row["cancel_requested"]
            or row["lease_token"] != token
            or row["status"] != "running"
            or row["heartbeat"] is None
            or row["heartbeat"] < now - LEASE_SECONDS
        )


def progress(identity, token, value):
    with connection() as conn:
        now = time.time()
        conn.execute(
            "UPDATE jobs SET progress=?,heartbeat=? WHERE id=? AND lease_token=? AND status='running' AND heartbeat>=?",
            (json.dumps(value, allow_nan=False), now, identity, token, now - LEASE_SECONDS),
        )


def complete(identity, token, result=None, error=None):
    with connection() as conn:
        now = time.time()
        conn.execute(
            "UPDATE jobs SET status=CASE WHEN cancel_requested=1 THEN 'cancelled' WHEN ? IS NOT NULL THEN 'failed' ELSE 'completed' END,result=?,error=?,finished=?,lease_token=NULL WHERE id=? AND lease_token=? AND status='running' AND heartbeat>=?",
            (
                error,
                json.dumps(result, allow_nan=False) if result is not None else None,
                error,
                now,
                identity,
                token,
                now - LEASE_SECONDS,
            ),
        )


def abandon(identity, token):
    with connection() as conn:
        conn.execute(
            "UPDATE jobs SET status=CASE WHEN cancel_requested=1 THEN 'cancelled' WHEN attempts>=3 THEN 'failed' ELSE 'queued' END, lease_token=NULL, heartbeat=NULL, progress=NULL, error='Worker stopped before completion', finished=CASE WHEN cancel_requested=1 OR attempts>=3 THEN ? ELSE NULL END WHERE id=? AND lease_token=? AND status='running'",
            (time.time(), identity, token),
        )
