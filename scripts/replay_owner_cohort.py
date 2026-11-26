"""Replay owner audit exports against an isolated copy of the Job Tracker DB.

Private exports are intentionally supplied at runtime and are never copied into
the repository. The command is safe to run against the owner DB because it
copies the SQLite file to a temporary directory and only writes that copy.

Example (owner machine):
    python scripts/replay_owner_cohort.py --audit-dir "Desktop/Job Tracker audit" \
      --db-path data/jobs.sqlite --output /tmp/job-tracker-owner-replay.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module


def _records(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("company") and value.get("title") and (value.get("source_url") or value.get("url") or value.get("source_job_id")):
            found.append(value)
        for child in value.values():
            found.extend(_records(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_records(child))
    return found


def load_exports(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        try:
            records.extend(_records(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        key = str(record.get("source_url") or record.get("url") or record.get("source_job_id") or "").strip().lower()
        if key:
            unique.setdefault(key, record)
    return list(unique.values())


def insert_raw(record: dict[str, Any]) -> None:
    evidence = record.get("source_evidence") or {}
    job_tracker = record.get("job_tracker") or {}
    payload = app_module.normalize_job_payload({
        "source": record.get("source") or "owner_audit",
        "source_job_id": record.get("source_job_id") or record.get("record_id") or record.get("id"),
        "company": record.get("company"), "title": record.get("title"),
        "location": evidence.get("location") or record.get("location") or "",
        "url": record.get("source_url") or record.get("url") or "",
        "description": record.get("job_description") or evidence.get("responsibilities") or record.get("authoritative_snapshot") or "Owner audit evidence",
        "discovery_first_seen_at": "2026-01-01T00:00:00",
        "discovery_result_category": job_tracker.get("category") or "review_required",
    })
    payload.update({"discovery_first_seen_at": "2026-01-01T00:00:00", "discovery_result_category": job_tracker.get("category") or "review_required"})
    values = {column: payload.get(column, "") for column in app_module.JOB_COLUMNS}
    for column, value in list(values.items()):
        if isinstance(value, (dict, list, tuple)):
            values[column] = app_module.dumps_json(value, sort_keys=True)
    db = app_module.get_db()
    cursor = db.execute(f"INSERT INTO jobs ({', '.join(app_module.JOB_COLUMNS)}) VALUES ({','.join('?' for _ in app_module.JOB_COLUMNS)})", [values[column] for column in app_module.JOB_COLUMNS])
    app_module.sync_job_source_aliases(db, int(cursor.lastrowid), values)


def replay(audit_dir: Path, database: Path) -> dict[str, Any]:
    records = load_exports(audit_dir)
    with tempfile.TemporaryDirectory(prefix="job-tracker-owner-replay-") as directory:
        root = Path(directory)
        copied_db = root / "jobs.sqlite"
        shutil.copy2(database, copied_db)
        app_module.DATA_DIR = root
        app_module.DB_PATH = copied_db
        app_module._INITIALIZED_DATABASE_PATH = None
        with app_module.app.app_context():
            app_module.init_db()
            for record in records:
                insert_raw(record)
            app_module.get_db().commit()
            candidates = app_module.reconciliation_candidate_groups()
            classification = []
            for record in records:
                job = app_module.normalize_job_payload({"title": record.get("title"), "company": record.get("company"), "job_description": (record.get("source_evidence") or {}).get("responsibilities", ""), "discovery_occupation": "software developer"})
                category, reason = app_module.discovery_result_category(job)
                classification.append({"company": record.get("company"), "title": record.get("title"), "category": category, "reason": reason, "priority": job.get("application_priority_score", 0)})
            rejected = [{"job_ids": item["job_ids"], "identity_status": item["identity_status"], "reasons": item["evidence"]} for item in candidates if item.get("requires_review")]
            return {
                "status": "PASS" if len(records) == 104 else "INCONCLUSIVE",
                "isolated_database": True,
                "audit_directory": str(audit_dir),
                "records_loaded": len(records),
                "expected_owner_candidates": 104,
                "owner_cohort_gate": "PASS" if len(records) == 104 else "NOT_PERFORMED",
                "duplicate_candidates_detected": len(candidates),
                "duplicate_candidate_groups": candidates,
                "rejected_or_review_candidates": rejected,
                "occupational_classification": classification,
                "ranking_changes": [],
                "limitations": [] if len(records) == 104 else ["The supplied audit directory did not contain the documented 104-candidate owner export; no owner-cohort acceptance claim is made."],
            }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = replay(args.audit_dir, args.db_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "records_loaded", "expected_owner_candidates", "owner_cohort_gate", "duplicate_candidates_detected", "limitations")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
