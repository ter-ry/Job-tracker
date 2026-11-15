import tempfile
import threading
import time
from pathlib import Path

import app as app_module


def test_async_search_acknowledges_and_persists_results(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        app_module.DATA_DIR = Path(directory)
        app_module.DB_PATH = app_module.DATA_DIR / "async.sqlite"
        app_module.app.config.update(TESTING=True)
        finished = threading.Event()

        def fake_pipeline(payload):
            finished.set()
            return {
                "jobs": [{"title": "Software Developer", "discovery_match_status": "verified"}],
                "matching_jobs": [{"title": "Software Developer", "discovery_match_status": "verified"}],
                "review_required_jobs": [], "total": 1, "duplicates": 0,
                "search_progress": {"requested_target": 10, "new_matching_jobs": 1, "review_required": 0, "raw_jobs_inspected": 1, "continuation_available": True, "termination_reason": "request_budget_reached_resumable"},
                "source_diagnostics": {"linkedin": {"state": "completed"}}, "errors": {},
            }

        monkeypatch.setattr(app_module, "run_discovery_pipeline", fake_pipeline)
        client = app_module.app.test_client()
        started = time.perf_counter()
        response = client.post("/api/discovery/searches", json={"keywords": "software developer", "new_matching_target": 10})
        latency = time.perf_counter() - started
        assert response.status_code == 202
        assert latency < 2
        search_id = response.get_json()["search_id"]
        assert finished.wait(2)
        for _ in range(40):
            status = client.get(f"/api/discovery/searches/{search_id}?after=0")
            if status.get_json().get("status") == "paused":
                break
            time.sleep(0.01)
        assert status.status_code == 200
        body = status.get_json()
        assert body["status"] == "paused"
        assert body["progress"]["qualifying_matches"] == 1
        assert body["jobs"][0]["result_sequence"] == 0
        assert body["continuation_available"] is True


def test_async_cancel_preserves_cancelled_state(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        app_module.DATA_DIR = Path(directory)
        app_module.DB_PATH = app_module.DATA_DIR / "cancel.sqlite"
        app_module.app.config.update(TESTING=True)
        started = threading.Event()
        release = threading.Event()

        def slow_pipeline(payload):
            started.set()
            release.wait(2)
            return {"jobs": [{"title": "Late result"}], "matching_jobs": [], "review_required_jobs": [], "total": 1, "errors": {}}

        monkeypatch.setattr(app_module, "run_discovery_pipeline", slow_pipeline)
        client = app_module.app.test_client()
        created = client.post("/api/discovery/searches", json={"keywords": "software developer"}).get_json()
        search_id = created["search_id"]
        assert started.wait(2)
        cancelled = client.post(f"/api/discovery/searches/{search_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.get_json()["status"] == "cancelled"
        release.set()
        time.sleep(0.1)
        assert client.get(f"/api/discovery/searches/{search_id}").get_json()["status"] == "cancelled"


def test_async_search_publishes_provider_progress_before_final_qualification(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        app_module.DATA_DIR = Path(directory)
        app_module.DB_PATH = app_module.DATA_DIR / "incremental.sqlite"
        app_module.app.config.update(TESTING=True)
        published = threading.Event()
        release = threading.Event()

        def fake_pipeline(payload, *, on_provider_update=None):
            assert on_provider_update is not None
            on_provider_update({
                "source": "indeed",
                "jobs": [{
                    "source": "indeed", "source_job_id": "incremental-1",
                    "title": "Junior Software Developer", "company": "Example",
                    "location": "Toronto, ON", "job_url": "https://example.test/incremental-1",
                }],
                "errors": {},
                "source_diagnostics": {"indeed": {"source": "indeed", "state": "working"}},
            })
            published.set()
            release.wait(2)
            return {
                "jobs": [{
                    "source": "Indeed", "source_job_id": "incremental-1",
                    "id": 17,
                    "title": "Junior Software Developer", "company": "Example",
                    "location": "Toronto, ON", "url": "https://example.test/incremental-1",
                    "discovery_result_category": "actionable", "discovery_match_status": "verified",
                }],
                "matching_jobs": [{"title": "Junior Software Developer"}],
                "review_required_jobs": [], "total": 1, "errors": {},
                "search_progress": {"requested_target": 10, "new_matching_jobs": 1, "raw_jobs_inspected": 1},
                "source_diagnostics": {"indeed": {"source": "indeed", "state": "working"}},
            }

        monkeypatch.setattr(app_module, "run_discovery_pipeline", fake_pipeline)
        client = app_module.app.test_client()
        search_id = client.post("/api/discovery/searches", json={"keywords": "software developer", "new_matching_target": 10}).get_json()["search_id"]
        assert published.wait(2)
        early = client.get(f"/api/discovery/searches/{search_id}?after=0").get_json()
        assert early["status"] == "running"
        assert early["provider_states"]["indeed"]["state"] == "working"
        assert early["jobs"] == []
        release.set()
        for _ in range(80):
            final = client.get(f"/api/discovery/searches/{search_id}?after={early['next_sequence']}").get_json()
            if final["status"] == "completed":
                break
            time.sleep(0.01)
        assert final["status"] == "completed"
        assert len(final["jobs"]) == 1
        assert final["jobs"][0]["result_stage"] == "qualified"
        assert final["jobs"][0]["discovery_match_status"] == "verified"
        assert final["jobs"][0]["id"] == 17


def test_async_worker_does_not_mark_results_presented_before_delivery(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        app_module.DATA_DIR = Path(directory)
        app_module.DB_PATH = app_module.DATA_DIR / "delivery.sqlite"
        app_module.app.config.update(TESTING=True)

        def fake_pipeline(payload):
            with app_module.app.app_context():
                job = app_module.normalize_job_payload({"source": "fixture", "source_job_id": "unseen", "title": "Junior Software Developer", "company": "Example", "location": "Toronto, ON", "job_url": "https://example.test/unseen"})
                app_module.persist_discovery_jobs([job], None, None)
            return {"jobs": [{**job, "discovery_result_category": "actionable"}], "matching_jobs": [job], "review_required_jobs": [], "total": 1, "errors": {}, "search_progress": {"requested_target": 1, "new_matching_jobs": 1, "raw_jobs_inspected": 1}}

        monkeypatch.setattr(app_module, "run_discovery_pipeline", fake_pipeline)
        client = app_module.app.test_client()
        response = client.post("/api/discovery/searches", json={"keywords": "software developer", "applicant_profile_id": 11, "new_matching_target": 1})
        search_id = response.get_json()["search_id"]
        for _ in range(80):
            final = client.get(f"/api/discovery/searches/{search_id}").get_json()
            if final["status"] == "completed":
                break
            time.sleep(0.01)
        job_id = final["jobs"][0]["id"]
        with app_module.app.app_context():
            assert not app_module.applicant_presented_discovery_job(job_id, 11)


def test_named_search_keeps_legacy_saved_search_contract():
    with tempfile.TemporaryDirectory() as directory:
        app_module.DATA_DIR = Path(directory)
        app_module.DB_PATH = app_module.DATA_DIR / "saved.sqlite"
        app_module.app.config.update(TESTING=True)
        response = app_module.app.test_client().post(
            "/api/discovery/searches",
            json={"name": "SWE saved", "keywords": "software developer", "enabled_sources": ["linkedin"]},
        )
        assert response.status_code == 201
        assert response.get_json()["name"] == "SWE saved"


def test_presented_history_and_actions_are_durable_and_applicant_scoped():
    with tempfile.TemporaryDirectory() as directory:
        app_module.DATA_DIR = Path(directory)
        app_module.DB_PATH = app_module.DATA_DIR / "presented.sqlite"
        app_module.app.config.update(TESTING=True)
        client = app_module.app.test_client()
        client.get("/api/health")
        jobs = [
            {
                "company": "Example", "title": f"Junior Software Developer {index}", "location": "Toronto, ON",
                "url": f"https://example.test/{index}", "application_url": f"https://example.test/{index}",
                "source": "Indeed", "source_job_id": f"new-{index}", "discovery_result_category": "actionable",
            }
            for index in range(10)
        ]
        with app_module.app.app_context():
            app_module.persist_discovery_jobs(jobs, None, None)
            assert all(int(job["id"]) > 0 for job in jobs)
            app_module.mark_discovery_jobs_presented([job["id"] for job in jobs], 101)
            assert all(app_module.applicant_presented_discovery_job(job["id"], 101) for job in jobs)
            assert not any(app_module.applicant_presented_discovery_job(job["id"], 202) for job in jobs)

        assert client.post(f"/api/discovery/inbox/{jobs[0]['id']}/applied", json={"applicant_profile_id": 101}).status_code == 200
        assert client.post(f"/api/discovery/inbox/{jobs[1]['id']}/save", json={"applicant_profile_id": 101}).status_code == 200
        assert client.post(f"/api/discovery/inbox/{jobs[2]['id']}/ignore", json={"applicant_profile_id": 101}).status_code == 200
        with app_module.app.app_context():
            assert app_module.applicant_discovery_state(jobs[0]["id"], 101) == "applied"
            assert app_module.applicant_discovery_state(jobs[1]["id"], 101) == "saved"
            assert app_module.applicant_discovery_state(jobs[2]["id"], 101) == "skipped"
            assert app_module.applicant_discovery_state(jobs[0]["id"], 202) == ""

        assert client.post(f"/api/discovery/inbox/{jobs[2]['id']}/restore", json={"applicant_profile_id": 101}).status_code == 200
        with app_module.app.app_context():
            assert not app_module.applicant_presented_discovery_job(jobs[2]["id"], 101)
            assert app_module.applicant_discovery_state(jobs[2]["id"], 101) == ""


def test_indexed_identity_lookup_scales_with_ten_thousand_jobs():
    with tempfile.TemporaryDirectory() as directory:
        app_module.DATA_DIR = Path(directory)
        app_module.DB_PATH = app_module.DATA_DIR / "large.sqlite"
        app_module.app.config.update(TESTING=True)
        client = app_module.app.test_client()
        client.get("/api/health")
        with app_module.app.app_context():
            db = app_module.get_db()
            db.executemany(
                "INSERT INTO jobs (company, title, location, url, application_url, source, source_job_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(f"Employer {i}", "Software Developer", "Toronto, ON", f"https://example.test/{i}", f"https://example.test/{i}", "indeed", f"id-{i}") for i in range(10000)],
            )
            db.commit()
            started = time.perf_counter()
            found = app_module.find_existing_job_match({
                "company": "Employer 9999", "title": "Software Developer", "location": "Toronto, ON",
                "url": "https://example.test/9999", "source": "indeed", "source_job_id": "id-9999",
            })
            elapsed = time.perf_counter() - started
        assert found is not None
        assert elapsed < 0.5
