"""Read-only employer-direct source contracts and distinct acquisition tests."""
from __future__ import annotations

from sources import ats_source
import app as app_module
import urllib.error


BOARDS = (
    {"kind": "lever", "slug": "policyme", "company": "PolicyMe"},
    {"kind": "ashby", "slug": "wealthsimple", "company": "Wealthsimple"},
    {"kind": "greenhouse", "slug": "greenhouse", "company": "Greenhouse"},
)


def _sample_feeds():
    return {
        "lever": [
            {
                "id": "lever-junior-101",
                "text": "Junior Software Engineer",
                "categories": {"location": "Toronto, Ontario, Canada"},
                "descriptionPlain": "Build Python APIs with React and SQL.",
                "hostedUrl": "https://jobs.lever.co/policyme/lever-junior-101",
                "createdAt": 1794931200000,
            },
            {
                "id": "lever-us-only",
                "text": "Software Engineer",
                "categories": {"location": "San Francisco, California, United States"},
                "hostedUrl": "https://jobs.lever.co/policyme/lever-us-only",
            },
        ],
        "ashby": {
            "jobs": [{
                "id": "ashby-123", "title": "Software Developer",
                "location": "Remote - Canada", "isRemote": True,
                "descriptionPlain": "Maintain cloud services and backend Python code.",
                "jobUrl": "https://jobs.ashbyhq.com/wealthsimple/ashby-123",
            }]
        },
        "greenhouse": {
            "jobs": [{
                "id": 12345, "title": "Backend Software Engineer",
                "location": {"name": "Toronto, Ontario, Canada"},
                "content": "<p>Build production APIs in Python and SQL.</p>",
                "absolute_url": "https://job-boards.greenhouse.io/greenhouse/jobs/12345",
            }]
        },
    }


def test_employer_board_endpoints_are_public_read_only():
    assert ats_source._url(BOARDS[0]) == "https://api.lever.co/v0/postings/policyme?mode=json"
    assert ats_source._url(BOARDS[1]) == "https://api.ashbyhq.com/posting-api/job-board/wealthsimple"
    assert ats_source._url(BOARDS[2]) == "https://boards-api.greenhouse.io/v1/boards/greenhouse/jobs?content=true"
    assert ats_source._url({"kind": "smartrecruiters", "slug": "d2l", "company": "D2L"}) == "https://api.smartrecruiters.com/v1/companies/d2l/postings?limit=100"


def test_rejects_untrusted_board_identifier():
    try:
        ats_source._url({"kind": "lever", "slug": "../evil", "company": "example"})
    except ValueError:
        pass
    else:
        raise AssertionError("Board identifiers must not turn into arbitrary URL paths")


def test_ats_feeds_return_relevant_canadian_jobs_with_stable_attribution():
    feeds = _sample_feeds()
    def fetcher(url, timeout):
        assert timeout > 0
        return feeds["lever" if "lever.co" in url else "ashby" if "ashbyhq" in url else "greenhouse"]
    result = ats_source.fetch_employer_direct_jobs(boards=BOARDS, fetch_json=fetcher)
    assert result["errors"] == {}
    assert result["source_counts"]["employer_direct"] == 3
    jobs = result["jobs"]
    assert {j["source_job_id"] for j in jobs} == {
        "lever:policyme:lever-junior-101", "ashby:wealthsimple:ashby-123",
        "greenhouse:greenhouse:12345"
    }
    assert all(j["job_url"].startswith("https://") for j in jobs)
    assert all(j["source"] == "employer_direct" for j in jobs)
    assert all(j["description"] for j in jobs)
    assert result["source_diagnostics"]["employer_direct"]["boards_succeeded"] == 3
    assert all("San Francisco" not in j["location"] for j in jobs)


def test_board_failures_do_not_delete_jobs_from_other_boards():
    feeds = _sample_feeds()
    def fetcher(url, timeout):
        if "ashbyhq" in url:
            raise TimeoutError("temporary board timeout")
        return feeds["lever" if "lever.co" in url else "greenhouse"]
    result = ats_source.fetch_employer_direct_jobs(boards=BOARDS, fetch_json=fetcher)
    assert result["source_counts"]["employer_direct"] == 2
    assert result["source_diagnostics"]["employer_direct"]["boards_failed"] == 1
    assert result["source_diagnostics"]["employer_direct"]["state"] == "working"
    assert result["errors"] == {}


def test_all_failed_boards_report_failure_not_empty_success():
    def fetcher(url, timeout):
        raise TimeoutError("unavailable")
    result = ats_source.fetch_employer_direct_jobs(boards=BOARDS, fetch_json=fetcher)
    assert result["jobs"] == []
    assert result["source_diagnostics"]["employer_direct"]["state"] == "unavailable"
    assert "employer_direct" in result["errors"]


