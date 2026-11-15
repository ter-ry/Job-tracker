import multiprocessing
import time

from sources.jobspy_source import fetch_jobspy_jobs
from sources.provider_runtime import GeocodeRuntime, ProviderCircuitBreaker, run_isolated_provider


def slow_worker(_request, _result_queue):
    time.sleep(2)


def test_isolated_provider_timeout_terminates_and_reaps_child():
    started = time.monotonic()
    try:
        run_isolated_provider({}, 0.05, worker_target=slow_worker)
    except TimeoutError as exc:
        assert "timed out" in str(exc)
    else:
        raise AssertionError("expected isolated timeout")
    assert time.monotonic() - started < 1.5
    assert not [child for child in multiprocessing.active_children() if child.name == "jobspy-provider"]


def test_one_injected_provider_failure_does_not_hide_another_result():
    def provider(**kwargs):
        if kwargs["site_name"] == "indeed":
            raise RuntimeError("403 forbidden")
        return [{"title": "Developer", "company": "Good Provider", "job_url": "https://example.test/1"}]

    result = fetch_jobspy_jobs(
        keywords="developer", location="Toronto, ON",
        enabled_sources=["linkedin", "indeed"], scrape_jobs_func=provider,
        execution_mode="thread",
    )
    assert [job["company"] for job in result["jobs"]] == ["Good Provider"]
    assert result["source_diagnostics"]["indeed"]["state"] == "blocked"
    assert result["source_diagnostics"]["linkedin"]["state"] == "working"


def test_geocode_runtime_deduplicates_city_queries_skips_remote_and_scopes_profiles():
    calls = []

    def provider(query, **_kwargs):
        calls.append(query)
        return {"ok": True, "status": "saved", "normalized_query": query}

    runtime = GeocodeRuntime(provider_name="test")
    first = runtime.resolve_many(
        [{"query": "Toronto, ON"}, {"query": " toronto,   on "}, {"query": "Canada", "remote": True}],
        provider=provider, context_key="profile-a",
    )
    second = runtime.resolve("Toronto, ON", provider=provider, context_key="profile-b")
    assert calls == ["Toronto, ON", "Toronto, ON"]
    assert runtime.calls == 2
    assert first[1]["cached"] is True
    assert first[2]["status"] == "skipped_remote"
    assert second["cached"] is False


def test_circuit_breaker_skips_repeated_failures_during_continuation():
    breaker = ProviderCircuitBreaker(failure_threshold=2, cooldown_seconds=60)
    calls = []

    def blocked(**_kwargs):
        calls.append(True)
        raise RuntimeError("DNS unavailable")

    for _ in range(2):
        result = fetch_jobspy_jobs(
            keywords="developer", location="Toronto", enabled_sources=["indeed"],
            scrape_jobs_func=blocked, execution_mode="thread", circuit_breaker=breaker,
        )
        assert result["source_diagnostics"]["indeed"]["state"] == "unavailable"
    skipped = fetch_jobspy_jobs(
        keywords="developer", location="Toronto", enabled_sources=["indeed"],
        scrape_jobs_func=blocked, execution_mode="thread", circuit_breaker=breaker,
    )
    assert skipped["source_diagnostics"]["indeed"]["state"] == "circuit_open"
    assert len(calls) == 2
