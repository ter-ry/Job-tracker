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


def test_ece_policy_is_full_time_title_based_and_keeps_supply_out_of_target():
    base = {"discovery_occupation": "early childhood educator", "discovery_search_mode": "title"}
    full_time = {**base, "title": "Registered Early Childhood Educator", "job_description": "Full-time permanent position in a licensed centre."}
    temporary = {**base, "title": "RECE Educator", "job_description": "Full-time temporary contract for the school year."}
    supply = {**base, "title": "Supply RECE Educator", "job_description": "Casual on-call supply coverage as needed."}
    part_time = {**base, "title": "Early Childhood Educator", "job_description": "Part-time only, weekday mornings."}
    eca = {**base, "title": "Early Childhood Assistant", "job_description": "Full-time permanent assistant role."}
    assert app_module.discovery_result_category(full_time)[0] == "actionable"
    assert app_module.discovery_result_category(temporary)[0] == "actionable"
    assert app_module.discovery_result_category(supply)[0] == "actionable"
    assert supply["discovery_employment_status"] == "supply_or_casual"
    assert app_module.discovery_result_category(part_time)[0] == "excluded"
    assert app_module.discovery_result_category(eca)[0] == "excluded"
    assert app_module.discovery_result_category({**base, "title": "Kindergarten Teacher", "job_description": "A school teaching role."})[0] == "review_required"
    assert app_module.discovery_result_category({**base, "title": "RECE / ECA Educator", "job_description": "Full-time classroom educator role."})[0] == "actionable"
    assert app_module.discovery_result_category({**base, "title": "ECE Supevisor", "job_description": "Full-time centre role."})[0] == "excluded"


def test_ece_search_config_uses_commute_origin_as_effective_location():
    config = app_module.discovery_search_config({
        "workflow": "ece", "keywords": "Registered Early Childhood Educator; RECE",
        "location": "an unrelated stale location",
        "distance_origin": "CF Fairview Mall, Toronto, ON", "distance": 20,
    })
    assert config["workflow"] == "ece"
    assert config["location"] == "CF Fairview Mall, Toronto, ON"
    assert config["distance_origin_input"] == config["location"]
    assert config["geographic_match_mode"] == "provisional"


