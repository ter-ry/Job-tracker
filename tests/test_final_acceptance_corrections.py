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
            "company": "Acceptance Centre", "location": "Toronto, ON", "url": f"https://example.test/acceptance-{occupation}",
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
    assert "stored discovery is a SOFTWARE job" in wrong.get_json()["error"]
    assert client.post(f"/api/discovery/inbox/{job_id}/save", json={"applicant_profile_id": ece, "workflow": "software"}).status_code == 400

    unknown = client.post(f"/api/discovery/inbox/{job_id}/save", json={"applicant_profile_id": 99999, "workflow": "software"})
    assert unknown.status_code == 400

    cross_workflow_omitted = client.post(f"/api/discovery/inbox/{job_id}/save", json={"applicant_profile_id": ece})
    assert cross_workflow_omitted.status_code == 400
    ece_job_id = _stored_job(client, occupation="early childhood educator")
    inferred = client.post(f"/api/discovery/inbox/{ece_job_id}/save", json={"applicant_profile_id": ece})
    assert inferred.status_code == 200
    assert client.post(f"/api/discovery/inbox/{ece_job_id}/save", json={"applicant_profile_id": swe, "workflow": "ece"}).status_code == 400
    review_wrong = client.post(f"/api/discovery/inbox/{job_id}/review", json={"applicant_profile_id": swe, "workflow": "ece"})
    assert review_wrong.status_code == 400


