import csv
import hashlib
import json
import sqlite3

from scripts.replay_workplace_extraction import replay_cohort, write_csv
from scripts.replay_glassdoor_description_probe import main as glassdoor_probe_main
from scripts.diagnose_ece_workplace_evidence import open_readonly


def _db(path):
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY, title TEXT, company TEXT, source TEXT, url TEXT,
            location TEXT, provider_location TEXT, provider_raw_json TEXT,
            job_description TEXT, workplace_address TEXT DEFAULT '', workplace_postal_code TEXT DEFAULT '',
            workplace_precision TEXT DEFAULT '', workplace_evidence TEXT DEFAULT '', workplace_alternatives_json TEXT DEFAULT '[]'
        );
        CREATE TABLE discovery_search_memberships (
            search_execution_id TEXT, job_id INTEGER, applicant_profile_id INTEGER,
            category TEXT, reason TEXT DEFAULT ''
        );
        """
    )
    db.executemany("INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (372, "Registered Early Childhood Educator", "Cityplace Daycare", "indeed", "https://example/372", "Toronto, ON", "Toronto, ON", "{}", "Cityplace Daycare is a brand-new daycare on Toronto’s waterfront at 350 Queens Quay West.", "", "", "", "", "[]"),
        (373, "RECE", "Corporate Child Care", "indeed", "https://example/373", "Toronto, ON", "Toronto, ON", "{}", "Corporate headquarters: 500 King Street, Toronto, ON M5V 1L9.", "", "", "", "", "[]"),
        (374, "RECE", "Known Centre", "glassdoor", "https://example/374", "Toronto, ON", "Toronto, ON", json.dumps({"jobLocation": {"address": {"streetAddress": "10 Main Street", "addressLocality": "Toronto", "postalCode": "M5V 1A1"}}}), "", "10 Main Street", "M5V 1A1", "street address", "saved owner evidence", "[]"),
    ])
    db.executemany("INSERT INTO discovery_search_memberships VALUES (?, ?, ?, ?, '')", [
        ("8a5db657811e4e8c9302e0478b5766aa", 372, 2, "actionable"),
        ("8a5db657811e4e8c9302e0478b5766aa", 373, 2, "actionable"),
        ("8a5db657811e4e8c9302e0478b5766aa", 374, 2, "actionable"),
        ("other-run", 372, 9, "actionable"),
    ])
    db.commit()
    db.close()


def test_replay_uses_exact_applicant_membership_and_keeps_job_372_unconfirmed(tmp_path):
    path = tmp_path / "jobs.sqlite"
    _db(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with open_readonly(path) as db:
        report = replay_cohort(db, "8a5db657811e4e8c9302e0478b5766aa", 2, 3)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert report["network_requests"] == 0
    by_id = {item["job_id"]: item for item in report["jobs"]}
    assert by_id[372]["newly_extracted_address"] == "350 Queens Quay West"
    assert by_id[372]["owner_confirmation_required"] is True
    assert by_id[372]["assignment_status"] == "candidate_requires_owner_confirmation"
    assert by_id[373]["result"] == "rejected"
    assert by_id[374]["result"] == "unchanged"


def test_replay_csv_contains_required_comparison_columns(tmp_path):
    path = tmp_path / "jobs.sqlite"
    _db(path)
    with open_readonly(path) as db:
        report = replay_cohort(db, "8a5db657811e4e8c9302e0478b5766aa", 2, 3)
    output = tmp_path / "replay.csv"
    write_csv(report, output)
    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert {"original_workplace", "newly_extracted_address", "supporting_description_excerpt", "owner_confirmation_required", "result"} <= set(rows[0])
    assert next(row for row in rows if row["job_id"] == "372")["newly_extracted_address"] == "350 Queens Quay West"


def test_glassdoor_probe_clamps_request_without_touching_database(monkeypatch, capsys):
    import scripts.replay_glassdoor_description_probe as probe

    def fake_fetch(**kwargs):
        assert kwargs["enabled_sources"] == ["glassdoor"]
        assert kwargs["results_wanted"] == 10
        assert kwargs["provider_timeout_seconds"] == 60
        return {"jobs": [{"title": "RECE", "company": "C", "description": "Work Location: 10 Main Street"}], "source_diagnostics": {"glassdoor": {"state": "working", "provider_status": "working", "raw_records_row_count": 1}}}

    monkeypatch.setattr(probe, "fetch_jobspy_jobs", fake_fetch)
    monkeypatch.setattr(probe, "get_jobspy_version", lambda: "1.4.1")
    assert glassdoor_probe_main(["--results-wanted", "100", "--timeout-seconds", "999"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["descriptions_returned"] == 1
    assert report["descriptions_with_workplace_evidence"] == 0
