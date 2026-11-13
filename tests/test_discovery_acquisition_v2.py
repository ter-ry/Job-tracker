from unittest.mock import patch

import app


def acquisition_search(**overrides):
    search = {
        "keywords": "software developer",
        "discovery_location": "Toronto, ON",
        "location": "Toronto, ON",
        "distance": 50,
        "remote_preference": "",
        "hours_old": None,
        "enabled_sources": ["linkedin"],
        "request_per_source_cap": 100,
        "progressive_acquisition": True,
        "occupation": "software developer",
    }
    search.update(overrides)
    return search


def batch(start, count):
    return {
        "jobs": [
            {
                "source_job_id": f"job-{index}",
                "title": "Software Developer",
                "company": f"Employer {index}",
                "location": "Toronto, ON",
                "source": "linkedin",
                "job_url": f"https://example.test/jobs/{index}",
            }
            for index in range(start, start + count)
        ],
        "errors": {},
        "source_counts": {"linkedin": count},
        "source_diagnostics": {},
        "source_snapshots": {},
    }


def test_target_driven_acquisition_stops_after_fifty_qualifying_jobs():
    calls = []
    results = [batch(0, 12), batch(12, 38), batch(50, 30)]

    def provider(**kwargs):
        calls.append(kwargs["keywords"])
        return results.pop(0)

    with patch.object(app, "fetch_jobspy_jobs", side_effect=provider):
        result = app.fetch_discovery_jobs_for_search(
            acquisition_search(), qualification_probe=lambda _job: True, target_matches=50,
        )

    assert len(result["jobs"]) == 50
    assert len(calls) == 2
    assert result["target_reached"] is True
    assert result["pending_query_batches"]


def test_short_results_are_planned_completion_not_provider_exhaustion():
    calls = []

    def provider(**kwargs):
        calls.append(kwargs["keywords"])
        return batch(len(calls) * 18, 18) if len(calls) == 1 else {"jobs": [], "errors": {}, "source_counts": {}, "source_diagnostics": {}, "source_snapshots": {}}

    with patch.object(app, "fetch_jobspy_jobs", side_effect=provider):
        result = app.fetch_discovery_jobs_for_search(
            acquisition_search(), qualification_probe=lambda _job: True, target_matches=50,
        )

    assert len(result["jobs"]) == 18
    assert result["target_reached"] is False
    assert result["providers_exhausted"] is False
    assert result["planned_queries_completed"] is True


def test_blocked_provider_is_resumable_and_not_exhausted():
    with patch.object(app, "fetch_jobspy_jobs", return_value={
        "jobs": [], "errors": {"linkedin": "403 blocked"}, "source_counts": {},
        "source_diagnostics": {}, "source_snapshots": {},
    }) as provider:
        result = app.fetch_discovery_jobs_for_search(
            acquisition_search(), qualification_probe=lambda _job: True, target_matches=50,
        )

    assert provider.call_count == 1
    assert result["providers_exhausted"] is False
    assert result["continuation_available"] is True
    assert result["pending_query_batches"]


def test_eighteen_matches_before_provider_block_are_incomplete_not_exhausted():
    results = [batch(0, 18), {
        "jobs": [], "errors": {"linkedin": "rate limited"}, "source_counts": {},
        "source_diagnostics": {}, "source_snapshots": {},
    }]
    with patch.object(app, "fetch_jobspy_jobs", side_effect=results):
        result = app.fetch_discovery_jobs_for_search(
            acquisition_search(), qualification_probe=lambda _job: True, target_matches=50,
        )
    assert len(result["jobs"]) == 18
    assert result["errors"]
    assert result["providers_exhausted"] is False


def test_processed_and_skipped_candidates_do_not_count_toward_target():
    def probe(job):
        return job["source_job_id"] != "job-0"

    with patch.object(app, "fetch_jobspy_jobs", return_value=batch(0, 6)):
        result = app.fetch_discovery_jobs_for_search(
            acquisition_search(), qualification_probe=probe, target_matches=5,
        )
    assert len(result["jobs"]) == 6
    assert result["probe_qualifying_count"] == 5


def test_senior_and_finance_probe_results_are_not_qualifying():
    rows = batch(0, 2)
    rows["jobs"][0]["title"] = "Senior Software Developer"
    rows["jobs"][1]["title"] = "Accounts Receivable Specialist"
    with patch.object(app, "fetch_jobspy_jobs", return_value=rows):
        result = app.fetch_discovery_jobs_for_search(
            acquisition_search(),
            qualification_probe=lambda job: not ("Senior" in job["title"] or "Accounts" in job["title"]),
            target_matches=1,
        )
    assert result["probe_qualifying_count"] == 0
    assert result["target_reached"] is False


def test_continuation_skips_completed_query_batches():
    completed = [{"location": "Toronto, ON", "keywords": "software developer"}]
    calls = []

    def provider(**kwargs):
        calls.append(kwargs["keywords"])
        return batch(0, 1)

    with patch.object(app, "fetch_jobspy_jobs", side_effect=provider):
        result = app.fetch_discovery_jobs_for_search(
            acquisition_search(completed_query_batches=completed),
        )

    assert calls
    assert calls[0] != "software developer"
    assert all(item["keywords"] != "software developer" for item in result["attempted_query_batches"])


def test_target_probe_does_not_call_later_queries_after_target():
    calls = []

    def provider(**kwargs):
        calls.append(kwargs["keywords"])
        return batch(0, 5)

    with patch.object(app, "fetch_jobspy_jobs", side_effect=provider):
        result = app.fetch_discovery_jobs_for_search(
            acquisition_search(), qualification_probe=lambda _job: True, target_matches=5,
        )

    assert len(result["jobs"]) == 5
    assert len(calls) == 1


def test_default_target_is_consistent_for_manual_and_saved_search_config():
    assert app.discovery_search_config({"keywords": "software developer"})["requested_target"] == 50
    assert app.normalize_saved_search_payload({"name": "SWE", "keywords": "software developer"})["new_matching_target"] == 50
