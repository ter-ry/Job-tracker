from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any


JOBSPY_SOURCE_NAMES = {
    "linkedin": "linkedin",
    "indeed": "indeed",
    "google": "google",
    "zip_recruiter": "zip_recruiter",
}


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
) -> dict[str, Any]:
    scrape_jobs = scrape_jobs_func or _load_scrape_jobs()
    sources = [source for source in (enabled_sources or ["linkedin", "indeed"]) if source in JOBSPY_SOURCE_NAMES]
    results: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    source_counts = {source: 0 for source in sources}
    source_diagnostics: dict[str, dict[str, Any]] = {
        source: {
            "source": source,
            "attempted": False,
            "success": False,
            "result_count": 0,
            "error": "",
            "skipped_reason": "disabled",
            "duration_ms": 0,
        }
        for source in JOBSPY_SOURCE_NAMES
    }

    for source in sources:
        started = time.perf_counter()
        source_diagnostics[source] = {
            "source": source,
            "attempted": True,
            "success": False,
            "result_count": 0,
            "error": "",
            "skipped_reason": "",
            "duration_ms": 0,
            "effective_country_indeed": country_indeed,
            "location": location,
            "distance": distance,
            "hours_old": hours_old,
            "results_wanted": results_wanted,
        }
        try:
            frame = scrape_jobs(
                site_name=JOBSPY_SOURCE_NAMES[source],
                search_term=keywords,
                google_search_term=f"{keywords} jobs near {location}",
                location=location,
                distance=distance,
                is_remote=(remote_preference or "").lower() == "remote",
                job_type=job_type or None,
                results_wanted=results_wanted,
                country_indeed=country_indeed,
                hours_old=hours_old,
                linkedin_fetch_description=False,
                verbose=0,
            )
            matched = 0
            for row in _iter_rows(frame):
                normalized = normalize_jobspy_row(row, fallback_source=source)
                if normalized["title"]:
                    results.append(normalized)
                    source_counts[source] = source_counts.get(source, 0) + 1
                    matched += 1
            source_diagnostics[source].update(
                {
                    "success": True,
                    "result_count": matched,
                    "duration_ms": int(round((time.perf_counter() - started) * 1000)),
                }
            )
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"
            errors[source] = error_message
            source_diagnostics[source].update(
                {
                    "success": False,
                    "error": error_message,
                    "duration_ms": int(round((time.perf_counter() - started) * 1000)),
                }
            )

    return {"jobs": results, "errors": errors, "source_counts": source_counts, "source_diagnostics": source_diagnostics}


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

    return {
        "source_job_id": clean(row.get("id") or row.get("job_id")),
        "title": clean(row.get("title")),
        "company": clean(row.get("company")),
        "location": location or ", ".join([part for part in [city, state] if part]),
        "city": city,
        "state_province": state,
        "remote_type": infer_remote_type(row),
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
    text = " ".join([clean(row.get("is_remote")), clean(row.get("location")), clean(row.get("title")), clean(row.get("description"))]).lower()
    if "hybrid" in text:
        return "Hybrid"
    if "true" in text or "remote" in text:
        return "Remote"
    if "on-site" in text or "onsite" in text:
        return "On-site"
    return ""


def extract_experience_requirement(description: str) -> str:
    import re

    match = re.search(r"(\d+)\+?\s*(?:-\s*\d+\s*)?(?:years|yrs)", description or "", re.I)
    return match.group(0) if match else ""


def extract_keyword_text(description: str) -> str:
    keywords = ["python", "javascript", "flask", "react", "sql", "aws", "azure", "cloud", "api", "dashboard", "automation"]
    lowered = (description or "").lower()
    return ", ".join([keyword for keyword in keywords if keyword in lowered])
