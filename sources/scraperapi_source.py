"""Small, opt-in ScraperAPI transport for bounded workplace feasibility tests."""
from __future__ import annotations

import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any

from sources.jobspy_source import normalize_indeed_source_id


_DIAGNOSTIC_HEADER_NAMES = {
    "content-type", "content-length", "date", "retry-after", "server",
    "x-request-id", "x-amzn-requestid", "sa-credit-cost",
}


@dataclass(frozen=True)
class ScraperApiConfig:
    api_key: str = ""
    enabled: bool = False
    allowed_hosts: tuple[str, ...] = ()
    timeout_seconds: float = 20.0
    max_bytes: int = 1_200_000
    max_cost: float = 1.0

    @classmethod
    def from_environment(cls) -> "ScraperApiConfig":
        hosts = tuple(sorted({item.strip().lower().rstrip(".") for item in os.environ.get("SCRAPERAPI_ALLOWED_HOSTS", "").split(",") if item.strip()}))
        return cls(
            api_key=os.environ.get("SCRAPERAPI_API_KEY", ""),
            enabled=os.environ.get("SCRAPERAPI_ENABLED", "0").lower() in {"1", "true", "yes", "on"},
            allowed_hosts=hosts,
            timeout_seconds=max(3.0, min(float(os.environ.get("SCRAPERAPI_TIMEOUT_SECONDS", "20")), 60.0)),
            max_bytes=max(100_000, min(int(os.environ.get("SCRAPERAPI_MAX_BYTES", "1200000")), 5_000_000)),
            max_cost=max(0.01, min(float(os.environ.get("SCRAPERAPI_MAX_COST", "1")), 100.0)),
        )


