import hashlib
import sqlite3

from scripts.replay_indeed_workplace_retrieval import replay_cohort
from scripts.diagnose_ece_workplace_evidence import open_readonly


def test_read_only_indeed_replay_uses_exact_membership_and_does_not_write(tmp_path, monkeypatch):
    path = tmp_path / "qa.sqlite"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY, title TEXT, company TEXT, source TEXT, url TEXT,
            application_url TEXT, source_job_id TEXT, location TEXT, provider_location TEXT,
            provider_raw_json TEXT, job_description TEXT, workplace_address TEXT,
            workplace_postal_code TEXT, workplace_precision TEXT, workplace_evidence TEXT
        );
        CREATE TABLE discovery_search_memberships (
            search_execution_id TEXT, job_id INTEGER, applicant_profile_id INTEGER,
            category TEXT
        );
        """
    )
    db.execute(
        "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (372, "RECE", "Cityplace Daycare", "Indeed", "https://ca.indeed.com/viewjob?jk=x1", "", "in-x1", "Toronto, ON", "Toronto, ON", "{}", "", "", "", "", ""),
    )
    db.execute("INSERT INTO discovery_search_memberships VALUES (?, ?, ?, ?)", ("a" * 32, 372, 2, "actionable"))
    db.commit()
    db.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    monkeypatch.setattr(
        "scripts.replay_indeed_workplace_retrieval._fetch_once",
        lambda *args, **kwargs: {"ok": True, "status": "ok", "final_url": args[0], "body": "<h1>RECE</h1><p>Our Centre</p><p>350 Queens Quay West, Toronto, ON M5V 1A1</p>"},
    )
    with open_readonly(path) as readonly:
        report = replay_cohort(readonly, "a" * 32, 2, 1)

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert report["read_only"] is True
    assert report["network_requests"] == 1
    assert report["counts"] == {"improved": 1}
    assert report["jobs"][0]["assignment_status"] == "candidate_unverified"
    assert report["jobs"][0]["owner_confirmation_required"] is True
    assert report["jobs"][0]["retrieval_status"] == "ok"
