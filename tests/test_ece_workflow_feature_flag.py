from unittest.mock import patch

import app as app_module


def _isolated_client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setattr(app_module, "_INITIALIZED_DATABASE_PATH", None)
    client = app_module.app.test_client()
    assert client.get("/api/health").status_code == 200
    return client


def test_disabled_ece_hides_profiles_and_rejects_new_discovery(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_TRACKER_ECE_ENABLED", "1")
    client = _isolated_client(tmp_path, monkeypatch)
    swe = client.post("/api/candidate-profiles", json={"name": "SWE", "workflow": "software"}).get_json()
    ece = client.post("/api/candidate-profiles", json={"name": "ECE", "workflow": "ece"}).get_json()

    monkeypatch.setenv("JOB_TRACKER_ECE_ENABLED", "0")
    profiles = client.get("/api/candidate-profiles")
    assert profiles.status_code == 200
    assert [profile["id"] for profile in profiles.get_json()] == [swe["id"]]
    page = client.get("/")
    assert page.status_code == 200
    assert b"JOB_TRACKER_ECE_ENABLED = false" in page.data
    assert b'id="global-applicant-selector" class="muted"' in page.data

    blocked = client.post(
        "/api/discovery/jobspy",
        json={"workflow": "ece", "applicant_profile_id": ece["id"], "keywords": "RECE", "location": "Toronto"},
    )
    assert blocked.status_code == 409
    assert "disabled" in blocked.get_json()["error"]


def test_reenabled_ece_restores_profiles_and_scheduler_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_TRACKER_ECE_ENABLED", "1")
    client = _isolated_client(tmp_path, monkeypatch)
    client.post("/api/candidate-profiles", json={"name": "SWE", "workflow": "software"})
    ece = client.post("/api/candidate-profiles", json={"name": "ECE", "workflow": "ece"}).get_json()
    search = client.post(
        "/api/discovery/searches",
        json={
            "name": "ECE scheduled",
            "keywords": "RECE",
            "workflow": "ece",
            "auto_prepare_candidate_profile_id": ece["id"],
            "enabled": True,
        },
    )
    assert search.status_code == 201
    assert {profile["id"] for profile in client.get("/api/candidate-profiles").get_json()} == {1, 2}

    from scripts.discovery_worker import run_due_searches

    with app_module.app.app_context():
        db = app_module.get_db()
        db.execute(
            "INSERT INTO app_settings (key, value) VALUES ('discovery_scheduler_enabled', '1') "
            "ON CONFLICT(key) DO UPDATE SET value = '1'"
        )
        db.commit()

    monkeypatch.setenv("JOB_TRACKER_ECE_ENABLED", "0")
    with patch.object(app_module, "run_discovery_pipeline") as pipeline:
        with app_module.app.app_context():
            result = run_due_searches()
    assert result["runs"] == 0
    pipeline.assert_not_called()

    monkeypatch.setenv("JOB_TRACKER_ECE_ENABLED", "1")
    with patch.object(
        app_module,
        "run_discovery_pipeline",
        return_value={"total": 0, "persisted": {"new": 0, "duplicate": 0}, "errors": {}, "source_diagnostics": {}},
    ) as pipeline:
        with app_module.app.app_context():
            result = run_due_searches()
    assert result["runs"] == 1
    pipeline.assert_called_once()
