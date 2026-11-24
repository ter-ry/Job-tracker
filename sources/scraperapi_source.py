"""Small, opt-in ScraperAPI transport for bounded workplace feasibility tests."""
from __future__ import annotations

import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sources.jobspy_source import normalize_indeed_source_id


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
    return float(parsed) if parsed >= 0 else None


def _redact_secret(value: Any, secret: str) -> str:
    """Make transport errors safe even when urllib embeds the request URL."""
    rendered = str(value)
    return rendered.replace(secret, "[REDACTED]") if secret else rendered


def fetch_scraperapi_page(
    url: str, *, config: ScraperApiConfig, source_job_id: str = "", max_cost: float | None = None,
) -> dict[str, Any]:
    """Fetch one approved page without exposing the API key in diagnostics."""
    request_max_cost = config.max_cost if max_cost is None else max(0.01, float(max_cost))
    safe_url = _redact_secret(url, config.api_key)
    result: dict[str, Any] = {
        "retrieval_succeeded": False, "provider": "scraperapi", "url": safe_url,
        "request_made": False, "credit_cost": None, "credit_cost_source": "unknown",
        "max_cost": request_max_cost,
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
            result.update({"http_status": int(getattr(response, "status", 200) or 200), "latency_ms": round((time.perf_counter() - started) * 1000, 1), "response_bytes": len(body), "response_truncated": len(body) > config.max_bytes})
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
        result.update({"status": f"http_{int(exc.code)}", "error": f"HTTP {int(exc.code)} from ScraperAPI.", "latency_ms": round((time.perf_counter() - started) * 1000, 1)})
    except Exception as exc:
        safe_error = _redact_secret(f"{type(exc).__name__}: {exc}", config.api_key)
        result.update({"status": "failed", "error": safe_error, "latency_ms": round((time.perf_counter() - started) * 1000, 1)})
    return result
