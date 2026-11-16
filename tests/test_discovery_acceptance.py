"""Independent acceptance checks for target pacing and resumable discovery.

These tests use synthetic provider responses only; they do not contain applicant
records or posting snapshots.
"""

from pathlib import Path
from unittest.mock import patch

import app as app_module
from app import (
    classify_title_match,
    discovery_diagnostic_breakdown,
    discovery_exclusion_reason_bucket,
    discovery_result_category,
    fetch_discovery_jobs_for_search,
)


def _search(**overrides):
    value = {
        "keywords": "software developer",
        "location": "Toronto, ON",
        "discovery_location": "Toronto, ON",
        "distance": 50,
        "remote_preference": "",
        "request_per_source_cap": 10,
        "hours_old": None,
        "enabled_sources": ["linkedin"],
        "search_mode": "title",
        "title_match_mode": "related",
        "occupation": "software developer",
        "requested_target": 50,
        "progressive_acquisition": True,
    }
    value.update(overrides)
    return value


def test_target_pacing_continues_until_qualifying_target(monkeypatch):
    calls = []

    def fake_fetch(**kwargs):
        calls.append(kwargs["keywords"])
        return {
            "jobs": [{
                "source_job_id": f"good-{len(calls)}",
                "title": "Junior Software Developer",
                "company": "Example",
                "location": "Toronto, ON",
                "job_url": f"https://example.test/{len(calls)}",
            }],
            "errors": {}, "source_counts": {"linkedin": 1},
            "source_diagnostics": {}, "source_snapshots": {},
        }

    monkeypatch.setattr("app.fetch_jobspy_jobs", fake_fetch)
    result = fetch_discovery_jobs_for_search(
        _search(requested_target=2),
        qualifying_predicate=lambda raw: raw.get("title", "").startswith("Junior"),
    )
    assert len(result["jobs"]) == 2
    assert len(calls) == 2
    assert calls[0] != calls[1]
    assert result["continuation_available"] is False


def test_ece_title_variants_keep_classroom_roles_and_separate_supervisory_roles():
    accepted = [
        "Registered Early Childhood Educator", "RECE", "Early Childhood Educator",
        "Casual RECE", "Supply RECE", "Preschool Educator", "Early Years Educator",
        "Childcare Educator", "Early Childhood Teacher", "Daycare Worker",
    ]
    for title in accepted:
        match, score = classify_title_match(title, "ECE", "related")
        assert match in {"exact", "related"}, title
        assert score > 0, title
    for title in [
        "RECE Supervisor", "Early Childhood Educator Supervisor", "Preschool Educator Manager",
        "ECE Program Instructor", "Childcare Administrator", "Early Childhood Therapist", "Childcare Manager",
    ]:
        for mode in ("strict", "related"):
            match, _ = classify_title_match(title, "ECE", mode)
            assert match == "uncertain", (title, mode)


def test_ece_fifty_qualifying_postings_are_acquired_across_query_batches(monkeypatch):
    calls = []

    def fake_fetch(**kwargs):
        calls.append(kwargs["keywords"])
        offset = (len(calls) - 1) * 13
        return {
            "jobs": [
                {
                    "source_job_id": f"ece-{index}",
                    "title": "Registered Early Childhood Educator",
                    "company": f"Centre {index}",
                    "location": "Toronto, ON",
                    "source": "indeed",
                    "job_url": f"https://example.test/ece/{index}",
                }
                for index in range(offset, offset + 13)
            ],
            "errors": {}, "source_counts": {"indeed": 13},
            "source_diagnostics": {}, "source_snapshots": {},
        }

    monkeypatch.setattr("app.fetch_jobspy_jobs", fake_fetch)
    result = fetch_discovery_jobs_for_search(
        _search(
            keywords="Registered Early Childhood Educator; RECE",
            enabled_sources=["indeed"], requested_target=50,
            total_cap=100, per_source_cap=100,
        ),
        qualifying_predicate=lambda raw: classify_title_match(raw["title"], "ECE", "related")[0] in {"exact", "related"},
        stop_when_target=False,
    )
    assert len(calls) == 8  # two base terms, four progressive variants each
    assert len(result["jobs"]) == 104
    assert len({item["source_job_id"] for item in result["jobs"]}) == 104
    assert len(result["completed_work_items"]) == 8
    assert result["pending_query_batches"] == []
    assert result["continuation_available"] is False


