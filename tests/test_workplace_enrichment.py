import tempfile
from pathlib import Path
from unittest.mock import patch

import app as app_module


class _Response:
    headers = {"Content-Type": "text/html"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return b"<html><body><h2>Our Centre</h2><p>1200 Bayview Avenue<br>Toronto, ON M4G 1Z8</p></body></html>"


class _Opener:
    def open(self, *_args, **_kwargs):
        return _Response()


class _BlockedOpener:
    def open(self, *_args, **_kwargs):
        raise app_module.urllib.error.HTTPError("https://ca.indeed.com/viewjob", 401, "Unauthorized", {}, None)


def test_workplace_fetch_rejects_local_and_private_destinations():
    assert app_module._safe_public_destination("http://localhost:5000/job") is False
    assert app_module._safe_public_destination("http://127.0.0.1/job") is False
    assert app_module._safe_public_destination("http://10.0.0.8/job") is False


def test_workplace_enrichment_is_preview_first_and_persists_evidence():
    with tempfile.TemporaryDirectory() as directory:
        app_module.DATA_DIR = Path(directory)
        app_module.DB_PATH = app_module.DATA_DIR / "test.sqlite"
        app_module._INITIALIZED_DATABASE_PATH = None
        app_module.app.config.update(TESTING=True)
        client = app_module.app.test_client()
        profile = client.post("/api/candidate-profiles", json={"name": "ECE QA", "workflow": "ece"}).get_json()
        created = client.post("/api/jobs", json={
            "title": "RECE", "company": "Example Child Care", "location": "Toronto, ON",
            "url": "https://example.com/jobs/rece-1", "source": "indeed",
            "job_description": "Join our early learning team.", "discovery_first_seen_at": "2026-11-20T00:00:00",
            "discovery_result_category": "actionable", "candidate_profile_id": profile["id"],
        })
        assert created.status_code == 201
        with app_module.app.app_context():
            app_module.get_db().execute(
                "INSERT INTO discovery_search_memberships(search_execution_id, job_id, applicant_profile_id, category, criteria_json) VALUES (?, ?, ?, 'actionable', ?)",
                ["a" * 32, 1, profile["id"], '{"occupation":"ece"}'],
            )
            app_module.get_db().commit()
        with patch.object(app_module, "_safe_public_destination", return_value=True), patch.object(app_module.urllib.request, "build_opener", return_value=_Opener()):
            preview = client.post("/api/jobs/enrich-workplace-locations", json={"apply": False, "limit": 25, "candidate_profile_id": profile["id"], "search_id": "a" * 32, "job_ids": [1]})
        assert preview.status_code == 200
        assert preview.get_json()["preview"] is True
        assert preview.get_json()["gained_candidate"] == 1
        with app_module.app.app_context():
            row = app_module.query_db("SELECT workplace_address FROM jobs WHERE id = 1", one=True)
        assert row["workplace_address"] == ""
        with patch.object(app_module, "_safe_public_destination", return_value=True), patch.object(app_module.urllib.request, "build_opener", return_value=_Opener()):
            applied = client.post("/api/jobs/enrich-workplace-locations", json={"apply": True, "limit": 25, "candidate_profile_id": profile["id"], "search_id": "a" * 32, "job_ids": [1]})
        assert applied.status_code == 200
        assert applied.get_json()["preview"] is False
        with app_module.app.app_context():
            row = app_module.query_db("SELECT workplace_address, workplace_alternatives_json, workplace_precision FROM jobs WHERE id = 1", one=True)
        assert row["workplace_address"] == ""
        assert "M4G 1Z8" in row["workplace_alternatives_json"]
        assert row["workplace_precision"] == "candidate street address"


def test_workplace_enrichment_advances_batches_and_requires_selected_applicant():
    with tempfile.TemporaryDirectory() as directory:
        app_module.DATA_DIR = Path(directory)
        app_module.DB_PATH = app_module.DATA_DIR / "test.sqlite"
        app_module._INITIALIZED_DATABASE_PATH = None
        app_module.app.config.update(TESTING=True)
        client = app_module.app.test_client()
        assert client.post("/api/jobs/enrich-workplace-locations", json={"apply": False}).get_json()["error"]
        profile = client.post("/api/candidate-profiles", json={"name": "ECE QA", "workflow": "ece"}).get_json()
        search_id = "b" * 32
        created_ids = []
        for index in range(26):
            response = client.post("/api/jobs", json={
                "title": "RECE", "company": f"Centre {index}", "location": "Toronto, ON",
                "url": f"https://example.com/jobs/rece-{index}", "source": "indeed",
                "job_description": "Join our early learning team.", "discovery_first_seen_at": f"2026-11-20T00:{index:02d}:00",
                "discovery_result_category": "actionable", "candidate_profile_id": profile["id"],
            })
            assert response.status_code == 201
            created_ids.append(response.get_json()["id"])
        with app_module.app.app_context():
            app_module.get_db().executemany(
                "INSERT INTO discovery_search_memberships(search_execution_id, job_id, applicant_profile_id, category, criteria_json) VALUES (?, ?, ?, 'actionable', ?)",
                [(search_id, job_id, profile["id"], '{"occupation":"ece"}') for job_id in created_ids],
            )
            app_module.get_db().commit()
        with patch.object(app_module, "_safe_public_destination", return_value=True), patch.object(app_module.urllib.request, "build_opener", return_value=_Opener()):
            first = client.post("/api/jobs/enrich-workplace-locations", json={"apply": False, "limit": 25, "candidate_profile_id": profile["id"], "search_id": search_id, "offset": 0}).get_json()
            second = client.post("/api/jobs/enrich-workplace-locations", json={"apply": False, "limit": 25, "candidate_profile_id": profile["id"], "search_id": search_id, "offset": first["next_offset"]}).get_json()
            confirmed = client.post("/api/jobs/enrich-workplace-locations", json={
                "apply": True, "limit": 25, "candidate_profile_id": profile["id"],
                "search_id": search_id, "offset": first["next_offset"], "job_ids": [second["records"][0]["id"]],
            }).get_json()
        assert len(first["records"]) == 25
        assert len(second["records"]) == 1
        assert first["records"][0]["id"] != second["records"][0]["id"]
        assert first["has_more"] is True
        assert second["has_more"] is False
        assert confirmed["processed"] == 1
        with app_module.app.app_context():
            row = app_module.query_db("SELECT workplace_address, workplace_alternatives_json FROM jobs WHERE id = ?", [second["records"][0]["id"]], one=True)
        assert row["workplace_address"] == ""
        assert "M4G 1Z8" in row["workplace_alternatives_json"]


def test_enrichment_prefers_saved_ece_jobspy_evidence_and_never_uses_swe_rows():
    with tempfile.TemporaryDirectory() as directory:
        app_module.DATA_DIR = Path(directory)
        app_module.DB_PATH = app_module.DATA_DIR / "test.sqlite"
        app_module._INITIALIZED_DATABASE_PATH = None
        app_module.app.config.update(TESTING=True)
        client = app_module.app.test_client()
        ece = client.post("/api/candidate-profiles", json={"name": "ECE QA", "workflow": "ece"}).get_json()
        swe = client.post("/api/candidate-profiles", json={"name": "SWE QA", "workflow": "software"}).get_json()
        ece_job = client.post("/api/jobs", json={
            "title": "RECE", "company": "Centre Example", "location": "Toronto, ON",
            "url": "https://ca.indeed.com/viewjob?jk=ece-1", "source": "indeed",
            "job_description": "Location: 1200 Bayview Avenue, Toronto, ON M4G 1Z8\\nJoin our early learning team.",
            "discovery_first_seen_at": "2026-11-20T00:00:00", "discovery_result_category": "actionable", "candidate_profile_id": ece["id"],
        }).get_json()
        swe_job = client.post("/api/jobs", json={
            "title": "Software Engineer", "company": "Finance Example", "location": "Toronto, ON",
            "url": "https://ca.indeed.com/viewjob?jk=swe-1", "source": "indeed",
            "job_description": "Location: 1 King Street West, Toronto, ON M5H 1A1",
            "discovery_first_seen_at": "2026-11-20T00:00:00", "discovery_result_category": "actionable", "candidate_profile_id": swe["id"],
        }).get_json()
        search_id = "c" * 32
        with app_module.app.app_context():
            app_module.get_db().executemany(
                "INSERT INTO discovery_search_memberships(search_execution_id, job_id, applicant_profile_id, category, criteria_json) VALUES (?, ?, ?, 'actionable', ?)",
                [(search_id, ece_job["id"], ece["id"], '{"occupation":"ece"}'), (search_id, swe_job["id"], swe["id"], '{"occupation":"software"}')],
            )
            app_module.get_db().commit()
        with patch.object(app_module.urllib.request, "build_opener", side_effect=AssertionError("stored evidence should avoid network")):
            result = client.post("/api/jobs/enrich-workplace-locations", json={
                "candidate_profile_id": ece["id"], "search_id": search_id, "job_ids": [ece_job["id"], swe_job["id"]],
            }).get_json()
        assert result.get("error") is not None
        assert "selected applicant search" in result["error"]
        with patch.object(app_module.urllib.request, "build_opener", side_effect=AssertionError("stored evidence should avoid network")):
            result = client.post("/api/jobs/enrich-workplace-locations", json={
                "candidate_profile_id": ece["id"], "search_id": search_id, "job_ids": [ece_job["id"]],
            }).get_json()
        assert result["gained_candidate"] == 1
        assert result["records"][0]["alternatives"][0]["postal_code"] == "M4G 1Z8"


def test_cloudflare_markup_is_not_workplace_evidence_and_blocked_sources_are_reported():
    page = "<html><script>var __CF$cv$params={cRay:'x'}; postal='E7C 0B8';</script><p>Access denied</p></html>"
    assert app_module._extract_workplace_from_page({"location": "Toronto, ON", "title": "RECE"}, page, "https://ca.indeed.com/viewjob") == []
    with tempfile.TemporaryDirectory() as directory:
        app_module.DATA_DIR = Path(directory)
        app_module.DB_PATH = app_module.DATA_DIR / "test.sqlite"
        app_module._INITIALIZED_DATABASE_PATH = None
        app_module.app.config.update(TESTING=True)
        client = app_module.app.test_client()
        profile = client.post("/api/candidate-profiles", json={"name": "ECE QA", "workflow": "ece"}).get_json()
        created = client.post("/api/jobs", json={
            "title": "RECE", "company": "Blocked Centre", "location": "Toronto, ON", "url": "https://ca.indeed.com/viewjob?jk=blocked", "source": "indeed",
            "job_description": "An early learning role with no workplace address.", "discovery_first_seen_at": "2026-11-20T00:00:00", "discovery_result_category": "actionable", "candidate_profile_id": profile["id"],
        }).get_json()
        search_id = "d" * 32
        with app_module.app.app_context():
            app_module.get_db().execute("INSERT INTO discovery_search_memberships(search_execution_id, job_id, applicant_profile_id, category, criteria_json) VALUES (?, ?, ?, 'actionable', ?)", [search_id, created["id"], profile["id"], '{"occupation":"ece"}'])
            app_module.get_db().commit()
        with patch.object(app_module, "_safe_public_destination", return_value=True), patch.object(app_module.urllib.request, "build_opener", return_value=_BlockedOpener()):
            result = client.post("/api/jobs/enrich-workplace-locations", json={"candidate_profile_id": profile["id"], "search_id": search_id, "job_ids": [created["id"]]}).get_json()
        assert result["records"][0]["status"] == "blocked"
        assert "HTTP 401" in result["records"][0]["reason"]


def test_universal_workplace_finder_handles_swe_saved_description_and_owner_confirmation():
    with tempfile.TemporaryDirectory() as directory:
        app_module.DATA_DIR = Path(directory)
        app_module.DB_PATH = app_module.DATA_DIR / "test.sqlite"
        app_module._INITIALIZED_DATABASE_PATH = None
        app_module.app.config.update(TESTING=True)
        client = app_module.app.test_client()
        profile = client.post("/api/candidate-profiles", json={"name": "SWE QA", "workflow": "software"}).get_json()
        created = client.post("/api/jobs", json={
            "title": "Software Developer", "company": "Example Software", "location": "Toronto, ON",
            "url": "https://example.test/swe", "source": "indeed",
            "job_description": "Our Toronto office is at 1200 Bayview Avenue, Toronto, ON M4G 1Z8.",
            "discovery_first_seen_at": "2026-11-20", "discovery_result_category": "actionable",
            "candidate_profile_id": profile["id"],
        }).get_json()
        result = client.post("/api/jobs/enrich-workplace-locations", json={
            "candidate_profile_id": profile["id"], "job_ids": [created["id"]], "limit": 25,
        }).get_json()
        assert result["gained_candidate"] == 1
        assert result["records"][0]["alternatives"][0]["postal_code"] == "M4G 1Z8"
        confirmed = client.post(f"/api/jobs/{created['id']}/workplace", json={
            "candidate_profile_id": profile["id"], "address": "1200 Bayview Avenue, Toronto, ON M4G 1Z8",
        })
        assert confirmed.status_code == 200
        app_module._INITIALIZED_DATABASE_PATH = None
        restarted = client.get(f"/api/jobs?candidate_profile_id={profile['id']}").get_json()
        saved = next(item for item in restarted if item["id"] == created["id"])
        assert saved["workplace_precision"] == "owner-confirmed"
        assert saved["workplace_address"].startswith("1200 Bayview Avenue")


def test_saved_search_run_restores_exact_28_job_workplace_cohort_after_restart():
    with tempfile.TemporaryDirectory() as directory:
        app_module.DATA_DIR = Path(directory)
        app_module.DB_PATH = app_module.DATA_DIR / "test.sqlite"
        app_module._INITIALIZED_DATABASE_PATH = None
        app_module.app.config.update(TESTING=True)
        client = app_module.app.test_client()
        profile = client.post("/api/candidate-profiles", json={"name": "ECE QA", "workflow": "ece"}).get_json()
        search_id = "e" * 32
        job_ids = []
        for index in range(28):
            job = client.post("/api/jobs", json={
                "title": "RECE", "company": f"Centre {index}", "location": "Toronto, ON",
                "url": f"https://example.test/ece/{index}", "source": "indeed",
                "discovery_first_seen_at": "2026-11-20", "discovery_result_category": "actionable",
                "candidate_profile_id": profile["id"],
            }).get_json()
            job_ids.append(job["id"])
        with app_module.app.app_context():
            app_module.get_db().executemany(
                "INSERT INTO discovery_search_memberships(search_execution_id, job_id, applicant_profile_id, category, criteria_json, created_at) VALUES (?, ?, ?, 'actionable', ?, ?)",
                [(search_id, job_id, profile["id"], '{"keywords":"RECE","occupation":"ece"}', f"2026-11-20 10:{index:02d}:00") for index, job_id in enumerate(job_ids)],
            )
            app_module.get_db().commit()
        first = client.get(f"/api/discovery/inbox/search-runs?candidate_profile_id={profile['id']}").get_json()
        assert first[0]["search_id"] == search_id
        assert first[0]["actionable_count"] == 28
        assert first[0]["actionable_job_ids"] == job_ids
        app_module._INITIALIZED_DATABASE_PATH = None
        restored = client.get(f"/api/discovery/inbox/search-runs?candidate_profile_id={profile['id']}").get_json()
        assert restored[0]["search_id"] == search_id
        assert restored[0]["workflow"] == "ece"
        assert restored[0]["actionable_job_ids"] == job_ids
