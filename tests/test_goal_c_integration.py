from pathlib import Path

import app as app_module


def _isolated_client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", Path(tmp_path))
    monkeypatch.setattr(app_module, "DB_PATH", Path(tmp_path) / "jobs.sqlite")
    monkeypatch.setattr(app_module, "_INITIALIZED_DATABASE_PATH", None)
    return app_module.app.test_client()


def test_ece_employment_ranking_persists_across_inbox_pages_and_reopen(tmp_path, monkeypatch):
    client = _isolated_client(tmp_path, monkeypatch)
    client.get("/api/health")
    profile = client.post("/api/candidate-profiles", json={"name": "ECE integration", "workflow": "ece"}).get_json()
    statuses = ["permanent_full_time", "temporary_full_time", "full_time_unspecified_term", "provisional", "supply_or_casual"]
    with app_module.app.app_context():
        jobs = []
        for index, status in enumerate(statuses, start=1):
            job = app_module.normalize_job_payload({
                "source": "fixture", "source_job_id": f"goal-c-{index}",
                "title": f"RECE {status}", "company": f"Centre {index}",
                "location": "Toronto, ON", "url": f"https://example.test/goal-c-{index}",
                "job_description": "ECE opportunity",
                "discovery_first_seen_at": "2026-11-25T00:00:00",
                "discovery_occupation": "early childhood educator",
                "discovery_result_category": "actionable",
                "discovery_employment_status": status,
                "discovery_employment_evidence": f"Fixture evidence: {status}",
                "candidate_profile_id": profile["id"],
                "application_priority_score": 90,
            })
            jobs.append(job)
        persisted = app_module.persist_discovery_jobs(jobs, None, None)
        rows = app_module.query_db(
            "SELECT id, discovery_employment_status, discovery_employment_evidence FROM jobs ORDER BY id"
        )
        assert [row["discovery_employment_status"] for row in rows] == statuses
        assert rows[-1]["discovery_employment_evidence"] == "Fixture evidence: supply_or_casual"
        app_module.persist_discovery_search_memberships("c" * 32, jobs, profile["id"], {
            "workflow": "ece", "policy_version": "goal-c-v1", "occupation": "early childhood educator",
            "geographic_match_mode": "provisional", "original_origin": "M2J 0B6",
            "resolved_origin": "M2J 0B6, Canada", "enabled_sources": ["indeed"],
        })
        criteria = app_module.query_db("SELECT criteria_json FROM discovery_search_memberships LIMIT 1", one=True)
        criteria_json = app_module.parse_json_object(criteria["criteria_json"])
        assert criteria_json["policy_version"] == "goal-c-v1"
        assert criteria_json["original_origin"] == "M2J 0B6"
        assert criteria_json["resolved_origin"] == "M2J 0B6, Canada"
        assert criteria_json["enabled_sources"] == ["indeed"]

    first = client.get(f"/api/discovery/inbox?category=ready_to_apply&candidate_profile_id={profile['id']}&page_size=2&page=0")
    second = client.get(f"/api/discovery/inbox?category=ready_to_apply&candidate_profile_id={profile['id']}&page_size=2&page=1")
    assert first.status_code == second.status_code == 200
    assert [item["discovery_employment_status"] for item in first.get_json()] == statuses[:2]
    assert [item["discovery_employment_status"] for item in second.get_json()] == statuses[2:4]
    assert first.headers["X-Job-Tracker-Total"] == "5"
    assert all(item["discovery_employment_status"] != "supply_or_casual" for item in first.get_json() + second.get_json())

    # Close/reopen the application database connection and verify the same
    # durable status and evidence drive the next page after restart.
    app_module._INITIALIZED_DATABASE_PATH = None
    reopened = client.get(f"/api/discovery/inbox?category=ready_to_apply&candidate_profile_id={profile['id']}&page_size=2&page=2")
    assert reopened.status_code == 200
    assert [item["discovery_employment_status"] for item in reopened.get_json()] == [statuses[4]]
    assert reopened.get_json()[0]["discovery_employment_evidence"] == "Fixture evidence: supply_or_casual"


def test_supply_never_satisfies_ece_target_accounting():
    search = {"occupation": "early childhood educator", "include_provisional_matches": True}
    supply = {"discovery_occupation": "early childhood educator", "discovery_employment_status": "supply_or_casual"}
    assert not app_module.discovery_target_eligible(supply, search)


def test_explicit_ece_workflow_owns_occupation_and_reassessment_policy():
    config = app_module.discovery_search_config({
        "workflow": "ece",
        "keywords": "software developer",
        "geographic_match_mode": "provisional",
        "distance": 25,
    })
    assert config["occupation"] == "early childhood educator"
    assert config["seniority"] == ""
    assert config["maximum_required_years"] == ""
    policy = app_module.resolve_reassessment_policy(
        {"match_policy": "apply_broadly", "geographic_match_mode": "provisional", "distance": 25},
        config,
        "ece",
    )
    assert policy["seniority"] == ""
    assert policy["maximum_required_years"] == ""
