import sqlite3
import unittest

from db.migrations import run_migrations
from profile_store import CandidateProfileStore


class FoundationArchitectureTest(unittest.TestCase):
    def test_migrations_are_versioned_and_repeatable(self):
        db = sqlite3.connect(":memory:")
        first = run_migrations(db)
        second = run_migrations(db)
        self.assertEqual(first, 2)
        self.assertEqual(second, 2)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 2)
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


if __name__ == "__main__":
    unittest.main()
