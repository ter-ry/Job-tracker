from datetime import datetime, timedelta, timezone

from sources.jobspy_source import JOBSPY_SOURCE_NAMES, fetch_jobspy_jobs


def test_active_jobspy_sources_exclude_google_and_include_glassdoor():
    assert set(JOBSPY_SOURCE_NAMES) == {"linkedin", "indeed", "zip_recruiter", "glassdoor"}

    result = fetch_jobspy_jobs(
        keywords="developer", location="Toronto, ON", enabled_sources=["google"],
        scrape_jobs_func=lambda **_kwargs: [],
    )
    assert result["jobs"] == []
    assert "google" not in result["source_diagnostics"]


def test_adapter_records_full_rows_evidence_and_deduplicates_diagnostic_identity():
    recent = datetime.now(timezone.utc).isoformat()

    def fake_scrape(**kwargs):
        assert kwargs["site_name"] == "glassdoor"
        assert kwargs["country_indeed"] == "Canada"
        assert kwargs["distance"] == 31  # 50 km converted to JobSpy miles
        assert kwargs["description_format"] == "markdown"
        return [
            {
                "id": "same-id",
                "title": "RECE",
                "company": "Example Child Care",
                "location": "Toronto, ON",
                "job_url": "https://example.test/rece",
                "description": "Work at 123 Main Street, Toronto, ON M1M 1M1. $24.50 hourly.",
                "date_posted": recent,
                "min_amount": 24.50,
                "max_amount": 24.50,
                "interval": "hourly",
                "currency": "CAD",
            },
            {
                "id": "same-id",
                "title": "RECE",
                "company": "Example Child Care",
                "location": "Toronto, ON",
                "job_url": "https://example.test/rece",
                "description": "Work at 123 Main Street, Toronto, ON M1M 1M1. $24.50 hourly.",
                "date_posted": recent,
            },
            {"company": "Malformed", "location": "Toronto, ON"},
        ]

    result = fetch_jobspy_jobs(
        keywords="Registered Early Childhood Educator",
        location="Toronto, ON",
        distance=50,
        enabled_sources=["glassdoor"],
        results_wanted=30,
        scrape_jobs_func=fake_scrape,
    )
    diagnostic = result["source_diagnostics"]["glassdoor"]
    assert diagnostic["state"] == "working"
    assert diagnostic["raw_records_row_count"] == 3
    assert diagnostic["valid_normalized_jobs"] == 2
    assert diagnostic["unique_job_count"] == 1
    assert diagnostic["raw_source_snapshot_count"] == 3
    assert diagnostic["original_url_count"] == 2
    assert diagnostic["description_complete_count"] == 2
    assert diagnostic["salary_evidence_count"] == 1
    assert diagnostic["address_evidence_count"] == 2
    assert result["jobs"][0]["salary_text"] == "$24.50-$24.50 hourly"


def test_adapter_filters_old_rows_and_reports_no_results_and_timeout_states():
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()

    def old_rows(**_kwargs):
        return [{"title": "Old role", "date_posted": old, "job_url": "https://example.test/old"}]

    result = fetch_jobspy_jobs(
        keywords="developer", location="Toronto, ON", hours_old=24,
        enabled_sources=["indeed"], scrape_jobs_func=old_rows,
    )
    diagnostic = result["source_diagnostics"]["indeed"]
    assert diagnostic["state"] == "partial"
    assert diagnostic["normalized_row_count"] == 1
    assert diagnostic["date_filtered_removed_count"] == 1
    assert result["jobs"] == []

    def blocked(**_kwargs):
        raise RuntimeError("403 forbidden by provider")

    blocked_result = fetch_jobspy_jobs(
        keywords="developer", location="Toronto, ON", enabled_sources=["linkedin"], scrape_jobs_func=blocked,
    )
    assert blocked_result["source_diagnostics"]["linkedin"]["state"] == "blocked"
