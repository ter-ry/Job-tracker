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
    required_skills, preferred_skills = extract_keyword_requirements(description)
    credentials = extract_explicit_credentials(description)
    benefits = extract_explicit_benefits(description)
    remote_type = infer_remote_type(row)
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
        "workplace_alternatives": workplace["alternatives"],
        "city": city,
        "state_province": state,
        "remote_type": remote_type,
        "arrangement_evidence": arrangement_evidence(row, description, remote_type, workplace["alternatives"]),
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
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "credentials": credentials,
        "benefits": benefits,
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
    if extract_workplace_alternatives(row, description) and re.search(
        r"\b(?:work\s+locations?|workplaces?|child\s*care\s+centres?|centres?\s+for\s+early\s+development|"
        r"float\s+(?:between|across|among)|work\s+at\s+(?:the|our|these)|based\s+at)\b",
        text,
        re.I,
    ):
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


POSTAL_PATTERN = r"[A-Z]\d[A-Z][ -]?\d[A-Z]\d"
STREET_PATTERN = re.compile(
    r"\b\d{1,6}\s+[A-Z0-9][A-Za-z0-9.'-]*(?:\s+[A-Za-z0-9.'-]+){0,6}\s+"
    r"(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Drive|Dr\.?|Boulevard|Blvd\.?|Way|"
    r"Parkway|Pkwy\.?|Crescent|Cres\.?|Court|Ct\.?|Lane|Ln\.?|Trail|Highway|Hwy\.?|"
    r"Terrace|Ter\.?|Place|Pl\.?|Square|Sq\.?|Circle|Cir\.?|Gate|Gardens?|Garden|"
    r"Manor|Mews|Path|Row|Quay)\b",
    re.I,
)
WORKPLACE_CUE = re.compile(
    r"\b(?:work(?:place|\s+locations?)?|job\s+locations?|locations?|sites?|centres?|centers?|office|"
    r"based|located|report(?:ing)?\s+to|float\s+(?:between|across|among)|work\s+at)\b",
    re.I,
)
NON_WORKPLACE_CUE = re.compile(r"\b(?:headquarters|corporate|mailing|registered)\s+(?:address|office)?\b", re.I)


def _address_evidence(description: str, match: re.Match[str], next_start: int | None = None) -> tuple[str, str]:
    end_limit = min(len(description), next_start if next_start is not None else match.end() + 120)
    tail = description[match.end():end_limit]
    postal = re.search(POSTAL_PATTERN, tail, re.I)
    end = match.end() + postal.end() if postal else match.end()
    start = match.start()
    line_start = max(description.rfind("\n", 0, start) + 1, description.rfind("|", 0, start) + 1)
    line_end_candidates = [value for value in (description.find("\n", end), description.find("|", end)) if value >= 0]
    line_end = min(line_end_candidates) if line_end_candidates else end
    evidence = clean(description[line_start:max(end, line_end)]).strip(" -•;|")
    if len(evidence) > 260:
        evidence = clean(description[max(line_start, start - 80):end])
    address = clean(description[start:end]).strip(" ,;-")
    return address, evidence or address


