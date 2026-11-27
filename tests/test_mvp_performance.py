import time
from datetime import date, timedelta

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
        db.execute(
            """UPDATE jobs SET qualification_fit_label = 'Good match',
               qualification_fit_seniority = ?, experience_requirements = ?,
               technical_compatibility = ?, qualification_fit_reasons = ?,
               qualification_fit_matched_requirements = ?
               WHERE source_job_id = 'fast-0'""",
            ('{"detected_level":"junior"}', '{"required":{"min":0,"max":3}}',
             '{"matched":["Python"]}', '["Stored evidence"]', '["Python"]'),
        )
        db.commit()
    monkeypatch.setattr(app_module, "_cached_qualification_fit", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("queue read hydrated qualification")))
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
    first = response.get_json()[0]
    assert first["qualification_fit_label"] == "Good match"
    assert first["qualification_fit_seniority"]["detected_level"] == "junior"
    assert first["experience_requirements"]["required"]["max"] == 3
    assert first["technical_compatibility"]["matched"] == ["Python"]
    assert elapsed < 2.0


def test_inbox_sql_order_matches_canonical_application_priority_order(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "ranking.sqlite")
    monkeypatch.setattr(app_module, "_INITIALIZED_DATABASE_PATH", None)
    client = app_module.app.test_client()
    client.get("/api/health")
    profile = client.post("/api/candidate-profiles", json={"name": "Ranking benchmark", "workflow": "software"}).get_json()
    records = [
        ("entry", "entry_level", 70),
        ("junior", "junior", 80),
        ("unknown", "unknown", 99),
        ("senior", "senior", 100),
        ("intermediate", "intermediate", 85),
    ]
    with app_module.app.app_context():
        db = app_module.get_db()
        db.executemany(
            """INSERT INTO jobs(company, title, location, url, source, source_job_id,
               discovery_first_seen_at, discovery_result_category, candidate_profile_id,
               canonical_job_id, application_priority_score, qualification_fit_seniority)
               VALUES ('Ranking Co', ?, 'Toronto, ON', ?, 'fixture', ?, '2026-11-27',
                       'actionable', ?, 0, ?, ?)""",
            [(f"Software {name}", f"https://ranking/{name}", name, profile["id"], score, '{"detected_level": "' + level + '"}') for name, level, score in records],
        )
        db.commit()
        rows = [dict(row) for row in db.execute("SELECT * FROM jobs WHERE source = 'fixture' ORDER BY id").fetchall()]
        expected = [row["source_job_id"] for row in sorted(rows, key=app_module.application_priority_sort_key)]
    response = client.get(f"/api/discovery/inbox?candidate_profile_id={profile['id']}&category=ready_to_apply&page_size=20")
    assert response.status_code == 200
    assert [row["source_job_id"] for row in response.get_json()] == expected


def test_discovery_preferences_are_isolated_by_applicant_and_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "preferences.sqlite")
    monkeypatch.setattr(app_module, "_INITIALIZED_DATABASE_PATH", None)
    client = app_module.app.test_client()
    client.get("/api/health")
    swe = client.post("/api/candidate-profiles", json={"name": "SWE", "workflow": "software"}).get_json()
    ece = client.post("/api/candidate-profiles", json={"name": "ECE", "workflow": "ece"}).get_json()
    swe_preferences = {"search": {"workflow": "software", "keywords": "platform engineer", "distance_origin_input": "M2J 0B6", "distance": "35", "new_matching_target": 27, "enabled_sources": ["indeed", "glassdoor"], "match_policy": "apply_broadly", "include_internships": True}}
    ece_preferences = {"search": {"workflow": "ece", "keywords": "Registered Early Childhood Educator; RECE", "distance_origin_input": "M5V 2T6", "distance": "12", "new_matching_target": 11, "enabled_sources": ["indeed", "employer_direct"], "match_policy": "strict_matching", "include_internships": False}}
    assert client.post("/api/discovery/preferences", json={"candidate_profile_id": swe["id"], "workflow": "software", "preferences": swe_preferences}).status_code == 200
    assert client.post("/api/discovery/preferences", json={"candidate_profile_id": ece["id"], "workflow": "ece", "preferences": ece_preferences}).status_code == 200
    swe_loaded = client.get(f"/api/discovery/preferences?candidate_profile_id={swe['id']}&workflow=software").get_json()
    ece_loaded = client.get(f"/api/discovery/preferences?candidate_profile_id={ece['id']}&workflow=ece").get_json()
    assert swe_loaded["preferences"]["search"]["keywords"] == "platform engineer"
    assert swe_loaded["preferences"]["search"]["match_policy"] == "apply_broadly"
    assert swe_loaded["preferences"]["search"]["enabled_sources"] == ["indeed", "glassdoor"]
    assert swe_loaded["preferences"]["search"]["distance"] == "35"
    assert swe_loaded["preferences"]["search"]["new_matching_target"] == 27
    assert swe_loaded["preferences"]["search"]["include_internships"] is True
    assert ece_loaded["preferences"]["search"]["keywords"] == "Registered Early Childhood Educator; RECE"
    assert ece_loaded["preferences"]["search"]["match_policy"] == "strict_matching"
    assert ece_loaded["preferences"]["search"]["enabled_sources"] == ["indeed", "employer_direct"]
    assert ece_loaded["preferences"]["search"]["distance"] == "12"
    assert ece_loaded["preferences"]["search"]["new_matching_target"] == 11
    assert ece_loaded["preferences"]["search"]["include_internships"] is False
    assert swe_loaded["search_key"] != ece_loaded["search_key"]