def test_smartrecruiters_rows_keep_requisition_url_and_description():
    board = {"kind": "smartrecruiters", "slug": "d2l", "company": "D2L"}
    payload = {"postings": [{
        "id": "req-42", "name": "Junior Software Developer",
        "location": {"city": "Toronto", "region": "Ontario", "country": "Canada"},
        "ref": "https://jobs.smartrecruiters.com/D2L/req-42",
        "releasedDate": "2026-11-17T00:00:00Z",
        "jobAd": {"sections": {"jobDescription": {"title": "About", "text": "Build Python services."}}},
    }]}
    job = ats_source._row(board, payload["postings"][0])
    assert job is not None
    assert job["source_job_id"] == "smartrecruiters:d2l:req-42"
    assert job["job_url"] == "https://jobs.smartrecruiters.com/D2L/req-42"
    assert "Build Python services" in job["description"]


def test_smartrecruiters_listing_paginates_and_fetches_missing_detail(monkeypatch):
    monkeypatch.setattr(ats_source, "SMARTRECRUITERS_PAGE_LIMIT", 2)
    board = {"kind": "smartrecruiters", "slug": "d2l", "company": "D2L"}
    def listing(number):
        return {
            "id": f"req-{number}", "name": f"Junior Software Developer {number}",
            "location": {"city": "Toronto", "region": "Ontario", "country": "Canada"},
            "ref": f"https://jobs.smartrecruiters.com/D2L/req-{number}",
            "releasedDate": "2026-11-17T00:00:00Z",
        }
    pages = {
        0: {"content": [listing(0), listing(1)], "offset": 0, "limit": 2, "totalFound": 5},
        2: {"content": [listing(2), listing(3)], "offset": 2, "limit": 2, "totalFound": 5},
        4: {"content": [listing(4)], "offset": 4, "limit": 2, "totalFound": 5},
    }
    def fetcher(url, timeout):
        assert timeout > 0
        if "postings/req-" in url:
            number = url.rsplit("req-", 1)[1]
            return {"id": f"req-{number}", "jobAd": {"sections": {"description": {"text": f"Requirements for {number}: Python and SQL."}}}}
        offset = int(url.split("offset=", 1)[1])
        return pages[offset]
    result = ats_source.fetch_employer_direct_jobs(boards=(board,), fetch_json=fetcher, max_workers=1)
    assert len(result["jobs"]) == 5
    diag = result["source_diagnostics"]["employer_direct"]
    assert diag["board_outcomes"][0]["pages"] == 3
    assert diag["detail_attempted_count"] == 5
    assert diag["detail_succeeded_count"] == 5
    assert diag["description_available_count"] == 5


def test_smartrecruiters_empty_response_is_no_results_not_failure():
    board = {"kind": "smartrecruiters", "slug": "d2l", "company": "D2L"}
    result = ats_source.fetch_employer_direct_jobs(
        boards=(board,), fetch_json=lambda url, timeout: {"content": [], "offset": 0, "limit": 100, "totalFound": 0},
    )
    diag = result["source_diagnostics"]["employer_direct"]
    assert result["jobs"] == []
    assert diag["state"] == "no_results"
    assert diag["boards_succeeded"] == 1
    assert diag["boards_failed"] == 0
    assert result["errors"] == {}


def test_smartrecruiters_malformed_response_and_detail_failure_are_diagnosed():
    board = {"kind": "smartrecruiters", "slug": "d2l", "company": "D2L"}
    malformed = ats_source.fetch_employer_direct_jobs(boards=(board,), fetch_json=lambda url, timeout: {"jobs": []})
    outcome = malformed["source_diagnostics"]["employer_direct"]["board_outcomes"][0]
    assert outcome["state"] == "failed"
    assert outcome["failure_class"] == "malformed_response"

    entry = {"id": "req-1", "name": "Software Developer", "location": "Toronto, Ontario, Canada", "ref": "https://jobs.smartrecruiters.com/D2L/req-1"}
    def detail_failure(url, timeout):
        if "offset=" in url:
            return {"content": [entry], "totalFound": 1}
        raise TimeoutError("detail timed out")
    result = ats_source.fetch_employer_direct_jobs(boards=(board,), fetch_json=detail_failure)
    diag = result["source_diagnostics"]["employer_direct"]
    assert len(result["jobs"]) == 1
    assert diag["detail_failure_count"] == 1


def test_proxy_tunnel_failure_is_distinct_from_employer_http_failure():
    proxy = ats_source.fetch_employer_direct_jobs(
        boards=(BOARDS[0],), fetch_json=lambda url, timeout: (_ for _ in ()).throw(
            urllib.error.URLError("Tunnel connection failed: 403 Forbidden")
        ),
    )
    assert proxy["source_diagnostics"]["employer_direct"]["board_outcomes"][0]["failure_class"] == "proxy_establishment_failure"

    employer = ats_source.fetch_employer_direct_jobs(
        boards=(BOARDS[0],), fetch_json=lambda url, timeout: (_ for _ in ()).throw(
            urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        ),
    )
    assert employer["source_diagnostics"]["employer_direct"]["board_outcomes"][0]["failure_class"] == "employer_http_403"


