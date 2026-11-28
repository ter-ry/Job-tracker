import sqlite3

from scripts.migrate_qa_applications import apply_transfer, plan_transfer


def _db(path):
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE candidate_profiles(id INTEGER PRIMARY KEY, name TEXT, workflow TEXT);
        CREATE TABLE jobs(
          id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP, url TEXT, application_url TEXT,
          source_links_json TEXT DEFAULT '[]', source TEXT, source_job_id TEXT,
          title TEXT, company TEXT, location TEXT, date_applied TEXT DEFAULT '',
          candidate_profile_id INTEGER DEFAULT 0, status TEXT DEFAULT 'Discovered',
          discovery_first_seen_at TEXT DEFAULT 'x'
        );
        CREATE TABLE discovery_applicant_states(
          job_id INTEGER, applicant_profile_id INTEGER, state TEXT, date_applied TEXT,
          PRIMARY KEY(job_id, applicant_profile_id)
        );
    """)
    return db


def test_transfer_is_preview_first_idempotent_and_preserves_applied_date(tmp_path):
    qa_path = tmp_path / "qa.sqlite"
    production_path = tmp_path / "production.sqlite"
    qa = _db(qa_path)
    production = _db(production_path)
    qa.execute("INSERT INTO candidate_profiles VALUES (7, 'QA SWE', 'software')")
    production.execute("INSERT INTO candidate_profiles VALUES (42, 'Owner SWE', 'software')")
    qa.execute("INSERT INTO jobs(url, source, source_job_id, title, company, location, date_applied) VALUES (?, ?, ?, ?, ?, ?, ?)", ("https://jobs.example/ReqABC", "indeed", "ReqABC", "Engineer", "Acme", "Toronto", "2026-11-19"))
    qa.execute("INSERT INTO discovery_applicant_states VALUES (1, 7, 'applied', '2026-11-19')")
    qa.commit(); production.commit(); qa.close(); production.close()

    qa = sqlite3.connect(qa_path); production = sqlite3.connect(production_path)
    plan = plan_transfer(qa, production, 7, 42)
    assert plan[0]["outcome"] == "imported"
    assert production.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    production.close(); qa.close()
    report = apply_transfer(qa_path, production_path, 7, 42, plan)
    assert report["imported"] == 1
    db = sqlite3.connect(production_path)
    assert db.execute("SELECT date_applied FROM discovery_applicant_states WHERE applicant_profile_id = 42").fetchone()[0] == "2026-11-19"
    db.close()
    qa = sqlite3.connect(qa_path); production = sqlite3.connect(production_path)
    repeat = plan_transfer(qa, production, 7, 42)
    assert repeat[0]["outcome"] == "matched_existing"
    qa.close(); production.close()
