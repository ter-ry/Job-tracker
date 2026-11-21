import sqlite3
import tempfile
import unittest
from pathlib import Path

from db.migrations import run_migrations
from profile_store import CandidateProfileStore
from seniority import analyze_job_seniority


class FoundationArchitectureTest(unittest.TestCase):
    def test_experience_parser_captures_years_with_work_context(self):
        analysis = analyze_job_seniority({"title": "Software Engineer", "job_description": "Requirements: 3+ years building and shipping production software."})
        self.assertEqual(analysis["required_experience"]["minimum"], 3)

    def test_experience_parser_does_not_treat_age_as_professional_experience(self):
        analysis = analyze_job_seniority({
            "title": "Software Engineering Co-op",
            "job_description": "Applicants must be 18+ years of age. Preferred: 3—5 years of software development experience.",
        })
        self.assertIsNone(analysis["required_experience"])
        self.assertEqual(analysis["preferred_experience"]["minimum"], 3)
        self.assertEqual(analysis["preferred_experience"]["maximum"], 5)

    def test_experience_parser_keeps_ambiguous_range_context(self):
        analysis = analyze_job_seniority({
            "title": "Co-op Developer",
            "job_description": "The company has 35+ years of history. Experience may be 3–5 years depending on placement.",
        })
        self.assertIsNone(analysis["required_experience"])
        self.assertTrue(analysis["ambiguous_experience"])

    def test_migrations_are_versioned_and_repeatable(self):
        db = sqlite3.connect(":memory:")
        first = run_migrations(db)
        second = run_migrations(db)
        self.assertEqual(first, 14)
        self.assertEqual(second, 14)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 14)
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
        self.assertEqual(run_migrations(db), 14)
        applied = db.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        self.assertEqual(applied, [(1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,), (9,), (10,), (11,), (12,), (13,), (14,)])
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

    def test_commute_origin_columns_are_additive_and_persist_across_reopen(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "commute.db"
            db = sqlite3.connect(database_path)
            db.row_factory = sqlite3.Row
            self.assertEqual(run_migrations(db), 14)
            profile_id = CandidateProfileStore(db).create_profile("SWE")
            db.execute(
                """UPDATE candidate_profiles SET commute_origin_input = ?, commute_origin_normalized = ?,
                   commute_origin_latitude = ?, commute_origin_longitude = ?, commute_origin_status = ? WHERE id = ?""",
                ("M2J 0B6", "M2J 0B6, Canada", "43.787", "-79.353", "saved", profile_id),
            )
            db.commit()
            db.close()
            reopened = sqlite3.connect(database_path)
            reopened.row_factory = sqlite3.Row
            profile = CandidateProfileStore(reopened).list_profiles()[0]
            self.assertEqual(profile["commute_origin_input"], "M2J 0B6")
            self.assertEqual(profile["commute_origin_status"], "saved")
            self.assertEqual(reopened.execute("PRAGMA user_version").fetchone()[0], 14)
            reopened.close()

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
