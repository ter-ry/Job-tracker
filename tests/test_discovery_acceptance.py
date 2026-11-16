"""Independent acceptance checks for target pacing and resumable discovery.

These tests use synthetic provider responses only; they do not contain applicant
records or posting snapshots.
"""

from app import discovery_result_category, fetch_discovery_jobs_for_search


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
