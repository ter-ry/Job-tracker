#!/usr/bin/env python3
"""Create a clean disposable workspace while retaining one profile and résumé.

The default is a read-only plan. ``--apply`` is required to create the target;
an existing target is refused unless ``--replace-existing`` is also supplied,
and replacement first creates a recoverable backup beside it.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


PROFILE_TABLES = {"candidate_profiles", "base_resumes", "cover_letter_templates", "keyword_memory"}


def tables(db: sqlite3.Connection) -> list[str]:
    return [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]


def columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def create_fresh_workspace(source: Path, target: Path, profile_id: int, *, apply: bool = False, replace_existing: bool = False) -> dict[str, object]:
    if source.resolve() == target.resolve():
        raise ValueError("Source and target databases must be different")
    if not source.is_file():
        raise ValueError(f"Source database does not exist: {source}")
    source_db = sqlite3.connect(source)
    source_db.row_factory = sqlite3.Row
    profile = source_db.execute("SELECT * FROM candidate_profiles WHERE id = ?", (profile_id,)).fetchone()
    if profile is None:
        source_db.close()
        raise ValueError(f"Candidate profile {profile_id} was not found in the source database")
    counts = {table: int(source_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables(source_db)}
    report = {"mode": "apply" if apply else "preview", "source": str(source), "target": str(target), "profile_id": profile_id, "source_counts": counts, "guarantees": {"discovered_jobs": 0, "search_runs": 0, "presentations": 0, "excluded": 0, "review_required": 0}}
    if not apply:
        source_db.close()
        return report
    if target.exists() and not replace_existing:
        source_db.close()
        raise ValueError("Target already exists; preview it and pass --replace-existing explicitly")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = target.with_name(f"{target.stem}-before-fresh-{stamp}{target.suffix}.bak")
        shutil.copy2(target, backup)
        report["target_backup"] = str(backup)
    target_db = sqlite3.connect(target)
    source_db.backup(target_db)
    target_db.execute("PRAGMA foreign_keys = OFF")
    all_tables = tables(target_db)
    for table in all_tables:
        if table == "candidate_profiles":
            target_db.execute("DELETE FROM candidate_profiles WHERE id <> ?", (profile_id,))
        elif table in {"base_resumes", "cover_letter_templates", "keyword_memory"}:
            profile_column = "candidate_profile_id" if "candidate_profile_id" in columns(target_db, table) else "profile_id"
            target_db.execute(f"DELETE FROM {table} WHERE {profile_column} <> ?", (profile_id,))
        elif table == "profile":
            target_db.execute("DELETE FROM profile")
        else:
            target_db.execute(f"DELETE FROM {table}")
    target_db.commit()
    target_db.close(); source_db.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--profile-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--replace-existing", action="store_true")
    args = parser.parse_args()
    try:
        report = create_fresh_workspace(args.source, args.target, args.profile_id, apply=args.apply, replace_existing=args.replace_existing)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps({"ok": True, **report}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
