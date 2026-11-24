import json

from sources.scraperapi_source import ScraperApiConfig, approved_indeed_url, fetch_scraperapi_page
from scripts.benchmark_scraperapi_workplace import benchmark


def test_scraperapi_requires_explicit_configuration_and_strict_url_scope():
    config = ScraperApiConfig(api_key="", enabled=False, allowed_hosts=("ca.indeed.com",))
    result = fetch_scraperapi_page("https://ca.indeed.com/viewjob?jk=abc", config=config)
    assert result["status"] == "disabled"
    assert result["request_made"] is False
    assert approved_indeed_url("https://ca.indeed.com/viewjob?jk=abc", "in-abc", config.allowed_hosts)
    assert not approved_indeed_url("https://ca.indeed.com/viewjob?jk=other", "in-abc", config.allowed_hosts)
    assert not approved_indeed_url("https://example.com/viewjob?jk=abc", "abc", config.allowed_hosts)


def test_scraperapi_benchmark_mock_validates_evidence_and_budget(monkeypatch):
    body = "<h1>RECE</h1><p>Work Location: 100 Galloway Road, Scarborough, ON M1E 1W7</p>"

    def fake_fetch(url, *, config, source_job_id=""):
        return {"retrieval_succeeded": True, "request_made": True, "status": "ok", "body": body, "latency_ms": 12.5, "credit_usage": "1"}

    monkeypatch.setattr("scripts.benchmark_scraperapi_workplace.fetch_scraperapi_page", fake_fetch)
    config = ScraperApiConfig(api_key="test-only", enabled=True, allowed_hosts=("ca.indeed.com",))
    report = benchmark(["https://ca.indeed.com/viewjob?jk=5b10c60264baec65", "https://ca.indeed.com/viewjob?jk=960d67145bdf8eb3"], config=config, max_credits=1)

    assert report["requests_attempted"] == 1
    assert report["credits_consumed"] == 1
    assert report["successful_valid_job_pages"] == 1
    assert report["expected_matches"] == 1
    assert any(item["status"] == "skipped_budget" for item in report["results"])


def test_scraperapi_response_does_not_print_or_return_api_key(monkeypatch):
    class Response:
        status = 200
        headers = {"x-scraperapi-credits-used": "1"}

        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self, _limit): return b"<html>blocked</html>"

    captured = {}
    def fake_open(request, timeout):
        captured["url"] = request.full_url
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    config = ScraperApiConfig(api_key="secret-test-key", enabled=True, allowed_hosts=("ca.indeed.com",))
    result = fetch_scraperapi_page("https://ca.indeed.com/viewjob?jk=abc", config=config)
    assert result["retrieval_succeeded"] is True
    assert "secret-test-key" not in json.dumps(result)
    assert "secret-test-key" in captured["url"]
