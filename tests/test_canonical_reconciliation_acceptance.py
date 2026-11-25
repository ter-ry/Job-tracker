import json
import time
from pathlib import Path

import app as app_module


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", Path(tmp_path))
    monkeypatch.setattr(app_module, "DB_PATH", Path(tmp_path) / "canonical.sqlite")
    monkeypatch.setattr(app_module, "_INITIALIZED_DATABASE_PATH", None)
    client = app_module.app.test_client()
    client.get("/api/health")
    return client


def _profile(client, name):
    response = client.post("/api/candidate-profiles", json={"name": name, "workflow": "software"})
    assert response.status_code == 201
    return response.get_json()["id"]


def _job(source, source_job_id, *, company="Affirm Inc.", title="Software Engineer", location="Toronto, ON", url=None, description=None):
    return app_module.normalize_job_payload({
        "source": source,
        "source_job_id": source_job_id,
        "company": company,
        "title": title,
        "location": location,
        "url": url or f"https://{source}.example/jobs/{source_job_id}",
        "description": description or ("Build reliable software systems with Python, APIs, testing, deployment, and production ownership. " * 4),
        "discovery_first_seen_at": "2026-11-25T00:00:00",
        "discovery_result_category": "actionable",
    })


def _insert_raw(job):
    clean = {column: job.get(column, "") for column in app_module.JOB_COLUMNS}
    clean.update({"status": "Discovered", "discovery_first_seen_at": "2026-11-25T00:00:00", "discovery_last_seen_at": "2026-11-25T00:00:00", "discovery_seen_count": 1, "discovery_state": "new"})
    for key, value in list(clean.items()):
        if isinstance(value, (dict, list, tuple)):
            clean[key] = app_module.dumps_json(value, sort_keys=True)
    db = app_module.get_db()
    cursor = db.execute(f"INSERT INTO jobs ({', '.join(app_module.JOB_COLUMNS)}) VALUES ({','.join('?' for _ in app_module.JOB_COLUMNS)})", [clean[column] for column in app_module.JOB_COLUMNS])
    job_id = int(cursor.lastrowid)
    app_module.sync_job_source_aliases(db, job_id, clean)
    db.commit()
    return job_id


def _preview(client):
    response = client.get("/api/discovery/reconciliation/preview")
    assert response.status_code == 200
    return response.get_json()


def _apply(client, preview, resolutions=None):
    return client.post(f"/api/discovery/reconciliation/{preview['reconciliation_id']}/apply", json={
        "confirm": True,
        "confirmation_token": preview["confirmation_token"],
        "resolutions": resolutions or {},
    })


