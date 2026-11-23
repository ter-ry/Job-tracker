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
        assert kwargs["fetch_description"] is True
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
    assert diagnostic["duplicate_count"] == 1
    assert diagnostic["provider_status"] == "working"


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


def test_normalization_keeps_unknown_currency_and_original_url_contract():
    from sources.jobspy_source import normalize_jobspy_row

    normalized = normalize_jobspy_row({
        "title": "Developer",
        "job_url": "https://provider.example/jobs/123",
        "job_url_direct": "https://employer.example/careers/123",
        "min_amount": 22.5,
        "max_amount": 27.0,
        "interval": "hourly",
        "description": "Requirements: 2 years of professional software experience.",
    }, "indeed")
    assert normalized["salary_currency"] == ""
    assert normalized["original_posting_url"] == "https://provider.example/jobs/123"
    assert normalized["direct_application_url"] == "https://employer.example/careers/123"


def test_structured_jobposting_locations_and_ambiguous_age_ranges_are_conservative():
    from sources.jobspy_source import normalize_jobspy_row

    normalized = normalize_jobspy_row({
        "title": "Registered Early Childhood Educator",
        "job_location": [
            {"address": {"streetAddress": "70 Playfair Avenue", "addressLocality": "Toronto", "addressRegion": "ON", "postalCode": "M6B 2P9"}},
            {"address": {"streetAddress": "340 Falstaff Avenue", "addressLocality": "Toronto", "addressRegion": "ON", "postalCode": "M6L 3E7"}},
        ],
        "description": "We care for children aged 3 to 5 years. Preferred: experience with children.",
    }, "glassdoor")
    assert [item["postal_code"] for item in normalized["workplace_alternatives"]] == ["M6B 2P9", "M6L 3E7"]
    assert normalized["workplace_precision"] == "multiple alternatives"
    assert normalized["experience_requirement"] == ""


def test_second_location_layer_handles_multiline_daycare_labels_and_html():
    from sources.jobspy_source import extract_workplace_alternatives

    description = """Our Centre:
    1200 Bayview Avenue
    Suite 400
    Toronto, ON M4G 1Z8
    Reporting Location: <strong>85 Eglinton Avenue East, Toronto, ON M4P 1A6</strong>"""
    alternatives = extract_workplace_alternatives({}, description)
    assert {item["postal_code"] for item in alternatives} == {"M4G 1Z8", "M4P 1A6"}
    assert all(item["evidence"] for item in alternatives)
    assert all(item["extraction_method"] == "labelled_text" for item in alternatives)


def test_second_location_layer_reads_jobposting_jsonld_and_preserves_branches():
    from sources.jobspy_source import normalize_jobspy_row

    normalized = normalize_jobspy_row({
        "title": "RECE",
        "location": "Toronto, ON",
        "raw": {"jsonld": '{"@type":"JobPosting","jobLocation":[{"address":{"streetAddress":"10 Main Street","addressLocality":"Toronto","addressRegion":"ON","postalCode":"M5V 2T6"}},{"address":{"streetAddress":"20 King Street","addressLocality":"Toronto","addressRegion":"ON","postalCode":"M5H 1A1"}}]}'},
        "description": "Join our early learning team.",
    }, "indeed")
    assert [item["postal_code"] for item in normalized["workplace_alternatives"]] == ["M5V 2T6", "M5H 1A1"]
    assert all(item["extraction_method"] == "json_ld" for item in normalized["workplace_alternatives"])


def test_second_location_layer_rejects_corporate_address_and_remote_location():
    from sources.jobspy_source import normalize_jobspy_row

    normalized = normalize_jobspy_row({
        "title": "RECE",
        "location": "Toronto, ON",
        "description": "Corporate headquarters: 500 King Street, Toronto, ON M5V 1L9. Work Location: Toronto, ON.",
    }, "indeed")
    assert normalized["workplace_alternatives"] == []
    remote = normalize_jobspy_row({
        "title": "Remote RECE",
        "location": "Toronto, ON",
        "remote_type": "Remote",
        "description": "Work from home across Canada. Mailing address: 100 Main Street, Toronto, ON M5V 1L9.",
    }, "indeed")
    assert remote["workplace_alternatives"] == []


def test_daycare_title_can_authorize_a_standalone_address_line_without_label():
    from sources.jobspy_source import normalize_jobspy_row

    normalized = normalize_jobspy_row({
        "title": "RECE - City Place Daycare",
        "location": "Toronto, ON",
        "description": "City Place Daycare\n350 Queens Quay West\nToronto, ON",
    }, "indeed")
    assert any(item["address"] == "350 Queens Quay West" for item in normalized["workplace_alternatives"])


def test_facility_context_does_not_authorize_headquarters_mailing_or_contact_addresses():
    from sources.jobspy_source import normalize_jobspy_row

    for description in (
        "City Place Daycare\nCorporate headquarters: 500 King Street, Toronto, ON M5V 1L9.",
        "City Place Daycare\nMailing address: 500 King Street, Toronto, ON M5V 1L9.",
        "City Place Daycare\nContact us at 500 King Street, Toronto, ON M5V 1L9.",
    ):
        normalized = normalize_jobspy_row({
            "title": "RECE - City Place Daycare",
            "location": "Toronto, ON",
            "description": description,
        }, "indeed")
        assert normalized["workplace_alternatives"] == []