def extract_workplace_alternatives(row: dict[str, Any], description: str) -> list[dict[str, Any]]:
    """Return every explicit advertised workplace without choosing an assigned site."""
    supplied = row.get("workplace_alternatives")
    if isinstance(supplied, list):
        return [dict(item) for item in supplied if isinstance(item, dict) and clean(item.get("address") or item.get("postal_code"))]
    raw_fields = [clean(row.get(key)) for key in ("workplace_address", "address", "street_address", "office_address", "office_location")]
    field_value = next((value for value in raw_fields if value), "")
    candidates: list[dict[str, Any]] = []
    if field_value:
        postal_match = re.search(POSTAL_PATTERN, field_value, re.I)
        candidates.append({
            "address": field_value,
            "postal_code": postal_match.group(0).upper() if postal_match else clean(row.get("postal_code") or row.get("zip_code")),
            "precision": "street address" if STREET_PATTERN.search(field_value) else "postal code" if postal_match else "city",
            "confidence": 95 if STREET_PATTERN.search(field_value) else 88 if postal_match else 65,
            "evidence": field_value,
            "evidence_source": "provider field",
            "assignment_status": "confirmed",
        })
    matches = list(STREET_PATTERN.finditer(description or ""))
    for index, match in enumerate(matches):
        context = (description or "")[max(0, match.start() - 180):match.start()]
        # Provider/PDF descriptions often flatten a workplace list onto one
        # line.  Evaluate each address against its nearby evidence instead of
        # allowing an unrelated cue elsewhere in the posting to authorize all
        # street-shaped numbers.
        nearby_context = (description or "")[max(0, match.start() - 240):min(len(description or ""), match.end() + 80)]
        if NON_WORKPLACE_CUE.search(nearby_context[-150:]):
            continue
        if not WORKPLACE_CUE.search(context):
            continue
        address, evidence = _address_evidence(description, match, matches[index + 1].start() if index + 1 < len(matches) else None)
        postal_match = re.search(POSTAL_PATTERN, address, re.I)
        canonical = clean(STREET_PATTERN.search(address).group(0) if STREET_PATTERN.search(address) else address).lower()
        if any(clean(item.get("address")).lower().startswith(canonical) or canonical.startswith(clean(item.get("address")).lower()) for item in candidates):
            continue
        candidates.append({
            "address": address,
            "postal_code": postal_match.group(0).upper() if postal_match else "",
            "precision": "street address",
            "confidence": 95,
            "evidence": evidence,
            "evidence_source": "description advertised workplace",
            "assignment_status": "advertised_alternative" if len(matches) > 1 else "confirmed",
        })
    if len(candidates) > 1:
        for item in candidates:
            item["assignment_status"] = "advertised_alternative"
    return candidates


def extract_workplace_location(row: dict[str, Any], description: str, provider_location: str) -> dict[str, Any]:
    """Preserve alternatives and populate legacy fields only for one confirmed site."""
    alternatives = extract_workplace_alternatives(row, description)
    if len(alternatives) > 1:
        return {
            "display_location": provider_location or f"{len(alternatives)} advertised workplace alternatives",
            "address": "", "postal_code": "", "evidence": "", "evidence_source": "",
            "precision": "multiple alternatives", "confidence": 95, "alternatives": alternatives,
        }
    if alternatives:
        item = alternatives[0]
        legacy_address_match = STREET_PATTERN.search(clean(item.get("address")))
        explicitly_labelled = bool(re.match(r"\s*(?:work\s+)?location\s*:", clean(item.get("evidence")), re.I))
        legacy_address = clean(item.get("address")) if explicitly_labelled else clean(legacy_address_match.group(0)) if legacy_address_match else clean(item.get("address"))
        return {
            "display_location": clean(item.get("address")) or provider_location,
            "address": legacy_address, "postal_code": clean(item.get("postal_code")),
            "evidence": clean(item.get("evidence")), "evidence_source": clean(item.get("evidence_source")),
            "precision": clean(item.get("precision")), "confidence": int(item.get("confidence") or 0),
            "alternatives": alternatives,
        }
    postal = clean(row.get("postal_code") or row.get("zip_code") or row.get("workplace_postal_code"))
    return {
        "display_location": provider_location, "address": "", "postal_code": postal,
        "evidence": "", "evidence_source": "", "precision": "city" if provider_location else "unknown",
        "confidence": 65 if provider_location else 0, "alternatives": [],
    }


SECTION_HEADINGS = [
    ("required", r"what\s+you\s+need\s+to\s+succeed|what\s+we(?:'re|\s+are|’re)\s+looking\s+for|"
                 r"required\s+qualifications?|minimum\s+qualifications?|requirements?|what\s+you\s+bring|"
                 r"who\s+you\s+are|your\s+background|core\s+skills(?:\s+and\s+experience)?|"
                 r"skills\s*(?:,\s*|and\s+)?experience\s*(?:&|and)\s*requirements?"),
    ("preferred", r"preferred\s+qualifications?|preferred|nice\s+to\s+have|bonus|assets?"),
    ("unclassified", r"technologies\s+that\s+we\s+use(?:\s*\([^)]*\))?|our\s+core\s+stack\s+includes|"
                     r"why\s+join\s+us|perks?\s*(?:&|and)\s*benefits?|about\s+(?:us|the\s+company)|"
                     r"equal\s+employment\s+opportunity|additional\s+notes"),
]


