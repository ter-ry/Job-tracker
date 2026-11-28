#!/usr/bin/env python3
"""Preview/apply applicant-specific Applied history from a QA database.

This utility intentionally does not import the Flask application.  It requires
explicit database paths and defaults to a read-only preview.  Applying requires
``--apply`` and never overwrites the production file; both source and target
are backed up before the transaction starts.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_KEYS = {"fbclid", "gclid", "ref", "source", "src"}


def canonical_url(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return raw
    query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
             if key.casefold() not in TRACKING_KEYS and not key.casefold().startswith("utm_")]
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path or "/", urlencode(query), ""))


def _columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in db.execute(f"PRAGMA table_info({table})")]


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _json_urls(row: sqlite3.Row) -> set[str]:
    values = {row["url"], row["application_url"]}
    try:
        values.update(json.loads(row["source_links_json"] or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return {canonical_url(str(value)) for value in values if value}


def _profile(db: sqlite3.Connection, profile_id: int | None, name: str) -> sqlite3.Row | None:
    if profile_id:
        return db.execute("SELECT * FROM candidate_profiles WHERE id = ?", (profile_id,)).fetchone()
    if name:
        return db.execute("SELECT * FROM candidate_profiles WHERE lower(name) = lower(?) ORDER BY id LIMIT 1", (name,)).fetchone()
    return None


def _applied_rows(db: sqlite3.Connection, profile_id: int) -> list[sqlite3.Row]:
    return db.execute(
        """SELECT j.*, s.date_applied AS state_date_applied
           FROM jobs j JOIN discovery_applicant_states s ON s.job_id = j.id
           WHERE s.applicant_profile_id = ? AND s.state = 'applied'
           ORDER BY j.id""", (profile_id,)
    ).fetchall()


def plan_transfer(qa: sqlite3.Connection, production: sqlite3.Connection, qa_profile_id: int, target_profile_id: int) -> list[dict[str, object]]:
    qa.row_factory = sqlite3.Row
    production.row_factory = sqlite3.Row
    target_jobs = production.execute("SELECT * FROM jobs").fetchall()
    by_url: dict[str, sqlite3.Row] = {}
    by_identity: dict[tuple[str, str], sqlite3.Row] = {}
    for row in target_jobs:
        for value in _json_urls(row):
            if value:
                by_url.setdefault(value, row)
        source = str(row["source"] or "").casefold()
        requisition = str(row["source_job_id"] or "")
        if source and requisition:
            by_identity[(source, requisition)] = row
    outcomes: list[dict[str, object]] = []
    for row in _applied_rows(qa, qa_profile_id):
        source = str(row["source"] or "").casefold()
        requisition = str(row["source_job_id"] or "")
        match = by_identity.get((source, requisition)) if source and requisition else None
        if not match:
            match = next((by_url[url] for url in _json_urls(row) if url in by_url), None)
        if match:
            outcomes.append({"outcome": "matched_existing", "qa_job_id": row["id"], "production_job_id": match["id"], "date_applied": row["state_date_applied"] or row["date_applied"]})
            continue
        same_shape = [candidate for candidate in target_jobs if str(candidate["company"] or "").casefold() == str(row["company"] or "").casefold() and str(candidate["title"] or "").casefold() == str(row["title"] or "").casefold()]
        if same_shape:
            outcomes.append({"outcome": "possible_duplicate", "qa_job_id": row["id"], "candidates": [candidate["id"] for candidate in same_shape]})
        else:
            outcomes.append({"outcome": "imported", "qa_job_id": row["id"], "target_profile_id": target_profile_id, "date_applied": row["state_date_applied"] or row["date_applied"]})
    return outcomes


def _backup(path: Path, label: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = path.with_name(f"{path.stem}-{label}-{stamp}{path.suffix}.bak")
    shutil.copy2(path, target)
    return target


def apply_transfer(qa_path: Path, production_path: Path, qa_profile_id: int, target_profile_id: int, plan: list[dict[str, object]]) -> dict[str, object]:
    qa = sqlite3.connect(qa_path)
    prod = sqlite3.connect(production_path)
    qa.row_factory = sqlite3.Row
    prod.row_factory = sqlite3.Row
    qa_backup = _backup(qa_path, "before-transfer")
    prod_backup = _backup(production_path, "before-transfer")
    try:
        prod.execute("BEGIN IMMEDIATE")
        qa_rows = {int(row["id"]): row for row in _applied_rows(qa, qa_profile_id)}
        job_columns = [column for column in _columns(prod, "jobs") if column not in {"id", "created_at", "updated_at"}]
        imported = 0
        for item in plan:
            if item["outcome"] == "possible_duplicate":
                continue
            if item["outcome"] == "matched_existing":
                production_job_id = int(item["production_job_id"])
            else:
                row = qa_rows[int(item["qa_job_id"])]
                values = [row[column] if column in row.keys() else "" for column in job_columns]
                if "candidate_profile_id" in job_columns:
                    values[job_columns.index("candidate_profile_id")] = target_profile_id
                cursor = prod.execute(f"INSERT INTO jobs ({','.join(job_columns)}) VALUES ({','.join('?' for _ in job_columns)})", values)
                production_job_id = int(cursor.lastrowid)
                imported += 1
            row = qa_rows[int(item["qa_job_id"])]
            if _table_exists(qa, "job_source_aliases") and _table_exists(prod, "job_source_aliases"):
                aliases = qa.execute("SELECT alias_type, alias_value, raw_value FROM job_source_aliases WHERE job_id = ?", (int(item["qa_job_id"]),)).fetchall()
                for alias in aliases:
                    prod.execute("INSERT OR IGNORE INTO job_source_aliases(job_id, alias_type, alias_value, raw_value) VALUES (?, ?, ?, ?)", (production_job_id, alias[0], alias[1], alias[2]))
            if "source_links_json" in row.keys():
                current = prod.execute("SELECT source_links_json FROM jobs WHERE id = ?", (production_job_id,)).fetchone()
                try:
                    links = json.loads(current[0] or "[]") if current else []
                except (TypeError, ValueError, json.JSONDecodeError):
                    links = []
                try:
                    incoming = json.loads(row["source_links_json"] or "[]")
                except (TypeError, ValueError, json.JSONDecodeError):
                    incoming = []
                merged_links = sorted({str(link) for link in [*links, *incoming, row["url"], row["application_url"]] if link}, key=str.casefold)
                prod.execute("UPDATE jobs SET source_links_json = ? WHERE id = ?", (json.dumps(merged_links), production_job_id))
            date_applied = str(item.get("date_applied") or row["date_applied"] or "")
            prod.execute("""INSERT INTO discovery_applicant_states(job_id, applicant_profile_id, state, date_applied)
                            VALUES (?, ?, 'applied', ?)
                            ON CONFLICT(job_id, applicant_profile_id) DO UPDATE SET state='applied', date_applied=CASE WHEN discovery_applicant_states.date_applied <> '' THEN discovery_applicant_states.date_applied ELSE excluded.date_applied END""", (production_job_id, target_profile_id, date_applied))
        prod.commit()
        return {"imported": imported, "matched_existing": sum(item["outcome"] == "matched_existing" for item in plan), "possible_duplicate": sum(item["outcome"] == "possible_duplicate" for item in plan), "qa_backup": str(qa_backup), "production_backup": str(prod_backup)}
    except Exception:
        prod.rollback()
        raise
    finally:
        qa.close(); prod.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa", type=Path, required=True)
    parser.add_argument("--production", type=Path, required=True)
    parser.add_argument("--qa-profile-id", type=int)
    parser.add_argument("--target-profile-id", type=int)
    parser.add_argument("--applicant-name", default="")
    parser.add_argument("--apply", action="store_true", help="Explicitly apply the preview plan")
    args = parser.parse_args()
    if args.qa.resolve() == args.production.resolve():
        parser.error("QA and production database paths must be different")
    qa = sqlite3.connect(args.qa); production = sqlite3.connect(args.production)
    qa.row_factory = sqlite3.Row; production.row_factory = sqlite3.Row
    qa_profile = _profile(qa, args.qa_profile_id, args.applicant_name)
    target_profile = _profile(production, args.target_profile_id, args.applicant_name)
    if not qa_profile or not target_profile:
        print(json.dumps({"outcome": "profile_mismatch", "qa_profile": dict(qa_profile) if qa_profile else None, "target_profile": dict(target_profile) if target_profile else None}, indent=2))
        return 2
    plan = plan_transfer(qa, production, int(qa_profile["id"]), int(target_profile["id"]))
    report = {"mode": "apply" if args.apply else "preview", "qa_profile_id": qa_profile["id"], "target_profile_id": target_profile["id"], "counts": {key: sum(item["outcome"] == key for item in plan) for key in {"matched_existing", "imported", "possible_duplicate"}}, "records": plan}
    if args.apply:
        report["applied"] = apply_transfer(args.qa, args.production, int(qa_profile["id"]), int(target_profile["id"]), plan)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
