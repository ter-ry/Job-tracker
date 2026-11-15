"""Synthetic regressions for the P0 API evidence audit.

These records model the audit counts only; they never open or mutate a user DB.
"""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import app as app_module


class P0EvidenceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        app_module.DATA_DIR = Path(self.tmpdir.name)
        app_module.DB_PATH = app_module.DATA_DIR / "synthetic.sqlite"
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_synthetic_323_record_audit_is_reported_without_losing_reason_counts(self):
        records = ([{"category": "review_required", "distance": "missing"}] * 184
                    + [{"category": "excluded"}] * 101
                    + [{"category": "actionable"}] * 38)
        self.assertEqual(len(records), 323)
        progress = app_module._async_discovery_progress({
            "total": len(records),
            "matching_jobs": records[-38:],
            "review_required_jobs": records[:184],
            "source_counts": {"indeed": 323},
            "search_progress": {
                "requested_target": 50,
                "raw_jobs_inspected": 323,
                "fetched_raw": 323,
                "new_matching_jobs": 0,
                "review_required": 184,
                "previously_presented": 38,
                "filtered_technical": 101,
                "review_missing_distance": 151,
                "confirmed_excluded": 101,
                "target_unmet_reason": "All fetched records were previously presented, review-only, or excluded.",
            },
        })
        self.assertEqual(progress["raw_inspected"], 323)
        self.assertEqual(progress["fetched_raw"], 323)
        self.assertEqual(progress["review_required"], 184)
        self.assertEqual(progress["no_new_reason"], "All fetched records were previously presented, review-only, or excluded.")

    def test_selected_applicant_id_resolves_resume_evidence_for_shortlist(self):
        selected = {"profile": {"_candidate_profile_id": "7", "resume_text": "Python Flask SQL"}, "profile_row": {"name": "SWE"}}
        with patch.object(app_module, "resolve_tailoring_resume_profile", return_value=selected) as resolver:
            profile = app_module.resolve_discovery_evidence_profile({
                "search_mode": "shortlist", "applicant_profile_id": 7,
            })
        resolver.assert_called_once()
        self.assertEqual(profile["_candidate_profile_id"], "7")

    def test_resume_terms_produce_matched_evidence(self):
        fit = app_module.build_qualification_fit({
            "title": "Full Stack Developer",
            "job_description": "Required: Python, Flask and SQL experience.",
            "required_skills": "Python, Flask, SQL",
            "discovery_search_mode": "shortlist",
        }, {"_candidate_profile_id": "7", "resume_text": "Built Python Flask APIs with SQL databases."})
        self.assertTrue(fit["qualification_fit_matched_requirements"])
        self.assertEqual(fit["qualification_evidence_profile_id"], "7")

    def test_ottawa_geocoder_result_cannot_verify_toronto_posting(self):
        self.assertFalse(app_module.geocode_matches_advertised_city(
            {"location": "Toronto, ON", "provider_location": "30 Adelaide St"},
            {"display_name": "30 Adelaide St, Ottawa, Ontario, Canada"},
        ))
        self.assertTrue(app_module.geocode_matches_advertised_city(
            {"location": "Toronto, ON", "provider_location": "30 Adelaide St"},
            {"display_name": "30 Adelaide St, Toronto, Ontario, Canada"},
        ))

    def test_all_discovered_history_isolated_by_applicant(self):
        first = self.client.get("/api/version")
        self.assertEqual(first.status_code, 200)
        with app_module.app.app_context():
            one = app_module.normalize_job_payload({"source": "fixture", "source_job_id": "one", "title": "Software Developer", "company": "A", "location": "Toronto, ON", "job_url": "https://fixture.test/one", "discovery_first_seen_at": "2026-01-01"})
            one["candidate_profile_id"] = 11
            two = app_module.normalize_job_payload({"source": "fixture", "source_job_id": "two", "title": "Software Developer", "company": "B", "location": "Toronto, ON", "job_url": "https://fixture.test/two", "discovery_first_seen_at": "2026-01-01"})
            two["candidate_profile_id"] = 22
            app_module.persist_discovery_jobs([one, two], None, None)
        records = self.client.get("/api/discovery/inbox?applicant_profile_id=11&include_history=1").get_json()
        self.assertEqual({item["company"] for item in records}, {"A"})


if __name__ == "__main__":
    unittest.main()