def test_progressive_discovery_policy_payload_preserves_broad_matching_and_internships():
    payload = {
        "workflow": "software",
        "keywords": "software developer",
        "location": "Toronto, ON",
        "enabled_sources": ["indeed", "glassdoor"],
        "match_policy": "apply_broadly",
        "include_internships": True,
        "distance": 50,
        "new_matching_target": 50,
    }
    config = app_module.discovery_search_config(payload)
    assert config["match_policy"] == "apply_broadly"
    assert config["include_internships"] is True
    assert config["enabled_sources"] == ["indeed", "glassdoor"]


def test_cross_provider_owner_pair_fixtures_remain_conservative_without_shared_identity():
    pairs = [
        ("Junior Software Engineer", "Junior Software Engineer/Developer"),
        ("Software Engineer I", "Software Engineer I"),
        ("Software Engineer II", "Software Engineer II"),
        ("Frontend Engineer", "Frontend Engineer"),
    ]
    for left_title, right_title in pairs:
        left = {"source": "indeed", "source_job_id": f"left-{left_title}", "company": "Fixture Employer", "title": left_title, "location": "Toronto, ON", "url": f"https://indeed.example/{left_title}"}
        right = {"source": "glassdoor", "source_job_id": f"right-{right_title}", "company": "Fixture Employer", "title": right_title, "location": "Toronto, ON", "url": f"https://glassdoor.example/{right_title}"}
        evidence = app_module.vacancy_identity_pair(left, right)
        assert evidence["identity"] in {"separate", "uncertain"}
        assert evidence["identity"] != "strong"


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


def test_applications_history_filters_searches_and_sorts_server_side(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "history-filters.sqlite")
    monkeypatch.setattr(app_module, "_INITIALIZED_DATABASE_PATH", None)
    client = app_module.app.test_client()
    client.get("/api/health")
    profile = client.post("/api/candidate-profiles", json={"name": "History filters", "workflow": "software"}).get_json()
    with app_module.app.app_context():
        db = app_module.get_db()
        jobs = []
        for index, company, title, salary in [
            (1, "Zeta", "Applied Engineer", "$70,000"),
            (2, "Alpha", "Saved Engineer", "$120,000"),
            (3, "Beta", "Skipped Analyst", "$80,000"),
        ]:
            cursor = db.execute(
                """INSERT INTO jobs(company, title, location, url, source, source_job_id,
                   discovery_first_seen_at, discovery_result_category, canonical_job_id, salary)
                   VALUES (?, ?, 'Toronto, ON', ?, 'fixture', ?, '2026-11-25T00:00:00', 'actionable', 0, ?)""",
                (company, title, f"https://history-filter/{index}", f"hf-{index}", salary),
            )
            jobs.append(cursor.lastrowid)
        db.executemany(
            "INSERT INTO discovery_applicant_states(job_id, applicant_profile_id, state, updated_at) VALUES (?, ?, ?, '2026-11-25T00:00:00')",
            [(jobs[0], profile["id"], "applied"), (jobs[1], profile["id"], "saved"), (jobs[2], profile["id"], "skipped")],
        )
        db.commit()
    base = f"/api/jobs?candidate_profile_id={profile['id']}&application_history=1&lightweight=1&page_size=1"
    response = client.get(base + "&history_category=saved&history_sort=salary")
    assert response.status_code == 200
    assert response.headers["X-Job-Tracker-Total"] == "1"
    assert response.get_json()[0]["company"] == "Alpha"
    response = client.get(base + "&history_q=Analyst&history_category=skipped")
    assert response.status_code == 200
    assert response.get_json()[0]["title"] == "Skipped Analyst"


def test_vacancy_retention_is_disabled_without_hiding_history(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "retention.sqlite")
    monkeypatch.setattr(app_module, "_INITIALIZED_DATABASE_PATH", None)
    client = app_module.app.test_client()
    client.get("/api/health")
    profile = client.post("/api/candidate-profiles", json={"name": "Retention owner", "workflow": "software"}).get_json()
    recent = (date.today() - timedelta(days=3)).isoformat()
    old = (date.today() - timedelta(days=30)).isoformat()
    with app_module.app.app_context():
        db = app_module.get_db()
        ids = {}
        for key, posted in (("recent", recent), ("old", old), ("unknown", ""), ("saved", old)):
            cursor = db.execute(
                """INSERT INTO jobs(company, title, location, url, source, source_job_id,
                   discovery_first_seen_at, posted_date, discovery_result_category,
                   canonical_job_id, status) VALUES (?, ?, 'Toronto, ON', ?, 'fixture', ?,
                   ?, ?, 'actionable', 0, 'Discovered')""",
                ("Retention Co", f"{key} role", f"https://retention/{key}", key, recent, posted),
            )
            ids[key] = cursor.lastrowid
        db.execute(
            "INSERT INTO discovery_applicant_states(job_id, applicant_profile_id, state) VALUES (?, ?, 'saved')",
            (ids["saved"], profile["id"]),
        )
        db.commit()
    response = client.get(f"/api/discovery/inbox?candidate_profile_id={profile['id']}&category=ready_to_apply&page_size=20")
    assert {item["title"] for item in response.get_json()} == {"recent role", "old role", "unknown role"}
    archived = client.post("/api/discovery/inbox/archive-expired", json={"confirm_archive": True})
    assert archived.status_code == 409
    assert archived.get_json()["archived_count"] == 0
    cleanup_blocked = client.post("/api/discovery/inbox/cleanup-archived-payloads", json={})
    assert cleanup_blocked.status_code == 409
    archived_view = client.get(f"/api/discovery/inbox?candidate_profile_id={profile['id']}&category=archived&page_size=20")
    assert archived_view.get_json() == []
    saved = client.get(f"/api/discovery/inbox?candidate_profile_id={profile['id']}&category=saved&include_history=1&page_size=20")
    assert [item["title"] for item in saved.get_json()] == ["saved role"]
