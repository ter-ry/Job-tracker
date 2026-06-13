import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module
import semantic_matching
import seniority
import tailoring


class FakeEmbeddingBackend:
    model_name = "fake-local-test-model"

    def encode(self, texts):
        vectors = []
        groups = {
            "automation": {"automation", "scripts", "workflow", "reporting"},
            "api": {"api", "apis", "flask", "backend", "integrations"},
            "cloud": {"cloud", "aws", "azure", "deployment"},
            "frontend": {"react", "javascript", "interface", "ui"},
            "unrelated": {"sales", "kitchen", "biology"},
        }
        for text in texts:
            lowered = text.lower()
            vector = []
            for terms in groups.values():
                vector.append(1.0 if any(term in lowered for term in terms) else 0.0)
            vectors.append(vector)
        return vectors


class JobAssistantTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        app_module.DATA_DIR = Path(self.tmpdir.name)
        app_module.DB_PATH = app_module.DATA_DIR / "test.sqlite"
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_profile_save_and_txt_upload(self):
        response = self.client.post(
            "/api/profile",
            json={
                "name": "Terry",
                "key_skills": "Python, Flask, React, SQL, dashboards",
                "work_authorization": "Legally authorized to work in Canada.",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["name"], "Terry")

        upload = self.client.post(
            "/api/profile/upload",
            data={"file": (io.BytesIO(b"Built Flask dashboards with SQL."), "resume.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 200)
        self.assertIn("Flask dashboards", upload.get_json()["resume_text"])

    def test_job_create_scores_and_dashboard(self):
        response = self.client.post(
            "/api/jobs",
            json={
                "company": "Northstar",
                "title": "Junior Full Stack Developer",
                "location": "Toronto hybrid",
                "salary": "$70k-$85k",
                "job_description": "Python JavaScript Flask React SQL AWS dashboards APIs internal tools",
            },
        )
        self.assertEqual(response.status_code, 201)
        job = response.get_json()
        self.assertGreaterEqual(job["fit_score"], 70)
        self.assertGreaterEqual(job["skills_match_score"], 70)

        dashboard = self.client.get("/api/dashboard").get_json()
        self.assertEqual(dashboard["jobs_saved"], 1)
        self.assertEqual(dashboard["high_fit"], 1)

    def test_generation_saves_versions_and_exports(self):
        created = self.client.post(
            "/api/jobs",
            json={
                "company": "OpsTools",
                "title": "Implementation Specialist",
                "location": "Remote Canada",
                "job_description": "APIs automation reporting business systems SQL Python",
            },
        ).get_json()
        generated = self.client.post("/api/generate", json={**created, "id": created["id"]})
        self.assertEqual(generated.status_code, 200)
        body = generated.get_json()
        self.assertIn("cover_letter", body)
        self.assertIn("resume_text", body)

        versions = self.client.get(f"/api/jobs/{created['id']}/versions").get_json()
        self.assertGreaterEqual(len(versions), 3)

        txt_export = self.client.get(f"/export/{created['id']}/cover_letter.txt")
        self.assertEqual(txt_export.status_code, 200)
        self.assertIn(b"Implementation Specialist", txt_export.data)

        docx_export = self.client.get(f"/export/{created['id']}/resume.docx")
        self.assertEqual(docx_export.status_code, 200)
        self.assertTrue(docx_export.data.startswith(b"PK"))

    def test_csv_import(self):
        csv_data = b"company,title,location,url,source,salary,description\nAcme,Cloud Support,Toronto,https://example.com,CSV,$60k,Azure SQL APIs\n"
        response = self.client.post(
            "/api/jobs/import-csv",
            data={"file": (io.BytesIO(csv_data), "jobs.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["imported"], 1)
        jobs = self.client.get("/api/jobs").get_json()
        self.assertEqual(jobs[0]["company"], "Acme")

    def test_jobspy_discovery_requires_keywords(self):
        response = self.client.post("/api/discovery/jobspy", json={"location": "Toronto"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Keywords are required", response.get_json()["error"])

    def test_jobspy_discovery_scores_saved_profile_and_handles_missing_fields(self):
        self.client.post(
            "/api/profile",
            json={
                "preferred_roles": "software developer",
                "preferred_locations": "Toronto, remote",
                "key_skills": "Python, Flask, React, SQL, APIs",
                "resume_text": "Built Flask APIs and React dashboards with SQL.",
            },
        )
        fake = {
            "jobs": [
                {
                    "source_job_id": "abc-1",
                    "title": "Junior Software Developer",
                    "company": "",
                    "location": "Toronto, Ontario",
                    "source": "linkedin",
                    "job_url": "https://example.com/job/1?utm_source=x",
                    "application_url": "https://apply.example.com/job/1",
                    "description": "Python Flask React SQL APIs dashboards",
                    "salary_text": "$70,000-$85,000",
                    "remote_type": "Hybrid",
                    "posted_date": "2026-06-10",
                }
            ],
            "errors": {},
            "source_counts": {"linkedin": 1, "indeed": 0},
        }
        with patch.object(app_module, "fetch_jobspy_jobs", return_value=fake):
            response = self.client.post(
                "/api/discovery/jobspy",
                json={"keywords": "software developer", "location": "Toronto, Ontario", "enabled_sources": ["linkedin"]},
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["total"], 1)
        job = body["jobs"][0]
        self.assertEqual(job["company"], "Unknown company")
        self.assertGreaterEqual(job["fit_score"], 70)
        self.assertIn("matched_keywords", job["score_breakdown"])
        self.assertTrue(job["description_available"])

    def test_jobspy_discovery_keeps_source_errors_and_counts(self):
        fake = {
            "jobs": [
                {
                    "source_job_id": "indeed-1",
                    "title": "Software Developer",
                    "company": "Northstar",
                    "location": "Toronto",
                    "source": "indeed",
                    "job_url": "https://indeed.example/job/1",
                    "description": "Python SQL APIs",
                }
            ],
            "errors": {"linkedin": "TimeoutError: source timed out"},
            "source_counts": {"linkedin": 0, "indeed": 1},
        }
        with patch.object(app_module, "fetch_jobspy_jobs", return_value=fake):
            response = self.client.post(
                "/api/discovery/jobspy",
                json={"keywords": "software developer", "enabled_sources": ["linkedin", "indeed"]},
            )

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["source_counts"]["indeed"], 1)
        self.assertEqual(body["source_counts"]["linkedin"], 0)
        self.assertIn("linkedin", body["errors"])
        self.assertEqual(body["total"], 1)

    def test_jobspy_discovery_deduplicates_existing_jobs(self):
        self.client.post(
            "/api/jobs",
            json={
                "company": "Acme",
                "title": "Software Developer",
                "location": "Toronto",
                "url": "https://example.com/jobs/123",
                "job_description": "Python SQL",
            },
        )
        fake = {
            "jobs": [
                {
                    "source_job_id": "1",
                    "title": "Software Developer",
                    "company": "Acme",
                    "location": "Toronto",
                    "source": "linkedin",
                    "job_url": "https://example.com/jobs/123?utm_source=linkedin",
                    "description": "Python SQL",
                },
                {
                    "source_job_id": "2",
                    "title": "Software Developer",
                    "company": "Acme",
                    "location": "Toronto",
                    "source": "indeed",
                    "job_url": "https://different.example/jobs/456",
                    "description": "Python SQL",
                },
            ],
            "errors": {},
            "source_counts": {"linkedin": 1, "indeed": 1},
        }
        with patch.object(app_module, "fetch_jobspy_jobs", return_value=fake):
            response = self.client.post("/api/discovery/jobspy", json={"keywords": "software developer"})

        body = response.get_json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["duplicates"], 2)
        self.assertTrue(body["jobs"][0]["already_saved"])

    def test_discovered_result_can_save_to_tracker_and_prevent_future_duplicate_button(self):
        fake = {
            "jobs": [
                {
                    "source_job_id": "zip-1",
                    "title": "Cloud Support Analyst",
                    "company": "OpsTools",
                    "location": "Remote Canada",
                    "source": "zip_recruiter",
                    "job_url": "https://zip.example/job/1",
                    "application_url": "https://zip.example/apply/1",
                    "description": "Azure SQL APIs technical support automation",
                    "remote_type": "Remote",
                }
            ],
            "errors": {},
            "source_counts": {"zip_recruiter": 1},
        }
        with patch.object(app_module, "fetch_jobspy_jobs", return_value=fake):
            discovery = self.client.post(
                "/api/discovery/jobspy",
                json={"keywords": "cloud support", "enabled_sources": ["zip_recruiter"]},
            ).get_json()
            saved = self.client.post("/api/jobs", json=discovery["jobs"][0])
            second = self.client.post(
                "/api/discovery/jobspy",
                json={"keywords": "cloud support", "enabled_sources": ["zip_recruiter"]},
            ).get_json()

        self.assertEqual(saved.status_code, 201)
        self.assertEqual(saved.get_json()["title"], "Cloud Support Analyst")
        self.assertTrue(second["jobs"][0]["already_saved"])
        self.assertEqual(second["duplicates"], 1)

    def test_salary_extraction_from_structured_fields(self):
        salary = app_module.determine_salary(
            {
                "salary_min": 65000,
                "salary_max": 80000,
                "salary_interval": "yearly",
                "salary_currency": "CAD",
                "job_description": "",
            }
        )
        self.assertEqual(salary["salary_source"], "structured")
        self.assertEqual(salary["salary_min"], 65000)
        self.assertEqual(salary["salary_max"], 80000)

    def test_salary_extraction_from_description_and_hourly_annualization(self):
        yearly = app_module.parse_salary_text("Compensation range: $65,000-$80,000 per year plus benefits.")
        hourly = app_module.parse_salary_text("From $30 an hour for full-time support work.")
        self.assertEqual(yearly["salary_source"], "description")
        self.assertEqual(yearly["salary_max"], 80000)
        self.assertEqual(hourly["salary_interval"], "hourly")
        self.assertEqual(hourly["salary_min"], 62400)

    def test_salary_parser_avoids_false_bonus_matches_and_estimates_missing(self):
        false_match = app_module.parse_salary_text("Includes a $5,000 signing bonus and wellness benefits.")
        estimate = app_module.determine_salary(
            {
                "title": "Software Developer",
                "location": "Toronto",
                "role_type": "software developer",
                "seniority_level": "Junior",
                "job_description": "Build APIs and dashboards.",
            }
        )
        self.assertEqual(false_match["salary_source"], "missing")
        self.assertEqual(estimate["salary_source"], "estimated")
        self.assertIn("Estimated market range", estimate["salary_text"])

    def test_revised_scoring_salary_location_dominate_and_missing_not_zero(self):
        profile = {
            "preferred_roles": "software developer",
            "preferred_locations": "Toronto, remote",
            "key_skills": "Python, SQL",
            "resume_text": "Target salary $75k. Built Python SQL tools.",
        }
        high = app_module.score_job(
            {
                "title": "Software Developer",
                "location": "Toronto hybrid",
                "remote_type": "Hybrid",
                "salary": "CAD $85,000 per year",
                "salary_min": 85000,
                "salary_max": 85000,
                "salary_source": "structured",
                "salary_confidence": 95,
                "job_description": "Python SQL APIs",
            },
            profile,
        )
        low = app_module.score_job(
            {
                "title": "Software Developer",
                "location": "Far Away",
                "remote_type": "On-site",
                "salary": "CAD $45,000 per year",
                "salary_min": 45000,
                "salary_max": 45000,
                "salary_source": "structured",
                "salary_confidence": 95,
                "job_description": "Python SQL APIs",
            },
            profile,
        )
        missing = app_module.score_job(
            {
                "title": "Software Developer",
                "location": "Toronto",
                "salary_source": "estimated",
                "salary_confidence": 38,
                "salary_min": 65000,
                "salary_max": 90000,
                "job_description": "Python SQL APIs",
            },
            profile,
        )
        self.assertGreater(high["fit_score"], low["fit_score"])
        self.assertGreater(missing["salary_score"], 0)
        self.assertEqual(high["breakdown"]["previous_formula"].startswith("salary 30%"), True)
        self.assertEqual(high["breakdown"]["weights"]["skills"], 30)

    def test_junior_profile_matched_with_zero_to_two_year_job(self):
        profile = {
            "target_seniority_levels": "junior",
            "maximum_required_years": "2",
            "willing_to_apply_to_stretch_roles": "true",
            "management_roles_allowed": "false",
        }
        job = {"title": "Junior Developer", "job_description": "Required: 0-2 years of experience building Python tools."}
        analysis = seniority.analyze_job_seniority(job)
        fit = seniority.score_seniority_fit(profile, analysis)
        self.assertEqual(analysis["detected_level"], "junior")
        self.assertGreaterEqual(fit["score"], 85)

    def test_junior_profile_penalized_for_five_plus_year_role(self):
        profile = {
            "target_seniority_levels": "junior",
            "maximum_required_years": "2",
            "willing_to_apply_to_stretch_roles": "false",
            "management_roles_allowed": "false",
        }
        job = {"title": "Software Developer", "job_description": "Minimum required 5+ years of experience with APIs."}
        fit = seniority.score_seniority_fit(profile, seniority.analyze_job_seniority(job))
        self.assertLess(fit["score"], 55)

    def test_junior_profile_strongly_penalized_for_ten_year_manager_role(self):
        profile = {
            "target_seniority_levels": "junior",
            "maximum_required_years": "2",
            "willing_to_apply_to_stretch_roles": "true",
            "management_roles_allowed": "false",
        }
        job = {
            "title": "Engineering Manager",
            "job_description": "Requires 10+ years of experience, people management, direct reports, hiring, and budget responsibility.",
        }
        fit = seniority.score_seniority_fit(profile, seniority.analyze_job_seniority(job))
        self.assertLessEqual(fit["score"], 15)
        self.assertTrue(fit["management_role"])

    def test_stretch_role_behaviour_and_management_disabled(self):
        stretch_profile = {
            "target_seniority_levels": "junior",
            "maximum_required_years": "2",
            "willing_to_apply_to_stretch_roles": "true",
            "management_roles_allowed": "false",
        }
        stretch_job = {"title": "Intermediate Developer", "job_description": "Required: 3 years of experience with Flask."}
        stretch_fit = seniority.score_seniority_fit(stretch_profile, seniority.analyze_job_seniority(stretch_job))
        self.assertTrue(stretch_fit["stretch_role"])
        self.assertGreater(stretch_fit["score"], 45)

        manager_job = {"title": "Developer Manager", "job_description": "Manage staff and run performance reviews."}
        manager_fit = seniority.score_seniority_fit(stretch_profile, seniority.analyze_job_seniority(manager_job))
        self.assertLess(manager_fit["score"], stretch_fit["score"])

    def test_title_description_disagreement_and_experience_false_positives(self):
        job = {
            "title": "Senior Software Developer",
            "job_description": "No experience required. Salary is $80,000 per year. Python 3.12. Team of 6. Founded in 2024.",
        }
        analysis = seniority.analyze_job_seniority(job)
        self.assertTrue(analysis["title_description_disagreement"])
        self.assertEqual(analysis["required_experience"]["minimum"], 0)
        self.assertFalse(any(item["minimum"] == 6 for item in analysis["ambiguous_experience"]))
        self.assertFalse(any(item["minimum"] == 2024 for item in analysis["ambiguous_experience"]))

    def test_direct_skill_match_semantic_transferable_and_unrelated_low(self):
        profile = {
            "key_skills": "Python, Flask, SQL",
            "work_experience": "Built Flask APIs and SQL reports for operations teams.",
            "projects": "Created scripts that automated weekly reporting workflows.",
        }
        job = {
            "title": "Backend Developer",
            "required_skills": "Flask APIs",
            "responsibilities": "Automate reporting workflows; maintain biology lab equipment",
        }
        result = semantic_matching.analyze_resume_match(
            job,
            profile,
            cache_dir=None,
            embedding_backend=FakeEmbeddingBackend(),
        )
        self.assertTrue(any(match["match_type"] == "direct" for match in result["matches"]))
        self.assertTrue(any("Automate reporting" in match["job_requirement"] and match["confidence"] >= 45 for match in result["matches"]))
        unrelated = [match for match in result["matches"] if "biology" in match["job_requirement"].lower()]
        self.assertTrue(unrelated)
        self.assertLess(unrelated[0]["confidence"], 45)

    def test_professional_evidence_weighted_above_project_evidence(self):
        profile = {
            "work_experience": "Built Python automation for production reporting.",
            "projects": "Built Python automation for a hobby dashboard.",
        }
        result = semantic_matching.analyze_resume_match(
            {"required_skills": "Python automation"},
            profile,
            cache_dir=None,
            embedding_backend=FakeEmbeddingBackend(),
        )
        best = result["matches"][0]
        self.assertEqual(best["evidence_source"], "professional experience")

    def test_unsupported_skill_not_added_and_original_bullet_preserved(self):
        profile = {
            "key_skills": "Python, SQL",
            "work_experience": "Built Python reports with SQL for operations teams.",
        }
        job = {"required_skills": "Kubernetes, Python", "job_description": "Use Kubernetes and Python."}
        match = semantic_matching.analyze_resume_match(job, profile, cache_dir=None, embedding_backend=FakeEmbeddingBackend())
        draft = tailoring.generate_tailored_resume_draft(
            job,
            profile,
            match,
            {"explanation": "Junior fit.", "score": 80},
        )
        self.assertIn("Built Python reports", draft["text"])
        self.assertNotIn("Built Kubernetes", draft["text"])
        self.assertTrue(all("original_bullet" in item for item in draft["rewrite_suggestions"]))

    def test_rule_based_rewrite_does_not_invent_content(self):
        original = "made Flask APIs for internal reporting"
        proposed = tailoring.controlled_rewrite(original, "Flask APIs")
        self.assertIn("Flask APIs", proposed)
        self.assertNotIn("Kubernetes", proposed)
        self.assertNotIn("%", proposed)

    def test_cache_reuse_and_sentence_transformer_fallback(self):
        cache_dir = Path(self.tmpdir.name) / "semantic_cache"
        profile = {"work_experience": "Built Flask APIs."}
        job = {"required_skills": "Flask APIs"}
        first = semantic_matching.analyze_resume_match(job, profile, cache_dir=cache_dir, embedding_backend=FakeEmbeddingBackend())
        second = semantic_matching.analyze_resume_match(job, profile, cache_dir=cache_dir, embedding_backend=FakeEmbeddingBackend())
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])

        fallback = semantic_matching.analyze_resume_match(job, profile, cache_dir=None, use_semantic=False)
        self.assertEqual(fallback["model"], "keyword-fallback")
        self.assertFalse(fallback["model_available"])

    def test_profile_changes_cause_different_score(self):
        job = {
            "title": "Junior Developer",
            "location": "Toronto",
            "job_description": "Required 2 years of experience. Python SQL APIs",
            "salary_source": "missing",
        }
        junior = {"target_seniority_levels": "junior", "maximum_required_years": "2", "key_skills": "Python, SQL"}
        senior_only = {"target_seniority_levels": "director", "maximum_required_years": "20", "key_skills": "Python, SQL"}
        self.assertNotEqual(
            app_module.score_job(job, junior)["seniority_score"],
            app_module.score_job(job, senior_only)["seniority_score"],
        )

    def seed_profile_for_documents(self):
        self.client.post(
            "/api/profile",
            json={
                "name": "Terry Mak",
                "preferred_roles": "software developer",
                "preferred_locations": "Toronto, remote",
                "key_skills": "Python, Flask, SQL, React, dashboards",
                "projects": "Built a Flask job tracker with SQLite, scoring, dashboards, and document generation.",
                "education": "Computer programming diploma, Toronto.",
                "work_experience": "Developer Intern at Northstar from 2024 to 2025. Built Python automation and SQL reports for operations teams.",
                "resume_text": "Terry Mak. Developer Intern at Northstar from 2024 to 2025. Built Python automation, Flask tools, SQL reports, React interfaces, and dashboards. Education: Computer programming diploma.",
            },
        )

    def test_shortlist_persistence_generation_safe_names_and_downloads(self):
        self.seed_profile_for_documents()
        response = self.client.post(
            "/api/shortlist",
            json={
                "company": "Acme/Tools",
                "title": "Junior Software Developer:*?",
                "location": "Toronto",
                "url": "https://example.com/job/abc",
                "application_url": "https://example.com/apply/abc",
                "source": "LinkedIn",
                "salary": "CAD $70,000-$85,000 per year",
                "job_description": "Python Flask SQL React dashboards APIs",
            },
        )
        self.assertEqual(response.status_code, 201)
        job = response.get_json()
        self.assertEqual(job["resume_generation_status"], "generated")
        self.assertEqual(job["cover_letter_generation_status"], "generated")
        resume_path = Path(job["resume_docx_path"])
        cover_path = Path(job["cover_letter_docx_path"])
        self.assertTrue(resume_path.exists())
        self.assertTrue(cover_path.exists())
        self.assertNotRegex(resume_path.name, r'[<>:"/\\|?*]')

        resume = self.client.get(f"/api/shortlist/{job['id']}/resume")
        cover = self.client.get(f"/api/shortlist/{job['id']}/cover-letter")
        self.assertEqual(resume.status_code, 200)
        self.assertEqual(cover.status_code, 200)
        self.assertTrue(resume.data.startswith(b"PK"))

        listed = self.client.get("/api/shortlist").get_json()
        self.assertEqual(len(listed), 1)

    def test_duplicate_shortlist_prevention_and_generation_failure_preserves_job(self):
        missing_profile = self.client.post(
            "/api/shortlist",
            json={
                "company": "SparseCo",
                "title": "Software Developer",
                "location": "Toronto",
                "url": "https://example.com/sparse",
                "job_description": "Python SQL",
            },
        )
        self.assertEqual(missing_profile.status_code, 201)
        first = missing_profile.get_json()
        self.assertEqual(first["resume_generation_status"], "failed")
        self.assertIn("Complete the Profile page", first["generation_error"])

        duplicate = self.client.post(
            "/api/shortlist",
            json={
                "company": "SparseCo",
                "title": "Software Developer",
                "location": "Toronto",
                "url": "https://example.com/sparse?utm_source=x",
                "job_description": "Python SQL",
            },
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.get_json()["duplicate"])
        self.assertEqual(len(self.client.get("/api/shortlist").get_json()), 1)

    def test_regeneration_after_profile_update(self):
        created = self.client.post(
            "/api/shortlist",
            json={
                "company": "LaterCo",
                "title": "Cloud Support Analyst",
                "location": "Remote Canada",
                "url": "https://example.com/later",
                "job_description": "Azure SQL APIs support automation dashboards",
            },
        ).get_json()
        self.assertEqual(created["resume_generation_status"], "failed")
        self.seed_profile_for_documents()
        regenerated = self.client.post(f"/api/shortlist/{created['id']}/regenerate", json={})
        self.assertEqual(regenerated.status_code, 200)
        job = regenerated.get_json()
        self.assertEqual(job["resume_generation_status"], "generated")
        self.assertTrue(Path(job["resume_docx_path"]).exists())


if __name__ == "__main__":
    unittest.main()
