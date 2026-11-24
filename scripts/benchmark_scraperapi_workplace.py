#!/usr/bin/env python3
"""Bounded, read-only ScraperAPI feasibility benchmark for job-specific pages."""
from __future__ import annotations

import argparse
import json
import re
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, urlsplit
from pathlib import Path
from typing import Any, Iterable

import app
from sources.scraperapi_source import ScraperApiConfig, fetch_scraperapi_page


CASES = {
    "https://ca.indeed.com/viewjob?jk=960d67145bdf8eb3": {"name": "Daycare Centre Midtown", "postal_code": "M5P 1J4"},
    "https://ca.indeed.com/viewjob?jk=5b10c60264baec65": {"name": "BGC East Scarborough", "address": "100 Galloway Road", "postal_code": "M1E 1W7"},
}


def _identity_evidence_is_present(page: str, employer: str, source_job_id: str) -> bool:
    """Require both page-contained identifier and contextual employer evidence."""
    visible = app._visible_job_page_text(page).casefold()
    tokens = [token for token in re.findall(r"[a-z0-9]+", employer.casefold()) if len(token) >= 3]
    if len(tokens) < 2:
        return False

    # A requested URL is not evidence about the document returned for it. Use
    # only identifiers retained by the returned document: canonical/job links,
    # explicit job-id fields, or JobPosting JSON-LD URLs.
    document_ids: set[str] = set()
    canonical_tags = re.findall(r"<link\b[^>]*\brel=[\"'][^\"']*canonical[^\"']*[\"'][^>]*>", page, re.I)
    canonical_tags += re.findall(r"<link\b[^>]*\bcanonical[^>]*>", page, re.I)
    for tag in canonical_tags:
        for href in re.findall(r"\bhref=[\"']([^\"']+)", tag, re.I):
            document_ids.update(dict(parse_qsl(urlsplit(href).query, keep_blank_values=True)).get("jk", "").casefold().split())
    for raw in re.findall(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", page, re.I | re.S):
        for found in re.findall(r"(?:[?&]jk=|[\"'](?:jobId|jobKey|jk)[\"']\s*:\s*[\"'])([a-z0-9_-]{6,})", raw, re.I):
            document_ids.add(found.casefold())
    expected_id = source_job_id.casefold()
    if expected_id not in document_ids or any(item != expected_id for item in document_ids):
        return False

    # Employer evidence must be in a role-bearing heading or structured
    # employer field, rather than an arbitrary footer/marketing occurrence.
    headings = " ".join(re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", page, re.I | re.S))
    heading_text = app._visible_job_page_text(headings).casefold()
    heading_match = sum(token in heading_text for token in tokens) >= min(2, len(tokens))
    structured_employer = False
    for raw in re.findall(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", page, re.I | re.S):
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        serialized = json.dumps(payload, ensure_ascii=False).casefold()
        if any(marker in serialized for marker in ("hiringorganization", "employer", "company")):
            structured_employer = sum(token in serialized for token in tokens) >= min(2, len(tokens))
            if structured_employer:
                break
    return heading_match or structured_employer


def benchmark(urls: list[str], *, config: ScraperApiConfig, max_credits: float) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    attempted = 0
    consumed = Decimal("0")
    authorized_budget = Decimal(str(max_credits))
    cost_unknown = False
    budget_exceeded = False
    max_requests = 2
    for url in urls:
        case = CASES.get(url, {})
        remaining = authorized_budget - consumed
        configured_cost = Decimal(str(config.max_cost))
        request_max_cost = min(configured_cost, remaining)
        if attempted >= max_requests or cost_unknown or budget_exceeded or request_max_cost <= 0:
            reason = "The maximum two-request benchmark limit was reached."
            if cost_unknown:
                reason = "Previous response did not report sa-credit-cost; stopped conservatively because cumulative cost is unknown."
            elif budget_exceeded:
                reason = "Previous response reported consumption above the authorized benchmark budget; stopped conservatively."
            elif remaining <= 0:
                reason = "Configured ScraperAPI credit budget exhausted."
            results.append({"url": url, "status": "skipped_budget", "retrieval_succeeded": False, "reason": reason})
            continue
        started = time.perf_counter()
        source_job_id = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True)).get("jk", "")
        page = fetch_scraperapi_page(url, config=config, source_job_id=source_job_id, max_cost=request_max_cost)
        if page.get("request_made"):
            attempted += 1
            cost = page.get("credit_cost")
            if cost is None:
                cost_unknown = True
            else:
                try:
                    parsed_cost = Decimal(str(cost))
                except (InvalidOperation, TypeError, ValueError):
                    parsed_cost = None
                if parsed_cost is None or not parsed_cost.is_finite() or parsed_cost < 0:
                    cost_unknown = True
                else:
                    consumed += parsed_cost
                    if parsed_cost > request_max_cost or consumed > authorized_budget:
                        budget_exceeded = True
        item = {key: value for key, value in page.items() if key != "body"}
        if budget_exceeded:
            item["budget_status"] = "exceeded"
        item["latency_ms"] = item.get("latency_ms") or round((time.perf_counter() - started) * 1000, 1)
        if page.get("retrieval_succeeded"):
            job = {"source": "Indeed", "source_job_id": source_job_id, "title": case.get("name", ""), "company": case.get("name", ""), "location": "Ontario"}
            parsed = app._extract_workplace_from_page(job, page.get("body", ""), url)
            identity_verified = _identity_evidence_is_present(page.get("body", ""), case.get("name", ""), source_job_id)
            item["identity_status"] = "verified" if identity_verified else "unverified"
            item["valid_job_page"] = bool(parsed) and identity_verified
            item["candidates"] = parsed
            item["precise_evidence"] = bool(parsed) and identity_verified
            item["expected_match"] = item["valid_job_page"] and all(any(str(expected).casefold() in json.dumps(candidate, ensure_ascii=False).casefold() for candidate in parsed) for expected in (case.get("address"), case.get("postal_code")) if expected)
            if not item["valid_job_page"]:
                item["status"] = "identity_unverified" if parsed and not identity_verified else "invalid_job_page"
        else:
            item["identity_status"] = "not_assessed"
            item["valid_job_page"] = False
            item["candidates"] = []
            item["precise_evidence"] = False
            item["expected_match"] = False
        item["expected"] = case
        results.append(item)
    return {
        "read_only": True, "provider": "scraperapi", "configured": bool(config.api_key and config.enabled),
        "request_budget": max_credits, "max_requests": max_requests, "requests_attempted": attempted,
        "credits_consumed": None if cost_unknown else float(consumed),
        "credits_consumed_status": "unknown" if cost_unknown else "known",
        "budget_exceeded": budget_exceeded,
        "timeout_policy": {"default_seconds": config.timeout_seconds, "configured_by": "SCRAPERAPI_TIMEOUT_SECONDS", "owner_note": "Do not cancel or retry a live request solely to shorten it; the provider may charge interrupted synchronous requests."},
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
