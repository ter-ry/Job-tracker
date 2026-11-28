#!/usr/bin/env python3
r"""Read-only diagnostic for saved workplace evidence in a Fresh QA database.

This deliberately does not fetch posting pages and never opens the database in
write mode.  It explains whether a missing workplace is caused by absent saved
description/provider evidence or by the current deterministic parser rejecting
evidence that is present.

Typical use on the owner's Fresh QA installation::

    python scripts/diagnose_ece_workplace_evidence.py --db \
      "$env:LOCALAPPDATA\Job Tracker QA 5002\Job Tracker\jobs.sqlite" \
      --list-searches --workflow ece

Then run the exact cohort with the opaque search execution ID shown above::

    python scripts/diagnose_ece_workplace_evidence.py --db $db \
      --search-id <search_execution_id> --applicant-id <ece_profile_id> \
      --output ece-workplace-diagnostic.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from sources.jobspy_source import (
    NON_WORKPLACE_CUE,
    POSTAL_PATTERN,
    STREET_PATTERN,
    WORKPLACE_CUE,
    WORKPLACE_LABEL_CUE,
    _plain_location_text,
    extract_workplace_alternatives,
    extract_workplace_location,
)


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default
    return parsed


def _text(value: Any) -> str:
    return str(value or "").strip()


def _table_exists(db: sqlite3.Connection, name: str) -> bool:
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def open_readonly(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite database without allowing writes."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Database does not exist: {resolved}")
    db = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only = ON")
    return db


def _candidate_location_values(value: Any, path: str = "") -> list[dict[str, str]]:
    """Report location-shaped provider values without treating them as proof."""
    values: list[dict[str, str]] = []
    if isinstance(value, str):
        parsed = _json(value, None)
        if parsed is not None:
            return _candidate_location_values(parsed, path)
        if path and any(token in path.casefold() for token in ("location", "address", "postal", "postcode", "zip")):
            if STREET_PATTERN.search(value) or re.search(POSTAL_PATTERN, value, re.I) or re.search(r"\b(?:Toronto|Mississauga|Brampton|Ontario|ON)\b", value, re.I):
                precision = "street address" if STREET_PATTERN.search(value) else "postal code" if re.search(POSTAL_PATTERN, value, re.I) else "city or region"
                values.append({"path": path, "value": value.strip()[:500], "precision": precision})
        return values
    if isinstance(value, list):
        for index, item in enumerate(value):
            values.extend(_candidate_location_values(item, f"{path}[{index}]") )
        return values
    if not isinstance(value, dict):
        return values
    for key, item in value.items():
        child = f"{path}.{key}" if path else str(key)
        key_lower = str(key).casefold()
        if key_lower in {"location", "job_location", "joblocation", "workplace_location", "structured_location", "address", "street_address", "streetaddress", "addresslocality", "addressregion", "postalcode", "postal_code", "postcode", "zip_code", "location_header", "title_header"}:
            values.extend(_candidate_location_values(item, child))
        elif isinstance(item, (dict, list)) and key_lower in {"raw", "metadata", "jsonld", "structured_data", "jobposting", "provider_raw_json"}:
            values.extend(_candidate_location_values(item, child))
    return values


def _description_evidence(description: str) -> dict[str, Any]:
    plain = _plain_location_text(description)
    postal = [m.group(0).upper().replace("-", " ") for m in re.finditer(POSTAL_PATTERN, plain, re.I)]
    street = [m.group(0) for m in re.finditer(STREET_PATTERN, plain)]
    labels = [m.group(0) for m in WORKPLACE_LABEL_CUE.finditer(plain)]
    wording = [m.group(0) for m in WORKPLACE_CUE.finditer(plain)]
    excerpts: list[str] = []
    for match in list(re.finditer(POSTAL_PATTERN, plain, re.I)) + list(re.finditer(STREET_PATTERN, plain)):
        excerpts.append(plain[max(0, match.start() - 110):min(len(plain), match.end() + 150)].strip())
    return {
        "plain_text_length": len(plain),
        "postal_codes": sorted(set(postal)),
        "street_like_values": sorted(set(street)),
        "workplace_labels": sorted(set(labels)),
        "location_wording": sorted(set(wording)),
        "excerpts": excerpts[:12],
    }


def _parser_rejection(description: str, provider_location: str, row: dict[str, Any], alternatives: list[dict[str, Any]]) -> list[str]:
    if alternatives:
        return []
    reasons: list[str] = []
    evidence = _description_evidence(description)
    plain = _plain_location_text(description)
    if not description:
        reasons.append("missing_description")
    elif not evidence["street_like_values"] and not evidence["postal_codes"]:
        if evidence["location_wording"]:
            reasons.append("location_wording_without_street_or_postal_evidence")
        else:
            reasons.append("no_street_or_canadian_postal_pattern")
    else:
        if evidence["street_like_values"] and not WORKPLACE_CUE.search(plain):
            reasons.append("street_like_text_has_no_nearby_workplace_cue")
        if evidence["postal_codes"] and not WORKPLACE_LABEL_CUE.search(plain):
            reasons.append("postal_code_has_no_workplace_label")
        if NON_WORKPLACE_CUE.search(plain):
            reasons.append("non_workplace_cue_headquarters_mailing_or_registered_address")
        if not reasons:
            reasons.append("candidate_rejected_by_current_parser; inspect excerpts and provider fields")
    if provider_location and not re.search(POSTAL_PATTERN, provider_location, re.I) and not STREET_PATTERN.search(provider_location):
        reasons.append("provider_location_is_city_or_region_only")
    if row.get("provider_raw_json") and not _candidate_location_values(_json(row.get("provider_raw_json"), {})):
        reasons.append("provider_raw_json_has_no_recognized_precise_location")
    return reasons


def list_searches(db: sqlite3.Connection, workflow: str = "", applicant_id: int | None = None) -> list[dict[str, Any]]:
    if not _table_exists(db, "discovery_search_memberships"):
        raise RuntimeError("Database has no discovery_search_memberships table")
    conditions = ["1=1"]
    params: list[Any] = []
    if applicant_id is not None:
        conditions.append("m.applicant_profile_id IN (0, ?)")
        params.append(applicant_id)
    rows = db.execute(
        f"""SELECT m.search_execution_id, MAX(m.created_at) AS last_seen,
                   SUM(CASE WHEN m.category = 'actionable' THEN 1 ELSE 0 END) AS actionable_count,
                   SUM(CASE WHEN m.category = 'review_required' THEN 1 ELSE 0 END) AS review_count,
                   COUNT(*) AS membership_count,
                   GROUP_CONCAT(DISTINCT m.applicant_profile_id) AS applicant_profile_ids,
                   MAX(m.criteria_json) AS criteria_json
            FROM discovery_search_memberships m
            WHERE {' AND '.join(conditions)}
            GROUP BY m.search_execution_id ORDER BY last_seen DESC""", params
    ).fetchall()
    result = []
    for row in rows:
        criteria = _json(row["criteria_json"], {})
        if workflow and _text(criteria.get("workflow") or criteria.get("occupation")).casefold() != workflow.casefold():
            # ECE searches historically use either workflow=e ce or an
            # occupation/title field, so retain rows whose keywords identify it.
            haystack = json.dumps(criteria, ensure_ascii=False).casefold()
            if workflow.casefold() not in haystack and not (workflow.casefold() == "ece" and "early childhood" in haystack):
                continue
        result.append({
            "search_execution_id": _text(row["search_execution_id"]),
            "last_seen": _text(row["last_seen"]),
            "actionable_count": int(row["actionable_count"] or 0),
            "review_count": int(row["review_count"] or 0),
            "membership_count": int(row["membership_count"] or 0),
            "applicant_profile_ids": [int(value) for value in _text(row["applicant_profile_ids"]).split(",") if value.strip().isdigit()],
            "criteria": criteria,
        })
    return result


def diagnose_database(db: sqlite3.Connection, search_id: str, applicant_id: int | None = None) -> dict[str, Any]:
    if not search_id:
        raise ValueError("--search-id is required for a cohort diagnostic")
    params: list[Any] = [search_id]
    applicant_clause = ""
    if applicant_id is not None:
        applicant_clause = " AND m.applicant_profile_id IN (0, ?)"
        params.append(applicant_id)
    rows = db.execute(
        f"""SELECT j.*, m.category AS membership_category, m.reason AS membership_reason,
                   m.evidence_json AS membership_evidence, m.criteria_json AS membership_criteria,
                   m.applicant_profile_id AS membership_applicant_id
            FROM jobs j JOIN discovery_search_memberships m ON m.job_id = j.id
            WHERE m.search_execution_id = ? AND m.category = 'actionable'{applicant_clause}
            ORDER BY j.id""", params
    ).fetchall()
    records: list[dict[str, Any]] = []
    for source_row in rows:
        row = dict(source_row)
        description = _text(row.get("job_description"))
        raw = _json(row.get("provider_raw_json"), {})
        raw_locations = _candidate_location_values(raw)
        raw_precise_locations = [item for item in raw_locations if item.get("precision") in {"street address", "postal code"}]
        provider_fields = []
        for key in ("provider_location", "location", "location_header", "title_header", "workplace_address", "workplace_postal_code"):
            if _text(row.get(key)):
                provider_fields.append({"field": key, "value": _text(row[key])})
        parser_row = dict(row)
        parser_row["provider_raw_json"] = raw
        provider_location = _text(row.get("provider_location") or row.get("location"))
        alternatives = extract_workplace_alternatives(parser_row, description, provider_location)
        parsed = extract_workplace_location(parser_row, description, provider_location)
        description_evidence = _description_evidence(description)
        parser_detected = bool(alternatives or parsed.get("address") or parsed.get("postal_code"))
        saved_precise = bool(_text(row.get("workplace_address")) or _text(row.get("workplace_postal_code")))
        records.append({
            "job_id": int(row["id"]),
            "title": _text(row.get("title")),
            "company": _text(row.get("company")),
            "source": _text(row.get("source")),
            "original_url": _text(row.get("url") or row.get("original_posting_url")),
            "description": {"present": bool(description), "character_length": len(description), **description_evidence},
            "provider_metadata": {
                "provider_location_fields": provider_fields,
                "all_location_candidates": raw_locations,
                "recognized_precise_location_candidates": raw_precise_locations,
                "saved_provider_raw_json_present": bool(_text(row.get("provider_raw_json"))),
            },
            "current_saved_workplace": {
                "address": _text(row.get("workplace_address")),
                "postal_code": _text(row.get("workplace_postal_code")),
                "precision": _text(row.get("workplace_precision")),
                "evidence": _text(row.get("workplace_evidence")),
            },
            "parser": {
                "detected": parser_detected,
                "alternatives": alternatives,
                "result": parsed,
                "rejection_reasons": _parser_rejection(description, provider_location, parser_row, alternatives),
            },
            "original_listing_comparison": {
                "status": "not_fetched_read_only_diagnostic",
                "saved_data_missing_precise_location": not bool(raw_locations or provider_fields or description_evidence["street_like_values"] or description_evidence["postal_codes"]),
                "interpretation": "An original-page address cannot be independently confirmed here; no blocked provider page was requested.",
            },
            "search_membership": {
                "search_execution_id": search_id,
                "applicant_profile_id": int(row.get("membership_applicant_id") or 0),
                "category": _text(row.get("membership_category")),
                "reason": _text(row.get("membership_reason")),
            },
        })
    counts = Counter()
    for item in records:
        if item["description"]["present"]:
            counts["description_present"] += 1
        else:
            counts["description_missing"] += 1
        if item["provider_metadata"]["recognized_precise_location_candidates"]:
            counts["provider_precise_candidates"] += 1
        if item["parser"]["detected"]:
            counts["parser_detected"] += 1
        else:
            counts["parser_not_detected"] += 1
        if item["original_listing_comparison"]["saved_data_missing_precise_location"]:
            counts["no_saved_precise_evidence"] += 1
    return {"read_only": True, "search_execution_id": search_id, "applicant_profile_id": applicant_id, "cohort_count": len(records), "counts": dict(counts), "jobs": records}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="SQLite database path; opened read-only")
    parser.add_argument("--search-id", help="Opaque search execution ID for the exact cohort")
    parser.add_argument("--applicant-id", type=int)
    parser.add_argument("--expected-count", type=int, help="Fail if the selected actionable cohort is not exactly this size")
    parser.add_argument("--workflow", default="", help="Optional workflow filter for --list-searches")
    parser.add_argument("--list-searches", action="store_true", help="List saved membership cohorts without diagnosing jobs")
    parser.add_argument("--output", help="Optional JSON report path; database remains read-only")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        with open_readonly(args.db) as db:
            if args.list_searches:
                result: dict[str, Any] = {"read_only": True, "database": str(Path(args.db).expanduser().resolve()), "searches": list_searches(db, args.workflow, args.applicant_id)}
            else:
                if not args.search_id:
                    parser.error("--search-id is required unless --list-searches is supplied")
                result = diagnose_database(db, args.search_id, args.applicant_id)
                if args.expected_count is not None and result["cohort_count"] != args.expected_count:
                    raise ValueError(
                        f"Selected search {args.search_id} has {result['cohort_count']} actionable jobs; expected {args.expected_count}."
                    )
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        print(f"Diagnostic failed without modifying the database: {exc}", file=sys.stderr)
        return 2
    payload = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=False)
    if args.output:
        Path(args.output).expanduser().write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
