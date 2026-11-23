#!/usr/bin/env python3
"""Bounded, read-only proof of job-specific workplace retrieval.

This performs one ordinary HTTPS GET per supplied posting URL.  It follows
normal redirects, has no retry/proxy/CAPTCHA behavior, caps response bytes,
and parses only JSON-LD and visible HTML text.  It never writes a database or
claims that a company address is the assigned worksite.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Iterable

from sources.jobspy_source import POSTAL_PATTERN, STREET_PATTERN, _plain_location_text


DEFAULT_URLS = [
    "https://ca.indeed.com/viewjob?jk=960d67145bdf8eb3",
    "https://ca.indeed.com/viewjob?jk=5b10c60264baec65",
]


def _json_ld_locations(html: str) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = []
    for match in re.finditer(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", html, re.I | re.S):
        try:
            payload = json.loads(unescape(match.group(1)))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        values = payload if isinstance(payload, list) else [payload]
        for item in values:
            if not isinstance(item, dict) or "jobposting" not in str(item.get("@type", "")).casefold():
                continue
            job_location = item.get("jobLocation") or item.get("job_location")
            for location in job_location if isinstance(job_location, list) else [job_location]:
                if isinstance(location, dict):
                    address = location.get("address") if isinstance(location.get("address"), dict) else location
                    parts = [str(address.get(key) or "").strip() for key in ("streetAddress", "addressLocality", "addressRegion", "postalCode")]
                    if any(parts):
                        locations.append({"address": ", ".join(part for part in parts if part), "raw": address})
    return locations


def _visible_header_evidence(html: str) -> list[dict[str, str]]:
    visible = _plain_location_text(html)
    header = re.split(r"\bfull\s+job\s+description\b", visible, maxsplit=1, flags=re.I)[0]
    evidence: list[dict[str, str]] = []
    for pattern_name, pattern in (("street_address", STREET_PATTERN), ("postal_code", re.compile(POSTAL_PATTERN, re.I))):
        for match in pattern.finditer(header):
            excerpt = header[max(0, match.start() - 100):min(len(header), match.end() + 100)].strip()
            evidence.append({"kind": pattern_name, "value": match.group(0), "excerpt": excerpt})
    return evidence


def probe_url(url: str, timeout: int, max_bytes: int) -> dict[str, Any]:
    result: dict[str, Any] = {"url": url, "retrieval_succeeded": False, "method": "ordinary_https_get", "manual_confirmation_required": True}
    request = urllib.request.Request(url, headers={"User-Agent": "JobTracker-workplace-feasibility/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            result.update({"retrieval_succeeded": True, "http_status": int(response.status), "final_url": response.geturl(), "content_type": response.headers.get("content-type", ""), "response_bytes_capped": len(body) > max_bytes})
    except Exception as exc:
        result.update({"failure_reason": f"{type(exc).__name__}: {exc}"})
        return result
    html = body[:max_bytes].decode("utf-8", errors="replace")
    json_locations = _json_ld_locations(html)
    visible_evidence = _visible_header_evidence(html)
    result.update({
        "jsonld_job_locations": json_locations,
        "visible_header_location_evidence": visible_evidence,
        "job_specific_tie": bool(json_locations or visible_evidence),
        "recovered_street_count": sum(1 for item in json_locations if STREET_PATTERN.search(item.get("address", ""))) + sum(1 for item in visible_evidence if item["kind"] == "street_address"),
        "recovered_postal_count": sum(1 for item in json_locations if re.search(POSTAL_PATTERN, item.get("address", ""), re.I)) + sum(1 for item in visible_evidence if item["kind"] == "postal_code"),
        "raw_location_evidence": json_locations or visible_evidence,
    })
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", action="append", dest="urls", help="Posting URL; may be repeated")
    parser.add_argument("--timeout-seconds", type=int, default=15)
    parser.add_argument("--max-bytes", type=int, default=2_000_000)
    parser.add_argument("--output")
    args = parser.parse_args(list(argv) if argv is not None else None)
    urls = args.urls or DEFAULT_URLS
    report = {"read_only": True, "recorded_at": datetime.now(timezone.utc).isoformat(), "request_policy": {"max_urls": len(urls), "timeout_seconds": args.timeout_seconds, "max_bytes": args.max_bytes, "retries": 0, "access_control_bypass": False}, "postings": [probe_url(url, max(3, min(args.timeout_seconds, 30)), max(100_000, min(args.max_bytes, 5_000_000))) for url in urls]}
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).expanduser().write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
