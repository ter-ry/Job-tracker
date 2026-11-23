#!/usr/bin/env python3
"""Read-only replay of bounded Indeed workplace retrieval for one saved cohort.

The selected SQLite database is opened read-only.  This tool never calls the
application cache or writes job rows; each eligible Indeed URL is fetched at
most once with a hard timeout and response-size bound.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

import app
from scripts.diagnose_ece_workplace_evidence import open_readonly
from scripts.replay_workplace_extraction import _canonical_address, _text


def _fetch_once(url: str, allowed_hosts: set[str], timeout: float, max_bytes: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": "Job Tracker workplace replay/1.0"})
    try:
        opener = urllib.request.build_opener(app._SafePublicRedirect(allowed_hosts))
        with opener.open(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            final_url = response.geturl() if hasattr(response, "geturl") else url
            if len(body) > max_bytes:
                return {"ok": False, "status": "response_too_large", "error": f"Response exceeded {max_bytes} bytes."}
            if (app.urlsplit(final_url).hostname or "").lower().rstrip(".") not in allowed_hosts:
                return {"ok": False, "status": "redirect_not_approved", "error": "Final host was not an approved Indeed host."}
            return {"ok": True, "status": "ok", "body": body.decode("utf-8", errors="replace"), "final_url": final_url, "http_status": int(getattr(response, "status", 200) or 200)}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": f"http_{int(exc.code)}", "error": f"HTTP {int(exc.code)}: access denied or unavailable."}
    except Exception as exc:
        return {"ok": False, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def _previous(row: dict[str, Any]) -> dict[str, str | bool]:
    address = _text(row.get("workplace_address"))
    postal = _text(row.get("workplace_postal_code"))
    return {"address": address, "postal_code": postal, "precision": _text(row.get("workplace_precision")), "present": bool(address or postal), "canonical": _canonical_address(address, postal) if address or postal else ""}


def replay_cohort(db: sqlite3.Connection, search_id: str, applicant_id: int, expected_count: int, *, timeout: float = 8, max_bytes: int = 1_200_000) -> dict[str, Any]:
    rows = db.execute(
        """SELECT j.* FROM jobs j JOIN discovery_search_memberships m ON m.job_id = j.id
           WHERE m.search_execution_id = ? AND m.applicant_profile_id = ? AND m.category = 'actionable'
           ORDER BY j.id""",
        (search_id, applicant_id),
    ).fetchall()
    if len(rows) != expected_count:
        raise ValueError(f"Selected search has {len(rows)} actionable jobs; expected {expected_count}.")
    records: list[dict[str, Any]] = []
    request_count = 0
    for source_row in rows:
        row = dict(source_row)
        before = _previous(row)
        saved = app._stored_workplace_alternatives(row)
        alternatives = saved
        retrieval: dict[str, Any] = {"status": "saved_evidence", "ok": bool(saved)}
        url = _text(row.get("url") or row.get("application_url"))
        approved, allowed_hosts = app._approved_job_page_url(row, url)
        if not alternatives and approved:
            request_count += 1
            retrieval = _fetch_once(url, allowed_hosts, timeout, max_bytes)
            if retrieval.get("ok"):
                alternatives = app._extract_workplace_from_page(row, _text(retrieval.get("body")), _text(retrieval.get("final_url")) or url)
        keys = {_canonical_address(item.get("address", ""), item.get("postal_code", "")) for item in alternatives}
        if len(alternatives) > 1:
            result = "ambiguous"
        elif alternatives and before["canonical"] and before["canonical"] in keys:
            result = "unchanged"
        elif alternatives:
            result = "improved"
        elif before["present"]:
            result = "unchanged"
        else:
            result = "blocked" if str(retrieval.get("status", "")).startswith(("http_", "failed", "redirect")) else "unresolved"
        records.append({
            "job_id": int(row["id"]), "title": _text(row.get("title")), "employer": _text(row.get("company")), "source": _text(row.get("source")),
            "original_posting_url": url, "original_workplace": before,
            "new_candidates": alternatives, "newly_extracted_address": alternatives[0].get("address", "") if len(alternatives) == 1 else "",
            "newly_extracted_postal_code": alternatives[0].get("postal_code", "") if len(alternatives) == 1 else "",
            "supporting_excerpt": alternatives[0].get("evidence", "") if len(alternatives) == 1 else "; ".join(_text(item.get("evidence")) for item in alternatives),
            "confidence": max((int(item.get("confidence") or 0) for item in alternatives), default=0),
            "assignment_status": "; ".join(sorted({_text(item.get("assignment_status")) for item in alternatives if _text(item.get("assignment_status"))})),
            "owner_confirmation_required": bool(alternatives), "result": result,
            "retrieval_status": retrieval.get("status", ""), "retrieval_error": retrieval.get("error", ""),
        })
    counts: dict[str, int] = {}
    for item in records:
        counts[item["result"]] = counts.get(item["result"], 0) + 1
    return {"read_only": True, "network_requests": request_count, "search_execution_id": search_id, "applicant_profile_id": applicant_id, "expected_count": expected_count, "cohort_count": len(records), "counts": counts, "jobs": records}


CSV_FIELDS = ("job_id", "title", "employer", "source", "original_posting_url", "original_workplace", "newly_extracted_address", "newly_extracted_postal_code", "supporting_excerpt", "confidence", "assignment_status", "owner_confirmation_required", "result", "retrieval_status", "retrieval_error")


def write_csv(report: dict[str, Any], path: str | Path) -> None:
    with Path(path).expanduser().open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for item in report["jobs"]:
            row = dict(item)
            row["original_workplace"] = json.dumps(row["original_workplace"], ensure_ascii=False, sort_keys=True)
            writer.writerow({key: row.get(key, "") for key in CSV_FIELDS})


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--search-id", required=True)
    parser.add_argument("--applicant-id", required=True, type=int)
    parser.add_argument("--expected-count", type=int, default=28)
    parser.add_argument("--timeout-seconds", type=float, default=8)
    parser.add_argument("--max-bytes", type=int, default=1_200_000)
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--csv-out", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    with open_readonly(args.db) as db:
        report = replay_cohort(db, args.search_id, args.applicant_id, args.expected_count, timeout=max(3, min(args.timeout_seconds, 30)), max_bytes=max(100_000, min(args.max_bytes, 5_000_000)))
    Path(args.json_out).expanduser().write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(report, args.csv_out)
    print(json.dumps({key: report[key] for key in ("read_only", "cohort_count", "network_requests", "counts")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
