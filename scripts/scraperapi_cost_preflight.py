#!/usr/bin/env python3
"""Opt-in, bounded ScraperAPI URL-cost preflight; never retrieves target pages."""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from sources.scraperapi_source import (
    ScraperApiConfig,
    _classify_http_failure,
    _error_body_excerpt,
    _parse_credit_cost,
    _provider_error_message,
    _redact_secret,
    _safe_headers,
)


DEFAULT_URLS = [
    "https://ca.indeed.com/viewjob?jk=960d67145bdf8eb3",
    "https://ca.indeed.com/viewjob?jk=5b10c60264baec65",
]


def estimate_url_cost(url: str, *, config: ScraperApiConfig) -> dict[str, Any]:
    """Call only the documented account/urlcost endpoint, not the target URL."""
    safe_url = _redact_secret(url, config.api_key)
    result: dict[str, Any] = {
        "url": safe_url, "request_made": False, "status": "not_configured",
        "estimated_cost": None, "estimated_cost_status": "unknown",
        "failure_classification": "none", "failure_source": "none",
        "provider_error_message": "", "response_headers": {}, "error_body_excerpt": "",
        "recommended_action": "",
    }
    if not config.enabled or not config.api_key:
        result.update({"status": "not_configured", "recommended_action": "Set SCRAPERAPI_ENABLED=1 and SCRAPERAPI_API_KEY locally before running this opt-in preflight."})
        return result
    endpoint = "https://api.scraperapi.com/account/urlcost"
    query = urllib.parse.urlencode({"api_key": config.api_key, "url": url})
    request = urllib.request.Request(endpoint + "?" + query, headers={"Accept": "application/json", "User-Agent": "Job Tracker ScraperAPI cost preflight/1.0"})
    started = time.perf_counter()
    result["request_made"] = True
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            body = response.read(16_384)
            excerpt = _error_body_excerpt(body, config.api_key)
            result.update({"status": "ok", "http_status": int(getattr(response, "status", 200) or 200), "latency_ms": round((time.perf_counter() - started) * 1000, 1), "response_headers": _safe_headers(getattr(response, "headers", None), config.api_key)})
            try:
                payload = json.loads(excerpt)
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = excerpt
            result["provider_response"] = payload if isinstance(payload, (dict, list, str, int, float, bool)) else str(payload)
            values: list[Any] = []
            if isinstance(payload, dict):
                for key in ("cost", "url_cost", "estimated_cost", "credits", "credit_cost"):
                    if key in payload:
                        values.append(payload[key])
            elif isinstance(payload, (int, float, str)):
                values.append(payload)
            for value in values:
                parsed = _parse_credit_cost(value)
                if parsed is not None:
                    result.update({"estimated_cost": parsed, "estimated_cost_status": "known"})
                    break
            if result["estimated_cost_status"] == "unknown":
                result["recommended_action"] = "Inspect the bounded provider response; no estimated cost was recognized."
            return result
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(16_384)
        except OSError:
            body = b""
        excerpt = _error_body_excerpt(body, config.api_key)
        message = _provider_error_message(excerpt)
        classification, source, action = _classify_http_failure(int(exc.code), message)
        result.update({"status": f"http_{int(exc.code)}", "http_status": int(exc.code), "latency_ms": round((time.perf_counter() - started) * 1000, 1), "response_headers": _safe_headers(getattr(exc, "headers", None), config.api_key), "provider_error_message": message, "error_body_excerpt": excerpt, "failure_classification": classification, "failure_source": source, "recommended_action": action})
        return result
    except Exception as exc:
        result.update({"status": "failed", "latency_ms": round((time.perf_counter() - started) * 1000, 1), "error": _redact_secret(f"{type(exc).__name__}: {exc}", config.api_key), "failure_classification": "transport_error", "failure_source": "transport", "recommended_action": "Inspect the sanitized transport error before an approved retry."})
        return result


def preflight(urls: list[str], *, config: ScraperApiConfig, max_budget: float) -> dict[str, Any]:
    urls = urls[:2]
    results = [estimate_url_cost(url, config=config) for url in urls]
    known = [item["estimated_cost"] for item in results if item["estimated_cost_status"] == "known"]
    budget_check_status = "known" if len(known) == len(results) else "unknown"
    return {
        "read_only": True, "provider": "scraperapi", "operation": "account/urlcost",
        "target_page_retrieval_performed": False, "request_limit": 2,
        "configured_credit_budget": max_budget,
        "results": results,
        "cost_estimation_may_consume_credits": "unknown; verify current plan/documentation before owner execution",
        "within_configured_budget": (sum(known) <= max_budget) if budget_check_status == "known" else None,
        "budget_check_status": budget_check_status,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", action="append", dest="urls", help="URL to estimate; at most two are accepted")
    parser.add_argument("--max-credits", type=float, default=2)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = preflight(args.urls or DEFAULT_URLS, config=ScraperApiConfig.from_environment(), max_budget=max(0.0, args.max_credits))
    Path(args.output).expanduser().write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("configured_credit_budget", "target_page_retrieval_performed", "within_configured_budget")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
