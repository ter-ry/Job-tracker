"""Independent acceptance checks for target pacing and resumable discovery.

These tests use synthetic provider responses only; they do not contain applicant
records or posting snapshots.
"""

from app import fetch_discovery_jobs_for_search


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
