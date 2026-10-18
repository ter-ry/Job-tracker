"""Independent Phase A discovery worker for Windows Task Scheduler or a service."""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


LEASE_NAME = "discovery-worker"
LEASE_MINUTES = 10


def scheduler_enabled() -> bool:
    row = app.query_db("SELECT value FROM app_settings WHERE key = 'discovery_scheduler_enabled'", one=True)
    return bool(row and app.as_bool(row["value"]))


def acquire_lease(owner: str) -> bool:
    now = datetime.now()
    expires = now + timedelta(minutes=LEASE_MINUTES)
    db = app.get_db()
    db.execute("BEGIN IMMEDIATE")
    row = db.execute("SELECT owner, expires_at FROM discovery_worker_leases WHERE name = ?", [LEASE_NAME]).fetchone()
    if row and row["owner"] != owner and row["expires_at"] > now.isoformat(timespec="seconds"):
        db.rollback()
        return False
    db.execute(
        "INSERT INTO discovery_worker_leases (name, owner, acquired_at, expires_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET owner = excluded.owner, acquired_at = excluded.acquired_at, expires_at = excluded.expires_at",
        [LEASE_NAME, owner, now.isoformat(timespec="seconds"), expires.isoformat(timespec="seconds")],
    )
    db.commit()
    return True


def release_lease(owner: str) -> None:
    app.get_db().execute("DELETE FROM discovery_worker_leases WHERE name = ? AND owner = ?", [LEASE_NAME, owner])
    app.get_db().commit()


def run_due_searches() -> dict[str, int]:
    app.init_db()
    if not scheduler_enabled():
        return {"disabled": 1, "runs": 0, "errors": 0}
    owner = f"{socket.gethostname()}:{os.getpid()}"
    if not acquire_lease(owner):
        return {"disabled": 0, "runs": 0, "errors": 0, "overlap_skipped": 1}
    counts = {"disabled": 0, "runs": 0, "errors": 0}
    try:
        now = datetime.now().isoformat(timespec="seconds")
        rows = app.query_db(
            "SELECT * FROM saved_search_profiles WHERE enabled = 1 AND (next_run_at = '' OR next_run_at <= ?)",
            [now],
        )
        for row in rows:
            run_id = app.create_discovery_run(int(row["id"]), "scheduled")
            try:
                result = app.run_discovery_pipeline(app.saved_search_to_discovery_payload(app.saved_search_to_dict(row)), search_id=int(row["id"]), run_id=run_id)
                app.finish_discovery_run(run_id, status="completed", fetched=result["total"], new_count=result["persisted"]["new"], duplicate_count=result["persisted"]["duplicate"], errors=len(result["errors"]), outcomes=result["source_diagnostics"])
                next_run = (datetime.now() + timedelta(minutes=int(row["interval_minutes"]))).isoformat(timespec="seconds")
                app.get_db().execute("UPDATE saved_search_profiles SET last_run_at = CURRENT_TIMESTAMP, next_run_at = ? WHERE id = ?", [next_run, row["id"]])
                app.get_db().commit()
                counts["runs"] += 1
            except Exception as exc:
                app.finish_discovery_run(run_id, status="failed", fetched=0, new_count=0, duplicate_count=0, errors=1, outcomes={}, error=str(exc))
                counts["errors"] += 1
    finally:
        release_lease(owner)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Run enabled Job Tracker discovery searches without Flask.")
    parser.add_argument("--once", action="store_true", help="Run due searches once and exit.")
    parser.add_argument("--daemon", action="store_true", help="Poll due searches until interrupted.")
    parser.add_argument("--poll-seconds", type=int, default=60, help="Polling interval for --daemon.")
    args = parser.parse_args()
    with app.app.app_context():
        if args.daemon:
            while True:
                run_due_searches()
                time.sleep(max(15, args.poll_seconds))
        run_due_searches()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