def test_re_evaluate_is_occupation_scoped_and_preserves_history(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    swe = _profile(client, "SWE", "software")
    software_id = _stored_job(client, occupation="software developer")
    _stored_job(client, occupation="early childhood educator")
    with app_module.app.app_context():
        app_module.get_db().execute(
            "UPDATE jobs SET job_description = ? WHERE id = ?",
            ["This complete posting describes a software development role, its responsibilities, required technologies, workplace evidence and compensation details for a current applicant.", software_id],
        )
        app_module.get_db().commit()
    with app_module.app.app_context():
        original_seen = app_module.query_db("SELECT discovery_first_seen_at FROM jobs WHERE id = ?", [software_id], one=True)["discovery_first_seen_at"]

    saved = client.post(f"/api/discovery/inbox/{software_id}/save", json={"applicant_profile_id": swe, "workflow": "software"})
    assert saved.status_code == 200
    preview = client.post("/api/discovery/re-evaluate", json={"applicant_profile_id": swe, "workflow": "software"})
    assert preview.status_code == 200
    assert preview.get_json()["preview"] is True
    result = client.post("/api/discovery/re-evaluate", json={"applicant_profile_id": swe, "workflow": "software", "preview": False, "confirm_apply": True, "preview_token": preview.get_json()["preview_token"]})
    assert result.status_code == 200
    assert result.get_json()["preview"] is False

    inbox = client.get(f"/api/discovery/inbox?candidate_profile_id={swe}&category=requalified&include_history=1&page_size=10")
    assert inbox.status_code == 200
    jobs = inbox.get_json()
    assert len(jobs) == 1
    assert jobs[0]["id"] == software_id
    assert jobs[0]["discovery_inbox_category"] == "requalified"
    assert jobs[0]["discovery_first_seen_at"] == original_seen


def test_history_reassessment_preview_and_audit_are_non_mutating(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    swe = _profile(client, "SWE", "software")
    job_id = _stored_job(client, occupation="software developer")
    with app_module.app.app_context():
        before = dict(app_module.query_db("SELECT discovery_result_category, discovery_result_reason FROM jobs WHERE id = ?", [job_id], one=True))
    preview = client.post("/api/discovery/re-evaluate", json={"applicant_profile_id": swe, "workflow": "software", "preview": True})
    assert preview.status_code == 200
    assert preview.get_json()["preview"] is True
    with app_module.app.app_context():
        after = dict(app_module.query_db("SELECT discovery_result_category, discovery_result_reason FROM jobs WHERE id = ?", [job_id], one=True))
    assert after == before
    audit = client.get(f"/api/discovery/inbox/audit?candidate_profile_id={swe}")
    assert audit.status_code == 200
    assert audit.get_json()["mutated"] is False
    assert audit.get_json()["total"] >= 1


def test_ready_to_apply_excludes_applications_but_keeps_seen_unapplied(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    swe = _profile(client, "SWE", "software")
    with app_module.app.app_context():
        jobs = []
        for index in range(3):
            job = app_module.normalize_job_payload({
                "source": "fixture", "source_job_id": f"ready-{index}",
                "title": f"Software Developer {index}", "company": "Ready Co",
                "location": "Toronto, ON", "url": f"https://example.test/ready-{index}",
                "description": "A software development position with source evidence and current responsibilities.",
                "discovery_first_seen_at": "2026-01-01T00:00:00",
                "discovery_result_category": "actionable", "discovery_occupation": "software developer",
            })
            job.update({"discovery_first_seen_at": "2026-01-01T00:00:00", "discovery_result_category": "actionable", "discovery_occupation": "software developer"})
            jobs.append(job)
        ids = app_module.persist_discovery_jobs(jobs, None, None)["new_job_ids"]
        app_module.get_db().execute("INSERT INTO discovery_applicant_presentations(job_id, applicant_profile_id) VALUES (?, ?)", [ids[0], swe])
        app_module.set_applicant_discovery_state(ids[1], swe, "applied", "2026-01-02")
        app_module.get_db().commit()
    new_rows = client.get(f"/api/discovery/inbox?candidate_profile_id={swe}&category=new_actionable&include_history=1").get_json()
    ready_rows = client.get(f"/api/discovery/inbox?candidate_profile_id={swe}&category=ready_to_apply&include_history=1").get_json()
    assert [row["id"] for row in new_rows] == [ids[2]]
    assert {row["id"] for row in ready_rows} == {ids[0], ids[2]}
    assert all(row["id"] != ids[1] for row in ready_rows)
    counts = client.get(f"/api/discovery/inbox/counts?candidate_profile_id={swe}").get_json()
    assert counts["new_actionable"] == 1
    assert counts["ready_to_apply"] == 2


def test_historical_application_import_is_preview_first_and_durable(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    swe = _profile(client, "SWE", "software")
    with app_module.app.app_context():
        existing = app_module.normalize_job_payload({
            "source": "indeed", "source_job_id": "known-apply", "title": "Software Engineer",
            "company": "Known Co", "location": "Toronto, ON", "url": "https://example.test/known-apply",
            "description": "A complete software engineering posting with responsibilities and requirements for applicants.",
        })
        existing.update({"discovery_first_seen_at": "2026-01-01T00:00:00", "discovery_result_category": "actionable", "discovery_occupation": "software developer"})
        existing_id = app_module.persist_discovery_jobs([existing], None, None)["new_job_ids"][0]
    payload = {"candidate_profile_id": swe, "workflow": "software", "records": [
        {"url": "https://example.test/known-apply", "company": "Known Co", "title": "Software Engineer", "date_applied": "2026-01-10"},
        {"url": "https://example.test/new-apply", "company": "New Co", "title": "Junior Developer", "date_applied": "2026-01-11"},
        {"url": "https://example.test/possible", "company": "Known Co", "title": "Software Engineer", "date_applied": "2026-01-12"},
        {"url": "not-a-url", "company": "Bad", "title": "Missing", "date_applied": "2026-01-12"},
    ]}
    preview = client.post("/api/applications/import-history", json=payload)
    assert preview.status_code == 200
    assert preview.get_json()["preview"] is True
    assert preview.get_json()["counts"] == {"matched_existing": 1, "new_imported": 1, "possible_duplicate": 1, "invalid": 1}
    with app_module.app.app_context():
        assert app_module.query_db("SELECT 1 FROM discovery_applicant_states WHERE job_id = ? AND applicant_profile_id = ?", [existing_id, swe], one=True) is None
    applied = client.post("/api/applications/import-history", json={**payload, "preview": False, "confirm_apply": True})
    assert applied.status_code == 200
    assert applied.get_json()["counts"]["matched_existing"] == 1
    with app_module.app.app_context():
        state = app_module.query_db("SELECT state, date_applied FROM discovery_applicant_states WHERE job_id = ? AND applicant_profile_id = ?", [existing_id, swe], one=True)
        assert dict(state) == {"state": "applied", "date_applied": "2026-01-10"}
        imported = app_module.query_db("SELECT id FROM jobs WHERE url = ?", ["https://example.test/new-apply"], one=True)
        assert imported is not None
    assert client.get(f"/api/discovery/inbox?candidate_profile_id={swe}&category=ready_to_apply&include_history=1").get_json() == []


def test_qa_status_and_reset_are_isolated_and_visible(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_TRACKER_QA_MODE", "1")
    client = _isolated_client(tmp_path, monkeypatch)
    assert client.get("/api/qa/status").get_json()["active"] is True
    assert "Disposable QA" in client.get("/api/qa/status").get_json()["message"]
    assert client.post("/api/candidate-profiles", json={"name": "QA", "workflow": "software"}).status_code == 201
    with app_module.app.app_context():
        app_module.get_db().execute("INSERT INTO discovery_async_searches(search_id, status) VALUES ('qa-active', 'running')")
        app_module.get_db().commit()
    assert client.post("/api/qa/reset").status_code == 409
    with app_module.app.app_context():
        app_module.get_db().execute("UPDATE discovery_async_searches SET status = 'completed' WHERE search_id = 'qa-active'")
        app_module.get_db().commit()
    assert client.post("/api/qa/reset").status_code == 200
    assert client.get("/api/candidate-profiles").get_json() == []
    monkeypatch.delenv("JOB_TRACKER_QA_MODE")
    assert client.post("/api/qa/reset").status_code == 403


def test_async_seen_requires_matching_applicant_and_rejects_forged_ids(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    swe = _profile(client, "SWE", "software")
    ece = _profile(client, "ECE", "ece")
    with app_module.app.app_context():
        job = app_module.normalize_job_payload({"source": "fixture", "source_job_id": "seen-owner", "title": "Junior Software Developer", "company": "Example", "location": "Toronto, ON", "job_url": "https://example.test/seen-owner"})
        job_id = app_module.persist_discovery_jobs([job], None, None)["new_job_ids"][0]
        event = {**job, "id": job_id, "result_stage": "qualified", "discovery_result_category": "actionable"}
        app_module.get_db().execute(
            "INSERT INTO discovery_async_searches(search_id, applicant_profile_id, search_json, results_json, next_sequence) VALUES (?, ?, ?, ?, ?)",
            ["seen-owner-search", swe, app_module.dumps_json({"keywords": "software developer", "location": "Toronto, ON", "workflow": "software", "applicant_profile_id": swe}), app_module.dumps_json([event]), 1],
        )
        app_module.get_db().commit()
    assert client.post("/api/discovery/searches/seen-owner-search/delivered", json={"applicant_profile_id": ece, "job_ids": [job_id]}).status_code == 403
    assert client.post("/api/discovery/searches/seen-owner-search/delivered", json={"job_ids": [job_id]}).status_code == 400
    matching = client.post("/api/discovery/searches/seen-owner-search/delivered", json={"applicant_profile_id": swe, "workflow": "software", "job_ids": [job_id, 999999]}).get_json()
    assert matching["acknowledged"] == 1
