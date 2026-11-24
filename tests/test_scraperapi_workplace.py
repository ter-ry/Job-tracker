import json
from urllib.parse import parse_qs, urlsplit

from sources.scraperapi_source import ScraperApiConfig, approved_indeed_url, fetch_scraperapi_page
from scripts.benchmark_scraperapi_workplace import CASES, benchmark


def test_scraperapi_requires_explicit_configuration_and_strict_url_scope():
    config = ScraperApiConfig(api_key="", enabled=False, allowed_hosts=("ca.indeed.com",))
    result = fetch_scraperapi_page("https://ca.indeed.com/viewjob?jk=abc", config=config)
    assert result["status"] == "disabled"
    assert result["request_made"] is False
    assert approved_indeed_url("https://ca.indeed.com/viewjob?jk=abc", "in-abc", config.allowed_hosts)
    assert not approved_indeed_url("https://ca.indeed.com/viewjob?jk=other", "in-abc", config.allowed_hosts)
    assert not approved_indeed_url("https://example.com/viewjob?jk=abc", "abc", config.allowed_hosts)


def test_scraperapi_benchmark_mock_validates_evidence_and_budget(monkeypatch):
    body = "<h1>BGC East Scarborough</h1><p>Work Location: 100 Galloway Road, Scarborough, ON M1E 1W7</p>"

    def fake_fetch(url, *, config, source_job_id="", max_cost=None):
        return {"retrieval_succeeded": True, "request_made": True, "status": "ok", "body": body, "latency_ms": 12.5, "credit_cost": 1.0, "credit_cost_source": "sa-credit-cost", "max_cost": max_cost}

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
        headers = {"sa-credit-cost": "0.5"}

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
    assert result["credit_cost"] == 0.5
    assert "secret-test-key" not in json.dumps(result)
    assert "secret-test-key" in captured["url"]
    query = parse_qs(urlsplit(captured["url"]).query)
    assert query["max_cost"] == ["1"]


def test_scraperapi_redacts_credentials_from_transport_errors(monkeypatch):
    secret = "secret-test-key"

    def fail(_request, timeout):
        raise RuntimeError(f"request failed for https://api.scraperapi.com/?api_key={secret}")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    config = ScraperApiConfig(api_key=secret, enabled=True, allowed_hosts=("ca.indeed.com",))
    result = fetch_scraperapi_page("https://ca.indeed.com/viewjob?jk=abc", config=config)
    assert result["status"] == "failed"
    assert secret not in json.dumps(result)


def test_unknown_credit_cost_stops_before_a_second_request(monkeypatch):
    calls = []

    def fake_fetch(url, *, config, source_job_id="", max_cost=None):
        calls.append((url, max_cost))
        return {"retrieval_succeeded": False, "request_made": True, "status": "ok", "credit_cost": None}

    monkeypatch.setattr("scripts.benchmark_scraperapi_workplace.fetch_scraperapi_page", fake_fetch)
    config = ScraperApiConfig(api_key="test-only", enabled=True, allowed_hosts=("ca.indeed.com",))
    report = benchmark(list(CASES), config=config, max_credits=2)
    assert len(calls) == 1
    assert report["credits_consumed"] is None
    assert report["credits_consumed_status"] == "unknown"
    assert report["results"][1]["status"] == "skipped_budget"


def test_benchmark_does_not_count_postal_evidence_without_posting_identity(monkeypatch):
    def fake_fetch(url, *, config, source_job_id="", max_cost=None):
        return {
            "retrieval_succeeded": True, "request_made": True, "status": "ok",
            "body": "<p>Work Location: 100 Galloway Road, Scarborough, ON M1E 1W7</p>",
            "credit_cost": 1.0, "credit_cost_source": "sa-credit-cost",
        }

    monkeypatch.setattr("scripts.benchmark_scraperapi_workplace.fetch_scraperapi_page", fake_fetch)
    config = ScraperApiConfig(api_key="test-only", enabled=True, allowed_hosts=("ca.indeed.com",))
    report = benchmark(["https://ca.indeed.com/viewjob?jk=5b10c60264baec65"], config=config, max_credits=1)
    item = report["results"][0]
    assert item["identity_status"] == "unverified"
    assert item["valid_job_page"] is False
    assert report["successful_valid_job_pages"] == 0
