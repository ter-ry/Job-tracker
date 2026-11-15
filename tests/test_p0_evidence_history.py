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

    def test_repeat_sighting_does_not_replace_another_applicants_evidence(self):
        self.client.get("/api/health")
        with app_module.app.app_context():
            first = app_module.normalize_job_payload({
                "source": "fixture", "source_job_id": "shared", "title": "Software Developer",
                "company": "Shared", "location": "Toronto, ON", "job_url": "https://fixture.test/shared",
            })
            first.update({"candidate_profile_id": 11, "qualification_evidence_profile_id": "11", "qualification_match_score": 88})
            app_module.persist_discovery_jobs([first], None, None)
            second = {**first, "candidate_profile_id": 22, "qualification_evidence_profile_id": "22", "qualification_match_score": 12,
                      "workplace_postal_code": "M5V 1E3"}
            app_module.persist_discovery_jobs([second], None, None)
            row = app_module.query_db("SELECT candidate_profile_id, qualification_evidence_profile_id, qualification_match_score FROM jobs WHERE id = ?", [first["id"]], one=True)
        self.assertEqual(row["candidate_profile_id"], 11)
        self.assertEqual(row["qualification_evidence_profile_id"], "11")
        self.assertEqual(row["qualification_match_score"], 88)

    def test_delivery_acknowledges_only_final_actionable_results_for_its_search(self):
        self.client.get("/api/health")
        with app_module.app.app_context():
            job = app_module.normalize_job_payload({"source": "fixture", "source_job_id": "delivery", "title": "Software Developer", "company": "Delivery", "location": "Toronto, ON", "job_url": "https://fixture.test/delivery"})
            app_module.persist_discovery_jobs([job], None, None)
            app_module.get_db().execute(
                "INSERT INTO discovery_async_searches (search_id, applicant_profile_id, results_json) VALUES (?, ?, ?)",
                ["delivery-test", 11, app_module.dumps_json([{"id": job["id"], "result_stage": "qualified", "discovery_result_category": "actionable"}])],
            )
            app_module.get_db().commit()
        acknowledged = self.client.post("/api/discovery/searches/delivery-test/delivered", json={"job_ids": [job["id"], 999999]}).get_json()
        self.assertEqual(acknowledged["acknowledged"], 1)
        with app_module.app.app_context():
            self.assertTrue(app_module.applicant_presented_discovery_job(job["id"], 11))

    def test_early_career_years_evidence_reaches_authoritative_target_assessment(self):
        """101 raw records include ten 2–3-year postings that must stay eligible."""
        self.client.get("/api/health")
        raw = [
            {"source": "fixture", "source_job_id": f"junior-{index}", "title": "Junior Software Developer", "company": "Fixture", "location": "Toronto, ON", "job_url": f"https://fixture.test/junior-{index}", "seniority": "2–3 years"}
            for index in range(10)
        ] + [
            {"source": "fixture", "source_job_id": f"senior-{index}", "title": "Senior Software Developer", "company": "Fixture", "location": "Toronto, ON", "job_url": f"https://fixture.test/senior-{index}", "seniority": "8 years"}
            for index in range(91)
        ]

        def enriched(job, *_args, **_kwargs):
            junior = "junior" in job["title"].lower()
            return {**job, "role_type": "software developer", "occupation_match_type": "exact", "application_priority_score": 80,
                    "distance_radius_status": "not_checked", "location_search_eligible": True,
                    "qualification_fit_seniority": {"detected_level": "junior" if junior else "senior", "required_experience": {"minimum": 2 if junior else 8}}}

        fetched = {"jobs": raw, "errors": {}, "source_counts": {"fixture": 101}, "source_diagnostics": {}, "source_snapshots": {}, "attempted_query_batches": [], "completed_query_batches": [], "pending_query_batches": []}
        with app_module.app.app_context(), patch.object(app_module, "fetch_discovery_jobs_for_search", return_value=fetched), patch.object(app_module, "geocode_discovery_job", side_effect=lambda job, *_args, **_kwargs: (job, {})), patch.object(app_module, "enrich_discovery_job", side_effect=enriched):
            result = app_module.run_discovery_pipeline({"keywords": "software developer", "location": "Toronto, ON", "enabled_sources": ["fixture"], "search_mode": "title", "occupation": "software developer", "seniority": "entry_level,junior", "new_matching_target": 50})
        self.assertEqual(result["search_progress"]["raw_jobs_inspected"], 101)
        self.assertEqual(result["search_progress"]["early_filtered"], 0)
        self.assertEqual(len(result["matching_jobs"]), 10)
        self.assertTrue(all("Junior" in job["title"] for job in result["matching_jobs"]))


if __name__ == "__main__":
    unittest.main()
