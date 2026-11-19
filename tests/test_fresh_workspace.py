import sqlite3

from scripts.create_fresh_workspace import create_fresh_workspace


def test_fresh_workspace_preview_and_apply_keeps_only_selected_profile(tmp_path):
    source = tmp_path / "production.sqlite"
    target = tmp_path / "Fresh QA Session" / "jobs.sqlite"
    db = sqlite3.connect(source)
    db.executescript("""
      CREATE TABLE candidate_profiles(id INTEGER PRIMARY KEY, name TEXT);
      CREATE TABLE base_resumes(id INTEGER PRIMARY KEY, profile_id INTEGER, content TEXT);
      CREATE TABLE jobs(id INTEGER PRIMARY KEY, title TEXT);
      CREATE TABLE discovery_async_searches(search_id TEXT PRIMARY KEY, status TEXT);
    """)
    db.execute("INSERT INTO candidate_profiles VALUES (1, 'SWE')")
    db.execute("INSERT INTO candidate_profiles VALUES (2, 'ECE')")
    db.execute("INSERT INTO base_resumes VALUES (1, 1, 'resume')")
    db.execute("INSERT INTO jobs VALUES (1, 'old')")
    db.execute("INSERT INTO discovery_async_searches VALUES ('old-search', 'completed')")
    db.commit(); db.close()

    preview = create_fresh_workspace(source, target, 1)
    assert preview["mode"] == "preview"
    assert not target.exists()
    create_fresh_workspace(source, target, 1, apply=True)
    db = sqlite3.connect(target)
    assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM discovery_async_searches").fetchone()[0] == 0
    assert db.execute("SELECT name FROM candidate_profiles").fetchone()[0] == "SWE"
    assert db.execute("SELECT COUNT(*) FROM base_resumes").fetchone()[0] == 1
    db.close()
