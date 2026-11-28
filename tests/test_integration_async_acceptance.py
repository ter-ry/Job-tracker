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


def _wait_for_worker_to_finish(search_id):
    """Wait for the executor boundary, not merely for the mock to return.

    The worker updates SQLite after the pipeline returns.  Windows does not
    permit TemporaryDirectory cleanup while that connection is still open.
    """
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with app_module._ASYNC_DISCOVERY_LOCK:
            if search_id not in app_module._ASYNC_DISCOVERY_ACTIVE:
                return
        time.sleep(0.01)
    raise AssertionError("async discovery worker did not finish")


def test_submission_and_status_poll_are_responsive_with_slow_pipeline(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def slow_pipeline(_payload):
            entered.set()
            try:
                release.wait(1)
                return {"jobs": [], "matching_jobs": [], "review_required_jobs": [], "errors": {"linkedin": "TimeoutError: timed out"}}
            finally:
                finished.set()

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
        assert finished.wait(2)
        _wait_for_worker_to_finish(search_id)


def test_cancel_and_continue_contracts_are_real_routes(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def slow_pipeline(_payload):
            entered.set()
            try:
                release.wait(1)
                return {"jobs": [{"title": "Indeed result"}], "matching_jobs": [], "review_required_jobs": [], "errors": {}}
            finally:
                finished.set()

        monkeypatch.setattr(app_module, "run_discovery_pipeline", slow_pipeline)
        client = _isolated_client(directory)
        created = client.post("/api/discovery/searches", json={"keywords": "software developer"}).get_json()
        search_id = created["search_id"]
        # A queued search may be cancelled before a provider worker starts.
        # This route test specifically exercises durable cancellation while a
        # provider is already running, so wait for that documented boundary.
        assert entered.wait(1)
        cancelled = client.post(f"/api/discovery/searches/{search_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.get_json()["status"] == "cancelled"
        release.set()
        assert finished.wait(2)
        _wait_for_worker_to_finish(search_id)
        snapshot = client.get(f"/api/discovery/searches/{search_id}?after=0").get_json()
        assert snapshot["status"] == "cancelled"
        assert client.post(f"/api/discovery/searches/{search_id}/continue").status_code == 409
