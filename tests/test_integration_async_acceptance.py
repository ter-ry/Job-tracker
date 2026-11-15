"""Independent integration acceptance coverage for the async discovery API."""

import tempfile
import threading
import time
from pathlib import Path

import app as app_module


def _isolated_client(tmp_path):
    app_module.DATA_DIR = Path(tmp_path)
    app_module.DB_PATH = app_module.DATA_DIR / "integration.sqlite"
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_submission_and_status_poll_are_responsive_with_slow_pipeline(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        entered = threading.Event()
        release = threading.Event()

        def slow_pipeline(_payload):
            entered.set()
            release.wait(1)
            return {"jobs": [], "matching_jobs": [], "review_required_jobs": [], "errors": {"linkedin": "TimeoutError: timed out"}}

        monkeypatch.setattr(app_module, "run_discovery_pipeline", slow_pipeline)
        client = _isolated_client(directory)
        started = time.perf_counter()
        created = client.post("/api/discovery/searches", json={"keywords": "software developer; junior software engineer", "new_matching_target": 10})
        assert created.status_code == 202
        assert time.perf_counter() - started < 2
        search_id = created.get_json()["search_id"]
        assert entered.wait(1)
        started = time.perf_counter()
        polling = client.get(f"/api/discovery/searches/{search_id}?after=0")
        assert polling.status_code == 200
        assert polling.get_json()["status"] == "running"
        assert time.perf_counter() - started < 2
        release.set()


def test_cancel_and_continue_contracts_are_real_routes(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        release = threading.Event()

        def slow_pipeline(_payload):
            release.wait(1)
            return {"jobs": [{"title": "Indeed result"}], "matching_jobs": [], "review_required_jobs": [], "errors": {}}

        monkeypatch.setattr(app_module, "run_discovery_pipeline", slow_pipeline)
        client = _isolated_client(directory)
        created = client.post("/api/discovery/searches", json={"keywords": "software developer"}).get_json()
        search_id = created["search_id"]
        cancelled = client.post(f"/api/discovery/searches/{search_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.get_json()["status"] == "cancelled"
        release.set()
        time.sleep(0.05)
        snapshot = client.get(f"/api/discovery/searches/{search_id}?after=0").get_json()
        assert snapshot["status"] == "cancelled"
        assert client.post(f"/api/discovery/searches/{search_id}/continue").status_code == 409