def _section_markers(description: str) -> list[tuple[int, str, str]]:
    markers = []
    for importance, pattern in SECTION_HEADINGS:
        # ATS HTML frequently drops both heading tags and the colon, leaving
        # strings such as "What you need to succeed - Git" or
        # "Preferred qualifications Kubernetes".  Require a sentence/line
        # boundary before a heading so ordinary prose is not promoted, while
        # accepting colon, bullet, line, and flattened title-to-value joins.
        heading_pattern = (
            rf"(?im)(?:^|(?<=[.!?]))\s*(?P<heading>{pattern})\b\s*:??"
            rf"(?=$|[\n:•*-]|\s+[A-Z0-9])"
        )
        for match in re.finditer(heading_pattern, description or ""):
            heading = clean(match.group("heading"))
            markers.append((match.start("heading"), importance, heading))
    return sorted(markers)


def requirement_phrase_evidence(description: str, phrases: tuple[str, ...]) -> tuple[str, str]:
    """Classify all phrase occurrences; explicit required evidence wins."""
    markers = _section_markers(description)
    observations: list[tuple[str, str]] = []
    for phrase in phrases:
        pattern = r"(?<![a-z0-9])" + r"\s+".join(re.escape(part) for part in phrase.split()) + r"(?![a-z0-9])"
        for match in re.finditer(pattern, description or "", re.I):
            preceding = [item for item in markers if item[0] < match.start()]
            importance = preceding[-1][1] if preceding else "unclassified"
            context = clean((description or "")[max(0, match.start() - 170):min(len(description), match.end() + 170)])
            # Provider HTML is often flattened.  Keep wording overrides inside
            # the current section so an earlier "you'll be exposed to" stack
            # cannot leak across a later required-section heading.
            section_start = preceding[-1][0] if preceding else 0
            before = clean((description or "")[max(section_start, match.start() - 170):match.start()]).lower()
            if re.search(r"\b(?:preferred|nice\s+to\s+have|bonus|asset)\b", before):
                importance = "preferred"
            elif re.search(r"\b(?:not\s+required|you\s+will\s+be\s+exposed\s+to|technologies\s+that\s+we\s+use)\b", before):
                importance = "unclassified"
            elif re.search(r"\b(?:must|required|proficien(?:t|cy)|strong\s+[^.]{0,70}\s+skills?|hands-on\s+experience|experience\s+(?:with|using)|you\s+build\s+with)\b", before):
                importance = "required"
            observations.append((importance, context))
    for wanted in ("required", "preferred", "unclassified"):
        evidence = next((snippet for importance, snippet in observations if importance == wanted), "")
        if evidence:
            return wanted, evidence
    return "unclassified", ""


KEYWORD_CAPABILITIES = [
    ("full-stack development", ("full-stack development", "full stack development")),
    ("python", ("python",)), ("react", ("react",)), ("redux", ("redux",)),
    ("postgresql", ("postgresql", "postgres")), ("aws", ("aws",)),
    ("ai api/model experience", ("ai apis/models", "ai apis", "ai models")),
    ("agentic coding tools", ("ai coding agents", "agentic coding tool", "claude code", "cursor")),
    ("agile project management tools", ("agile project management tools",)),
    ("git", ("git",)), ("typescript", ("typescript",)), ("nodejs", ("nodejs", "node.js")),
    ("nestjs", ("nestjs",)), ("javascript", ("javascript",)), ("java", ("java",)),
    ("go", ("golang",)), ("c++", ("c++",)), ("c#", ("c#",)),
    ("kubernetes", ("kubernetes",)), ("docker", ("docker",)), ("sql", ("sql",)),
    ("api", ("apis", "api")),
]


