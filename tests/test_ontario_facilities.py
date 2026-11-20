import io
import tempfile
from pathlib import Path

import pandas as pd

import app as app_module
from sources.ontario_facilities import load_facilities, match_cohort


def _workbook(rows):
    frame = pd.DataFrame(rows)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False)
    return buffer.getvalue()


def _facility(site, licensee, city="Toronto", address="10 Main Street", postal="M1A 1A1"):
    return {
        "Report Snapshot Date": "2026-10-31", "Licensee Name": licensee,
        "Program Type Desc": "Child Care Centre", "Child Care Site Name": site,
        "Licence Number": "12345", "Licence Status": "Active", "Street Number": address.split()[0],
        "Street Name": " ".join(address.split()[1:-1]), "Street Type": "Street",
        "City": city, "Province": "ON", "Postal Code": postal,
    }


def test_offline_matching_preserves_ambiguity_and_rejects_generic_names():
    workbook = _workbook([
        _facility("Roden Community Child Care Centre", "Roden Community Child Care Centre", postal="M1A 1A1"),
        _facility("Roden Community Child Care Centre - Annex", "Roden Community Child Care Centre", address="20 Main Street", postal="M1A 1A2"),
        _facility("Downtown Montessori At Concord City Place", "Downtown Montessori", address="30 Main Street", postal="M1A 1A3"),
    ])
    facilities = load_facilities(workbook)
    results = match_cohort([
        {"job_id": "1", "employer": "Roden Community Child Care Centre", "job_title": "RECE", "advertised_location": "Toronto, ON"},
        {"job_id": "2", "employer": "City Place Daycare", "job_title": "RECE", "advertised_location": "Toronto, ON"},
    ], facilities)
    assert results[0]["category"] == "multiple_licensed_facilities"
    assert all(item["assigned_workplace_confirmed"] is False for item in results)
    assert results[1]["category"] == "no_defensible_registry_match"


def test_registry_preview_is_read_only_and_ece_scoped():
    with tempfile.TemporaryDirectory() as directory:
        app_module.DATA_DIR = Path(directory)
        app_module.DB_PATH = app_module.DATA_DIR / "test.sqlite"
        app_module._INITIALIZED_DATABASE_PATH = None
        app_module.app.config.update(TESTING=True)
        client = app_module.app.test_client()
        profile = client.post("/api/candidate-profiles", json={"name": "ECE QA", "workflow": "ece"}).get_json()
        job = client.post("/api/jobs", json={
            "title": "RECE", "company": "Roden Community Child Care Centre", "location": "Toronto, ON",
            "url": "https://example.test/rece", "source": "indeed", "discovery_first_seen_at": "2026-11-20",
            "discovery_result_category": "actionable", "candidate_profile_id": profile["id"],
        }).get_json()
        search_id = "e" * 32
        with app_module.app.app_context():
            app_module.get_db().execute(
                "INSERT INTO discovery_search_memberships(search_execution_id, job_id, applicant_profile_id, category, criteria_json) VALUES (?, ?, ?, 'actionable', ?)",
                [search_id, job["id"], profile["id"], '{"occupation":"ece"}'],
            )
            app_module.get_db().commit()
        cohort = pd.DataFrame([{"job_id": job["id"], "employer": "Roden Community Child Care Centre", "job_title": "RECE", "advertised_location": "Toronto, ON"}]).to_csv(index=False).encode()
        response = client.post("/api/jobs/enrich-workplace-registry", data={
            "candidate_profile_id": str(profile["id"]), "search_id": search_id,
            "cohort_file": (io.BytesIO(cohort), "cohort.csv"),
            "registry_file": (io.BytesIO(_workbook([_facility("Roden Community Child Care Centre", "Roden Community Child Care Centre")])), "registry.xlsx"),
        }, content_type="multipart/form-data")
        assert response.status_code == 200
        result = response.get_json()
        assert result["preview"] is True
        assert result["jobs"][0]["candidates"][0]["status"].startswith("Possible licensed facility")
        with app_module.app.app_context():
            row = app_module.query_db("SELECT workplace_address, status FROM jobs WHERE id = ?", [job["id"]], one=True)
        assert row["workplace_address"] == ""
        assert row["status"] == "Discovered"
