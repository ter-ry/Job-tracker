from __future__ import annotations

import warnings
import re
from importlib import metadata
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from typing import Any


JOBSPY_SOURCE_NAMES = {
    "linkedin": "linkedin",
    "indeed": "indeed",
    "google": "google",
    "zip_recruiter": "zip_recruiter",
}


def get_jobspy_version() -> str:
    try:
        return metadata.version("python-jobspy")
    except Exception:
        return ""


def frame_row_count(frame: Any) -> int:
    if frame is None:
        return 0
    if hasattr(frame, "shape"):
        try:
            return int(frame.shape[0])
        except Exception:
            pass
    try:
        return len(frame)  # type: ignore[arg-type]
    except Exception:
        return 0


def frame_to_records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        try:
            records = frame.to_dict("records")
            return [item for item in records if isinstance(item, dict)]
        except Exception:
            return []
    if isinstance(frame, list):
        return [item for item in frame if isinstance(item, dict)]
    return []


def raw_field_types(row: dict[str, Any]) -> dict[str, str]:
    return {key: type(value).__name__ for key, value in row.items()}


def coerce_posted_date(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def fetch_jobspy_jobs(
    *,
    keywords: str,
    location: str,
    distance: int | None = 50,
    job_type: str | None = None,
    remote_preference: str | None = None,
    results_wanted: int = 10,
    hours_old: int | None = 168,
    enabled_sources: list[str] | None = None,
    country_indeed: str = "Canada",
    scrape_jobs_func: Any | None = None,
    provider_timeout_seconds: int | None = 45,
) -> dict[str, Any]:
    scrape_jobs = scrape_jobs_func or _load_scrape_jobs()
    sources = [source for source in (enabled_sources or ["linkedin", "indeed"]) if source in JOBSPY_SOURCE_NAMES]
    results: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    source_counts = {source: 0 for source in sources}
    source_snapshots: dict[str, list[dict[str, Any]]] = {}
    source_diagnostics: dict[str, dict[str, Any]] = {
        source: {
            "source": source,
            "enabled": source in sources,
            "attempted": False,
            "request_params": {},
            "jobspy_version": get_jobspy_version(),
            "started_at": "",
            "ended_at": "",
            "duration_ms": 0,
            "raw_return_type": "",
            "raw_frame_row_count": 0,
            "raw_records_row_count": 0,
            "normalized_row_count": 0,
            "date_filtered_row_count": 0,
            "date_filtered_removed_count": 0,
            "deduped_row_count": 0,
            "returned_to_frontend_row_count": 0,
            "success": False,
            "error_type": "",
            "error": "",
            "skipped_reason": "disabled",
            "warnings": [],
            "warnings_count": 0,
            "raw_source_snapshot_count": 0,
            "result_count": 0,
            "cached": False,
            "effective_country_indeed": country_indeed,
        }
        for source in JOBSPY_SOURCE_NAMES
    }

    for source in sources:
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        source_diagnostics[source] = {
            "source": source,
            "enabled": True,
            "attempted": True,
            "request_params": {
                "keywords": keywords,
                "location": location,
                "distance": round(float(distance or 0) * 0.621371) if distance is not None else None,
                "distance_km": distance,
                "distance_unit": "miles",
                "job_type": job_type,
                "remote_preference": remote_preference,
                "results_wanted": results_wanted,
                "hours_old": hours_old,
                "enabled_sources": list(sources),
                "country_indeed": country_indeed,
                "site_name": JOBSPY_SOURCE_NAMES[source],
                "google_search_term": f"{keywords} jobs near {location}",
            },
            "jobspy_version": get_jobspy_version(),
            "started_at": started_at,
            "ended_at": "",
            "duration_ms": 0,
            "raw_return_type": "",
            "raw_frame_row_count": 0,
            "raw_records_row_count": 0,
            "normalized_row_count": 0,
            "date_filtered_row_count": 0,
            "date_filtered_removed_count": 0,
            "deduped_row_count": 0,
            "returned_to_frontend_row_count": 0,
            "success": False,
            "error_type": "",
            "error": "",
            "skipped_reason": "",
            "warnings": [],
            "warnings_count": 0,
            "raw_source_snapshot_count": 0,
            "result_count": 0,
            "cached": False,
            "effective_country_indeed": country_indeed,
        }
        try:
            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always")
                scrape_kwargs = {
                    "site_name": JOBSPY_SOURCE_NAMES[source],
                    "search_term": keywords,
                    "google_search_term": f"{keywords} jobs near {location}",
                    "location": location,
                    # JobSpy expects miles; the application accepts kilometres.
                    "distance": round(float(distance or 0) * 0.621371) if distance is not None else None,
                    "is_remote": (remote_preference or "").lower() == "remote",
                    "job_type": job_type or None,
                    "results_wanted": results_wanted,
                    "country_indeed": country_indeed,
                    "hours_old": hours_old,
                    # Request the provider description when JobSpy supports it.
                    # Without this, LinkedIn rows often arrive as title/URL-only
                    # records and cannot be qualified transparently.
                    "linkedin_fetch_description": True,
                    "verbose": 0,
                }
                # JobSpy has no portable provider timeout parameter.  Run each
                # provider call behind a bounded future so one stalled source
                # becomes a partial failure instead of holding the HTTP request
                # forever.  The underlying provider cannot be force-killed, so
                # cancellation is best-effort and diagnostics retain the timeout.
                executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"jobspy-{source}")
                future = executor.submit(scrape_jobs, **scrape_kwargs)
                try:
                    frame = future.result(timeout=provider_timeout_seconds)
                except FutureTimeoutError as exc:
                    future.cancel()
                    raise TimeoutError(f"{source} provider timed out after {provider_timeout_seconds}s") from exc
                finally:
                    executor.shutdown(wait=False, cancel_futures=True)
            raw_type = type(frame).__name__ if frame is not None else "NoneType"
            raw_rows = frame_to_records(frame)
            normalized_rows: list[dict[str, Any]] = []
            snapshots: list[dict[str, Any]] = []
            for row in raw_rows[:25]:
                snapshots.append(
                    {
                        "source": source,
                        "title": clean(row.get("title")),
                        "company": clean(row.get("company")),
                        "location": clean(row.get("location")),
                        "date_posted": clean(row.get("date_posted") or row.get("date")),
                        "url": clean(row.get("job_url") or row.get("job_url_direct")),
                        "raw_field_types": raw_field_types(row),
                    }
                )
            for row in raw_rows:
                normalized = normalize_jobspy_row(row, fallback_source=source)
                if normalized["title"]:
                    source_counts[source] = source_counts.get(source, 0) + 1
                    normalized_rows.append(normalized)
            date_filtered_removed = 0
            if hours_old not in (None, 0):
                limit = max(int(hours_old or 0), 0)
                now = datetime.now(timezone.utc)
                for normalized in normalized_rows:
                    posted_at = coerce_posted_date(normalized.get("posted_date"))
                    if posted_at is None:
                        continue
                    if posted_at.tzinfo is None:
                        posted_at = posted_at.replace(tzinfo=timezone.utc)
                    age_hours = (now - posted_at).total_seconds() / 3600
                    if age_hours > limit:
                        date_filtered_removed += 1
            source_snapshots[source] = snapshots
            source_diagnostics[source].update(
                {
                    "success": True,
                    "raw_return_type": raw_type,
                    "raw_frame_row_count": frame_row_count(frame),
                    "raw_records_row_count": len(raw_rows),
                    "normalized_row_count": len(normalized_rows),
                    "date_filtered_removed_count": date_filtered_removed,
                    "date_filtered_row_count": max(0, len(normalized_rows) - date_filtered_removed),
                    "deduped_row_count": len(normalized_rows),
                    "returned_to_frontend_row_count": len(normalized_rows),
                    "warnings": [str(item.message) for item in caught_warnings],
                    "warnings_count": len(caught_warnings),
                    "raw_source_snapshot_count": len(snapshots),
                    "result_count": len(normalized_rows),
                    "ended_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": int(round((time.perf_counter() - started) * 1000)),
                }
            )
            results.extend(normalized_rows)
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"
            errors[source] = error_message
            source_diagnostics[source].update(
                {
                    "success": False,
                    "raw_return_type": "",
                    "raw_frame_row_count": 0,
                    "raw_records_row_count": 0,
                    "normalized_row_count": 0,
                    "date_filtered_removed_count": 0,
                    "date_filtered_row_count": 0,
                    "deduped_row_count": 0,
                    "returned_to_frontend_row_count": 0,
                    "error_type": type(exc).__name__,
                    "error": error_message,
                    "warnings": [],
                    "warnings_count": 0,
                    "raw_source_snapshot_count": 0,
                    "result_count": 0,
                    "ended_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": int(round((time.perf_counter() - started) * 1000)),
                }
            )

    return {
        "jobs": results,
        "errors": errors,
        "source_counts": source_counts,
        "source_diagnostics": source_diagnostics,
        "source_snapshots": source_snapshots,
    }