def extract_keyword_requirements(description: str) -> tuple[str, str]:
    required, preferred = [], []
    for canonical, phrases in KEYWORD_CAPABILITIES:
        importance, evidence = requirement_phrase_evidence(description, phrases)
        if not evidence:
            continue
        target = required if importance == "required" else preferred if importance == "preferred" else None
        if target is not None and canonical not in target:
            target.append(canonical)
    # An explicit AI-API capability is not also a generic API requirement.
    if "ai api/model experience" in required and "api" in required:
        required.remove("api")
    if "ai api/model experience" in preferred and "api" in preferred:
        preferred.remove("api")
    return ", ".join(required), ", ".join(preferred)


def _evidence_records(description: str, patterns: list[tuple[str, str]]) -> list[dict[str, Any]]:
    records = []
    for category, pattern in patterns:
        for match in re.finditer(pattern, description or "", re.I):
            value = clean(match.group(0)).strip(" .;•-")
            if value and value.lower() not in {clean(item["value"]).lower() for item in records}:
                records.append({"value": value, "category": category, "evidence": value, "confidence": 90})
    return records


def extract_explicit_credentials(description: str) -> list[dict[str, Any]]:
    return _evidence_records(description, [
        ("education", r"\b(?:bachelor(?:’|')?s?|master(?:’|')?s?)\s+degree\b[^.;\n]{0,110}"),
        ("education", r"\b(?:diploma|degree)\s+in\s+early\s+childhood\s+education\b[^.;\n]{0,90}"),
        ("registration", r"\b(?:registered|registration|good\s+standing)\s+with\s+(?:the\s+)?(?:Ontario\s+)?College\s+of\s+(?:Early\s+Childhood\s+Educators|ECE)\b[^.;\n]{0,90}"),
        ("safety", r"\b(?:standard\s+)?first\s+aid(?:\s+and|/|\s*,\s*)\s*CPR(?:\s+(?:level\s+)?[A-C])?\b"),
    ])


def extract_explicit_benefits(description: str) -> list[dict[str, Any]]:
    return _evidence_records(description, [
        ("time off", r"\b(?:generous\s+)?PTO\s*[-–:]?\s*\d+\s+vacation\s+days\b|\b\d+\s+weeks?\s+of\s+vacation\b"),
        ("health", r"\bcomprehensive\s+benefits(?:\s+plan|\s+program)?\b[^.;\n]{0,100}"),
        ("health", r"\bhealth\s+care\s+spending\s+account\b"),
        ("family", r"\bparental\s+leave\s+top-up\b"),
        ("equity", r"\bstock\s+options?(?:\s+plan)?\b"),
        ("development", r"\b(?:learning\s+and\s+development|L&D|professional\s+development)\s+budget\b"),
        ("development", r"\bAI\s+tooling\s+budget\b"),
        ("equipment", r"\bMacBook\b[^.;\n]{0,90}\bequipment\b"),
        ("time off", r"\b\d+\s+personal\s+days\b"),
    ])


def arrangement_evidence(row: dict[str, Any], description: str, remote_type: str, alternatives: list[dict[str, Any]]) -> str:
    explicit = clean(row.get("remote_type") or row.get("work_arrangement"))
    if explicit:
        return f"Provider arrangement: {explicit}"
    patterns = {
        "Hybrid": r"\bhybrid\b[^.;\n]{0,150}",
        "Remote": r"\b(?:fully|100%)?\s*remote\b[^.;\n]{0,150}|\bwork\s+from\s+home\b[^.;\n]{0,120}",
        "On-site": r"\b(?:on[- ]site|in[- ]person|work\s+at\s+(?:the|our|these)|float\s+(?:between|across|among))\b[^.;\n]{0,150}",
    }
    match = re.search(patterns.get(remote_type, r"$^"), description or "", re.I)
    if match:
        return clean(match.group(0))
    if remote_type == "On-site" and alternatives:
        return "Posting explicitly advertises physical workplace alternatives."
    return ""


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
