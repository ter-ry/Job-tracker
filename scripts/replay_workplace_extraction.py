#!/usr/bin/env python3
"""Read-only replay of workplace extraction for one saved search cohort.

The database is opened with SQLite ``mode=ro`` and ``query_only``.  This tool
does not fetch posting pages, call geocoders, or update jobs.  It replays only
the saved description/provider metadata for the exact search execution and
applicant supplied by the caller.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from scripts.diagnose_ece_workplace_evidence import (
    _json,
    _parser_rejection,
    _text,
    open_readonly,
)
from sources.jobspy_source import extract_workplace_alternatives, extract_workplace_location

POSTAL_PATTERN = r"[A-Z]\d[A-Z][ -]?\d[A-Z]\d"


def _canonical_address(address: str, postal_code: str = "") -> str:
    """Normalize harmless formatting/directional variants for deduplication."""
    raw = _text(address).casefold()
    raw = re.sub(r"\b[a-z]\d[a-z][ -]?\d[a-z]\d\b", " ", raw, flags=re.I)
    comma_parts = [part.strip() for part in raw.split(",") if part.strip()]
    if len(comma_parts) > 1 and re.match(r"^\d+\b", comma_parts[0]):
        raw = comma_parts[0]
    value = re.sub(r"[^a-z0-9]+", " ", raw).strip()
    replacements = {
        "street": "st", "avenue": "ave", "road": "rd", "drive": "dr",
        "boulevard": "blvd", "place": "pl", "court": "ct", "lane": "ln",
        "west": "w", "east": "e", "north": "n", "south": "s",
    }
    value = " ".join(replacements.get(part, part) for part in value.split())
    embedded_postal = re.search(POSTAL_PATTERN, _text(address), re.I)
    postal = re.sub(r"[^a-z0-9]", "", (_text(postal_code) or (embedded_postal.group(0) if embedded_postal else "")).casefold())
    # A street address is authoritative for this replay; provider variants
    # may append city/postal text to one candidate but omit it from another.
    # Postal-only candidates still need their postal identity.
    return value if re.match(r"^\d+\b", value) else f"{value}|{postal}" if postal else value


def _merge_saved_provider_row(row: dict[str, Any]) -> dict[str, Any]:
    """Expose nested saved provider fields without overwriting normalized data."""
    merged = dict(row)
    raw = _json(row.get("provider_raw_json"), {})
    if isinstance(raw, dict):
        for key, value in raw.items():
            if not _text(merged.get(key)) and value not in (None, "", [], {}):
                merged[key] = value
    merged["provider_raw_json"] = raw
    return merged


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        address = _text(candidate.get("address"))
        postal = _text(candidate.get("postal_code"))
        key = _canonical_address(address, postal)
        if not key:
            continue
        existing = seen.get(key)
        if existing is None:
            item = dict(candidate)
            item["owner_confirmation_required"] = True
            seen[key] = item
            result.append(item)
            continue
        # Keep the most informative evidence while retaining the original
        # candidate status and never converting it into an owner confirmation.
        if len(_text(candidate.get("evidence"))) > len(_text(existing.get("evidence"))):
            existing["evidence"] = candidate.get("evidence")
        existing["confidence"] = max(int(existing.get("confidence") or 0), int(candidate.get("confidence") or 0))
    return result


def _previous_location(row: dict[str, Any]) -> dict[str, Any]:
    address = _text(row.get("workplace_address"))
    postal = _text(row.get("workplace_postal_code"))
    return {
        "address": address,
        "postal_code": postal,
        "precision": _text(row.get("workplace_precision")),
        "evidence": _text(row.get("workplace_evidence")),
        "present": bool(address or postal),
        "canonical": _canonical_address(address, postal) if address or postal else "",
    }


def _raw_location_fields(row: dict[str, Any]) -> list[dict[str, str]]:
    """Expose saved JobSpy location-shaped fields without treating them as proof."""
    fields: list[dict[str, str]] = []
    keys = {"location", "job_location", "joblocation", "location_header", "title_header", "street_address", "postal_code", "postcode", "zip_code", "address"}

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child = f"{path}.{key}" if path else str(key)
                if str(key).casefold() in keys and not isinstance(item, (dict, list)) and _text(item):
                    fields.append({"field": child, "value": _text(item)})
                elif isinstance(item, (dict, list)):
                    visit(item, child)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    for key in ("location", "provider_location", "location_header", "title_header", "job_location", "street_address", "postal_code", "address"):
        if _text(row.get(key)):
            fields.append({"field": key, "value": _text(row[key])})
    visit(_json(row.get("provider_raw_json"), {}), "provider_raw_json")
    return fields


def replay_cohort(db: sqlite3.Connection, search_id: str, applicant_id: int, expected_count: int | None = None) -> dict[str, Any]:
    rows = db.execute(
        """SELECT j.*, m.category AS membership_category, m.reason AS membership_reason
           FROM jobs j JOIN discovery_search_memberships m ON m.job_id = j.id
           WHERE m.search_execution_id = ? AND m.applicant_profile_id = ?
             AND m.category = 'actionable'
           ORDER BY j.id""",
        (search_id, applicant_id),
    ).fetchall()
    if expected_count is not None and len(rows) != expected_count:
        raise ValueError(f"Selected search has {len(rows)} exact actionable memberships; expected {expected_count}.")
    records: list[dict[str, Any]] = []
    for source_row in rows:
        row = _merge_saved_provider_row(dict(source_row))
        description = _text(row.get("job_description"))
        provider_location = _text(row.get("provider_location") or row.get("location"))
        previous = _previous_location(row)
        raw_location_fields = _raw_location_fields(row)
        alternatives = _dedupe_candidates(extract_workplace_alternatives(row, description, provider_location))
        parsed = extract_workplace_location(row, description, provider_location)
        candidate_keys = {_canonical_address(item.get("address", ""), item.get("postal_code", "")) for item in alternatives}
        if alternatives:
            if len(alternatives) > 1:
                outcome = "ambiguous"
            elif previous["canonical"] and previous["canonical"] in candidate_keys:
                outcome = "unchanged"
            else:
                outcome = "improved"
            reason = ""
        else:
            outcome = "unchanged" if previous["present"] else "rejected"
            reason = "; ".join(_parser_rejection(description, provider_location, row, [])) or "No street or postal candidate survived workplace-context checks."
        records.append({
            "job_id": int(row["id"]),
            "title": _text(row.get("title")),
            "employer": _text(row.get("company")),
            "source": _text(row.get("source")),
            "original_posting_url": _text(row.get("url") or row.get("original_posting_url")),
            "raw_jobspy_location_fields": raw_location_fields,
            "normalized_provider_location": provider_location,
            "original_workplace": previous,
            "new_candidates": alternatives,
            "newly_extracted_address": alternatives[0].get("address", "") if len(alternatives) == 1 else "",
            "newly_extracted_postal_code": alternatives[0].get("postal_code", "") if len(alternatives) == 1 else "",
            "supporting_description_excerpt": alternatives[0].get("evidence", "") if len(alternatives) == 1 else "; ".join(_text(item.get("evidence")) for item in alternatives),
            "extraction_confidence": max((int(item.get("confidence") or 0) for item in alternatives), default=0),
            "assignment_status": "; ".join(sorted({_text(item.get("assignment_status")) for item in alternatives if _text(item.get("assignment_status"))})),
            "owner_confirmation_required": bool(alternatives),
            "retrieval_improved_saved_data": outcome == "improved",
            "result": outcome,
            "reason_no_address": reason,
            "parser_result": parsed,
            "description_present": bool(description),
            "description_length": len(description),
        })
    counts: dict[str, int] = {}
    for record in records:
        counts[record["result"]] = counts.get(record["result"], 0) + 1
    return {
        "read_only": True,
        "network_requests": 0,
        "search_execution_id": search_id,
        "applicant_profile_id": applicant_id,
        "expected_count": expected_count,
        "cohort_count": len(records),
        "jobspy_indeed_location_note": "JobSpy 1.4.1's IndeedLocation exposes city, admin1Code and countryCode only; street/postal header evidence is reported when preserved elsewhere, but is not reconstructed from a city-only value.",
        "counts": counts,
        "jobs": records,
    }


CSV_FIELDS = (
    "job_id", "title", "employer", "source", "original_workplace",
    "original_posting_url", "raw_jobspy_location_fields", "normalized_provider_location",
    "newly_extracted_address", "newly_extracted_postal_code",
    "supporting_description_excerpt", "extraction_confidence", "assignment_status",
    "owner_confirmation_required", "result", "reason_no_address",
    "retrieval_improved_saved_data",
)


def write_csv(report: dict[str, Any], path: str | Path) -> None:
    with Path(path).expanduser().open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for item in report["jobs"]:
            row = dict(item)
            row["original_workplace"] = json.dumps(row["original_workplace"], ensure_ascii=False, sort_keys=True)
            row["raw_jobspy_location_fields"] = json.dumps(row["raw_jobspy_location_fields"], ensure_ascii=False, sort_keys=True)
            writer.writerow({key: row.get(key, "") for key in CSV_FIELDS})


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--search-id", required=True)
    parser.add_argument("--applicant-id", required=True, type=int)
    parser.add_argument("--expected-count", type=int, default=28)
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--csv-out", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    with open_readonly(args.db) as db:
        report = replay_cohort(db, args.search_id, args.applicant_id, args.expected_count)
    json_path = Path(args.json_out).expanduser()
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(report, args.csv_out)
    print(json.dumps({"read_only": True, "cohort_count": report["cohort_count"], "counts": report["counts"], "json": str(json_path), "csv": str(Path(args.csv_out).expanduser())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