def test_ece_fifty_target_runs_full_discovery_pipeline_and_persists_inbox(monkeypatch, tmp_path):
    old_data_dir, old_db_path, old_initialized = app_module.DATA_DIR, app_module.DB_PATH, app_module._INITIALIZED_DATABASE_PATH
    app_module.DATA_DIR = Path(tmp_path)
    app_module.DB_PATH = Path(tmp_path) / "acceptance.sqlite"
    app_module._INITIALIZED_DATABASE_PATH = None
    calls = []

    class FakeProvider:
        name = "synthetic"
        def geocode(self, query, *, country="Canada"):
            return {"ok": True, "status": "saved", "provider": self.name, "normalized_query": query, "latitude": 43.65, "longitude": -79.38, "confidence": 80, "precision": "city", "display_name": query}

    def fake_fetch(**kwargs):
        calls.append(kwargs["keywords"])
        offset = (len(calls) - 1) * 13
        return {"jobs": [{
            "source_job_id": f"pipeline-ece-{index}", "title": "Registered Early Childhood Educator",
            "company": f"Centre {index}", "location": "Toronto, ON", "source": "indeed",
            "job_url": f"https://example.test/pipeline-ece/{index}", "description": "Classroom educator role.",
        } for index in range(offset, offset + 13)], "errors": {}, "source_counts": {"indeed": 13}, "source_diagnostics": {}, "source_snapshots": {}}

    try:
        client = app_module.app.test_client()
        profile = client.post("/api/candidate-profiles", json={"name": "ECE acceptance", "identity_mode": "distinct", "applicant_name": "ECE Applicant"}).get_json()
        with patch.object(app_module, "fetch_jobspy_jobs", side_effect=fake_fetch), patch.object(app_module, "get_geocoding_provider", return_value=FakeProvider()):
            response = client.post("/api/discovery/jobspy", json={
                "keywords": "Registered Early Childhood Educator", "location": "Toronto, ON", "distance": 50,
                "enabled_sources": ["indeed"], "search_mode": "title", "title_match_mode": "related",
                "applicant_profile_id": profile["id"], "candidate_profile_id": "", "new_matching_target": 50,
                "total_cap": 100, "per_source_cap": 100, "remote_preference": "",
            })
        assert response.status_code == 200, response.get_data(as_text=True)
        body = response.get_json()
        assert len(calls) == 4
        assert body["diagnostics"]["raw_jobs_inspected"] == 52
        assert body["diagnostics"]["new_matching_count"] == 50
        assert body["diagnostics"]["excluded_count"] == 0
        assert len(body["jobs"]) == 50
        persisted = client.get("/api/discovery/inbox?include_history=1").get_json()
        saved_ids = {item.get("source_job_id") for item in persisted}
        assert {f"pipeline-ece-{index}" for index in range(52)} <= saved_ids
    finally:
        app_module.DATA_DIR, app_module.DB_PATH, app_module._INITIALIZED_DATABASE_PATH = old_data_dir, old_db_path, old_initialized


def test_representative_ece_audit_keeps_exact_exclusion_and_review_reasons():
    records = []
    for index in range(29):
        records.append({
            "discovery_result_category": "excluded",
            "discovery_result_reason": [
                "Posting is confirmed closed.",
                "The role family is unrelated to the requested occupation.",
                "Confirmed workplace distance is outside the requested radius.",
                "The posting is an internship.",
            ][index % 4],
            "posting_availability": "confirmed_closed" if index % 4 == 0 else "",
            "role_type": "intern" if index % 4 == 3 else "",
            "distance_radius_status": "outside_radius" if index % 4 == 2 else "",
            "distance_confidence": 95 if index % 4 == 2 else "",
        })
    for index in range(5):
        records.append({
            "discovery_result_category": "review_required",
            "discovery_result_reason": "The role family is outside the selected target family." if index < 2 else "The posting expects experience or seniority that is not confirmed as aligned.",
            "qualification_fit_seniority": {"stretch_role": index >= 2},
        })
    records.extend({"discovery_result_category": "new", "previously_presented": True} for _ in range(6))
    records.extend({"discovery_result_category": "new"} for _ in range(2))
    audit = discovery_diagnostic_breakdown(records)
    assert audit["total"] == 42
    assert audit["category_counts"] == {"excluded": 29, "review_required": 5, "new": 8}
    assert sum(audit["exclusion_reason_counts"].values()) == 29
    assert audit["review_reason_counts"]["software_adjacent_occupation"] == 2
    assert audit["review_reason_counts"]["stretch_or_intermediate_seniority"] == 3
    assert audit["previously_presented"] == 6
    assert audit["new_count"] == 2


