#!/usr/bin/env python3
"""Bounded, read-only ScraperAPI feasibility benchmark for job-specific pages."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Iterable

import app
from sources.scraperapi_source import ScraperApiConfig, fetch_scraperapi_page


CASES = {
    "https://ca.indeed.com/viewjob?jk=960d67145bdf8eb3": {"name": "Daycare Centre Midtown", "postal_code": "M5P 1J4"},
    "https://ca.indeed.com/viewjob?jk=5b10c60264baec65": {"name": "BGC East Scarborough", "address": "100 Galloway Road", "postal_code": "M1E 1W7"},
}


def benchmark(urls: list[str], *, config: ScraperApiConfig, max_credits: int) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    attempted = 0
    consumed = 0
    for url in urls:
        case = CASES.get(url, {})
        if attempted >= max_credits:
            results.append({"url": url, "status": "skipped_budget", "retrieval_succeeded": False, "reason": "Configured ScraperAPI request/credit budget exhausted."})
            continue
        started = time.perf_counter()
        page = fetch_scraperapi_page(url, config=config)
        if page.get("request_made"):
            attempted += 1
            consumed += 1
        item = {key: value for key, value in page.items() if key != "body"}
        item["latency_ms"] = item.get("latency_ms") or round((time.perf_counter() - started) * 1000, 1)
        if page.get("retrieval_succeeded"):
            parsed = app._extract_workplace_from_page({"source": "Indeed", "source_job_id": url.split("jk=", 1)[-1], "title": case.get("name", ""), "company": case.get("name", ""), "location": "Ontario"}, page.get("body", ""), url)
            item["valid_job_page"] = bool(parsed)
            item["candidates"] = parsed
            item["precise_evidence"] = bool(parsed)
            item["expected_match"] = bool(parsed) and all(any(str(expected).casefold() in json.dumps(candidate, ensure_ascii=False).casefold() for candidate in parsed) for expected in (case.get("address"), case.get("postal_code")) if expected)
            if not item["valid_job_page"]:
                item["status"] = "invalid_job_page"
        else:
            item["valid_job_page"] = False
            item["candidates"] = []
            item["precise_evidence"] = False
            item["expected_match"] = False
        item["expected"] = case
        results.append(item)
    return {
        "read_only": True, "provider": "scraperapi", "configured": bool(config.api_key and config.enabled),
        "request_budget": max_credits, "requests_attempted": attempted, "credits_consumed": consumed,
        "successful_valid_job_pages": sum(bool(item.get("valid_job_page")) for item in results),
        "precise_evidence_count": sum(bool(item.get("precise_evidence")) for item in results),
        "expected_matches": sum(bool(item.get("expected_match")) for item in results),
        "results": results,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", action="append", dest="urls", help="Approved Indeed URL; repeat for additional bounded cases")
    parser.add_argument("--max-credits", type=int, default=2)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = benchmark(args.urls or list(CASES), config=ScraperApiConfig.from_environment(), max_credits=max(0, min(args.max_credits, 20)))
    Path(args.output).expanduser().write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("configured", "requests_attempted", "credits_consumed", "successful_valid_job_pages", "expected_matches")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