def test_reconciliation_preview_apply_rollback_is_explicit_and_idempotent(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    client.get("/api/health")
    with app_module.app.app_context():
        first = app_module.normalize_job_payload({
            "source": "indeed", "source_job_id": "indeed-104-a", "company": "Alias Employer Inc.",
            "title": "Software Engineer", "location": "Toronto, ON",
            "url": "https://example.test/jobs/requisition-104?utm_source=indeed",
            "description": "Build and maintain software systems with Python, APIs, testing and production ownership. Coordinate delivery, documentation, and support for internal stakeholders." * 2,
            "discovery_first_seen_at": "2026-11-25T00:00:00", "discovery_result_category": "actionable",
        })
        second = app_module.normalize_job_payload({
            "source": "employer_direct", "source_job_id": "req-104", "company": "Alias Employer Inc.",
            "title": "Software Engineer", "location": "Toronto, ON",
            "url": "https://boards.example.test/roles/requisition-104",
            "description": "Build and maintain software systems with Python, APIs, testing and production ownership." * 3,
            "discovery_first_seen_at": "2026-11-25T00:00:00", "discovery_result_category": "actionable",
        })
        first_id = app_module.persist_discovery_jobs([first], None, None)["new_job_ids"][0]
        second_id = app_module.persist_discovery_jobs([second], None, None)["new_job_ids"][0]
    preview = client.get("/api/discovery/reconciliation/preview").get_json()
    assert preview["candidate_count"] == 1
    assert preview["mutated"] is False
    group_key = "group:" + ",".join(map(str, preview["candidates"][0]["job_ids"]))
    applied = client.post(f"/api/discovery/reconciliation/{preview['reconciliation_id']}/apply", json={"confirm": True, "confirmation_token": preview["confirmation_token"], "resolutions": {group_key: "merge"}})
    assert applied.status_code == 200
    with app_module.app.app_context():
        assert app_module.query_db("SELECT canonical_job_id FROM jobs WHERE id = ?", [second_id], one=True)["canonical_job_id"] == first_id
    again = client.post(f"/api/discovery/reconciliation/{preview['reconciliation_id']}/apply", json={"confirm": True, "confirmation_token": preview["confirmation_token"], "resolutions": {group_key: "merge"}}).get_json()
    assert again["idempotent"] is True
    rolled_back = client.post(f"/api/discovery/reconciliation/{preview['reconciliation_id']}/rollback")
    assert rolled_back.status_code == 200
    with app_module.app.app_context():
        assert app_module.query_db("SELECT canonical_job_id FROM jobs WHERE id = ?", [second_id], one=True)["canonical_job_id"] == 0


def test_effective_membership_criteria_survive_database_reopen(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    client.get("/api/health")
    with app_module.app.app_context():
        job = app_module.normalize_job_payload({
            "source": "fixture", "source_job_id": "criteria-1", "title": "Registered Early Childhood Educator",
            "company": "Criteria Centre", "location": "Toronto, ON", "url": "https://criteria.example/1",
            "description": "Full-time RECE position.", "discovery_first_seen_at": "2026-11-25T00:00:00",
            "discovery_result_category": "actionable", "discovery_occupation": "early childhood educator",
        })
        job_id = app_module.persist_discovery_jobs([job], None, None)["new_job_ids"][0]
        app_module.persist_discovery_search_memberships("c" * 32, [{**job, "id": job_id}], 27, {
            "workflow": "ece", "location": "Toronto, ON", "distance_origin_input": "M4P 1E4",
            "original_origin": "M4P 1E4", "distance": 20, "geographic_match_mode": "provisional",
            "enabled_sources": ["indeed", "employer_direct"], "match_policy": "strict_matching",
        })
    with app_module.app.app_context():
        row = app_module.query_db("SELECT applicant_profile_id, criteria_json FROM discovery_search_memberships WHERE search_execution_id = ?", ["c" * 32], one=True)
        criteria = app_module.parse_json_object(row["criteria_json"])
        assert int(row["applicant_profile_id"]) == 27
        assert criteria["workflow"] == "ece"
        assert criteria["distance_origin_input"] == "M4P 1E4"
        assert criteria["enabled_sources"] == ["indeed", "employer_direct"]


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
    policy = {"match_policy": "apply_broadly", "geographic_match_mode": "provisional", "distance": 20, "seniority": "entry_level,junior", "maximum_required_years": 3, "include_internships": False}
    preview = client.post("/api/discovery/re-evaluate", json={"applicant_profile_id": swe, "workflow": "software", **policy})
    assert preview.status_code == 200
    assert preview.get_json()["preview"] is True
    result = client.post("/api/discovery/re-evaluate", json={"applicant_profile_id": swe, "workflow": "software", "preview": False, "confirm_apply": True, "preview_token": preview.get_json()["preview_token"], **policy})
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
    preview = client.post("/api/discovery/re-evaluate", json={"applicant_profile_id": swe, "workflow": "software", "match_policy": "apply_broadly", "geographic_match_mode": "provisional", "distance": 20, "seniority": "entry_level,junior", "maximum_required_years": 3, "include_internships": False, "preview": True})
    assert preview.status_code == 200
    assert preview.get_json()["preview"] is True
    with app_module.app.app_context():
        after = dict(app_module.query_db("SELECT discovery_result_category, discovery_result_reason FROM jobs WHERE id = ?", [job_id], one=True))
    assert after == before
    audit = client.get(f"/api/discovery/inbox/audit?candidate_profile_id={swe}")
    assert audit.status_code == 200
    assert audit.get_json()["mutated"] is False
    assert audit.get_json()["total"] >= 1


def test_legacy_membership_requires_explicit_policy_and_reassesses_recall_first(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    swe = _profile(client, "SWE", "software")
    job_id = _stored_job(client, category="excluded", occupation="software developer")
    with app_module.app.app_context():
        app_module.get_db().execute(
            """INSERT INTO discovery_search_memberships
               (search_execution_id, job_id, applicant_profile_id, category, reason, evidence_json, criteria_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ["legacy-run", job_id, swe, "excluded", "Old strict-looking result", "{}", app_module.dumps_json({
                "keywords": "software developer; junior software engineer",
                "location": "m2j0b6", "location_scope": "Toronto, ON",
                "occupation": "software developer", "seniority": "entry_level,junior",
                "maximum_required_years": 3, "include_internships": True,
                "search_mode": "shortlist",
            })],
        )
        app_module.get_db().commit()
    missing_policy = client.post("/api/discovery/re-evaluate", json={"applicant_profile_id": swe, "workflow": "software"})
    assert missing_policy.status_code == 400
    policy = {"match_policy": "apply_broadly", "geographic_match_mode": "provisional", "distance": 20, "seniority": "entry_level,junior", "maximum_required_years": 3, "include_internships": True}
    preview = client.post("/api/discovery/re-evaluate", json={"applicant_profile_id": swe, "workflow": "software", **policy})
    assert preview.status_code == 200
    body = preview.get_json()
    assert body["effective_policy"]["match_policy"] == "apply_broadly"
    assert body["effective_policy"]["geographic_match_mode"] == "provisional"
    assert body["jobs"][0]["effective_policy"] == body["effective_policy"]
    with app_module.app.app_context():
        membership = app_module.query_db("SELECT criteria_json FROM discovery_search_memberships WHERE search_execution_id = ?", ["legacy-run"], one=True)
        assert "match_policy" not in app_module.parse_json_object(membership["criteria_json"])


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


def test_ready_to_apply_is_globally_ranked_before_pagination(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    swe = _profile(client, "SWE", "software")
    with app_module.app.app_context():
        ids = []
        for index, (title, score, level) in enumerate([
            ("Senior stretch", 95, "senior"),
            ("Junior opportunity", 70, "junior"),
            ("Intermediate opportunity", 80, "intermediate"),
        ]):
            job = app_module.normalize_job_payload({
                "source": "fixture", "source_job_id": f"ranked-{index}",
                "title": title, "company": "Ranking Co", "location": "Toronto, ON",
                "url": f"https://example.test/ranked-{index}",
                "description": "A software development position with requirements.",
                "discovery_first_seen_at": f"2026-01-0{index + 1}T00:00:00",
                "discovery_result_category": "actionable", "discovery_occupation": "software developer",
            })
            job.update({
                "discovery_first_seen_at": f"2026-01-0{index + 1}T00:00:00",
                "discovery_result_category": "actionable",
                "application_priority_score": score,
                "qualification_fit_seniority": {"detected_level": level, "score": 80},
            })
            ids.extend(app_module.persist_discovery_jobs([job], None, None)["new_job_ids"])
        app_module.get_db().commit()
    first = client.get(f"/api/discovery/inbox?candidate_profile_id={swe}&category=ready_to_apply&page_size=1&page=0")
    second = client.get(f"/api/discovery/inbox?candidate_profile_id={swe}&category=ready_to_apply&page_size=1&page=1")
    assert first.status_code == second.status_code == 200
    # Senior score is intentionally higher; the applicant-aware tier still
    # puts junior/intermediate opportunities ahead of weak stretch roles.
    assert first.get_json()[0]["title"] == "Junior opportunity"
    assert second.get_json()[0]["title"] == "Intermediate opportunity"
    assert first.headers["X-Job-Tracker-Total"] == "3"


def test_new_count_and_listing_reconcile_with_mixed_applicant_history(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    swe = _profile(client, "SWE", "software")
    with app_module.app.app_context():
        jobs = []
        for index in range(76):
            job = app_module.normalize_job_payload({
                "source": "fixture", "source_job_id": f"count-{index}",
                "title": f"Junior Software Developer {index}", "company": "Count Co",
                "location": "Toronto, ON", "url": f"https://count.example/{index}",
                "job_description": "A software developer posting with current responsibilities.",
            })
            job.update({"discovery_first_seen_at": "2026-01-01T00:00:00", "discovery_result_category": "actionable", "discovery_occupation": "software developer"})
            jobs.append(job)
        ids = app_module.persist_discovery_jobs(jobs, None, None)["new_job_ids"]
        for job_id in ids[47:]:
            app_module.get_db().execute("INSERT INTO discovery_applicant_presentations(job_id, applicant_profile_id) VALUES (?, ?)", [job_id, swe])
        app_module.get_db().commit()
    counts = client.get(f"/api/discovery/inbox/counts?candidate_profile_id={swe}").get_json()
    rows = client.get(f"/api/discovery/inbox?candidate_profile_id={swe}&category=new_actionable&include_history=1").get_json()
    assert counts["new_actionable"] == 47
    assert len(rows) == counts["new_actionable"]
    assert {row["id"] for row in rows} == set(ids[:47])


def test_applications_and_inbox_share_selected_applicant_applied_state(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    swe = _profile(client, "SWE", "software")
    ece = _profile(client, "ECE", "ece")
    job_id = _stored_job(client, occupation="software developer")

    applied = client.post(f"/api/jobs/{job_id}/applied", json={"candidate_profile_id": swe, "date_applied": "2026-11-19"})
    assert applied.status_code == 200
    assert applied.get_json()["applicant_status"] == "Applied"
    # The shared job remains a source record; the other applicant has no
    # Applied decision and therefore cannot inherit SWE's lifecycle state.
    swe_jobs = client.get(f"/api/jobs?candidate_profile_id={swe}").get_json()
    ece_jobs = client.get(f"/api/jobs?candidate_profile_id={ece}").get_json()
    assert next(job for job in swe_jobs if job["id"] == job_id)["status"] == "Applied"
    assert next(job for job in ece_jobs if job["id"] == job_id)["status"] != "Applied"
    applied_history = client.get(f"/api/discovery/inbox?candidate_profile_id={swe}&category=applied&include_history=1")
    assert applied_history.status_code == 200
    assert [job["id"] for job in applied_history.get_json()] == [job_id]
    assert client.get(f"/api/discovery/inbox?candidate_profile_id={ece}&category=applied&include_history=1").get_json() == []
    # A reload reads the durable applicant state rather than a frontend cache.
    with app_module.app.app_context():
        app_module.get_db().close()
        app_module.g.pop("db", None)
    assert next(job for job in client.get(f"/api/jobs?candidate_profile_id={swe}").get_json() if job["id"] == job_id)["applicant_status"] == "Applied"


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
    with app_module.app.app_context():
        app_module.get_db().close()
        app_module.g.pop("db", None)
    assert len(client.get(f"/api/applications/duplicate-matches?candidate_profile_id={swe}").get_json()) == 1
    released = client.post(f"/api/applications/duplicate-matches/{match_id}/resolve", json={"candidate_profile_id": swe, "resolution": "different_vacancy"})
    assert released.status_code == 200
    assert client.get(f"/api/discovery/inbox/counts?candidate_profile_id={swe}").get_json()["ready_to_apply"] == 1
    with app_module.app.app_context():
        imported = app_module.query_db("SELECT id, possible_duplicate_job_id FROM jobs WHERE url = ?", ["https://example.test/imported"], one=True)
        assert imported["possible_duplicate_job_id"] == original_id
        imported_state = app_module.query_db("SELECT state, date_applied FROM discovery_applicant_states WHERE job_id = ? AND applicant_profile_id = ?", [int(imported["id"]), swe], one=True)
        assert dict(imported_state) == {"state": "applied", "date_applied": "2026-02-03"}
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


def test_csv_duplicate_matches_keep_each_row_source_identity_and_location(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    swe = _profile(client, "SWE", "software")
    with app_module.app.app_context():
        for index, company in enumerate(("CSV One", "CSV Two"), start=1):
            original = app_module.normalize_job_payload({
                "source": "indeed", "source_job_id": f"original-{index}", "title": "Software Developer",
                "company": company, "location": "Toronto, ON", "url": f"https://example.test/original-{index}",
                "description": "A complete software development posting with requirements and responsibilities for applicants.",
            })
            original.update({"discovery_first_seen_at": "2026-01-01T00:00:00", "discovery_result_category": "actionable", "discovery_occupation": "software developer"})
            assert app_module.persist_discovery_jobs([original], None, None)["new_job_ids"]
    csv_text = "url,company,title,date_applied,provider,requisition_id,location\nhttps://example.test/import-1,CSV One,Software Developer,2026-03-01,greenhouse,GH-1,Ottawa ON\nhttps://example.test/import-2,CSV Two,Software Developer,2026-03-02,workday,WD-2,Montreal QC\n"
    response = client.post("/api/applications/import-history", json={"candidate_profile_id": swe, "workflow": "software", "csv": csv_text, "preview": False, "confirm_apply": True})
    assert response.status_code == 200
    matches = client.get(f"/api/applications/duplicate-matches?candidate_profile_id={swe}").get_json()
    assert sorted((item["evidence"]["source"], item["evidence"]["source_job_id"], item["evidence"]["location"]) for item in matches) == [
        ("greenhouse", "GH-1", "Ottawa ON"), ("workday", "WD-2", "Montreal QC")
    ]


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
