import json

from scripts.scraperapi_cost_preflight import estimate_url_cost, preflight
from sources.scraperapi_source import ScraperApiConfig


def test_cost_preflight_is_separate_and_parses_estimate(monkeypatch):
    class Response:
        status = 200
        headers = {"content-type": "application/json"}

        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self, _limit): return b'{"estimated_cost": 0.75}'

    calls = []

    def fake_open(request, timeout):
        calls.append(request.full_url)
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    config = ScraperApiConfig(api_key="test-key", enabled=True, allowed_hosts=("ca.indeed.com",))
    report = preflight(["https://ca.indeed.com/viewjob?jk=abc"], config=config, max_budget=2)
    assert report["target_page_retrieval_performed"] is False
    assert report["results"][0]["estimated_cost"] == 0.75
    assert report["within_configured_budget"] is True
    assert report["budget_check_status"] == "known"
    assert "/account/urlcost?" in calls[0]
    assert "viewjob%3Fjk%3Dabc" in calls[0]


def test_cost_preflight_redacts_encoded_key_and_bounds_to_two_urls(monkeypatch):
    class Response:
        status = 200
        headers = {}

        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self, _limit): return b'{"cost": 1}'

    captured = []

    def fake_open(request, timeout):
        captured.append(request.full_url)
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    secret = "secret/key+value"
    config = ScraperApiConfig(api_key=secret, enabled=True, allowed_hosts=("ca.indeed.com",))
    report = preflight(["https://ca.indeed.com/viewjob?jk=1", "https://ca.indeed.com/viewjob?jk=2", "https://ca.indeed.com/viewjob?jk=3"], config=config, max_budget=2)
    assert len(captured) == 2
    assert secret not in json.dumps(report)
    assert "secret%2Fkey%2Bvalue" not in json.dumps(report)
