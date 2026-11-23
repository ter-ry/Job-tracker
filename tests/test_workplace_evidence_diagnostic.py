import hashlib
import json
import sqlite3
from pathlib import Path

from scripts.diagnose_ece_workplace_evidence import diagnose_database, main, open_readonly


def _make_db(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY, title TEXT, company TEXT, source TEXT, url TEXT,
            location TEXT, provider_location TEXT, provider_raw_json TEXT,
            job_description TEXT, workplace_address TEXT DEFAULT '',
            workplace_postal_code TEXT DEFAULT '', workplace_precision TEXT DEFAULT '',
            workplace_evidence TEXT DEFAULT ''
        );
        CREATE TABLE discovery_search_memberships (
            search_execution_id TEXT, job_id INTEGER, applicant_profile_id INTEGER,
            category TEXT, reason TEXT DEFAULT '', evidence_json TEXT DEFAULT '{}',
            criteria_json TEXT DEFAULT '{}', created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    db.executemany(
        "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "RECE", "Known Centre", "indeed", "https://example/1", "Toronto, ON", "Toronto, ON", json.dumps({"location": "Toronto, ON"}), "Work Location:\n120 Main Street\nToronto, ON M1M 1M1", "", "", "", ""),
            (2, "RECE", "No Description", "indeed", "https://example/2", "Toronto, ON", "Toronto, ON", json.dumps({"jobLocation": {"address": {"streetAddress": "5 King Street", "addressLocality": "Toronto", "postalCode": "M5V 1A1"}}}), "", "", "", "", ""),
            (3, "RECE", "Ambiguous", "glassdoor", "https://example/3", "Toronto, ON", "Toronto, ON", "{}", "Contact us at 500 King Street, Toronto, ON M5V 1L9.", "", "", "", ""),
        ],
    )
    db.executemany(
        "INSERT INTO discovery_search_memberships VALUES (?, ?, ?, ?, '', '{}', ?, CURRENT_TIMESTAMP)",
        [("ece-run", 1, 7, "actionable", json.dumps({"workflow": "ece"})), ("ece-run", 2, 7, "actionable", json.dumps({"workflow": "ece"})), ("ece-run", 3, 7, "actionable", json.dumps({"workflow": "ece"}))],
    )
    db.commit()
    db.close()


def test_diagnostic_distinguishes_missing_description_and_parser_rejection(tmp_path):
    path = tmp_path / "jobs.sqlite"
    _make_db(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with open_readonly(path) as db:
        report = diagnose_database(db, "ece-run", 7)
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    assert before == after
    assert report["read_only"] is True
    assert report["cohort_count"] == 3
    assert report["counts"]["provider_precise_candidates"] == 1
    by_id = {item["job_id"]: item for item in report["jobs"]}
    assert by_id[1]["description"]["present"] is True
    assert by_id[1]["parser"]["detected"] is True
    assert by_id[2]["description"]["present"] is False
    assert by_id[2]["provider_metadata"]["recognized_precise_location_candidates"]
    assert by_id[1]["provider_metadata"]["all_location_candidates"][0]["precision"] == "city or region"
    assert by_id[2]["parser"]["detected"] is True
    assert "missing_description" not in by_id[2]["parser"]["rejection_reasons"]
    assert by_id[3]["parser"]["detected"] is False
    assert "street_like_text_has_no_nearby_workplace_cue" in by_id[3]["parser"]["rejection_reasons"]
    assert by_id[3]["original_listing_comparison"]["status"] == "not_fetched_read_only_diagnostic"


def test_cli_lists_and_writes_only_report_file(tmp_path, capsys):
    path = tmp_path / "jobs.sqlite"
    _make_db(path)
    output = tmp_path / "report.json"
    assert main(["--db", str(path), "--list-searches", "--workflow", "ece", "--output", str(output)]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["searches"][0]["search_execution_id"] == "ece-run"
    assert listed["searches"][0]["actionable_count"] == 3
    assert json.loads(output.read_text())["read_only"] is True


def test_cli_can_require_the_exact_cohort_size(tmp_path, capsys):
    path = tmp_path / "jobs.sqlite"
    _make_db(path)
    assert main(["--db", str(path), "--search-id", "ece-run", "--applicant-id", "7", "--expected-count", "3"]) == 0
    assert json.loads(capsys.readouterr().out)["cohort_count"] == 3
