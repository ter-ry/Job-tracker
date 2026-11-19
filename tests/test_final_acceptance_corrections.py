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
        possible_existing = dict(existing)
        possible_existing.update({"source": "workday", "source_job_id": "possible-original", "company": "Possible Co", "url": "https://example.test/possible-original", "application_url": "https://example.test/possible-original", "source_links_json": "[]"})
        possible_existing_id = app_module.persist_discovery_jobs([possible_existing], None, None)["new_job_ids"][0]
    payload = {"candidate_profile_id": swe, "workflow": "software", "records": [
        {"url": "https://example.test/known-apply", "company": "Known Co", "title": "Software Engineer", "date_applied": "2026-01-10"},
        {"url": "https://example.test/new-apply", "company": "New Co", "title": "Junior Developer", "date_applied": "2026-01-11"},
        {"url": "https://example.test/possible", "company": "Possible Co", "title": "Software Engineer", "date_applied": "2026-01-12"},
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
        held = app_module.query_db("SELECT possible_duplicate, possible_duplicate_job_id, discovery_result_category FROM jobs WHERE url = ?", ["https://example.test/possible"], one=True)
        assert dict(held) == {"possible_duplicate": 1, "possible_duplicate_job_id": possible_existing_id, "discovery_result_category": "review_required"}
        pending = app_module.query_db("SELECT existing_job_id, applicant_profile_id, application_date, status FROM discovery_applicant_duplicate_matches WHERE imported_job_id = (SELECT id FROM jobs WHERE url = ?)", ["https://example.test/possible"], one=True)
        assert dict(pending) == {"existing_job_id": possible_existing_id, "applicant_profile_id": swe, "application_date": "2026-01-12", "status": "pending"}
        assert client.get(f"/api/discovery/inbox/counts?candidate_profile_id={swe}").get_json()["pending_duplicate"] == 1
    assert client.get(f"/api/discovery/inbox?candidate_profile_id={swe}&category=ready_to_apply&include_history=1").get_json() == []


def test_possible_duplicate_import_is_held_and_ats_identity_keeps_case(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    swe = _profile(client, "SWE", "software")
    with app_module.app.app_context():
        first = app_module.normalize_job_payload({
            "source": "indeed", "source_job_id": "ReqABC", "title": "Software Engineer",
            "company": "Identity Co", "location": "Toronto, ON", "url": "https://jobs.example/ReqABC",
            "description": "A complete software engineering posting with requirements and responsibilities.",
        })
        first.update({"discovery_first_seen_at": "2026-01-01T00:00:00", "discovery_result_category": "actionable", "discovery_occupation": "software developer"})
        first_id = app_module.persist_discovery_jobs([first], None, None)["new_job_ids"][0]
        second = dict(first)
        second.update({"source": "glassdoor", "source_job_id": "reqabc", "url": "https://jobs.example/reqabc", "application_url": "", "source_links_json": app_module.dumps_json(["https://jobs.example/reqabc"])})
        assert app_module.find_existing_job_match(second) is None
        employer = dict(first)
        employer.update({"source": "employer_direct", "source_job_id": "", "url": "https://careers.example/jobs/ReqABC"})
        employer["source_links_json"] = app_module.dumps_json(["https://jobs.example/ReqABC", "https://careers.example/jobs/ReqABC"])
        assert app_module.find_existing_job_match(employer)["id"] == first_id
        app_module.persist_discovery_jobs([employer], None, None)
        app_module.get_db().commit()
    with app_module.app.app_context():
        app_module.get_db().close()
        app_module.g.pop("db", None)
        reloaded = app_module.find_existing_job_match({"source": "employer_direct", "url": "https://careers.example/jobs/ReqABC", "title": "Software Engineer", "company": "Identity Co", "location": "Toronto, ON"})
        assert reloaded["id"] == first_id

def test_possible_duplicate_resolution_is_applicant_scoped_and_releases_without_merge(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    swe = _profile(client, "SWE", "software")
    other = _profile(client, "Other", "software")
    with app_module.app.app_context():
        original = app_module.normalize_job_payload({
            "source": "indeed", "source_job_id": "actionable-original", "title": "Backend Developer",
            "company": "Resolution Co", "location": "Toronto, ON", "url": "https://example.test/original",
            "description": "A complete backend development posting with requirements and responsibilities for applicants.",
        })
        original.update({"discovery_first_seen_at": "2026-01-01T00:00:00", "discovery_result_category": "actionable", "discovery_occupation": "software developer"})
        original_id = app_module.persist_discovery_jobs([original], None, None)["new_job_ids"][0]
    payload = {"candidate_profile_id": swe, "workflow": "software", "preview": False, "confirm_apply": True, "records": [{
        "url": "https://example.test/imported", "company": "Resolution Co", "title": "Backend Developer", "date_applied": "2026-02-03"
    }]}
    assert client.post("/api/applications/import-history", json=payload).get_json()["counts"] == {"possible_duplicate": 1}
    pending = client.get(f"/api/applications/duplicate-matches?candidate_profile_id={swe}").get_json()
    assert len(pending) == 1
    match_id = pending[0]["id"]
    before = client.get(f"/api/discovery/inbox/counts?candidate_profile_id={swe}").get_json()
    assert before["new_actionable"] == 0 and before["ready_to_apply"] == 0 and before["pending_duplicate"] == 1
    assert client.get(f"/api/discovery/inbox/counts?candidate_profile_id={other}").get_json()["ready_to_apply"] == 1
    released = client.post(f"/api/applications/duplicate-matches/{match_id}/resolve", json={"candidate_profile_id": swe, "resolution": "different_vacancy"})
    assert released.status_code == 200
    assert client.get(f"/api/discovery/inbox/counts?candidate_profile_id={swe}").get_json()["ready_to_apply"] == 1
    with app_module.app.app_context():
        imported = app_module.query_db("SELECT id, possible_duplicate_job_id FROM jobs WHERE url = ?", ["https://example.test/imported"], one=True)
        assert imported["possible_duplicate_job_id"] == original_id
        assert app_module.query_db("SELECT status FROM discovery_applicant_duplicate_matches WHERE id = ?", [match_id], one=True)["status"] == "resolved_different"
        second = dict(original)
        second.update({"source_job_id": "actionable-second", "company": "Same Co", "url": "https://example.test/second", "application_url": "https://example.test/second", "source_links_json": "[]"})
        second_id = app_module.persist_discovery_jobs([second], None, None)["new_job_ids"][0]
    same_payload = {"candidate_profile_id": swe, "workflow": "software", "preview": False, "confirm_apply": True, "records": [{
        "url": "https://example.test/same-import", "company": "Same Co", "title": "Backend Developer", "date_applied": "2026-02-04"
    }]}
    client.post("/api/applications/import-history", json=same_payload)
    same_match = client.get(f"/api/applications/duplicate-matches?candidate_profile_id={swe}").get_json()[0]
    assert client.post(f"/api/applications/duplicate-matches/{same_match['id']}/resolve", json={"candidate_profile_id": swe, "resolution": "same_vacancy"}).status_code == 200
    with app_module.app.app_context():
        state = app_module.query_db("SELECT state, date_applied FROM discovery_applicant_states WHERE job_id = ? AND applicant_profile_id = ?", [second_id, swe], one=True)
        assert dict(state) == {"state": "applied", "date_applied": "2026-02-04"}


def test_history_audit_export_is_read_only_and_resume_free(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    swe = _profile(client, "SWE", "software")
    _stored_job(client, occupation="software developer")
    response = client.get(f"/api/discovery/inbox/audit/export?candidate_profile_id={swe}")
    assert response.status_code == 200
    assert response.headers["Content-Disposition"].startswith("attachment;")
    payload = response.get_json()
    assert payload["mutated"] is False
    assert payload["total"] == 1
    assert "resume_text" not in payload["records"][0]
    assert "source_excerpt" in payload["records"][0]


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
