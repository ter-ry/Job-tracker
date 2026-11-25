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