def approved_indeed_url(url: str, source_job_id: str = "", allowed_hosts: tuple[str, ...] = ()) -> bool:
    parsed = urllib.parse.urlsplit(url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    configured = set(allowed_hosts)
    host_allowed = any(host == item or host.endswith("." + item) for item in configured)
    if not host_allowed or parsed.scheme not in {"http", "https"} or parsed.path.rstrip("/") != "/viewjob":
        return False
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    jk = query.get("jk", "")
    expected = normalize_indeed_source_id(source_job_id)
    return bool(jk and (not expected or jk == expected))


def _parse_credit_cost(value: Any) -> float | None:
    """Parse ScraperAPI's documented sa-credit-cost value, if supplied."""
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    value = float(parsed)
    return value if isfinite(value) else None


def _redact_secret(value: Any, secret: str) -> str:
    """Make transport errors safe even when urllib embeds the request URL."""
    rendered = str(value)
    if not secret:
        return rendered
    # urllib and proxy errors may render query parameters either literally or
    # percent-encoded.  Redact both forms before anything reaches a report.
    for encoded in (secret, urllib.parse.quote(secret, safe=""), urllib.parse.quote_plus(secret)):
        rendered = rendered.replace(encoded, "[REDACTED]")
    return rendered


def _safe_headers(headers: Any, secret: str) -> dict[str, str]:
    """Keep only bounded, non-credential response metadata."""
    safe: dict[str, str] = {}
    if headers is None:
        return safe
    try:
        items = headers.items()
    except AttributeError:
        return safe
    for name, value in items:
        lowered = str(name).lower()
        if lowered in _DIAGNOSTIC_HEADER_NAMES:
            safe[lowered] = _redact_secret(str(value)[:300], secret)
    return safe


def _error_body_excerpt(body: bytes | str, secret: str) -> str:
    """Return short text/JSON evidence, never an unrestricted provider body."""
    rendered = _redact_secret(body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body, secret)
    rendered = rendered.replace("\x00", " ").strip()
    return rendered[:2000]


def _provider_error_message(excerpt: str) -> str:
    if not excerpt:
        return ""
    try:
        payload = urllib.parse.unquote(excerpt)
        import json
        decoded = json.loads(payload)
        if isinstance(decoded, dict):
            for key in ("error", "message", "detail", "reason"):
                if decoded.get(key):
                    return str(decoded[key])[:500]
    except (TypeError, ValueError):
        pass
    return " ".join(excerpt.split())[:500]


def _classify_http_failure(status: int, message: str) -> tuple[str, str, str]:
    """Classify only when status/body provide supporting evidence."""
    lowered = message.casefold()
    if status == 401 and any(term in lowered for term in ("api key", "apikey", "unauthorized", "authentication", "credential")):
        return "invalid_or_unauthorized_credentials", "provider", "Verify the owner-configured ScraperAPI key; do not retry automatically."
    if status == 403:
        if any(term in lowered for term in ("max_cost", "maximum cost", "cost limit", "cost exceeds")):
            return "request_exceeds_max_cost", "provider", "Lower the requested target scope or obtain owner approval for a different budget."
        if any(term in lowered for term in ("credit", "credits", "quota", "balance")) and any(term in lowered for term in ("exhaust", "insufficient", "limit", "exceed", "depleted")):
            return "account_credit_exhaustion", "provider", "Check the ScraperAPI plan balance; do not retry automatically."
        if any(term in lowered for term in ("plan", "domain", "not allowed", "subscription")):
            return "plan_or_domain_restriction", "Check the account plan and permitted domains; do not bypass the restriction."
        if any(term in lowered for term in ("target", "upstream", "website", "origin", "source site")):
            return "target_website_access_forbidden", "target_website", "The provider reported target-site access denial; preserve the result as blocked."
        return "unknown_forbidden", "provider", "Inspect the bounded provider diagnostic before deciding whether owner-side retry is appropriate."
    if status == 429:
        return "rate_limited", "provider", "Wait for the provider retry window; do not retry inside this benchmark."
    if status in {408, 504}:
        return "transport_timeout", "transport", "Use the bounded timeout policy; do not cancel and immediately retry."
    if 500 <= status <= 599:
        return "provider_service_degradation", "provider", "Record the failure and retry only in a separately approved run."
    return "http_error", "provider", "Review the bounded provider message and status before taking action."


def fetch_scraperapi_page(
    url: str, *, config: ScraperApiConfig, source_job_id: str = "", max_cost: float | None = None,
) -> dict[str, Any]:
    """Fetch one approved page without exposing the API key in diagnostics."""
    configured_cost = _parse_credit_cost(config.max_cost)
    requested_cost = configured_cost if max_cost is None else _parse_credit_cost(max_cost)
    if configured_cost is None or requested_cost is None or requested_cost <= 0:
        return {
            "retrieval_succeeded": False, "provider": "scraperapi", "url": _redact_secret(url, config.api_key),
            "request_made": False, "credit_cost": None, "credit_cost_source": "unknown",
            "max_cost": None, "status": "invalid_budget", "failure_classification": "invalid_budget",
            "failure_source": "local_configuration", "recommended_action": "Provide a finite positive ScraperAPI cost budget.",
            "error": "ScraperAPI request budget is invalid.",
        }
    request_max_cost = min(configured_cost, requested_cost)
    safe_url = _redact_secret(url, config.api_key)
    result: dict[str, Any] = {
        "retrieval_succeeded": False, "provider": "scraperapi", "url": safe_url,
        "request_made": False, "credit_cost": None, "credit_cost_source": "unknown",
        "max_cost": request_max_cost, "timeout_seconds": config.timeout_seconds,
        "failure_classification": "none", "failure_source": "none",
        "recommended_action": "", "provider_error_message": "", "response_headers": {},
        "error_body_excerpt": "",
    }
    if not config.enabled:
        result.update({"status": "disabled", "error": "ScraperAPI is disabled; set SCRAPERAPI_ENABLED=1 for the owner benchmark."})
        return result
    if not config.api_key:
        result.update({"status": "not_configured", "error": "SCRAPERAPI_API_KEY is not configured."})
        return result
    if not approved_indeed_url(url, source_job_id, config.allowed_hosts):
        result.update({"status": "url_not_approved", "error": "URL is not an approved Indeed /viewjob?jk destination."})
        return result
    endpoint = "https://api.scraperapi.com/"
    query = urllib.parse.urlencode({"api_key": config.api_key, "url": url, "max_cost": f"{request_max_cost:g}"})
    request = urllib.request.Request(endpoint + "?" + query, headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": "Job Tracker workplace feasibility/1.0"})
    started = time.perf_counter()
    result["request_made"] = True
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            body = response.read(config.max_bytes + 1)
            result.update({"http_status": int(getattr(response, "status", 200) or 200), "latency_ms": round((time.perf_counter() - started) * 1000, 1), "response_bytes": len(body), "response_truncated": len(body) > config.max_bytes, "response_headers": _safe_headers(getattr(response, "headers", None), config.api_key)})
            credit_header = response.headers.get("sa-credit-cost")
            if credit_header is not None:
                parsed_cost = _parse_credit_cost(credit_header)
                if parsed_cost is not None:
                    result.update({"credit_cost": parsed_cost, "credit_cost_source": "sa-credit-cost"})
            if len(body) > config.max_bytes:
                result.update({"status": "response_too_large", "error": "Response exceeded the configured byte limit."})
                return result
            result.update({"retrieval_succeeded": True, "status": "ok", "body": _redact_secret(body.decode("utf-8", errors="replace"), config.api_key)})
            return result
    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read(config.max_bytes if config.max_bytes < 16_384 else 16_384)
        except OSError:
            error_body = b""
        excerpt = _error_body_excerpt(error_body, config.api_key)
        message = _provider_error_message(excerpt)
        headers = _safe_headers(getattr(exc, "headers", None), config.api_key)
        header_cost = _parse_credit_cost(headers.get("sa-credit-cost"))
        if header_cost is not None:
            result.update({"credit_cost": header_cost, "credit_cost_source": "sa-credit-cost"})
        classification, source, action = _classify_http_failure(int(exc.code), message)
        result.update({"status": f"http_{int(exc.code)}", "error": f"HTTP {int(exc.code)} from ScraperAPI.", "latency_ms": round((time.perf_counter() - started) * 1000, 1), "response_headers": headers, "provider_error_message": message, "error_body_excerpt": excerpt, "failure_classification": classification, "failure_source": source, "recommended_action": action})
    except Exception as exc:
        safe_error = _redact_secret(f"{type(exc).__name__}: {exc}", config.api_key)
        is_timeout = isinstance(exc, TimeoutError) or isinstance(exc, urllib.error.URLError) and "timed out" in str(exc).casefold()
        result.update({"status": "timeout" if is_timeout else "failed", "error": safe_error, "latency_ms": round((time.perf_counter() - started) * 1000, 1), "failure_classification": "transport_timeout" if is_timeout else "transport_error", "failure_source": "transport", "recommended_action": "Use the bounded timeout policy and inspect connectivity before an approved retry." if is_timeout else "Inspect the sanitized transport error before an approved retry."})
    return result
