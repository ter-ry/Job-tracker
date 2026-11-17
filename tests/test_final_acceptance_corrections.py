import os
from pathlib import Path

import app as app_module


def _isolated_client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", Path(tmp_path))
    monkeypatch.setattr(app_module, "DB_PATH", Path(tmp_path) / "jobs.sqlite")
    monkeypatch.setattr(app_module, "_INITIALIZED_DATABASE_PATH", None)
    return app_module.app.test_client()


def _profile(client, name, workflow):
    response = client.post("/api/candidate-profiles", json={"name": name, "workflow": workflow, "identity_mode": "distinct", "applicant_name": name})
    assert response.status_code == 201
    return response.get_json()["id"]


def _stored_job(client, category="excluded", occupation="software developer"):
    with app_module.app.app_context():
        job = app_module.normalize_job_payload({
            "source": "fixture", "source_job_id": f"acceptance-{category}-{occupation}",
            "title": "Junior Software Developer" if occupation == "software developer" else "Registered Early Childhood Educator",
            "company": "Acceptance Centre", "location": "Toronto, ON", "job_url": "https://example.test/acceptance",
            "description": "A current classroom or software opportunity.",
        })
        job.update({
            "discovery_first_seen_at": "2026-01-01T00:00:00",
            "discovery_last_seen_at": "2026-01-01T00:00:00",
            "discovery_result_category": category,
            "discovery_result_reason": "Old matching rule",
            "discovery_occupation": occupation,
            "discovery_search_mode": "shortlist",
            "role_type": "software developer" if occupation == "software developer" else "early childhood educator",
        })
        result = app_module.persist_discovery_jobs([job], None, None)
        assert result["new_job_ids"]
        return result["new_job_ids"][0]


def test_server_authoritatively_rejects_wrong_missing_and_unknown_applicants(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    swe = _profile(client, "SWE", "software")
    ece = _profile(client, "ECE", "ece")
    job_id = _stored_job(client)

    wrong = client.post(f"/api/discovery/inbox/{job_id}/save", json={"applicant_profile_id": swe, "workflow": "ece"})
    assert wrong.status_code == 400
    assert "configured for SOFTWARE" in wrong.get_json()["error"]

    unknown = client.post(f"/api/discovery/inbox/{job_id}/save", json={"applicant_profile_id": 99999, "workflow": "software"})
    assert unknown.status_code == 400

    inferred = client.post(f"/api/discovery/inbox/{job_id}/save", json={"applicant_profile_id": ece})
    assert inferred.status_code == 200
    review_wrong = client.post(f"/api/discovery/inbox/{job_id}/review", json={"applicant_profile_id": swe, "workflow": "ece"})
    assert review_wrong.status_code == 400


def test_re_evaluate_is_occupation_scoped_and_preserves_history(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    swe = _profile(client, "SWE", "software")
    software_id = _stored_job(client, occupation="software developer")
    _stored_job(client, occupation="early childhood educator")
    original_seen = client.get(f"/api/discovery/inbox?include_history=1&page_size=10").get_json()[0]["discovery_first_seen_at"]

    saved = client.post(f"/api/discovery/inbox/{software_id}/save", json={"applicant_profile_id": swe, "workflow": "software"})
    assert saved.status_code == 200
    result = client.post("/api/discovery/re-evaluate", json={"applicant_profile_id": swe, "workflow": "software"})
    assert result.status_code == 200
    assert result.get_json()["count"] == 1

    inbox = client.get(f"/api/discovery/inbox?candidate_profile_id={swe}&category=requalified&include_history=1&page_size=10")
    assert inbox.status_code == 200
    jobs = inbox.get_json()
    assert len(jobs) == 1
    assert jobs[0]["id"] == software_id
    assert jobs[0]["discovery_inbox_category"] == "requalified"
    assert jobs[0]["discovery_first_seen_at"] == original_seen


def test_qa_status_and_reset_are_isolated_and_visible(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_TRACKER_QA_MODE", "1")
    client = _isolated_client(tmp_path, monkeypatch)
    assert client.get("/api/qa/status").get_json()["active"] is True
    assert "Disposable QA" in client.get("/api/qa/status").get_json()["message"]
    assert client.post("/api/candidate-profiles", json={"name": "QA", "workflow": "software"}).status_code == 201
    assert client.post("/api/qa/reset").status_code == 200
    assert client.get("/api/candidate-profiles").get_json() == []
    monkeypatch.delenv("JOB_TRACKER_QA_MODE")
    assert client.post("/api/qa/reset").status_code == 403
