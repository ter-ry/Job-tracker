#!/usr/bin/env python3
"""Run one bounded, read-only Glassdoor JobSpy description probe.

This uses the normal pinned JobSpy adapter.  It does not open saved databases,
retry blocked pages, bypass access controls, or write provider results.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sources.jobspy_source import fetch_jobspy_jobs, get_jobspy_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keywords", default="Registered Early Childhood Educator")
    parser.add_argument("--location", default="Toronto, Ontario")
    parser.add_argument("--results-wanted", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    bounded_results = max(1, min(args.results_wanted, 10))
    bounded_timeout = max(5, min(args.timeout_seconds, 60))
    result = fetch_jobspy_jobs(
        keywords=args.keywords,
        location=args.location,
        distance=25,
        results_wanted=bounded_results,
        hours_old=None,
        enabled_sources=["glassdoor"],
        country_indeed="Canada",
        provider_timeout_seconds=bounded_timeout,
        execution_mode="process",
    )
    diagnostic = result.get("source_diagnostics", {}).get("glassdoor", {})
    jobs = result.get("jobs", [])
    descriptions = [item for item in jobs if str(item.get("description") or "").strip()]
    workplace_evidence = [item for item in descriptions if item.get("workplace_address") or item.get("workplace_postal_code") or item.get("workplace_alternatives")]
    report = {
        "read_only": True,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "jobspy_version": get_jobspy_version(),
        "request": {"provider": "glassdoor", "keywords": args.keywords, "location": args.location, "results_wanted": bounded_results, "timeout_seconds": bounded_timeout},
        "provider_state": diagnostic.get("state", ""),
        "provider_status": diagnostic.get("provider_status", ""),
        "error": diagnostic.get("error", ""),
        "raw_records": diagnostic.get("raw_records_row_count", 0),
        "usable_jobs": len(jobs),
        "descriptions_returned": len(descriptions),
        "descriptions_with_workplace_evidence": len(workplace_evidence),
        "network_policy": "one bounded normal JobSpy call; no retries or bypass",
        "jobs": [{"title": item.get("title", ""), "company": item.get("company", ""), "url": item.get("job_url", ""), "description_length": len(str(item.get("description") or "")), "workplace_evidence": bool(item.get("workplace_address") or item.get("workplace_postal_code") or item.get("workplace_alternatives"))} for item in jobs],
    }
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).expanduser().write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