def test_exclusion_diagnostics_do_not_turn_unknown_location_into_hard_exclusion():
    assert discovery_exclusion_reason_bucket({"discovery_result_reason": "Posting is outside the confirmed radius", "distance_radius_status": "outside_radius", "distance_confidence": "0"}) == "unverified_location_not_hard_exclusion"
    assert discovery_exclusion_reason_bucket({"discovery_result_reason": "Posting explicitly excludes Ontario"}) == "confirmed_geographic_ineligibility"
    assert discovery_exclusion_reason_bucket({"discovery_result_reason": "The role family is unrelated"}) == "confirmed_unrelated_or_management"
    category, reason = discovery_result_category({
        "discovery_search_mode": "shortlist",
        "distance_radius_status": "outside_radius",
        "distance_confidence": 0,
        "location_search_eligible": True,
        "role_type": "software_developer",
    })
    assert category == "review_required", reason


def test_continuation_starts_after_completed_query_without_repeating(monkeypatch):
    calls = []

    def fake_fetch(**kwargs):
        calls.append(kwargs["keywords"])
        return {"jobs": [{"title": "Junior Software Developer", "company": "Example", "job_url": f"https://example.test/{len(calls)}"}], "errors": {}, "source_counts": {"linkedin": 1}, "source_diagnostics": {}, "source_snapshots": {}}

    monkeypatch.setattr("app.fetch_jobspy_jobs", fake_fetch)
    first = fetch_discovery_jobs_for_search(_search(requested_target=1), qualifying_predicate=lambda raw: True)
    second = fetch_discovery_jobs_for_search(_search(requested_target=2, continuation_index=first["continuation_index"]), qualifying_predicate=lambda raw: True)
    assert first["continuation_index"] == 1
    assert second["attempted_query_batches"][0]["keywords"] != calls[0]


def test_short_result_set_is_not_called_provider_exhaustion_and_failures_are_visible(monkeypatch):
    def fake_fetch(**_kwargs):
        return {"jobs": [{"title": "Junior Software Developer", "company": "Example", "job_url": "https://example.test/1"}], "errors": {}, "source_counts": {"linkedin": 1}, "source_diagnostics": {}, "source_snapshots": {}}

    monkeypatch.setattr("app.fetch_jobspy_jobs", fake_fetch)
    result = fetch_discovery_jobs_for_search(_search(), qualifying_predicate=lambda raw: True)
    assert result["attempted_queries_exhausted"] is True
    assert result["providers_exhausted"] is False

    def failed_fetch(**_kwargs):
        return {"jobs": [], "errors": {"linkedin": "TimeoutError: provider timed out"}, "source_counts": {"linkedin": 0}, "source_diagnostics": {}, "source_snapshots": {}}

    monkeypatch.setattr("app.fetch_jobspy_jobs", failed_fetch)
    failed = fetch_discovery_jobs_for_search(_search(), qualifying_predicate=lambda raw: True)
    assert failed["errors"]["linkedin"].startswith("TimeoutError")
    assert failed["attempted_queries_exhausted"] is False


def test_linkedin_failure_does_not_stop_later_indeed_batches(monkeypatch):
    calls = []

    def fake_fetch(**kwargs):
        calls.append((kwargs["keywords"], tuple(kwargs["enabled_sources"])))
        index = len(calls)
        return {
            "jobs": [{"source_job_id": f"indeed-{index}", "title": "Registered Early Childhood Educator", "company": "Example", "location": "Toronto, ON", "source": "indeed", "job_url": f"https://example.test/{index}"}],
            "errors": {"linkedin": "TimeoutError: provider timed out"} if index == 1 else {},
            "source_counts": {"indeed": 1}, "source_diagnostics": {}, "source_snapshots": {},
        }

    monkeypatch.setattr("app.fetch_jobspy_jobs", fake_fetch)
    result = fetch_discovery_jobs_for_search(
        _search(keywords="Registered Early Childhood Educator; RECE", enabled_sources=["linkedin", "indeed"], requested_target=3),
        qualifying_predicate=lambda _raw: True,
    )
    assert len(result["jobs"]) == 3
    assert calls[0][1] == ("linkedin", "indeed")
    assert all("linkedin" not in sources for _, sources in calls[1:])
    assert result["errors"]["linkedin"].startswith("TimeoutError")
    assert len(result["completed_work_items"]) == 3
    assert len(result["pending_query_batches"]) == 8
    # The requested target was reached; retryable failed-provider work remains
    # visible in diagnostics but does not require a Continue action.
    assert result["continuation_available"] is False


