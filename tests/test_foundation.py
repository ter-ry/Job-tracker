import sqlite3
import tempfile
import unittest
from pathlib import Path

from db.migrations import run_migrations
from profile_store import CandidateProfileStore


class FoundationArchitectureTest(unittest.TestCase):
    def test_migrations_are_versioned_and_repeatable(self):
        db = sqlite3.connect(":memory:")
        first = run_migrations(db)
        second = run_migrations(db)
        self.assertEqual(first, 3)
        self.assertEqual(second, 3)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 3)
        self.assertTrue(db.execute("SELECT 1 FROM sqlite_master WHERE name = 'base_resumes'").fetchone())

    def test_profile_store_supports_multiple_document_variants(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        run_migrations(db)
        store = CandidateProfileStore(db)
        profile_id = store.create_profile("Product profile")
        store.add_resume(profile_id, "General resume", "grounded content", is_default=True)
        store.add_resume(profile_id, "Research resume", "research content")
        store.add_cover_letter_template(profile_id, "Concise letter", "Hello {{company}}", is_default=True)
        documents = store.documents_for(profile_id)
        self.assertEqual([item["name"] for item in documents["resumes"]], ["General resume", "Research resume"])
        self.assertEqual(documents["cover_letter_templates"][0]["name"], "Concise letter")

    def test_migrations_upgrade_legacy_user_version_without_replaying_baseline(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE legacy_jobs (id INTEGER PRIMARY KEY, title TEXT)")
        db.execute("PRAGMA user_version = 1")
        self.assertEqual(run_migrations(db), 3)
        applied = db.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        self.assertEqual(applied, [(1,), (2,), (3,)])
        self.assertTrue(db.execute("SELECT 1 FROM sqlite_master WHERE name = 'legacy_jobs'").fetchone())
        self.assertTrue(db.execute("SELECT 1 FROM sqlite_master WHERE name = 'candidate_profiles'").fetchone())

    def test_candidate_identity_fields_persist_without_profile_label_leakage(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        run_migrations(db)
        store = CandidateProfileStore(db)
        profile_id = store.create_profile("SWE Resume", identity_mode="distinct", applicant_name="Alex Rivera", applicant_email="alex@example.com")
        profile = store.list_profiles()[0]
        self.assertEqual(profile["name"], "SWE Resume")
        self.assertEqual(profile["applicant_name"], "Alex Rivera")
        self.assertEqual(profile["identity_mode"], "distinct")
        updated = store.update_profile(profile_id, applicant_phone="555-0100")
        self.assertEqual(updated["applicant_phone"], "555-0100")

    def test_multiple_profiles_and_documents_persist_across_reopen(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "profiles.db"
            db = sqlite3.connect(database_path)
            db.row_factory = sqlite3.Row
            run_migrations(db)
            store = CandidateProfileStore(db)
            product_id = store.create_profile("Product profile", "Product-focused applications")
            research_id = store.create_profile("Research profile", "Research-focused applications")
            store.add_resume(product_id, "Product resume", "product evidence", is_default=True)
            store.add_cover_letter_template(research_id, "Research letter", "research evidence", is_default=True)
            db.close()

            reopened = sqlite3.connect(database_path)
            reopened.row_factory = sqlite3.Row
            profiles = CandidateProfileStore(reopened).list_profiles()
            self.assertEqual([profile["name"] for profile in profiles], ["Product profile", "Research profile"])
            self.assertEqual(CandidateProfileStore(reopened).documents_for(product_id)["resumes"][0]["name"], "Product resume")
            self.assertEqual(CandidateProfileStore(reopened).documents_for(research_id)["cover_letter_templates"][0]["name"], "Research letter")
            reopened.close()


if __name__ == "__main__":
    unittest.main()