def normalize_jobspy_row(row: dict[str, Any], fallback_source: str = "") -> dict[str, Any]:
    fetched_at = datetime.now(timezone.utc).isoformat()
    source = clean(row.get("site") or row.get("source") or fallback_source)
    min_amount = number_or_none(row.get("min_amount"))
    max_amount = number_or_none(row.get("max_amount"))
    interval = clean(row.get("interval"))
    currency = clean(row.get("currency") or row.get("salary_currency")) or "CAD"
    salary_text = clean(row.get("salary"))
    salary_source = "missing"
    confidence = 0
    if not salary_text and (min_amount is not None or max_amount is not None):
        salary_text = salary_range_text(min_amount, max_amount, interval)
    if min_amount is not None or max_amount is not None:
        salary_source = "structured"
        confidence = 95
    elif salary_text:
        salary_source = "jobspy_text"
        confidence = 82

    job_url = clean(row.get("job_url") or row.get("job_url_direct"))
    direct_url = clean(row.get("job_url_direct") or row.get("job_url"))
    location = clean(row.get("location"))
    city = clean(row.get("city"))
    state = clean(row.get("state") or row.get("state_province"))
    description = clean(row.get("description"))
    workplace = extract_workplace_location(row, description, location or ", ".join([part for part in [city, state] if part]))
    raw_status = clean(row.get("status") or row.get("posting_status")).lower()
    if row.get("is_closed") is True or raw_status in {"closed", "expired", "removed"}:
        posting_availability = "confirmed_closed"
    elif row.get("is_active") is True or raw_status in {"active", "open", "published"}:
        posting_availability = "verified_active"
    elif description and clean(row.get("date_posted") or row.get("date")) and job_url:
        posting_availability = "likely_active"
    else:
        posting_availability = "unverified"

    return {
        "source_job_id": clean(row.get("id") or row.get("job_id")),
        "title": clean(row.get("title")),
        "company": clean(row.get("company")),
        "location": workplace["display_location"] or location or ", ".join([part for part in [city, state] if part]),
        "provider_location": location or ", ".join([part for part in [city, state] if part]),
        "workplace_address": workplace["address"],
        "workplace_postal_code": workplace["postal_code"],
        "workplace_evidence": workplace["evidence"],
        "workplace_evidence_source": workplace["evidence_source"],
        "workplace_precision": workplace["precision"],
        "workplace_confidence": workplace["confidence"],
        "city": city,
        "state_province": state,
        "remote_type": infer_remote_type(row),
        "remote_classification_conflict": remote_classification_conflict(row),
        "job_type": clean(row.get("job_type")),
        "salary_min": min_amount,
        "salary_max": max_amount,
        "salary_interval": interval,
        "salary_currency": currency,
        "salary_text": salary_text,
        "salary_source": salary_source,
        "salary_confidence": confidence,
        "source": source,
        "job_url": job_url,
        "application_url": direct_url,
        "description": description,
        "posting_availability": posting_availability,
        "posted_date": clean(row.get("date_posted")),
        "company_url": clean(row.get("company_url")),
        "experience_requirement": extract_experience_requirement(description),
        "required_skills": extract_keyword_text(description),
        "preferred_skills": "",
        "fetched_at": fetched_at,
        "raw": row,
    }