def test_board_diagnostics_separate_fetched_usable_excluded_and_duplicate_counts():
    board = {"kind": "lever", "slug": "policyme", "company": "PolicyMe"}
    feed = [{
        "id": "one", "text": "Backend Engineer", "categories": {"location": "Toronto, Ontario, Canada"},
        "hostedUrl": "https://jobs.lever.co/policyme/one",
    }, {
        "id": "us", "text": "Backend Engineer", "categories": {"location": "Austin, Texas, United States"},
        "hostedUrl": "https://jobs.lever.co/policyme/us",
    }, {
        "id": "one", "text": "Backend Engineer", "categories": {"location": "Toronto, Ontario, Canada"},
        "hostedUrl": "https://jobs.lever.co/policyme/one",
    }]
    result = ats_source.fetch_employer_direct_jobs(boards=(board,), fetch_json=lambda *_args, **_kwargs: feed)
    diag = result["source_diagnostics"]["employer_direct"]
    assert diag["fetched_count"] == 3
    assert diag["usable_count"] == 1
    assert diag["excluded_count"] == 1
    assert diag["duplicate_count"] == 1


def _search(**overrides):
    return {
        "keywords": "software developer",
        "location": "Toronto, ON",
        "discovery_location": "Toronto, ON",
        "distance": 50,
        "remote_preference": "",
        "hours_old": None,
        "enabled_sources": ["employer_direct"],
        "per_source_cap": 20,
        "request_per_source_cap": 20,
        "total_cap": 50,
        "progressive_acquisition": True,
        **overrides,
    }


def test_employer_direct_is_real_selectable_discovery_source():
    assert app_module.normalize_discovery_sources(["employer_direct"]) == ["employer_direct"]
    assert "employer_direct" in app_module.DISCOVERY_SOURCES


def test_employer_direct_scans_once_not_on_every_keyword_variant(monkeypatch):
    feeds = _sample_feeds()
    direct = ats_source.fetch_employer_direct_jobs(
        boards=BOARDS,
        fetch_json=lambda url, timeout: feeds["lever" if "lever.co" in url else "ashby" if "ashbyhq" in url else "greenhouse"],
    )
    invocations = []
    def fake_direct(**kwargs):
        invocations.append(kwargs)
        return direct
    def forbidden_jobspy(**kwargs):
        raise AssertionError("ATS-only selection should never call the JobSpy scraper")
    monkeypatch.setattr(app_module, "fetch_employer_direct_jobs", fake_direct)
    monkeypatch.setattr(app_module, "fetch_jobspy_jobs", forbidden_jobspy)
    result = app_module.fetch_discovery_jobs_for_search(_search())
    assert len(result["jobs"]) == 3
    assert len(invocations) == 1
    assert result["source_counts"]["employer_direct"] == 3
    marker = {"provider": "employer_direct", "location": "__employer_registry__", "keywords": "all_boards"}
    assert marker in result["completed_query_batches"]
    assert result["continuation_available"] is False


def test_resume_skips_already_completed_ats_board_scan(monkeypatch):
    marker = {"provider": "employer_direct", "location": "__employer_registry__", "keywords": "all_boards"}
    monkeypatch.setattr(app_module, "fetch_employer_direct_jobs", lambda **_: (_ for _ in ()).throw(
        AssertionError("Resumed search must not re-scan completed ATS work")))
    result = app_module.fetch_discovery_jobs_for_search(_search(completed_query_batches=[marker]))
    assert result["jobs"] == []
    assert result["continuation_available"] is False


def test_mixed_sources_keep_distinct_ats_and_indeed_rows(monkeypatch):
    feeds = _sample_feeds()
    monkeypatch.setattr(
        app_module, "fetch_employer_direct_jobs",
        lambda **_: ats_source.fetch_employer_direct_jobs(
            boards=BOARDS,
            fetch_json=lambda url, timeout: feeds["lever" if "lever.co" in url else "ashby" if "ashbyhq" in url else "greenhouse"],
        ),
    )
    monkeypatch.setattr(app_module, "fetch_jobspy_jobs", lambda **kwargs: {
        "jobs": [{
            "source": "indeed", "source_job_id": "indeed-888", "title": "Junior Developer",
            "company": "Example Toronto", "location": "Toronto, ON",
            "description": "Build applications.", "job_url": "https://example.test/indeed-888",
        }],
        "errors": {}, "source_counts": {"indeed": 1},
        "source_diagnostics": {"indeed": {"state": "working", "result_count": 1}},
        "source_snapshots": {},
    })
    result = app_module.fetch_discovery_jobs_for_search(
        _search(enabled_sources=["indeed", "employer_direct"], total_cap=70)
    )
    assert len(result["jobs"]) == 4
    assert {j["source"] for j in result["jobs"]} == {"indeed", "employer_direct"}
    assert result["source_counts"]["employer_direct"] == 3
