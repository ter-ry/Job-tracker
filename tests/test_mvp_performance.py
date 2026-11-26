import time

import app as app_module


def test_inbox_handles_10000_discovery_records_with_bounded_page_latency(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setattr(app_module, "_INITIALIZED_DATABASE_PATH", None)
    client = app_module.app.test_client()
    client.get("/api/health")
    profile = client.post("/api/candidate-profiles", json={"name": "10k benchmark", "workflow": "software"}).get_json()
    with app_module.app.app_context():
        db = app_module.get_db()
        db.executemany(
            """INSERT INTO jobs(company, title, location, url, source, source_job_id,
               job_description, discovery_first_seen_at, discovery_result_category,
               canonical_job_id, application_priority_score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            [
                ("Benchmark Co", f"Software Developer {index}", "Toronto, ON",
                 f"https://benchmark.example/{index}", "fixture", f"10k-{index}",
                 "A grounded software development posting with current responsibilities.",
                 "2026-11-25T00:00:00", "actionable", index % 100)
                for index in range(10000)
            ],
        )
        db.commit()
    started = time.perf_counter()
    response = client.get(f"/api/discovery/inbox?candidate_profile_id={profile['id']}&category=ready_to_apply&page=0&page_size=50")
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert len(response.get_json()) == 50
    assert response.headers["X-Job-Tracker-Total"] == "10000"
    assert elapsed < 5.0


def test_fast_apply_returns_first_bounded_page_without_qualification_hydration(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "fast-apply.sqlite")
    monkeypatch.setattr(app_module, "_INITIALIZED_DATABASE_PATH", None)
    client = app_module.app.test_client()
    client.get("/api/health")
    profile = client.post("/api/candidate-profiles", json={"name": "Fast Apply benchmark", "workflow": "software"}).get_json()
    with app_module.app.app_context():
        db = app_module.get_db()
        db.executemany(
            """INSERT INTO jobs(company, title, location, url, source, source_job_id,
               job_description, discovery_first_seen_at, discovery_result_category,
               canonical_job_id, application_priority_score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            [
                ("Fast Apply Co", f"Software Engineer {index}", "Toronto, ON",
                 f"https://fast-apply.example/{index}", "fixture", f"fast-{index}",
                 "A long posting whose qualification evidence should not be hydrated for the queue card.",
                 "2026-11-25T00:00:00", "actionable", 10000 - index)
                for index in range(500)
            ],
        )
        db.commit()
    started = time.perf_counter()
    response = client.get(
        f"/api/discovery/inbox?candidate_profile_id={profile['id']}&category=ready_to_apply"
        "&page=0&page_size=10&lightweight=1"
    )
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert len(response.get_json()) == 10
    assert response.headers["X-Job-Tracker-Total"] == "500"
    assert len(response.data) < 100_000
    assert elapsed < 2.0


def test_applications_history_is_applicant_scoped_and_paginated_for_10000_records(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "applications.sqlite")
    monkeypatch.setattr(app_module, "_INITIALIZED_DATABASE_PATH", None)
    client = app_module.app.test_client()
    client.get("/api/health")
    profile = client.post("/api/candidate-profiles", json={"name": "History benchmark", "workflow": "software"}).get_json()
    other = client.post("/api/candidate-profiles", json={"name": "Other applicant", "workflow": "software"}).get_json()
    with app_module.app.app_context():
        db = app_module.get_db()
        db.executemany(
            """INSERT INTO jobs(company, title, location, url, source, source_job_id,
               job_description, discovery_first_seen_at, discovery_result_category,
               canonical_job_id, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'actionable', 0, ?)""",
            [
                ("History Co", f"Processed {index}", "Toronto, ON",
                 f"https://history.example/{index}", "fixture", f"history-{index}",
                 "Processed fixture posting.", "2026-11-25T00:00:00", f"2026-11-25T00:{index % 60:02d}:00")
                for index in range(10000)
            ],
        )
        rows = db.execute("SELECT id FROM jobs ORDER BY id DESC LIMIT 10000").fetchall()
        db.executemany(
            "INSERT INTO discovery_applicant_states(job_id, applicant_profile_id, state, updated_at) VALUES (?, ?, 'saved', ?)" ,
            [(row["id"], profile["id"], "2026-11-25T00:00:00") for row in rows],
        )
        db.executemany(
            "INSERT INTO discovery_applicant_states(job_id, applicant_profile_id, state, updated_at) VALUES (?, ?, 'saved', ?)" ,
            [(row["id"], other["id"], "2026-11-25T00:00:00") for row in rows[:3]],
        )
        db.commit()
    started = time.perf_counter()
    response = client.get(
        f"/api/jobs?candidate_profile_id={profile['id']}&application_history=1&lightweight=1"
        "&page=0&page_size=50"
    )
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert len(response.get_json()) == 50
    assert response.headers["X-Job-Tracker-Total"] == "10000"
    assert elapsed < 2.0