def _load_scrape_jobs() -> Any:
    from jobspy import scrape_jobs

    return scrape_jobs


def _iter_rows(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        return frame.to_dict("records")
    if isinstance(frame, list):
        return [item for item in frame if isinstance(item, dict)]
    return []


def clean(value: Any) -> str:
    if value is None:
        return ""
    if str(value) == "nan":
        return ""
    return str(value).strip()


def number_or_none(value: Any) -> float | None:
    try:
        if value is None or str(value) == "nan" or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def salary_range_text(min_amount: float | None, max_amount: float | None, interval: str) -> str:
    left = f"${int(min_amount):,}" if min_amount is not None else ""
    right = f"${int(max_amount):,}" if max_amount is not None else ""
    amount = f"{left}-{right}" if left and right else left or right
    return f"{amount} {interval}".strip()


def infer_remote_type(row: dict[str, Any]) -> str:
    explicit = row.get("is_remote")
    location = clean(row.get("location")).lower()
    description = clean(row.get("description")).lower()
    title = clean(row.get("title")).lower()
    provider_arrangement = clean(row.get("remote_type") or row.get("work_arrangement")).lower()
    text = " ".join([location, title, provider_arrangement, description])
    negative = bool(re.search(r"\b(?:not|no)\s+remote\b|remote\s*(?::|-)?\s*(?:no|false)\b|work\s+remotely\s*(?::|-)?\s*no\b|work\s+location\s*:\s*in\s+person\b|on[- ]site\s+only", text))
    positive = bool(re.search(r"\b(?:fully|100%|work(?:ing)?|position|role|job)\s+(?:is\s+)?remote\b|\bremote\s+(?:position|role|work|job|in\s+canada)\b|\bwork\s+from\s+home\b", text))
    explicit = clean(explicit).lower()
    if negative and explicit in {"true", "1", "yes"}:
        return "Unknown"
    if positive and explicit in {"false", "0", "no"}:
        return "Unknown"
    if negative:
        return "On-site"
    if "hybrid" in text or provider_arrangement == "hybrid":
        return "Hybrid"
    if isinstance(row.get("is_remote"), bool):
        if row.get("is_remote"):
            return "Remote"
        return "On-site"
    elif explicit in {"true", "1", "yes"}:
        return "Remote"
    elif explicit in {"false", "0", "no"}:
        return "On-site"
    if "on-site" in text or "onsite" in text:
        return "On-site"
    if positive:
        return "Remote"
    return "Unknown"


def remote_classification_conflict(row: dict[str, Any]) -> str:
    location = clean(row.get("location")).lower()
    description = clean(row.get("description")).lower()
    title = clean(row.get("title")).lower()
    arrangement = clean(row.get("remote_type") or row.get("work_arrangement")).lower()
    content = " ".join([location, title, arrangement, description])
    negative = bool(re.search(r"\b(?:not|no)\s+remote\b|remote\s*(?::|-)?\s*(?:no|false)\b|work\s+remotely\s*(?::|-)?\s*no\b|work\s+location\s*:\s*in\s+person\b|on[- ]site\s+only", content))
    positive = bool(re.search(r"\b(?:fully|100%|work(?:ing)?|position|role|job)\s+(?:is\s+)?remote\b|\bremote\s+(?:position|role|work|job|in\s+canada)\b|\bwork\s+from\s+home\b", content))
    explicit = clean(row.get("is_remote")).lower()
    if negative and explicit in {"true", "1", "yes"}:
        return "provider_remote_conflicts_with_explicit_on_site_evidence"
    if positive and explicit in {"false", "0", "no"}:
        return "provider_on_site_conflicts_with_explicit_remote_evidence"
    return ""


def extract_workplace_location(row: dict[str, Any], description: str, provider_location: str) -> dict[str, Any]:
    """Extract only explicitly labeled workplace evidence; never infer an employer HQ."""
    postal_pattern = r"[A-Z]\d[A-Z][ -]?\d[A-Z]\d"
    raw_fields = [clean(row.get(key)) for key in ("workplace_address", "address", "street_address", "office_address", "office_location")]
    field_value = next((value for value in raw_fields if value), "")
    source = "provider field" if field_value else ""
    labeled = re.search(r"(?im)^\s*(?:location|work\s+location|address|office\s+location)\s*:\s*([^\n\r|]+)", description)
    # Accept an explicitly written street address even when the provider does
    # not add a field label (for example, "Maple RECE — 9350 Keele St"). The
    # pattern is intentionally Canadian-street-shaped and never turns a city
    # or employer headquarters into a workplace.
    street = re.search(
        r"\b\d{1,6}\s+[A-Z0-9][A-Za-z0-9.'-]*(?:\s+[A-Za-z0-9.'-]+){0,5}\s+"
        r"(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Drive|Dr\.?|Boulevard|Blvd\.?|Way|Parkway|Pkwy\.?)\b",
        description,
        re.I,
    )
    if not labeled and street:
        labeled = street
    evidence = field_value or ((labeled.group(1) if labeled.lastindex else labeled.group(0)).strip() if labeled else "")
    if evidence:
        source = source or "description labeled workplace field"
    postal = clean(row.get("postal_code") or row.get("zip_code") or row.get("workplace_postal_code"))
    postal_match = re.search(postal_pattern, f"{evidence} {description}", re.I)
    postal = postal or (postal_match.group(0).upper().replace(" ", " ") if postal_match else "")
    address = evidence
    if not address and postal:
        address = postal
        source = "description postal code"
    if not address and provider_location:
        return {"display_location": provider_location, "address": "", "postal_code": postal, "evidence": "", "evidence_source": "", "precision": "city" if provider_location else "unknown", "confidence": 65 if provider_location else 0}
    display = address or provider_location
    precision = "street address" if re.search(r"\b\d{1,6}\s+[^,\n]+\b(?:street|st|avenue|ave|road|rd|drive|dr|boulevard|blvd|way|parkway|pkwy)\b", address, re.I) else "postal code" if postal else "city"
    return {"display_location": display, "address": address, "postal_code": postal, "evidence": evidence or address, "evidence_source": source or "provider location", "precision": precision, "confidence": 95 if precision == "street address" else 88 if precision == "postal code" else 65}


def extract_experience_requirement(description: str) -> str:
    # Reuse the evidence-aware parser so company-history prose such as
    # "For 30 years, we've..." cannot become a job requirement. Prefer a
    # classified required range, then preferred, then explicitly ambiguous
    # wording while preserving the original matched phrase.
    from seniority import extract_experience_ranges

    required, preferred, ambiguous = extract_experience_ranges(description or "")
    candidates = required or preferred or ambiguous
    if not candidates:
        return ""
    strongest = max(candidates, key=lambda item: (item.minimum or 0, item.maximum or item.minimum or 0))
    return strongest.text


def extract_keyword_text(description: str) -> str:
    keywords = ["python", "javascript", "flask", "react", "sql", "aws", "azure", "cloud", "api", "dashboard", "automation"]
    lowered = (description or "").lower()
    return ", ".join([keyword for keyword in keywords if keyword in lowered])
