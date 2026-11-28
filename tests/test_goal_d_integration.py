from pathlib import Path
from unittest.mock import patch
import urllib.error

import app as app_module


def test_ece_queue_keeps_supply_but_target_counts_only_full_time(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", Path(tmp_path))
    monkeypatch.setattr(app_module, "DB_PATH", Path(tmp_path) / "goal-d.sqlite")
    monkeypatch.setattr(app_module, "_INITIALIZED_DATABASE_PATH", None)

    class FakeGeocoder:
        name = "fixture"

        def geocode(self, query, *, country="Canada"):
            if "Montreal" in query:
                return {"ok": True, "status": "saved", "provider": self.name,
                        "normalized_query": query, "latitude": 45.50,
                        "longitude": -73.56, "confidence": 90, "precision": "city",
                        "display_name": query}
            return {"ok": True, "status": "saved", "provider": self.name,
                    "normalized_query": query, "latitude": 43.65,
                    "longitude": -79.38, "confidence": 90, "precision": "city",
                    "display_name": query}

    postings = [
        ("permanent", "Registered Early Childhood Educator", "Full-time permanent educator role.", "Full-time"),
        ("temporary", "RECE Educator", "Full-time temporary educator role.", "Temporary full-time"),
        ("provisional", "RECE", "Educator opportunity; employment details are not stated.", ""),
        ("supply", "Supply RECE", "Supply educator position.", "Supply"),
        ("eca", "Early Childhood Assistant", "Full-time assistant role.", "Full-time"),
        ("outside", "Registered Early Childhood Educator", "Full-time permanent educator role.", "Full-time"),
    ]

    def fake_fetch(**_kwargs):
        return {"jobs": [{
            "source_job_id": key, "source": "indeed", "title": title,
            "company": f"Centre {key}", "location": "Montreal, QC" if key == "outside" else "Toronto, ON",
            "job_url": f"https://example.test/{key}", "description": description,
            "employment_type": employment,
            **({"distance_km": 1000, "distance_confidence": 100} if key == "outside" else {}),
        } for key, title, description, employment in postings], "errors": {},
            "source_counts": {"indeed": len(postings)}, "source_diagnostics": {},
            "source_snapshots": {}}

    client = app_module.app.test_client()
    profile = client.post("/api/candidate-profiles", json={"name": "Goal D ECE", "workflow": "ece"}).get_json()
    with patch.object(app_module, "fetch_jobspy_jobs", side_effect=fake_fetch), patch.object(app_module, "get_geocoding_provider", return_value=FakeGeocoder()):
        response = client.post("/api/discovery/jobspy", json={
            "workflow": "ece", "keywords": "RECE", "location": "Toronto, ON",
            "distance": 50, "distance_origin": "Toronto, ON", "enabled_sources": ["indeed"],
            "applicant_profile_id": profile["id"], "new_matching_target": 2,
            "total_cap": 100, "per_source_cap": 100,
        })
    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body["diagnostics"]["target_eligible_count"] == 2
    assert body["diagnostics"]["target_reached"] is True
    queue = {item["source_job_id"]: item for item in body["jobs"]}
    assert queue["supply"]["discovery_result_category"] == "actionable"
    assert queue["supply"]["discovery_employment_status"] == "supply_or_casual"
    assert "eca" not in queue
    assert "outside" not in queue
    assert body["diagnostics"]["continuation_available"] is False

    inbox = client.get(f"/api/discovery/inbox?category=ready_to_apply&candidate_profile_id={profile['id']}&page_size=20&page=0").get_json()
    statuses = [item["discovery_employment_status"] for item in inbox]
    assert statuses[-1] == "supply_or_casual"


def test_workplace_denial_circuit_stops_repeated_401s_and_preserves_partial_results(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", Path(tmp_path))
    monkeypatch.setattr(app_module, "DB_PATH", Path(tmp_path) / "denial.sqlite")
    monkeypatch.setattr(app_module, "_INITIALIZED_DATABASE_PATH", None)
    client = app_module.app.test_client()
    profile = client.post("/api/candidate-profiles", json={"name": "Denial fixture", "workflow": "ece"}).get_json()
    ids = []
    for index in range(22):
        item = client.post("/api/jobs", json={
            "title": "RECE", "company": f"Denied Centre {index}", "location": "Toronto, ON",
            "url": f"https://ca.indeed.com/viewjob?jk=denied-{index}", "source": "indeed",
            "source_job_id": f"denied-{index}", "job_description": "Educator posting without a stored workplace address.",
            "discovery_first_seen_at": "2026-11-26", "discovery_result_category": "actionable",
            "discovery_occupation": "early childhood educator", "candidate_profile_id": profile["id"],
        }).get_json()
        ids.append(item["id"])

    class DeniedOpener:
        def open(self, *_args, **_kwargs):
            raise urllib.error.HTTPError("https://ca.indeed.com/viewjob", 401, "Unauthorized", {}, None)

    with patch.object(app_module, "_safe_public_destination", return_value=True), patch.object(app_module.urllib.request, "build_opener", return_value=DeniedOpener()) as opener:
        result = client.post("/api/jobs/enrich-workplace-locations", json={
            "candidate_profile_id": profile["id"], "job_ids": ids, "limit": 25,
        }).get_json()
    assert opener.call_count == 3
    assert result["provider_denial_attempts"]["ca.indeed.com"] == 3
    assert result["blocked_providers"] == ["ca.indeed.com"]
    assert len(result["records"]) == 22
    assert all(record["status"] == "blocked" for record in result["records"])


def test_ece_persisted_search_accounting_distinguishes_new_represented_and_reclassified(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DATA_DIR", Path(tmp_path))
    monkeypatch.setattr(app_module, "DB_PATH", Path(tmp_path) / "accounting.sqlite")
    monkeypatch.setattr(app_module, "_INITIALIZED_DATABASE_PATH", None)
    client = app_module.app.test_client()
    profile = client.post("/api/candidate-profiles", json={"name": "Accounting ECE", "workflow": "ece"}).get_json()
    postings = [
        {"source_job_id": "ft-1", "title": "Registered Early Childhood Educator", "description": "Full-time permanent educator role."},
        {"source_job_id": "supply-1", "title": "Supply RECE", "description": "Supply educator position."},
    ]

    def fake_fetch(**_kwargs):
        return {"jobs": [{"source_job_id": item["source_job_id"], "source": "indeed", "title": item["title"], "company": "Accounting Centre", "location": "Toronto, ON", "job_url": f"https://example.test/{item['source_job_id']}", "description": item["description"]} for item in postings], "errors": {}, "source_counts": {"indeed": 2}, "source_diagnostics": {}, "source_snapshots": {}}

    payload = {"workflow": "ece", "keywords": "RECE", "location": "Toronto, ON", "distance": 50, "distance_origin": "Toronto, ON", "enabled_sources": ["indeed"], "applicant_profile_id": profile["id"], "new_matching_target": 1, "total_cap": 10, "per_source_cap": 10}
    with patch.object(app_module, "fetch_jobspy_jobs", side_effect=fake_fetch):
        first = client.post("/api/discovery/jobspy", json=payload).get_json()
        with app_module.app.app_context():
            app_module.mark_discovery_jobs_presented([item["id"] for item in first["jobs"]], profile["id"])
            app_module.get_db().commit()
        postings[1]["title"] = "Registered Early Childhood Educator"
        postings[1]["description"] = "Full-time permanent educator role after classification correction."
        second = client.post("/api/discovery/jobspy", json=payload).get_json()
    diagnostics = second["diagnostics"]
    assert diagnostics["newly_acquired_count"] == 0
    assert diagnostics["previously_acquired_unseen_count"] >= 0
    assert diagnostics["previously_acquired_newly_presented_count"] >= 0
    assert "reclassified_count" in diagnostics
    assert diagnostics["newly_acquired_count"] != diagnostics["newly_presented_count"]