def test_continuation_retries_failed_provider_without_repeating_successful_provider(monkeypatch):
    calls = []

    def fake_fetch(**kwargs):
        calls.append(tuple(kwargs["enabled_sources"]))
        return {"jobs": [], "errors": {}, "source_counts": {}, "source_diagnostics": {}, "source_snapshots": {}}

    monkeypatch.setattr("app.fetch_jobspy_jobs", fake_fetch)
    completed = [{"location": "Toronto, ON", "keywords": "software developer", "provider": "indeed"}]
    fetch_discovery_jobs_for_search(_search(enabled_sources=["linkedin", "indeed"], completed_query_batches=completed), qualifying_predicate=lambda _raw: False)
    assert calls[0] == ("linkedin",)


def test_all_provider_failure_does_not_complete_unattempted_queries(monkeypatch):
    calls = []

    def failed(**kwargs):
        calls.append(tuple(kwargs["enabled_sources"]))
        return {"jobs": [], "errors": {source: "timeout" for source in kwargs["enabled_sources"]}, "source_counts": {}, "source_diagnostics": {}, "source_snapshots": {}}

    monkeypatch.setattr("app.fetch_jobspy_jobs", failed)
    result = fetch_discovery_jobs_for_search(_search(enabled_sources=["linkedin", "indeed"], requested_target=5), qualifying_predicate=lambda _raw: True)
    assert len(calls) == 1
    assert result["completed_query_batches"] == []
    assert len(result["pending_query_batches"]) == 4
    assert len(result["pending_work_items"]) == 8
    assert result["continuation_available"] is True


def test_provider_specific_records_override_legacy_numeric_cursor(monkeypatch):
    calls = []

    def fake_fetch(**kwargs):
        calls.append(tuple(kwargs["enabled_sources"]))
        return {"jobs": [], "errors": {}, "source_counts": {}, "source_diagnostics": {}, "source_snapshots": {}}

    monkeypatch.setattr("app.fetch_jobspy_jobs", fake_fetch)
    result = fetch_discovery_jobs_for_search(_search(enabled_sources=["linkedin", "indeed"], continuation_index=3, completed_query_batches=[{"provider": "indeed", "location": "Toronto, ON", "keywords": "software developer"}]), qualifying_predicate=lambda _raw: False)
    assert calls[0] == ("linkedin",)
    assert result["completed_query_batches"][0] == {"provider": "indeed", "location": "Toronto, ON", "keywords": "software developer"}
    assert len(result["completed_query_batches"]) == 8


def test_final_eligibility_mode_does_not_stop_at_preliminary_target(monkeypatch):
    """The API must normalize/finally qualify all planned batches first.

    A preliminary title probe cannot know whether later location, required-years
    or qualification checks will reject a candidate, so it may not end a
    50-target search early.
    """
    calls = []

    def fake_fetch(**kwargs):
        calls.append(kwargs["keywords"])
        return {"jobs": [{"source_job_id": kwargs["keywords"], "title": "Junior Software Developer"}], "errors": {}, "source_counts": {}, "source_diagnostics": {}, "source_snapshots": {}}

    monkeypatch.setattr("app.fetch_jobspy_jobs", fake_fetch)
    result = fetch_discovery_jobs_for_search(
        _search(requested_target=1),
        qualifying_predicate=lambda _raw: True,
        stop_when_target=False,
    )
    assert len(calls) == 4
    assert result["target_reached"] is False
    assert result["planned_queries_completed"] is True


def test_internship_preference_is_an_authoritative_backend_gate():
    job = {"role_type": "intern", "discovery_search_mode": "shortlist", "discovery_include_internships": False}
    assert discovery_result_category(job)[0] == "excluded"
    job["discovery_include_internships"] = True
    assert discovery_result_category(job)[0] != "excluded"