def test_A_B_N_future_acquisition_is_one_opportunity_and_preserves_skip(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    profile = _profile(client, "Applicant 1")
    with app_module.app.app_context():
        first = _job("Indeed", "indeed-aff-1")
        first_id = app_module.persist_discovery_jobs([first], None, None)["new_job_ids"][0]
        app_module.set_applicant_discovery_state(first_id, profile, "skipped")
        app_module.get_db().commit()
        second = _job("Glassdoor", "glassdoor-aff-1")
        result = app_module.persist_discovery_jobs([second], None, None)
        assert result["new"] == 0
        assert result["duplicate"] == 1
        assert app_module.query_db("SELECT COUNT(*) AS n FROM jobs", one=True)["n"] == 1
        assert app_module.query_db("SELECT state FROM discovery_applicant_states WHERE job_id = ? AND applicant_profile_id = ?", [first_id, profile], one=True)["state"] == "skipped"
        assert app_module.query_db("SELECT COUNT(*) AS n FROM job_source_aliases WHERE job_id = ?", [first_id], one=True)["n"] >= 2


def test_C_D_E_P_decisions_transfer_independently_and_applied_never_ready(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    applicant_one = _profile(client, "Applicant 1")
    applicant_two = _profile(client, "Applicant 2")
    with app_module.app.app_context():
        indeed_id = _insert_raw(_job("Indeed", "indeed-amazon-1", company="Amazon Web Services"))
        glassdoor_id = _insert_raw(_job("Glassdoor", "glassdoor-amazon-1", company="Amazon"))
        app_module.set_applicant_discovery_state(glassdoor_id, applicant_one, "applied", "2026-11-20")
        app_module.set_applicant_discovery_state(indeed_id, applicant_two, "saved")
        app_module.get_db().commit()
    preview = _preview(client)
    assert preview["candidate_count"] == 1
    applied = _apply(client, preview)
    assert applied.status_code == 200, applied.get_json()
    with app_module.app.app_context():
        assert app_module.query_db("SELECT canonical_job_id FROM jobs WHERE id = ?", [glassdoor_id], one=True)["canonical_job_id"] == indeed_id
        states = app_module.query_db("SELECT applicant_profile_id, state FROM discovery_applicant_states WHERE job_id = ? ORDER BY applicant_profile_id", [indeed_id])
        assert {(int(row["applicant_profile_id"]), row["state"]) for row in states} == {(applicant_one, "applied"), (applicant_two, "saved")}
    counts = client.get(f"/api/discovery/inbox/counts?candidate_profile_id={applicant_one}").get_json()
    assert counts["applied"] == 1 and counts["ready_to_apply"] == 0


def test_F_K_conflicts_and_stale_confirmation_are_explicit(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    profile = _profile(client, "Conflict Applicant")
    with app_module.app.app_context():
        left = _insert_raw(_job("Indeed", "indeed-conflict-1", company="Microsoft"))
        right = _insert_raw(_job("Glassdoor", "glassdoor-conflict-1", company="Microsoft"))
        app_module.set_applicant_discovery_state(left, profile, "saved")
        app_module.set_applicant_discovery_state(right, profile, "skipped")
        app_module.get_db().commit()
    preview = _preview(client)
    assert preview["candidates"][0]["decision_conflicts"]
    rejected = _apply(client, preview)
    assert rejected.status_code == 409
    with app_module.app.app_context():
        app_module.set_applicant_discovery_state(left, profile, "applied", "2026-11-25")
        app_module.get_db().commit()
    stale = _apply(client, preview)
    assert stale.status_code == 409 and stale.get_json()["stale"] is True


def test_F_conflict_resolution_requires_a_real_state_and_preserves_applied(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    profile = _profile(client, "Resolution Applicant")
    with app_module.app.app_context():
        left = _insert_raw(_job("Indeed", "indeed-resolution-1", company="TD"))
        right = _insert_raw(_job("Glassdoor", "glassdoor-resolution-1", company="TD"))
        app_module.set_applicant_discovery_state(left, profile, "applied", "2026-11-25")
        app_module.set_applicant_discovery_state(right, profile, "saved")
        app_module.get_db().commit()
    preview = _preview(client)
    conflict = preview["candidates"][0]["decision_conflicts"][0]
    group_key = "group:" + ",".join(map(str, preview["candidates"][0]["job_ids"]))
    rejected = _apply(client, preview, {group_key: "merge", conflict["conflict_key"]: "saved"})
    assert rejected.status_code == 409
    applied = _apply(client, preview, {group_key: "merge", conflict["conflict_key"]: "applied"})
    assert applied.status_code == 200
    with app_module.app.app_context():
        assert app_module.query_db("SELECT state FROM discovery_applicant_states WHERE job_id = ? AND applicant_profile_id = ?", [left, profile], one=True)["state"] == "applied"


def test_G_J_three_sources_aliases_form_one_group_without_cycles(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    description = "Deliver platform software, APIs, tests, observability, and production support for customers. " * 5
    with app_module.app.app_context():
        ids = [_insert_raw(_job(source, f"{source}-yuja-1", company=company, description=description)) for source, company in [("Indeed", "YuJa Inc."), ("Glassdoor", "YuJa"), ("Employer Direct", "YuJa Corporation")]]
    preview = _preview(client)
    assert preview["candidate_count"] == 1
    assert set(preview["candidates"][0]["sources"]) == {"Indeed", "Glassdoor", "Employer Direct"}
    applied = _apply(client, preview)
    assert applied.status_code == 200
    with app_module.app.app_context():
        assert app_module.query_db("SELECT COUNT(*) AS n FROM jobs WHERE canonical_job_id = ?", [ids[0]], one=True)["n"] == 2
        assert app_module.query_db("SELECT COUNT(*) AS n FROM jobs WHERE canonical_job_id = id", one=True)["n"] == 0


def test_H_I_distinct_requisitions_and_workplaces_remain_separate(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    generic = "Join our team and contribute to a collaborative workplace with excellent communication and problem solving. " * 4
    with app_module.app.app_context():
        _insert_raw(_job("Indeed", "req-101", description=generic))
        _insert_raw(_job("Glassdoor", "req-202", description=generic))
        _insert_raw(_job("Employer Direct", "req-303", location="Ottawa, ON", description=generic))
    preview = _preview(client)
    assert preview["candidate_count"] == 0


def test_M_L_rollback_restores_relationship_and_decisions_without_losing_later_change(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    profile = _profile(client, "Rollback Applicant")
    with app_module.app.app_context():
        canonical = _insert_raw(_job("Indeed", "indeed-rbc-1", company="RBC"))
        duplicate = _insert_raw(_job("Glassdoor", "glassdoor-rbc-1", company="RBC"))
        app_module.set_applicant_discovery_state(duplicate, profile, "saved")
        app_module.get_db().execute("INSERT INTO discovery_search_memberships(search_execution_id, job_id, applicant_profile_id, category) VALUES (?, ?, ?, ?)", ["rollback-search", duplicate, profile, "actionable"])
        app_module.get_db().execute("INSERT INTO discovery_applicant_presentations(job_id, applicant_profile_id) VALUES (?, ?)", [duplicate, profile])
        app_module.get_db().commit()
    preview = _preview(client)
    assert _apply(client, preview).status_code == 200
    with app_module.app.app_context():
        app_module.set_applicant_discovery_state(canonical, profile, "applied", "2026-11-25")
        app_module.get_db().commit()
    rolled = client.post(f"/api/discovery/reconciliation/{preview['reconciliation_id']}/rollback")
    assert rolled.status_code == 200
    with app_module.app.app_context():
        assert app_module.query_db("SELECT canonical_job_id FROM jobs WHERE id = ?", [duplicate], one=True)["canonical_job_id"] == 0
        assert app_module.query_db("SELECT state FROM discovery_applicant_states WHERE job_id = ? AND applicant_profile_id = ?", [canonical, profile], one=True)["state"] == "applied"
        assert app_module.query_db("SELECT 1 FROM discovery_search_memberships WHERE search_execution_id = ? AND job_id = ?", ["rollback-search", canonical], one=True) is None
        assert app_module.query_db("SELECT 1 FROM discovery_applicant_presentations WHERE job_id = ? AND applicant_profile_id = ?", [canonical, profile], one=True) is None


def test_G_bridge_identity_is_contradictory_and_cannot_be_merged_transitively(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    common = "Build software platforms, APIs, automated tests, deployment tooling, and production support. " * 5
    with app_module.app.app_context():
        # A-B share a requisition signal and B-C share a description signal;
        # A-C has a contradictory requisition and must not form a chain.
        _insert_raw(_job("Indeed", "req-bridge-a", company="SalesJack", url="https://boards.example/common-a", description=common))
        middle = _insert_raw(_job("Glassdoor", "req-bridge-a", company="SalesJack", url="https://boards.example/common-a", description=common))
        last = _insert_raw(_job("Employer Direct", "req-bridge-c", company="SalesJack", url="https://boards.example/common-c", description=common))
        app_module.get_db().execute("UPDATE jobs SET source_links_json = ? WHERE id = ?", [json.dumps(["https://boards.example/common-a", "https://boards.example/common-c"]), middle])
        app_module.get_db().commit()
    preview = _preview(client)
    assert preview["candidate_count"] == 1
    assert preview["candidates"][0]["identity_status"] == "contradictory"
    assert _apply(client, preview, {"group:" + ",".join(map(str, preview["candidates"][0]["job_ids"])): "merge"}).status_code == 409


def test_O_uncertain_candidates_are_review_only_and_M_is_idempotent(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    with app_module.app.app_context():
        _insert_raw(_job("Indeed", "affirm-uncertain-1", company="HOOPP", description="A general role with communication and collaboration responsibilities." * 3))
        _insert_raw(_job("Glassdoor", "affirm-uncertain-2", company="HOOPP", description="A different role with communication and collaboration responsibilities." * 3))
    preview = _preview(client)
    assert preview["candidate_count"] == 1 and preview["candidates"][0]["requires_review"] is True
    rejected = _apply(client, preview)
    assert rejected.status_code == 409
    key = "group:" + ",".join(map(str, preview["candidates"][0]["job_ids"]))
    applied = _apply(client, preview, {key: "merge"})
    assert applied.status_code == 200
    assert _apply(client, preview, {key: "merge"}).get_json()["idempotent"] is True


def test_Q_candidate_generation_is_bounded_for_10000_mixed_records(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    with app_module.app.app_context():
        db = app_module.get_db()
        rows = []
        for index in range(10000):
            source = ("Indeed", "Glassdoor", "Employer Direct")[index % 3]
            title = f"Role {index}"
            company = f"Company {index}"
            rows.append((company, title, "Toronto, ON", f"https://{source}.example/{index}", source, f"id-{index}", "Generic posting description." * 4, "2026-11-25T00:00:00", "actionable"))
        db.executemany("INSERT INTO jobs(company, title, location, url, source, source_job_id, job_description, discovery_first_seen_at, discovery_result_category, canonical_job_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)", rows)
        db.commit()
        started = time.perf_counter()
        candidates = app_module.reconciliation_candidate_groups()
        elapsed = time.perf_counter() - started
    assert candidates == []
    assert elapsed < 3.0
    assert app_module._LAST_RECONCILIATION_STATS["records"] == 10000
    assert app_module._LAST_RECONCILIATION_STATS["comparisons"] < 1000
