import json
import gc
import io
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
import zipfile

import app as app_module
import grounding
import ollama_client
import semantic_matching
import seniority
import tailoring_pipeline
import tailoring
import sources.jobspy_source as jobspy_source
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt


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


class FakeUrlopenResponse:
    def __init__(self, body: dict[str, object]):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


class FakeGeocodingProvider:
    name = "fake"

    def __init__(self, responses: dict[str, dict[str, object]]):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def geocode(self, query: str, *, country: str = "Canada") -> dict[str, object]:
        self.calls.append((query, country))
        if query not in self.responses:
            raise ValueError(f"No geocoding match for {query}")
        response = self.responses[query]
        if isinstance(response, Exception):
            raise response
        return response


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

    def test_profile_save_populates_evidence_library(self):
        self.client.post(
            "/api/profile",
            json={
                "name": "Terry",
                "work_experience": "Harmony 88 Co. | Backend Developer | 2023-2025. Built Python tools backed by PostgreSQL and automated monitoring.",
                "resume_text": "Harmony 88 Co. Built Python tools backed by PostgreSQL and automated monitoring. Implemented validation and logging.",
            },
        )
        evidence = self.client.get("/api/evidence").get_json()
        self.assertGreaterEqual(len(evidence), 2)
        self.assertTrue(any(item["source_kind"] == "profile" for item in evidence))
        self.assertTrue(any(item["source_kind"] == "resume_import" for item in evidence))

    def test_job_analysis_and_resume_variants_endpoints(self):
        self.client.post(
            "/api/profile",
            json={
                "name": "Terry",
                "work_experience": "Harmony 88 Co. | Backend Developer | 2023-2025. Built Python tools backed by PostgreSQL and automated monitoring.",
                "resume_text": "Harmony 88 Co. Built Python tools backed by PostgreSQL and automated monitoring. Implemented validation and logging.",
            },
        )
        job = self.client.post(
            "/api/jobs",
            json={
                "company": "Scotiabank",
                "title": "Software Developer",
                "location": "Toronto",
                "job_description": "Python PostgreSQL monitoring validation logging automation",
            },
        ).get_json()
        analysis = self.client.get(f"/api/jobs/{job['id']}/analysis").get_json()
        self.assertEqual(analysis["job_id"], job["id"])
        self.assertGreaterEqual(analysis["approved_evidence_count"], 2)
        self.assertTrue(analysis["matched_evidence"])
        variants = self.client.get(f"/api/jobs/{job['id']}/resume-variants").get_json()
        self.assertIsInstance(variants, list)

    def test_ollama_profile_defaults_and_overrides(self):
        with patch.dict(
            "os.environ",
            {
                "OLLAMA_ENABLED": "true",
                "OLLAMA_BASE_URL": "http://ollama.local:11434",
                "OLLAMA_MODEL": "llama3.1:8b",
                "OLLAMA_TIMEOUT_SECONDS": "45",
                "OLLAMA_MAX_OUTPUT_TOKENS": "777",
                "OLLAMA_MAX_PROMPT_CHARS": "11111",
            },
            clear=False,
        ):
            config = ollama_client.OllamaConfig.from_mapping({})
        self.assertTrue(config.enabled)
        self.assertEqual(config.base_url, "http://ollama.local:11434")
        self.assertEqual(config.model, "llama3.1:8b")
        self.assertEqual(config.timeout_seconds, 45)
        self.assertEqual(config.max_output_tokens, 777)
        self.assertEqual(config.max_prompt_chars, 11111)

    def test_ollama_health_reports_available_model(self):
        with patch.object(ollama_client.urllib.request, "urlopen", return_value=FakeUrlopenResponse({"models": [{"name": "qwen3:4b"}]})):
            report = ollama_client.build_ollama_health_report(
                ollama_client.OllamaConfig(
                    enabled=True,
                    base_url="http://127.0.0.1:11434",
                    model="qwen3:4b",
                    timeout_seconds=1,
                    max_output_tokens=1200,
                    max_prompt_chars=24000,
                )
            )
        self.assertTrue(report["reachable"])
        self.assertTrue(report["model_available"])
        self.assertEqual(report["status"], "ok")

    def test_ollama_health_reports_missing_model(self):
        with patch.object(ollama_client.urllib.request, "urlopen", return_value=FakeUrlopenResponse({"models": [{"name": "another-model"}]})):
            report = ollama_client.build_ollama_health_report(
                ollama_client.OllamaConfig(
                    enabled=True,
                    base_url="http://127.0.0.1:11434",
                    model="qwen3:4b",
                    timeout_seconds=1,
                    max_output_tokens=1200,
                    max_prompt_chars=24000,
                )
            )
        self.assertTrue(report["reachable"])
        self.assertFalse(report["model_available"])
        self.assertEqual(report["status"], "missing_model")
        self.assertIn("ollama pull qwen3:4b", report["summary"])

    def test_ollama_health_reports_timeout_and_disabled_state(self):
        with patch.object(ollama_client.urllib.request, "urlopen", side_effect=TimeoutError):
            report = ollama_client.build_ollama_health_report(
                ollama_client.OllamaConfig(
                    enabled=True,
                    base_url="http://127.0.0.1:11434",
                    model="qwen3:4b",
                    timeout_seconds=1,
                    max_output_tokens=1200,
                    max_prompt_chars=24000,
                )
            )
        self.assertEqual(report["status"], "timeout")
        self.assertFalse(report["reachable"])
        self.assertFalse(report["model_available"])

        disabled = ollama_client.build_ollama_health_report(
            ollama_client.OllamaConfig(
                enabled=False,
                base_url="http://127.0.0.1:11434",
                model="qwen3:4b",
                timeout_seconds=1,
                max_output_tokens=1200,
                max_prompt_chars=24000,
            )
        )
        self.assertEqual(disabled["status"], "disabled")
        self.assertFalse(disabled["reachable"])

    def test_job_create_scores_and_dashboard(self):
        self.seed_profile_for_documents(with_template=True)
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
        self.seed_profile_for_documents(with_template=True)
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

    def test_discovery_page_uses_compact_toolbar_and_full_width_layout(self):
        html = self.client.get("/").data.decode("utf-8")
        self.assertIn('id="discovery-submit">Search jobs</button>', html)
        self.assertIn('id="discovery-sort-mode"', html)
        self.assertIn('id="discovery-filter-toggle"', html)
        self.assertIn('id="discovery-filter-panel"', html)
        self.assertNotIn('id="discovery-sort-controls"', html)
        self.assertNotIn('workspace narrow', html)
        self.assertIn('workspace discovery-layout', html)
        self.assertLess(html.index('id="discovery-sort-mode"'), html.index('id="discovery-results"'))
        self.assertLess(html.index('id="discovery-results"'), html.index('id="csv-import-form"'))
        self.assertIn('id="csv-import-form"', html)

    def test_jobspy_discovery_requires_keywords(self):
        response = self.client.post("/api/discovery/jobspy", json={"location": "Toronto"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Keywords are required", response.get_json()["error"])

    def test_discovery_location_resolution_normalizes_city_and_postal_inputs(self):
        provider = FakeGeocodingProvider(
            {
                "Toronto, Ontario, Canada": {
                    "latitude": 43.6532,
                    "longitude": -79.3832,
                    "display_name": "Toronto, Ontario, Canada",
                    "ok": True,
                    "status": "saved",
                    "provider": "fake",
                    "confidence": 80,
                    "precision": "city",
                    "geocoded_at": "2026-06-20T10:00:00",
                    "normalized_query": "Toronto, Ontario, Canada",
                    "error": "",
                },
                "M2J 0B6, Canada": {
                    "latitude": 43.787,
                    "longitude": -79.353,
                    "display_name": "Toronto, Ontario, Canada",
                    "ok": True,
                    "status": "saved",
                    "provider": "fake",
                    "confidence": 95,
                    "precision": "postal code",
                    "geocoded_at": "2026-06-20T10:00:00",
                    "normalized_query": "M2J 0B6, Canada",
                    "error": "",
                },
            }
        )
        city = app_module.resolve_discovery_location_context("Toronto", {}, provider)
        toronto_on = app_module.resolve_discovery_location_context("Toronto, ON", {}, provider)
        postal = app_module.resolve_discovery_location_context("m2j0b6", {}, provider)
        self.assertEqual(city["normalized_input"], "Toronto")
        self.assertEqual(city["distance_origin"], "Toronto")
        self.assertEqual(city["discovery_location"], "Toronto, ON")
        self.assertEqual(toronto_on["normalized_input"], "Toronto, ON")
        self.assertEqual(toronto_on["discovery_location"], "Toronto, ON")
        self.assertEqual(postal["normalized_input"], "M2J 0B6")
        self.assertEqual(postal["distance_origin"], "M2J 0B6")
        self.assertEqual(postal["discovery_location"], "Toronto, ON")
        self.assertEqual(postal["resolution_method"], "postal_code_prefix_fallback")

    def test_canadian_postal_code_normalization_and_cached_profile_geocoding(self):
        self.assertEqual(app_module.normalize_canadian_postal_code("m5v2t6"), "M5V 2T6")
        self.assertEqual(app_module.extract_canadian_postal_code("Suite 400, M5V 2T6"), "M5V 2T6")
        provider = FakeGeocodingProvider(
            {
                "M5V 2T6, Canada": {
                    "ok": True,
                    "status": "saved",
                    "latitude": 43.6426,
                    "longitude": -79.3871,
                    "provider": "fake",
                    "confidence": 95,
                    "precision": "postal code",
                    "geocoded_at": "2026-06-20T10:00:00",
                    "normalized_query": "M5V 2T6, Canada",
                    "error": "",
                }
            }
        )
        with app_module.app.app_context():
            app_module.init_db()
            profile, first = app_module.geocode_profile_home_location({"location": "m5v2t6"}, provider)
            self.assertTrue(first["ok"])
            self.assertEqual(profile["home_location_normalized"], "M5V 2T6, Canada")
            self.assertEqual(profile["home_location_precision"], "postal code")
            self.assertEqual(len(provider.calls), 1)

            cached_profile, second = app_module.geocode_profile_home_location(profile, provider)
            self.assertTrue(second["ok"])
            self.assertEqual(cached_profile["home_location_normalized"], "M5V 2T6, Canada")
            self.assertEqual(len(provider.calls), 1)

    def test_invalid_canadian_postal_code_is_rejected(self):
        response = self.client.post("/api/profile", json={"location": "M5V2T"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid Canadian postal code", response.get_json()["error"])

    def test_api_health_reports_environment_diagnostics(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        body = health.get_json()
        self.assertEqual(body["sqlite_db_path"], str(app_module.DB_PATH))
        self.assertEqual(body["discovery_cache_path"], str(app_module.DB_PATH))
        self.assertEqual(body["schema_version"], 1)
        self.assertIn("python_executable", body)
        self.assertIn("python_version", body)
        self.assertIn("os", body)
        self.assertIn("jobspy_version", body)
        self.assertIn("pandas_version", body)
        self.assertIn("numpy_version", body)
        self.assertIn("cwd", body)

    def test_discovery_returns_jobs_without_profile_origin(self):
        provider = FakeGeocodingProvider(
            {
                "Toronto, Ontario, Canada": {
                    "latitude": 43.6532,
                    "longitude": -79.3832,
                    "display_name": "Toronto, Ontario, Canada",
                    "ok": True,
                    "status": "saved",
                    "provider": "fake",
                    "confidence": 80,
                    "precision": "city",
                    "geocoded_at": "2026-06-20T10:00:00",
                    "normalized_query": "Toronto, ON",
                    "error": "",
                },
            }
        )
        fake = {
            "jobs": [
                {
                    "source_job_id": "1",
                    "title": "Software Developer",
                    "company": "Northstar",
                    "location": "Toronto, ON",
                    "source": "linkedin",
                    "job_url": "https://example.com/1",
                    "description": "Python SQL APIs",
                    "posted_date": "2026-06-19",
                }
            ],
            "errors": {},
            "source_counts": {"linkedin": 1},
            "source_diagnostics": {
                "linkedin": {"source": "linkedin", "attempted": True, "success": True, "result_count": 1, "error": "", "skipped_reason": "", "duration_ms": 5, "raw_records_row_count": 1, "normalized_row_count": 1},
                "indeed": {"source": "indeed", "attempted": False, "success": False, "result_count": 0, "error": "", "skipped_reason": "disabled", "duration_ms": 0},
                "google": {"source": "google", "attempted": False, "success": False, "result_count": 0, "error": "", "skipped_reason": "disabled", "duration_ms": 0},
                "zip_recruiter": {"source": "zip_recruiter", "attempted": False, "success": False, "result_count": 0, "error": "", "skipped_reason": "disabled", "duration_ms": 0},
            },
            "source_snapshots": {"linkedin": [{"source": "linkedin", "title": "Software Developer", "company": "Northstar", "location": "Toronto, ON", "date_posted": "2026-06-19", "url": "https://example.com/1", "raw_field_types": {"title": "str"}}]},
        }
        with patch.object(app_module, "get_geocoding_provider", return_value=provider), patch.object(app_module, "fetch_jobspy_jobs", return_value=fake):
            response = self.client.post(
                "/api/discovery/jobspy",
                json={"keywords": "software developer", "location": "Toronto, ON", "enabled_sources": ["linkedin"], "bypass_cache": True},
            )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["visible_total"], 1)
        self.assertFalse(body["diagnostics"]["origin_available"])
        self.assertEqual(body["bypass_cache"], True)

    def test_discovery_source_smoke_test_reports_each_enabled_source(self):
        provider = FakeGeocodingProvider(
            {
                "Toronto, Ontario, Canada": {
                    "latitude": 43.6532,
                    "longitude": -79.3832,
                    "display_name": "Toronto, Ontario, Canada",
                    "ok": True,
                    "status": "saved",
                    "provider": "fake",
                    "confidence": 80,
                    "precision": "city",
                    "geocoded_at": "2026-06-20T10:00:00",
                    "normalized_query": "Toronto, ON",
                    "error": "",
                }
            }
        )
        fake = {
            "jobs": [],
            "errors": {"indeed": "RuntimeError: parser error"},
            "source_counts": {"linkedin": 0, "indeed": 0},
            "source_diagnostics": {
                "linkedin": {"source": "linkedin", "attempted": True, "success": True, "result_count": 0, "error": "", "skipped_reason": "", "duration_ms": 5, "raw_records_row_count": 0, "normalized_row_count": 0},
                "indeed": {"source": "indeed", "attempted": True, "success": False, "result_count": 0, "error": "RuntimeError: parser error", "skipped_reason": "", "duration_ms": 7, "raw_records_row_count": 0, "normalized_row_count": 0},
                "google": {"source": "google", "attempted": False, "success": False, "result_count": 0, "error": "", "skipped_reason": "disabled", "duration_ms": 0},
                "zip_recruiter": {"source": "zip_recruiter", "attempted": False, "success": False, "result_count": 0, "error": "", "skipped_reason": "disabled", "duration_ms": 0},
            },
            "source_snapshots": {},
        }
        with patch.object(app_module, "get_geocoding_provider", return_value=provider), patch.object(app_module, "fetch_jobspy_jobs", return_value=fake) as mocked_fetch:
            response = self.client.post(
                "/api/discovery/jobspy/test-sources",
                json={"enabled_sources": ["linkedin", "indeed"], "bypass_cache": True},
            )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["location_context"]["discovery_location"], "Toronto, ON")
        self.assertEqual(body["source_diagnostics"]["linkedin"]["attempted"], True)
        self.assertEqual(body["source_diagnostics"]["indeed"]["attempted"], True)
        self.assertEqual(body["source_diagnostics"]["indeed"]["error"], "RuntimeError: parser error")
        self.assertEqual(mocked_fetch.call_args.kwargs["location"], "Toronto, ON")
        self.assertEqual(body["source_counts"]["linkedin"], 0)

    def test_discovery_debug_latest_endpoint_returns_latest_run(self):
        provider = FakeGeocodingProvider(
            {
                "Toronto, Ontario, Canada": {
                    "latitude": 43.6532,
                    "longitude": -79.3832,
                    "display_name": "Toronto, Ontario, Canada",
                    "ok": True,
                    "status": "saved",
                    "provider": "fake",
                    "confidence": 80,
                    "precision": "city",
                    "geocoded_at": "2026-06-20T10:00:00",
                    "normalized_query": "Toronto, ON",
                    "error": "",
                },
            }
        )
        fake = {
            "jobs": [],
            "errors": {},
            "source_counts": {"linkedin": 0},
            "source_diagnostics": {
                "linkedin": {"source": "linkedin", "attempted": True, "success": True, "result_count": 0, "error": "", "skipped_reason": "", "duration_ms": 4, "raw_records_row_count": 0, "normalized_row_count": 0},
                "indeed": {"source": "indeed", "attempted": False, "success": False, "result_count": 0, "error": "", "skipped_reason": "disabled", "duration_ms": 0},
                "google": {"source": "google", "attempted": False, "success": False, "result_count": 0, "error": "", "skipped_reason": "disabled", "duration_ms": 0},
                "zip_recruiter": {"source": "zip_recruiter", "attempted": False, "success": False, "result_count": 0, "error": "", "skipped_reason": "disabled", "duration_ms": 0},
            },
            "source_snapshots": {},
        }
        with patch.object(app_module, "get_geocoding_provider", return_value=provider), patch.object(app_module, "fetch_jobspy_jobs", return_value=fake):
            self.client.post(
                "/api/discovery/jobspy",
                json={"keywords": "software developer", "location": "Toronto, ON", "enabled_sources": ["linkedin"], "bypass_cache": True},
            )
        latest = self.client.get("/api/discovery/debug/latest")
        self.assertEqual(latest.status_code, 200)
        body = latest.get_json()
        self.assertIn("source_snapshots", body)
        self.assertIn("metadata", body)
        self.assertEqual(body["metadata"]["jobs_returned_to_frontend"], 0)

    def test_toronto_city_and_job_distance_metadata_are_geocoded(self):
        provider = FakeGeocodingProvider(
            {
                "Toronto, Ontario, Canada": {
                    "latitude": 43.6532,
                    "longitude": -79.3832,
                    "display_name": "Toronto, Ontario, Canada",
                    "ok": True,
                    "status": "saved",
                    "provider": "fake",
                    "confidence": 80,
                    "precision": "city",
                    "geocoded_at": "2026-06-20T10:00:00",
                    "normalized_query": "Toronto, Ontario, Canada",
                    "error": "",
                },
                "M5V 2T6, Canada": {
                    "latitude": 43.6426,
                    "longitude": -79.3871,
                    "display_name": "M5V 2T6, Canada",
                    "ok": True,
                    "status": "saved",
                    "provider": "fake",
                    "confidence": 95,
                    "precision": "postal code",
                    "geocoded_at": "2026-06-20T10:00:00",
                    "normalized_query": "M5V 2T6, Canada",
                    "error": "",
                },
            }
        )
        with patch.object(app_module, "get_geocoding_provider", return_value=provider):
            profile_response = self.client.post("/api/profile", json={"location": "Toronto"})
        self.assertEqual(profile_response.status_code, 200)
        profile = profile_response.get_json()
        self.assertEqual(profile["home_location_normalized"], "Toronto, ON")
        self.assertEqual(profile["home_location_precision"], "city")
        self.assertEqual(profile["location_result"]["status"], "saved")

        fake = {
            "jobs": [
                {
                    "source_job_id": "job-1",
                    "title": "Software Developer",
                    "company": "Northstar",
                    "location": "M5V2T6",
                    "source": "linkedin",
                    "job_url": "https://example.com/job/1",
                    "description": "Python SQL APIs",
                    "posted_date": date(2026, 6, 19),
                }
            ],
            "errors": {},
            "source_counts": {"linkedin": 1},
        }
        with patch.object(app_module, "get_geocoding_provider", return_value=provider), patch.object(app_module, "fetch_jobspy_jobs", return_value=fake):
            response = self.client.post(
                "/api/discovery/jobspy",
                json={"keywords": "software developer", "location": "Toronto", "enabled_sources": ["linkedin"]},
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["total"], 1)
        job = body["jobs"][0]
        self.assertEqual(job["normalized_location"], "M5V 2T6, Canada")
        self.assertEqual(job["distance_label"], "approximate")
        self.assertTrue(job["distance_note"].startswith("Approx. distance from Toronto, ON"))
        self.assertGreaterEqual(job["distance_km"], 0)

    def test_discovery_jobspy_accepts_date_objects_in_raw_payloads(self):
        provider = FakeGeocodingProvider(
            {
                "Toronto, Ontario, Canada": {
                    "latitude": 43.6532,
                    "longitude": -79.3832,
                    "display_name": "Toronto, Ontario, Canada",
                    "ok": True,
                    "status": "saved",
                    "provider": "fake",
                    "confidence": 80,
                    "precision": "city",
                    "geocoded_at": "2026-06-20T10:00:00",
                    "normalized_query": "Toronto, Ontario, Canada",
                    "error": "",
                }
            }
        )
        fake = {
            "jobs": [
                {
                    "source_job_id": "job-serial",
                    "title": "Backend Developer",
                    "company": "SerialCo",
                    "location": "Toronto",
                    "source": "linkedin",
                    "job_url": "https://example.com/job/serial",
                    "description": "Python Flask SQL",
                    "posted_date": date(2026, 6, 19),
                }
            ],
            "errors": {},
            "source_counts": {"linkedin": 1},
        }
        with patch.object(app_module, "get_geocoding_provider", return_value=provider), patch.object(app_module, "fetch_jobspy_jobs", return_value=fake):
            response = self.client.post(
                "/api/discovery/jobspy",
                json={"keywords": "backend developer", "location": "Toronto", "enabled_sources": ["linkedin"]},
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["jobs"][0]["posted_date"], "2026-06-19")
        self.assertEqual(body["visible_total"], 1)

    def test_discovery_jobspy_uses_resolved_search_location_and_reports_source_diagnostics(self):
        provider = FakeGeocodingProvider(
            {
                "Toronto, Ontario, Canada": {
                    "latitude": 43.6532,
                    "longitude": -79.3832,
                    "display_name": "Toronto, Ontario, Canada",
                    "ok": True,
                    "status": "saved",
                    "provider": "fake",
                    "confidence": 80,
                    "precision": "city",
                    "geocoded_at": "2026-06-20T10:00:00",
                    "normalized_query": "Toronto, Ontario, Canada",
                    "error": "",
                },
                "M2J 0B6, Canada": {
                    "latitude": 43.787,
                    "longitude": -79.353,
                    "display_name": "Toronto, Ontario, Canada",
                    "ok": True,
                    "status": "saved",
                    "provider": "fake",
                    "confidence": 95,
                    "precision": "postal code",
                    "geocoded_at": "2026-06-20T10:00:00",
                    "normalized_query": "M2J 0B6, Canada",
                    "error": "",
                },
            }
        )
        calls: list[dict[str, object]] = []

        def fake_fetch_jobspy_jobs(**kwargs):
            calls.append(kwargs)
            return {
                "jobs": [],
                "errors": {},
                "source_counts": {"linkedin": 0, "indeed": 0},
                "source_diagnostics": {
                    "linkedin": {"source": "linkedin", "attempted": True, "success": True, "result_count": 0, "error": "", "skipped_reason": "", "duration_ms": 5, "effective_country_indeed": "Canada"},
                    "indeed": {"source": "indeed", "attempted": True, "success": True, "result_count": 0, "error": "", "skipped_reason": "", "duration_ms": 7, "effective_country_indeed": "Canada"},
                    "google": {"source": "google", "attempted": False, "success": False, "result_count": 0, "error": "", "skipped_reason": "disabled", "duration_ms": 0},
                    "zip_recruiter": {"source": "zip_recruiter", "attempted": False, "success": False, "result_count": 0, "error": "", "skipped_reason": "disabled", "duration_ms": 0},
                },
            }

        with patch.object(app_module, "get_geocoding_provider", return_value=provider), patch.object(app_module, "fetch_jobspy_jobs", side_effect=fake_fetch_jobspy_jobs):
            response = self.client.post(
                "/api/discovery/jobspy",
                json={"keywords": "Registered Early Childhood Educator", "location": "M2J0B6", "distance": 25, "enabled_sources": ["linkedin", "indeed"], "date_window": "30d"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(calls)
        self.assertEqual(calls[0]["location"], "Toronto, ON")
        self.assertEqual(calls[0]["country_indeed"], "Canada")
        body = response.get_json()
        self.assertEqual(body["search"]["original_location"], "M2J0B6")
        self.assertEqual(body["search"]["normalized_location"], "M2J 0B6")
        self.assertEqual(body["search"]["distance_origin"], "M2J 0B6")
        self.assertEqual(body["search"]["discovery_location"], "Toronto, ON")
        self.assertIn("source_diagnostics", body["diagnostics"])
        self.assertIn("indeed", body["diagnostics"]["source_diagnostics"])
        self.assertTrue(body["diagnostics"]["source_diagnostics"]["indeed"]["attempted"])

    def test_jobspy_source_diagnostics_capture_success_failure_and_disabled_sources(self):
        def fake_scrape_jobs(**kwargs):
            if kwargs["site_name"] == "linkedin":
                return [
                    {"title": "Role", "company": "A", "location": "Toronto, ON", "date_posted": "2026-06-19"}
                ]
            raise RuntimeError("parser error")

        linkedin_only = jobspy_source.fetch_jobspy_jobs(
            keywords="developer",
            location="Toronto, ON",
            distance=10,
            results_wanted=5,
            hours_old=72,
            enabled_sources=["linkedin"],
            country_indeed="Canada",
            scrape_jobs_func=fake_scrape_jobs,
        )
        self.assertEqual(linkedin_only["source_counts"]["linkedin"], 1)
        self.assertTrue(linkedin_only["source_diagnostics"]["linkedin"]["attempted"])
        self.assertFalse(linkedin_only["source_diagnostics"]["indeed"]["attempted"])
        self.assertEqual(linkedin_only["source_diagnostics"]["indeed"]["skipped_reason"], "disabled")

        indeed_only = jobspy_source.fetch_jobspy_jobs(
            keywords="developer",
            location="Toronto, ON",
            distance=10,
            results_wanted=5,
            hours_old=72,
            enabled_sources=["indeed"],
            country_indeed="Canada",
            scrape_jobs_func=fake_scrape_jobs,
        )
        self.assertTrue(indeed_only["source_diagnostics"]["linkedin"]["skipped_reason"])
        self.assertTrue(indeed_only["source_diagnostics"]["indeed"]["attempted"])
        self.assertFalse(indeed_only["source_diagnostics"]["indeed"]["success"])
        self.assertIn("parser error", indeed_only["source_diagnostics"]["indeed"]["error"])

        result = jobspy_source.fetch_jobspy_jobs(
            keywords="developer",
            location="Toronto, ON",
            distance=10,
            results_wanted=5,
            hours_old=72,
            enabled_sources=["linkedin", "indeed"],
            country_indeed="Canada",
            scrape_jobs_func=fake_scrape_jobs,
        )
        self.assertEqual(result["source_counts"]["linkedin"], 1)
        self.assertIn("indeed", result["errors"])
        self.assertTrue(result["source_diagnostics"]["linkedin"]["attempted"])
        self.assertTrue(result["source_diagnostics"]["linkedin"]["success"])
        self.assertEqual(result["source_diagnostics"]["linkedin"]["result_count"], 1)
        self.assertTrue(result["source_diagnostics"]["indeed"]["attempted"])
        self.assertFalse(result["source_diagnostics"]["indeed"]["success"])
        self.assertIn("parser error", result["source_diagnostics"]["indeed"]["error"])
        self.assertFalse(result["source_diagnostics"]["google"]["attempted"])
        self.assertEqual(result["source_diagnostics"]["google"]["skipped_reason"], "disabled")

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
        self.assertEqual(body["visible_total"], 1)
        job = body["jobs"][0]
        self.assertEqual(job["company"], "Unknown company")
        self.assertGreaterEqual(job["fit_score"], 70)
        self.assertIn("components", job["score_breakdown"])
        self.assertIn("overall_score", job["score_breakdown"])
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
        self.assertEqual(body["visible_total"], 1)

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
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["visible_total"], 1)
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

    def test_discovery_salary_normalization_and_hourly_conversion(self):
        salary = app_module.determine_salary(
            {
                "salary_text": "$30 an hour",
                "job_description": "Hourly support work",
            }
        )
        self.assertEqual(salary["salary_interval"], "hourly")
        self.assertEqual(salary["salary_min"], 62400)
        self.assertEqual(salary["salary_max"], 62400)

    def test_discovery_salary_sorting_keeps_unknowns_after_known_when_requested(self):
        jobs = [
            {
                "company": "KnownCo",
                "title": "Role A",
                "salary_min": 90000,
                "salary_max": 100000,
                "salary_midpoint": 95000,
                "salary_listed": 1,
                "distance_km": 10,
                "distance_confidence": 80,
                "overall_score": 82,
            },
            {
                "company": "UnknownCo",
                "title": "Role B",
                "salary_min": 0,
                "salary_max": 0,
                "salary_midpoint": 0,
                "salary_listed": 0,
                "distance_km": 10,
                "distance_confidence": 80,
                "overall_score": 91,
            },
        ]
        ordered = app_module.sort_discovery_jobs(jobs, "salary", "asc", unknown_salary_position="last")
        self.assertEqual(ordered[0]["company"], "KnownCo")
        self.assertEqual(ordered[1]["company"], "UnknownCo")
        ordered_first = app_module.sort_discovery_jobs(jobs, "salary", "asc", unknown_salary_position="first")
        self.assertEqual(ordered_first[0]["company"], "UnknownCo")

    def test_discovery_distance_remote_and_unknown_location_ordering(self):
        jobs = [
            {
                "company": "LocalCo",
                "title": "Role A",
                "distance_km": 5,
                "distance_confidence": 90,
                "remote_type": "",
                "overall_score": 70,
            },
            {
                "company": "RemoteCo",
                "title": "Role B",
                "distance_km": 9999,
                "distance_confidence": 95,
                "remote_type": "Remote",
                "overall_score": 70,
            },
            {
                "company": "UnknownCo",
                "title": "Role C",
                "distance_km": 9999,
                "distance_confidence": 10,
                "remote_type": "",
                "overall_score": 70,
            },
        ]
        remote_first = app_module.sort_discovery_jobs(jobs, "distance", "asc", remote_rule="remote_first")
        self.assertEqual(remote_first[0]["company"], "RemoteCo")
        remote_after_local = app_module.sort_discovery_jobs(jobs, "distance", "asc", remote_rule="remote_after_local")
        self.assertEqual(remote_after_local[-1]["company"], "UnknownCo")

    def test_discovery_newest_first_and_multi_key_sorting(self):
        jobs = [
            {"company": "B", "title": "Role", "posted_date": "2026-06-18", "overall_score": 80},
            {"company": "A", "title": "Role", "posted_date": "2026-06-19", "overall_score": 80},
            {"company": "C", "title": "Role", "posted_date": "2026-06-17", "overall_score": 90},
        ]
        ordered = app_module.sort_discovery_jobs(jobs, "posted_date", "desc", secondary_field="company", secondary_direction="asc")
        self.assertEqual([job["company"] for job in ordered], ["A", "B", "C"])

    def test_discovery_overall_score_and_explanation_totals(self):
        profile = {
            "location": "Toronto",
            "preferred_locations": "Toronto",
            "preferred_roles": "software developer",
            "key_skills": "Python, Flask, React, SQL",
            "resume_text": "Built Python Flask React SQL tools.",
        }
        job = {
            "company": "GroundedCo",
            "title": "Software Developer",
            "location": "Toronto",
            "remote_type": "Hybrid",
            "salary_min": 90000,
            "salary_max": 100000,
            "salary_midpoint": 95000,
            "salary_source": "structured",
            "salary_confidence": 95,
            "salary": "CAD $90,000-$100,000",
            "salary_listed": 1,
            "job_description": "Python Flask React SQL automation dashboards",
            "required_skills": "Python, SQL",
            "preferred_skills": "React",
            "responsibilities": "Build and maintain internal tools.",
            "posted_date": "2026-06-19",
        }
        breakdown = app_module.discovery_score_breakdown(job, profile)
        self.assertGreaterEqual(breakdown["overall_score"], 0)
        self.assertLessEqual(breakdown["overall_score"], 100)
        component_total = sum(item["score"] for item in breakdown["components"])
        penalty_total = sum(item["points"] for item in breakdown["penalties"])
        self.assertEqual(component_total - penalty_total, breakdown["overall_score"])

    def test_discovery_filters_before_sorting(self):
        jobs = [
            {"company": "SkipCo", "title": "Role A", "salary_max": 60000, "distance_km": 5, "overall_score": 90, "remote_type": "Remote", "posted_date": "2026-06-19"},
            {"company": "KeepCo", "title": "Role B", "salary_max": 90000, "distance_km": 10, "overall_score": 85, "remote_type": "Hybrid", "posted_date": "2026-06-19"},
            {"company": "LowerCo", "title": "Role C", "salary_max": 95000, "distance_km": 50, "overall_score": 60, "remote_type": "Hybrid", "posted_date": "2026-06-19"},
        ]
        filters = {"salary_min": 80000, "overall_score_min": 70, "remote_type": "Hybrid"}
        filtered = [job for job in jobs if app_module.apply_discovery_filters(job, filters)]
        ordered = app_module.sort_discovery_jobs(filtered, "salary", "desc")
        self.assertEqual([job["company"] for job in ordered], ["KeepCo"])

    def test_discovery_saved_search_sort_preferences_persist(self):
        search = {
            "keywords": "software developer",
            "location": "Toronto",
            "enabled_sources": ["linkedin"],
            "search_depth": "standard",
            "date_window": "14d",
            "per_source_cap": 100,
            "total_cap": 200,
            "sort": {"field": "salary", "direction": "asc", "secondary_field": "posted_date", "secondary_direction": "desc", "unknown_salary_position": "last", "remote_rule": "remote_after_local"},
            "filters": {"salary_min": 0, "max_distance": 0, "overall_score_min": 0, "posted_within": 0},
        }
        search_key = app_module.discovery_search_signature(search)
        self.client.post(
            "/api/discovery/preferences",
            json={"search_key": search_key, "preferences": app_module.discovery_preferences_payload(search)},
        )
        response = self.client.get(f"/api/discovery/preferences?search_key={search_key}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["preferences"]["sort"]["field"], "salary")

        fake = {
            "jobs": [
                {
                    "source_job_id": "1",
                    "title": "Role A",
                    "company": "A",
                    "location": "Toronto",
                    "source": "linkedin",
                    "job_url": "https://example.com/a",
                    "salary_text": "$120,000",
                    "salary_min": 120000,
                    "salary_max": 120000,
                    "salary_interval": "yearly",
                    "salary_currency": "CAD",
                    "posted_date": "2026-06-18",
                },
                {
                    "source_job_id": "2",
                    "title": "Role B",
                    "company": "B",
                    "location": "Toronto",
                    "source": "linkedin",
                    "job_url": "https://example.com/b",
                    "salary_text": "$80,000",
                    "salary_min": 80000,
                    "salary_max": 80000,
                    "salary_interval": "yearly",
                    "salary_currency": "CAD",
                    "posted_date": "2026-06-19",
                },
            ],
            "errors": {},
            "source_counts": {"linkedin": 2},
        }
        with patch.object(app_module, "fetch_jobspy_jobs", return_value=fake):
            result = self.client.post(
                "/api/discovery/jobspy",
                json={"keywords": "software developer", "location": "Toronto", "enabled_sources": ["linkedin"]},
            ).get_json()
        self.assertEqual(result["preferences"]["sort"]["field"], "salary")
        self.assertEqual(result["jobs"][0]["company"], "B")

    def test_discovery_search_results_are_stored_and_filtering_is_local(self):
        fake = {
            "jobs": [
                {
                    "source_job_id": "1",
                    "title": "Software Developer",
                    "company": "Scotiabank",
                    "location": "Toronto",
                    "source": "linkedin",
                    "job_url": "https://example.com/1",
                    "salary_text": "$90,000",
                    "salary_min": 90000,
                    "salary_max": 90000,
                    "salary_interval": "yearly",
                    "salary_currency": "CAD",
                    "posted_date": "2026-06-19",
                },
                {
                    "source_job_id": "2",
                    "title": "Support Analyst",
                    "company": "Scotiabank",
                    "location": "Toronto",
                    "source": "linkedin",
                    "job_url": "https://example.com/2",
                    "salary_text": "$80,000",
                    "salary_min": 80000,
                    "salary_max": 80000,
                    "salary_interval": "yearly",
                    "salary_currency": "CAD",
                    "posted_date": "2026-06-18",
                },
            ],
            "errors": {},
            "source_counts": {"linkedin": 2},
        }
        with patch.object(app_module, "fetch_jobspy_jobs", return_value=fake):
            result = self.client.post(
                "/api/discovery/jobspy",
                json={
                    "keywords": "software developer",
                    "location": "Toronto, Ontario",
                    "enabled_sources": ["linkedin"],
                    "search_depth": "thorough",
                    "date_window": "30d",
                    "per_source_cap": 250,
                    "total_cap": 500,
                    "salary_min": 70000,
                    "overall_score_min": 70,
                    "company": "Scotiabank",
                },
            ).get_json()

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["visible_total"], 2)
        self.assertIn("search", result)
        stored = self.client.get(f"/api/discovery/results?search_key={result['search_key']}").get_json()
        self.assertEqual(len(stored["jobs"]), 2)
        self.assertEqual(stored["search"]["search_depth"], "thorough")
        self.assertEqual(stored["metadata"]["raw_jobs_returned"], 2)
        self.assertTrue(stored["cache_hit"])
        self.assertEqual(stored["cached_raw_result_count"], 2)

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

    def rece_profile(self):
        return {
            "name": "Avery Chen",
            "preferred_roles": "Registered Early Childhood Educator, Early Childhood Educator",
            "key_skills": "child-centred programming, play-based learning, developmental observation, family communication, health and safety compliance, inclusive practice, teamwork",
            "work_experience": "Registered Early Childhood Educator at Little Pines Child Care. Planned child-centred and play-based programming, completed developmental observation and documentation, maintained health and safety compliance, communicated with families, and supported inclusive classroom routines.",
            "education": "Early Childhood Education diploma.",
            "projects": "",
            "resume_text": "",
        }

    def software_profile(self, extra_skills=""):
        skills = "Python, SQL, Flask, cloud, automation"
        if extra_skills:
            skills = f"{skills}, {extra_skills}"
        return {
            "name": "Terry Mak",
            "preferred_roles": "software developer",
            "key_skills": skills,
            "work_experience": "Software developer with Python automation, Flask APIs, SQL reports, and cloud deployment experience.",
            "projects": "Built Flask tools for reporting and automation.",
            "education": "Computer programming diploma.",
            "resume_text": "Built Python, SQL, Flask, cloud, and automation projects.",
        }

    def ece_job(self):
        return {
            "company": "Little Sprouts",
            "title": "Early Childhood Educator",
            "required_skills": "child-centred programming, developmental observation, family communication, health and safety compliance",
            "job_description": "Plan play-based learning, document development, communicate with families, and maintain safe inclusive classrooms.",
        }

    def software_job(self, required="Python, SQL, Flask, cloud, automation"):
        return {
            "company": "BuildCo",
            "title": "Software Developer",
            "required_skills": required,
            "job_description": f"Build software using {required}.",
        }

    def scotiabank_job(self):
        return {
            "company": "Scotiabank",
            "title": "Software Developer",
            "location": "Toronto, ON",
            "required_skills": "Develop and maintain software applications, write well-designed testable REST APIs, software documentation, collaboration with developers, product managers, and designers, version control and Git branching, production troubleshooting, software reliability, sprint objectives and project milestones, backend integrations, database design, cloud platforms",
            "preferred_skills": "Node.js, Express, JavaScript, Agile, Scrum, microservice architecture, unit and integration testing",
            "responsibilities": "Build backend integrations, support production incident troubleshooting, document release steps, and deliver project milestones with cross-functional teams.",
            "job_description": "Develop and maintain software applications and REST APIs, collaborate with developers, product managers, and designers, support production troubleshooting, strengthen software reliability, and contribute to sprint objectives and project milestones. The role also values cloud platform work, database design, technical documentation, and backend integrations.",
        }

    def test_rece_profile_does_not_generate_software_terminology(self):
        output = app_module.generate_application_materials(self.ece_job(), self.rece_profile())
        combined = "\n".join([output["resume_text"], output["cover_letter"], app_module.answers_to_text(output["short_answers"])])
        self.assertIn("Registered Early Childhood Educator", combined)
        self.assertIn("child-centred", combined)
        self.assertNotRegex(combined.lower(), r"\b(aws|python|flask|react|sql|dashboard|api|cloud|software projects)\b")

    def test_software_profile_can_generate_supported_software_terms(self):
        output = app_module.generate_application_materials(self.software_job(), self.software_profile())
        combined = "\n".join([output["resume_text"], output["cover_letter"]])
        self.assertIn("Python", combined)
        self.assertIn("Flask", combined)
        self.assertIn("software developer", combined.lower())

    def test_aws_suggestion_requires_candidate_evidence(self):
        without_aws = app_module.generate_application_materials(self.software_job("AWS, Python"), self.software_profile())
        self.assertIn("aws", [item.lower() for item in without_aws["unsupported_keywords"]])
        self.assertNotIn("AWS", without_aws["skill_guidance"]["supported_relevant"])

        with_aws = app_module.generate_application_materials(self.software_job("AWS, Python"), self.software_profile("AWS"))
        self.assertIn("AWS", with_aws["skill_guidance"]["supported_relevant"])

    def test_corrupted_pdf_text_detected_and_rejected(self):
        noisy_pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Page /FontName /CIDFont /XObject >>\nstream\n\\x00\\xff\\x10FFFFAAAAFFFFAAAAFFFFAAAAFFFF\nendstream\nendobj\nxref\ntrailer\nstartxref"
        with self.assertRaisesRegex(ValueError, "This PDF could not be read reliably"):
            app_module.extract_pdf_text(noisy_pdf)

    def test_structured_profile_used_when_pdf_extraction_fails(self):
        profile = self.rece_profile()
        profile["resume_text"] = "endobj xref trailer stream glyph CIDFont FFFFEEEEFFFFEEEE"
        output = app_module.generate_application_materials(self.ece_job(), profile)
        self.assertIn("developmental observation", output["resume_text"])
        self.assertNotIn("CIDFont", output["resume_text"])

    def test_cross_domain_generation_blocks_unsupported_terms(self):
        with self.assertRaisesRegex(ValueError, "Unsupported or conflicting phrases"):
            app_module.generate_application_materials(self.software_job(), self.rece_profile())

    def test_cache_invalidation_after_profile_change(self):
        job = self.software_job()
        first = semantic_matching.analyze_resume_match(job, self.software_profile(), cache_dir=None, use_semantic=False)
        second = semantic_matching.analyze_resume_match(job, self.software_profile("AWS"), cache_dir=None, use_semantic=False)
        self.assertNotEqual(first["profile_resume_hash"], second["profile_resume_hash"])

    def test_generated_versions_mark_outdated_after_profile_change(self):
        self.seed_profile_for_documents(with_template=True)
        created = self.client.post(
            "/api/jobs",
            json={"company": "OpsTools", "title": "Software Developer", "job_description": "Python SQL Flask"},
        ).get_json()
        generated = self.client.post("/api/generate", json={**created, "id": created["id"]})
        self.assertEqual(generated.status_code, 200)
        self.client.post("/api/profile", json={**self.rece_profile(), "name": "New Profile"})
        versions = self.client.get(f"/api/jobs/{created['id']}/versions").get_json()
        self.assertTrue(any(version["status"] == "Outdated — regenerate using current profile" for version in versions))

    def test_tailored_resume_preserves_master_docx_formatting(self):
        self.seed_profile_for_documents(with_template=True)
        profile = self.client.get("/api/profile").get_json()
        master_path = Path(profile["resume_docx_template_path"])
        master_before = master_path.read_bytes()
        created = self.client.post(
            "/api/shortlist",
            json={
                "company": "Northstar",
                "title": "Software Developer",
                "location": "Toronto",
                "url": "https://example.com/job/format",
                "job_description": "Python Flask SQL React dashboards cloud automation",
            },
        ).get_json()
        self.assertEqual(created["resume_generation_status"], "generated")
        resume_path = Path(created["resume_docx_path"])
        self.assertEqual(master_before, master_path.read_bytes())

        master_doc = Document(io.BytesIO(master_path.read_bytes()))
        tailored_doc = Document(io.BytesIO(resume_path.read_bytes()))

        self.assertEqual(len(master_doc.sections), len(tailored_doc.sections))
        self.assertEqual(len(master_doc.paragraphs), len(tailored_doc.paragraphs))
        self.assertEqual(len(master_doc.tables), len(tailored_doc.tables))

        self.assertEqual(master_doc.paragraphs[0].style.name, tailored_doc.paragraphs[0].style.name)
        self.assertEqual(master_doc.paragraphs[0].text, tailored_doc.paragraphs[0].text)

        self.assertNotEqual(master_doc.paragraphs[2].text, tailored_doc.paragraphs[2].text)
        self.assertEqual(master_doc.paragraphs[2].runs[0].font.name, tailored_doc.paragraphs[2].runs[0].font.name)
        self.assertEqual(master_doc.paragraphs[2].runs[0].font.size.pt, tailored_doc.paragraphs[2].runs[0].font.size.pt)

        self.assertEqual(master_doc.paragraphs[5].style.name, "List Bullet")
        self.assertEqual(tailored_doc.paragraphs[5].style.name, "List Bullet")
        self.assertNotEqual(master_doc.paragraphs[5].text, tailored_doc.paragraphs[5].text)
        self.assertIn("Built Python automation", tailored_doc.paragraphs[5].text)
        self.assertEqual(master_doc.paragraphs[6].text, tailored_doc.paragraphs[6].text)
        self.assertEqual(master_doc.paragraphs[8].style.name, tailored_doc.paragraphs[8].style.name)
        self.assertNotEqual(master_doc.paragraphs[8].text, tailored_doc.paragraphs[8].text)
        self.assertEqual(tailored_doc.paragraphs[8].text, "Skills: Python, Flask, SQL, React, dashboards, cloud")

        self.assertEqual(tailored_doc.tables[0].cell(1, 1).text, "Flask, React")
        self.assertEqual(tailored_doc.tables[1].cell(1, 1).text, "Computer programming diploma")
        with zipfile.ZipFile(resume_path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
        self.assertNotIn("Suggested summary", xml)
        self.assertIn("w:hyperlink", xml)

    def test_resume_without_summary_keeps_protected_paragraphs_and_changes_only_bullet_text(self):
        self.seed_profile_for_documents(with_template=True, resume_template="no_summary")
        profile = self.client.get("/api/profile").get_json()
        master_path = Path(profile["resume_docx_template_path"])
        master_before = master_path.read_bytes()
        created = self.client.post(
            "/api/shortlist",
            json={
                "company": "Northstar",
                "title": "Software Developer",
                "location": "Toronto",
                "url": "https://example.com/job/no-summary",
                "job_description": "Python Flask SQL React dashboards cloud automation",
            },
        ).get_json()
        self.assertEqual(created["resume_generation_status"], "generated")
        resume_path = Path(created["resume_docx_path"])
        change_log = json.loads((resume_path.parent / "resume_change_log.json").read_text(encoding="utf-8"))
        self.assertTrue(any(item.get("reason") == "Skipped summary tailoring: no existing summary section" for item in change_log["skipped"]))
        self.assertEqual(master_before, master_path.read_bytes())

        master_doc = Document(io.BytesIO(master_path.read_bytes()))
        tailored_doc = Document(io.BytesIO(resume_path.read_bytes()))
        self.assertEqual(len(master_doc.paragraphs), len(tailored_doc.paragraphs))
        self.assertEqual(len(master_doc.tables), len(tailored_doc.tables))
        self.assertEqual(master_doc.paragraphs[0].style.name, tailored_doc.paragraphs[0].style.name)
        self.assertEqual(master_doc.paragraphs[0].text, tailored_doc.paragraphs[0].text)

        protected_texts = [
            "Terry Mak",
            "terry@example.com | LinkedIn | GitHub",
            "Software Developer | Northstar Labs | 2021-2025",
            "George Brown College",
            "Computer programming diploma | 2023",
            "Work Experience",
            "Education",
            "Skills",
            "Portfolio: example.com/portfolio",
        ]
        for text_value in protected_texts:
            self.assertIn(text_value, [paragraph.text for paragraph in master_doc.paragraphs])
            self.assertIn(text_value, [paragraph.text for paragraph in tailored_doc.paragraphs])

        master_bullet = next(paragraph for paragraph in master_doc.paragraphs if paragraph.text.startswith("made Python automation"))
        tailored_bullet = next(paragraph for paragraph in tailored_doc.paragraphs if "Built Python automation" in paragraph.text)
        self.assertEqual(master_bullet.style.name, tailored_bullet.style.name)
        self.assertNotEqual(master_bullet.text, tailored_bullet.text)
        self.assertIn("Built Python automation", tailored_bullet.text)

        xml = zipfile.ZipFile(resume_path).read("word/document.xml").decode("utf-8", errors="ignore")
        self.assertNotIn("Suggested summary", xml)
        self.assertNotIn("analysis", xml.lower())

    def test_resume_tailoring_makes_grounded_ats_edits_for_python_developer_job(self):
        self.seed_python_developer_profile()
        self.upload_resume_template(self.build_python_developer_resume_fixture())
        profile = self.client.get("/api/profile").get_json()
        master_path = Path(profile["resume_docx_template_path"])
        master_before = master_path.read_bytes()

        created = self.client.post(
            "/api/shortlist",
            json={
                "company": "Northstar",
                "title": "Python Developer",
                "location": "Toronto",
                "url": "https://example.com/job/python-dev",
                "job_description": "Python SQL database design AWS Linux testing debugging documentation collaboration",
            },
        ).get_json()

        self.assertEqual(created["resume_generation_status"], "generated")
        resume_path = Path(created["resume_docx_path"])
        self.assertEqual(master_before, master_path.read_bytes())

        change_log = json.loads((resume_path.parent / "resume_change_log.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(change_log["summary"]["total_editable_paragraphs"], 6)
        self.assertGreaterEqual(change_log["summary"]["total_proposed_changes"], 4)
        self.assertGreaterEqual(change_log["summary"]["total_applied_changes"], 4)
        self.assertLessEqual(change_log["summary"]["total_applied_changes"], 6)
        self.assertGreaterEqual(change_log["summary"]["total_skipped_changes"], 1)
        self.assertTrue(any(item.get("applied") for item in change_log["applied"]))
        self.assertTrue(any(item.get("skip_reason") for item in change_log["skipped"]))

        tailored_doc = Document(io.BytesIO(resume_path.read_bytes()))
        tailored_text = "\n".join(paragraph.text for paragraph in tailored_doc.paragraphs)
        self.assertIn("George Brown College", tailored_text)
        self.assertIn("Software Developer | Northstar Labs | 2021-2025", tailored_text)
        self.assertIn("Computer programming diploma | 2023", tailored_text)
        self.assertIn("validation, logging", tailored_text.lower())
        self.assertIn("Strengthened software reliability by implementing validation, logging, and data-cleaning logic that detected malformed inputs and reduced manual data-entry errors by 90%.", tailored_text)
        self.assertIn("database structures and data models", tailored_text)
        self.assertIn("cross-functional data workflows using Retool and Google Docs", tailored_text)

        skills_line = next(paragraph.text for paragraph in tailored_doc.paragraphs if paragraph.text.startswith("Skills:"))
        self.assertTrue(skills_line.startswith("Skills: Python, SQL, AWS, Linux"))
        self.assertIn("documentation", skills_line.lower())
        self.assertIn("collaboration", skills_line.lower())

        bullet_texts = [paragraph.text for paragraph in tailored_doc.paragraphs if getattr(getattr(paragraph, "style", None), "name", "").startswith("List")]
        self.assertTrue(any("Strengthened software reliability by implementing validation, logging, and data-cleaning logic that detected malformed inputs and reduced manual data-entry errors by 90%." in text for text in bullet_texts))
        self.assertTrue(any("database structures and data models" in text for text in bullet_texts))
        self.assertTrue(any("cross-functional data workflows using Retool and Google Docs" in text for text in bullet_texts))

        opened = Document(io.BytesIO(resume_path.read_bytes()))
        self.assertGreater(len(opened.paragraphs), 0)

    def test_scotiabank_resume_tailoring_makes_meaningful_supported_edits(self):
        self.seed_python_developer_profile()
        self.upload_resume_template(self.build_python_developer_resume_fixture())
        profile = self.client.get("/api/profile").get_json()
        master_path = Path(profile["resume_docx_template_path"])
        master_doc = Document(io.BytesIO(master_path.read_bytes()))
        master_before = master_path.read_bytes()

        created = self.client.post(
            "/api/shortlist",
            json=self.scotiabank_job(),
        ).get_json()

        self.assertEqual(created["resume_generation_status"], "generated")
        resume_path = Path(created["resume_docx_path"])
        self.assertEqual(master_before, master_path.read_bytes())
        change_log = json.loads((resume_path.parent / "resume_change_log.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(change_log["summary"]["total_applied_changes"], 3)
        self.assertLessEqual(change_log["summary"]["total_applied_changes"], 6)
        self.assertGreaterEqual(change_log["summary"]["total_skipped_changes"], 1)
        self.assertTrue(
            all(
                re.sub(r"[^a-z0-9]+", "", item["original"].lower())
                != re.sub(r"[^a-z0-9]+", "", item["replacement"].lower())
                for item in change_log["applied"]
            )
        )
        meaningful_applied = [
            item
            for item in change_log["applied"]
            if any(
                phrase in item["replacement"].lower()
                for phrase in [
                    "strengthened software reliability by implementing validation, logging, and data-cleaning logic",
                    "database structures and data models",
                    "backend integrations and data workflows",
                    "collaborated with cross-functional",
                    "technical documentation",
                ]
            )
        ]
        self.assertGreaterEqual(len(meaningful_applied), 2)

        tailored_doc = Document(io.BytesIO(resume_path.read_bytes()))
        changed_paragraphs = [
            {
                "index": index,
                "base": base.text,
                "tailored": tailored.text,
                "style": getattr(getattr(base, "style", None), "name", "") or "",
            }
            for index, (base, tailored) in enumerate(zip(master_doc.paragraphs, tailored_doc.paragraphs))
            if base.text != tailored.text
        ]
        substantive_bullet_changes = [
            item for item in changed_paragraphs if item["style"].startswith("List") and not tailoring.is_cosmetic_only_change(item["base"], item["tailored"])
        ]
        self.assertGreaterEqual(len(substantive_bullet_changes), 2)
        tailored_text = "\n".join(paragraph.text for paragraph in tailored_doc.paragraphs)
        self.assertIn("database structures and data models", tailored_text)
        self.assertIn("Strengthened software reliability by implementing validation, logging, and data-cleaning logic that detected malformed inputs and reduced manual data-entry errors by 90%.", tailored_text)
        self.assertIn("collaborated with cross-functional teammates", tailored_text.lower())
        self.assertIn("cross-functional data workflows", tailored_text.lower())
        self.assertNotIn("saved profile", tailored_text.lower())

    def test_scotiabank_requirements_rank_and_map_to_grounded_evidence(self):
        self.seed_python_developer_profile()
        self.upload_resume_template(self.build_python_developer_resume_fixture())
        profile = self.client.get("/api/profile").get_json()
        job = self.scotiabank_job()
        match = semantic_matching.analyze_resume_match(job, profile, cache_dir=None, use_semantic=False)
        plan = tailoring_pipeline.build_tailoring_plan(job, profile, match)

        ranked = plan["ranked_requirements"]
        self.assertGreaterEqual(len(ranked), 8)
        self.assertEqual(ranked[0]["source_field"], "required_skills")
        self.assertTrue(any("database" in item["phrase"].lower() for item in ranked[:5]))
        self.assertTrue(any("testing" in item["phrase"].lower() or "document" in item["phrase"].lower() for item in ranked[:8]))

        inventory = plan["requirement_evidence_inventory"]
        self.assertGreaterEqual(len(inventory), 5)
        top_match = inventory[0]
        self.assertIn("requirement", top_match)
        self.assertIn("matched_source_bullet", top_match)
        self.assertIn("match_reason", top_match)
        self.assertIn("supported_technologies", top_match)
        self.assertIn("supported_outcome", top_match)
        self.assertGreaterEqual(top_match["confidence"], 40)
        self.assertTrue(any("database structures" in item["matched_source_bullet"].lower() or "validation" in item["matched_source_bullet"].lower() for item in inventory))

    def test_controlled_rewrite_rejects_cosmetic_only_changes(self):
        original = "Built supplier specific items and data entry workflows for operations."
        rewritten = tailoring.controlled_rewrite(
            original,
            "database design",
            evidence_text=original,
            section="projects",
        )
        self.assertEqual(rewritten, original)

    def test_cover_letter_template_upload_and_placeholder_replacement(self):
        self.seed_profile_for_documents(with_template=True)
        profile = self.client.get("/api/profile").get_json()
        master_path = self.build_cover_letter_template_fixture()
        master_before = master_path.read_bytes()
        payload = self.upload_cover_letter_template(master_path)
        self.assertEqual(payload["cover_letter_template_status"], "DOCX template uploaded")

        created = self.client.post(
            "/api/shortlist",
            json={
                "company": "Northstar",
                "title": "Python Developer",
                "location": "Toronto",
                "url": "https://example.com/job/cover-template",
                "job_description": "Python Flask SQL React dashboards cloud automation",
            },
        ).get_json()
        self.assertEqual(created["cover_letter_generation_status"], "generated")
        cover_path = Path(created["cover_letter_docx_path"])
        self.assertEqual(master_before, master_path.read_bytes())

        master_doc = Document(io.BytesIO(master_path.read_bytes()))
        cover_doc = Document(io.BytesIO(cover_path.read_bytes()))
        master_text = "\n".join(paragraph.text for paragraph in master_doc.paragraphs)
        cover_text = "\n".join(paragraph.text for paragraph in cover_doc.paragraphs)
        self.assertIn("{{DATE}}", master_text)
        self.assertNotIn("{{DATE}}", cover_text)
        self.assertNotIn("{{OPENING_PARAGRAPH}}", cover_text)
        self.assertIn("Northstar Hiring Team", cover_text)
        self.assertIn("Sincerely", cover_text)
        self.assertEqual(master_doc.paragraphs[0].style.name, cover_doc.paragraphs[0].style.name)
        self.assertEqual(master_doc.paragraphs[-1].alignment, cover_doc.paragraphs[-1].alignment)
        self.assertEqual(master_doc.paragraphs[-1].text, cover_doc.paragraphs[-1].text)

    def test_cover_letter_validation_uses_body_boundaries_for_contact_details(self):
        evidence = grounding.build_candidate_evidence(self.software_profile())
        header_safe = (
            "Terry Mak\n"
            "terry@example.com | Toronto, ON | linkedin.com/in/terrymak\n\n"
            "June 17, 2026\n\n"
            "Scotiabank - Toronto, ON\n\n"
            "Dear Scotiabank Hiring Team,\n\n"
            "I built Python Flask applications backed by SQL and documented workflows.\n\n"
            "Sincerely,\n"
            "Terry Mak"
        )
        header_validation = grounding.validate_cover_letter_output(header_safe, evidence, self.software_job())
        self.assertTrue(header_validation["ok"])

        body_leak = (
            "Terry Mak\n"
            "terry@example.com | Toronto, ON | linkedin.com/in/terrymak\n\n"
            "June 17, 2026\n\n"
            "Scotiabank - Toronto, ON\n\n"
            "Dear Scotiabank Hiring Team,\n\n"
            "I built Python Flask applications backed by SQL. Contact me at terry@example.com for details.\n\n"
            "Sincerely,\n"
            "Terry Mak"
        )
        body_validation = grounding.validate_cover_letter_output(body_leak, evidence, self.software_job())
        self.assertFalse(body_validation["ok"])
        self.assertTrue(any("Contact details detected in body paragraph" in item for item in body_validation["conflicting_phrases"]))

    def test_scotiabank_cover_letter_template_preserves_structure_and_replaces_stale_content(self):
        self.seed_profile_for_documents(with_template=True)
        self.upload_resume_template(self.build_python_developer_resume_fixture())
        master_path = self.build_software_cover_letter_fixture()
        master_before = master_path.read_bytes()
        payload = self.upload_cover_letter_template(master_path)
        self.assertEqual(payload["cover_letter_template_status"], "DOCX template uploaded")

        created = self.client.post(
            "/api/shortlist",
            json=self.scotiabank_job(),
        ).get_json()
        self.assertEqual(created["cover_letter_generation_status"], "generated")
        self.assertIn("tailoring_changes", created)
        self.assertGreaterEqual(len(created["tailoring_changes"]["resume"]["applied"]), 1)
        self.assertGreaterEqual(len(created["tailoring_changes"]["cover_letter"]["applied"]), 1)
        cover_path = Path(created["cover_letter_docx_path"])
        self.assertEqual(master_before, master_path.read_bytes())

        cover_doc = Document(io.BytesIO(cover_path.read_bytes()))
        paragraphs = [paragraph.text for paragraph in cover_doc.paragraphs if paragraph.text.strip()]
        joined = "\n".join(paragraphs)
        body_start = next(index for index, text in enumerate(paragraphs) if text.startswith("I'm excited"))
        body_end = next(index for index, text in enumerate(paragraphs) if text.startswith("Thank you"))
        body_paragraphs = paragraphs[body_start:body_end]
        body_text = " ".join(body_paragraphs)
        self.assertRegex(paragraphs[0], r"\b[A-Z][a-z]+ \d{1,2}, \d{4}\b")
        self.assertIn("Scotiabank Hiring Team", joined)
        self.assertIn("Dear Scotiabank Hiring Team,", joined)
        self.assertIn("I'm excited to apply for the Software Developer role at Scotiabank", joined)
        self.assertNotIn("CentralSquare", joined)
        self.assertNotIn("Software Developer Co-op", joined)
        self.assertNotIn("Remote - Ontario", joined)
        self.assertNotIn("8- or 12-month term", joined)
        self.assertNotIn("8/12-month", joined)
        self.assertNotIn("saved profile", joined.lower())
        self.assertNotIn("ATS-oriented", joined)
        self.assertNotIn("grounded wording", joined)
        self.assertNotIn("practical experience that aligns", joined.lower())
        self.assertNotIn("together, these examples", joined.lower())
        self.assertNotIn("Python, JavaScript, Flask, React, SQL, cloud, AWS, Azure, dashboards, automation, APIs, reporting. This is the kind of work I would bring to Scotiabank.", joined)
        self.assertEqual(len(body_paragraphs), 3)
        self.assertGreaterEqual(len(body_text.split()), 180)
        self.assertLessEqual(len(body_text.split()), 260)
        self.assertIn("Developer Intern at Northstar", joined)
        self.assertEqual(sum(1 for text in paragraphs if re.search(r"\b[A-Z][a-z]+ \d{1,2}, \d{4}\b", text)), 1)
        self.assertEqual(sum(1 for text in paragraphs if text == "Sincerely,"), 1)
        self.assertEqual(paragraphs[-2], "Sincerely,")
        self.assertEqual(paragraphs[-1], "Terry Mak")
        self.assertIsNone(app_module.validate_cover_letter_document(cover_doc, self.scotiabank_job(), {"name": "Terry Mak"}))
        self.assertTrue(created["generation_debug"].get("generated_at"))

    def test_scotiabank_cover_letter_rewrites_all_visible_template_content(self):
        self.seed_profile_for_documents(with_template=True)
        self.upload_resume_template(self.build_python_developer_resume_fixture())
        master_path = self.build_centralsquare_cover_letter_fixture()
        self.upload_cover_letter_template(master_path)

        created = self.client.post(
            "/api/shortlist",
            json=self.scotiabank_job(),
        ).get_json()
        cover_path = Path(created["cover_letter_docx_path"])
        cover_doc = Document(io.BytesIO(cover_path.read_bytes()))
        visible_text = "\n".join(paragraph.text for paragraph in app_module.iter_document_paragraphs(cover_doc) if paragraph.text.strip())

        self.assertEqual(created["cover_letter_generation_status"], "generated")
        self.assertNotIn("CentralSquare", visible_text)
        self.assertNotIn("Software Developer Co-op", visible_text)
        self.assertNotIn("Remote - Ontario", visible_text)
        self.assertNotIn("8- or 12-month term", visible_text)
        self.assertNotIn("hochitterry.mak@georgebrown.ca", visible_text)
        self.assertIn("Scotiabank Hiring Team", visible_text)
        self.assertIn("I'm excited to apply for the Software Developer role at Scotiabank", visible_text)
        self.assertIn("Developer Intern at Northstar", visible_text)
        self.assertNotIn("Retool and Google Docs", visible_text)
        self.assertIsNone(app_module.validate_cover_letter_document(cover_doc, self.scotiabank_job(), {"name": "Terry Mak"}))

        downloaded = self.client.get(f"/api/shortlist/{created['id']}/cover-letter")
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.data, cover_path.read_bytes())

    def test_cover_letter_validation_reports_hidden_metadata_location(self):
        source = self.build_cover_letter_template_fixture()
        hidden = Path(self.tmpdir.name) / "cover_letter_template_hidden_metadata.docx"
        with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(hidden, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "docProps/core.xml":
                    data = data.replace(b"python-docx", b"python-docx CentralSquare")
                zout.writestr(item, data)

        doc = Document(io.BytesIO(hidden.read_bytes()))
        warning = app_module.validate_cover_letter_document(doc, self.software_job(), {"name": "Terry Mak"})
        self.assertIsNotNone(warning)
        self.assertIn("metadata part docProps/core.xml", warning)

    def test_cover_letter_no_template_fallback_and_validation_guards(self):
        self.seed_profile_for_documents(with_template=True)
        created = self.client.post(
            "/api/shortlist",
            json={
                "company": "Northstar",
                "title": "Python Developer",
                "location": "Toronto",
                "url": "https://example.com/job/cover-fallback",
                "job_description": "Python Flask SQL React dashboards cloud automation",
            },
        ).get_json()
        self.assertEqual(created["cover_letter_generation_status"], "generated")
        cover_path = Path(created["cover_letter_docx_path"])
        cover_doc = Document(io.BytesIO(cover_path.read_bytes()))
        cover_paragraphs = [paragraph.text.strip() for paragraph in cover_doc.paragraphs if paragraph.text.strip()]
        cover_text = "\n".join(cover_paragraphs)
        cover_body_start = next(index for index, text in enumerate(cover_paragraphs) if text.startswith("I'm excited"))
        cover_body_end = next(index for index, text in enumerate(cover_paragraphs) if text.startswith("Thank you"))
        cover_body = cover_paragraphs[cover_body_start:cover_body_end]
        self.assertIn("Dear Northstar Hiring Team", cover_text)
        self.assertIn("Sincerely", cover_text)
        self.assertNotIn("EDUCATION", cover_text)
        self.assertNotIn("SKILLS", cover_text)
        self.assertNotIn("EXPERIENCE", cover_text)
        self.assertNotIn("PROJECTS", cover_text)
        self.assertEqual(len(cover_body), 3)
        self.assertGreaterEqual(len(" ".join(cover_body).split()), 180)
        self.assertLessEqual(len(" ".join(cover_body).split()), 260)
        self.assertLessEqual(max(len(paragraph.text) for paragraph in cover_doc.paragraphs), 400)
        self.assertNotIn("Terry Mak. Developer Intern at Northstar", cover_text)

        bad_validation = grounding.validate_cover_letter_output(
            "EDUCATION\nSKILLS\nEXPERIENCE\nPROJECTS",
            grounding.build_candidate_evidence(self.rece_profile()),
            self.ece_job(),
        )
        self.assertFalse(bad_validation["ok"])
        self.assertTrue(any("Resume section dump detected" in item for item in bad_validation["conflicting_phrases"]))

        prose_validation = grounding.validate_cover_letter_output(
            "I built Python and Flask applications backed by SQL and used validation, logging, and data-cleaning logic to improve reliability.",
            grounding.build_candidate_evidence(self.software_profile()),
            self.software_job(),
        )
        self.assertTrue(prose_validation["ok"])

        keyword_validation = grounding.validate_cover_letter_output(
            "Python, Flask, SQL, AWS, Linux, React, JavaScript, APIs, cloud, dashboards, automation.",
            grounding.build_candidate_evidence(self.software_profile("AWS")),
            self.software_job("AWS, Python"),
        )
        self.assertFalse(keyword_validation["ok"])
        self.assertTrue(any("Raw keyword list detected" in item for item in keyword_validation["conflicting_phrases"]))

        section_dump_validation = grounding.validate_cover_letter_output(
            "Skills\nPython Flask SQL\nExperience\nBuilt reports.",
            grounding.build_candidate_evidence(self.software_profile()),
            self.software_job(),
        )
        self.assertFalse(section_dump_validation["ok"])
        self.assertTrue(any("Resume section dump detected" in item for item in section_dump_validation["conflicting_phrases"]))

        long_paragraph = "Python " * 90
        length_validation = grounding.validate_cover_letter_output(
            long_paragraph,
            grounding.build_candidate_evidence(self.rece_profile()),
            self.ece_job(),
        )
        self.assertFalse(length_validation["ok"])

    def test_cover_letter_template_falls_back_for_unrelated_retail_content(self):
        self.seed_profile_for_documents(with_template=True)
        retail_template = self.build_retail_cover_letter_fixture()
        payload = self.upload_cover_letter_template(retail_template)
        self.assertEqual(payload["cover_letter_template_status"], "DOCX template uploaded")

        created = self.client.post(
            "/api/shortlist",
            json={
                "company": "Northstar",
                "title": "Python Developer",
                "location": "Toronto",
                "url": "https://example.com/job/cover-retail",
                "job_description": "Python Flask SQL React dashboards cloud automation",
            },
        ).get_json()
        self.assertEqual(created["cover_letter_generation_status"], "generated")
        self.assertIn("incompatible role-specific content", created["cover_letter_generation_warning"])

        cover_doc = Document(io.BytesIO(Path(created["cover_letter_docx_path"]).read_bytes()))
        cover_text = "\n".join(paragraph.text for paragraph in cover_doc.paragraphs)
        self.assertNotIn("supermarket", cover_text.lower())
        self.assertNotIn("customer service", cover_text.lower())
        self.assertIn("Northstar Hiring Team", cover_text)

    def test_shortlist_restore_reuses_existing_row_and_regenerates_documents(self):
        self.seed_profile_for_documents(with_template=True)
        created = self.client.post(
            "/api/shortlist",
            json={
                "company": "RestorableCo",
                "title": "Software Developer",
                "location": "Toronto",
                "url": "https://example.com/job/restorable",
                "job_description": "Python Flask SQL React dashboards cloud automation",
            },
        ).get_json()
        job_id = created["id"]

        removed = self.client.delete(f"/api/shortlist/{job_id}").get_json()
        self.assertTrue(removed["restored_to_saved"])
        self.assertEqual(self.client.get("/api/shortlist").get_json(), [])

        restored = self.client.post(
            "/api/shortlist",
            json={
                "company": "RestorableCo",
                "title": "Software Developer",
                "location": "Toronto",
                "url": "https://example.com/job/restorable?utm_source=search",
                "job_description": "Python Flask SQL React dashboards cloud automation",
            },
        )
        self.assertEqual(restored.status_code, 200)
        restored_job = restored.get_json()
        self.assertTrue(restored_job["restored"])
        self.assertEqual(restored_job["id"], job_id)
        self.assertEqual(len(self.client.get("/api/shortlist").get_json()), 1)
        self.assertEqual(restored_job["resume_generation_status"], "generated")
        self.assertEqual(restored_job["cover_letter_generation_status"], "generated")

    def test_cover_failure_does_not_block_resume_download(self):
        self.seed_profile_for_documents(with_template=True)
        with patch.object(app_module, "build_format_preserving_cover_letter", side_effect=RuntimeError("cover exploded")):
            created = self.client.post(
                "/api/shortlist",
                json={
                    "company": "SplitCo",
                    "title": "Software Developer",
                    "location": "Toronto",
                    "url": "https://example.com/job/split-cover",
                    "job_description": "Python Flask SQL React dashboards cloud automation",
                },
            ).get_json()
        self.assertEqual(created["resume_generation_status"], "generated")
        self.assertEqual(created["cover_letter_generation_status"], "failed")
        self.assertIn("cover exploded", created["cover_letter_generation_error"])
        self.assertTrue(Path(created["resume_docx_path"]).exists())
        self.assertEqual(self.client.get(f"/api/shortlist/{created['id']}/resume").status_code, 200)
        self.assertEqual(self.client.get(f"/api/shortlist/{created['id']}/cover-letter").status_code, 404)

    def test_resume_failure_does_not_block_cover_download(self):
        self.seed_profile_for_documents(with_template=True)
        with patch.object(app_module, "build_format_preserving_resume", side_effect=RuntimeError("resume exploded")):
            created = self.client.post(
                "/api/shortlist",
                json={
                    "company": "SplitCo",
                    "title": "Software Developer",
                    "location": "Toronto",
                    "url": "https://example.com/job/split-resume",
                    "job_description": "Python Flask SQL React dashboards cloud automation",
                },
            ).get_json()
        self.assertEqual(created["resume_generation_status"], "failed")
        self.assertEqual(created["cover_letter_generation_status"], "generated")
        self.assertIn("resume exploded", created["resume_generation_error"])
        self.assertTrue(Path(created["cover_letter_docx_path"]).exists())
        self.assertEqual(self.client.get(f"/api/shortlist/{created['id']}/resume").status_code, 404)
        self.assertEqual(self.client.get(f"/api/shortlist/{created['id']}/cover-letter").status_code, 200)

    def test_failed_regeneration_preserves_previous_successful_documents(self):
        self.seed_profile_for_documents(with_template=True)
        created = self.client.post(
            "/api/shortlist",
            json={
                "company": "RecoveryCo",
                "title": "Software Developer",
                "location": "Toronto",
                "url": "https://example.com/job/recovery",
                "job_description": "Python Flask SQL React dashboards cloud automation",
            },
        ).get_json()
        previous_resume = Path(created["resume_docx_path"])
        previous_cover = Path(created["cover_letter_docx_path"])
        with patch.object(app_module, "build_format_preserving_resume", side_effect=RuntimeError("resume retry failed")), patch.object(
            app_module, "build_format_preserving_cover_letter", side_effect=RuntimeError("cover retry failed")
        ):
            regenerated = self.client.post(f"/api/shortlist/{created['id']}/regenerate", json={}).get_json()

        self.assertEqual(regenerated["resume_generation_status"], "failed")
        self.assertEqual(regenerated["cover_letter_generation_status"], "failed")
        self.assertEqual(Path(regenerated["resume_docx_path"]), previous_resume)
        self.assertEqual(Path(regenerated["cover_letter_docx_path"]), previous_cover)
        self.assertTrue(previous_resume.is_file())
        self.assertTrue(previous_cover.is_file())
        self.assertEqual(self.client.get(f"/api/shortlist/{created['id']}/resume").status_code, 200)
        self.assertEqual(self.client.get(f"/api/shortlist/{created['id']}/cover-letter").status_code, 200)

    def test_pdf_only_profile_cannot_request_format_preserving_export(self):
        self.client.post(
            "/api/profile",
            json={
                "name": "Sparse Profile",
                "resume_text": "Built Python reports with SQL.",
                "work_experience": "Supported families, planned play-based learning, and completed developmental observation and documentation in a classroom setting.",
                "preferred_roles": "software developer",
                "key_skills": "Python, SQL",
            },
        )
        created = self.client.post(
            "/api/shortlist",
            json={
                "company": "SparseCo",
                "title": "Software Developer",
                "location": "Toronto",
                "url": "https://example.com/sparse",
                "job_description": "Python SQL Flask",
            },
        ).get_json()
        self.assertEqual(created["resume_generation_status"], "failed")
        self.assertIn("Upload a DOCX resume", created["generation_error"])

    def test_output_docx_is_readable(self):
        self.seed_profile_for_documents(with_template=True)
        created = self.client.post(
            "/api/shortlist",
            json={
                "company": "Northstar",
                "title": "Software Developer",
                "location": "Toronto",
                "url": "https://example.com/job/readable",
                "job_description": "Python Flask SQL React dashboards cloud automation",
            },
        ).get_json()
        resume_path = Path(created["resume_docx_path"])
        opened = Document(io.BytesIO(resume_path.read_bytes()))
        self.assertGreater(len(opened.paragraphs), 0)
        self.assertIn("Terry Mak", opened.paragraphs[0].text)

    def test_shortlist_can_generate_from_selected_candidate_profile_documents(self):
        self.seed_profile_for_documents(with_template=True)
        current_profile = self.client.get("/api/profile").get_json()
        created_profile = self.client.post(
            "/api/candidate-profiles",
            json={"name": "SWE Resume", "description": "Python developer with documented API and SQL project experience.", "identity_mode": "distinct", "applicant_name": "Alex Rivera"},
        )
        self.assertEqual(created_profile.status_code, 201)
        profile_id = created_profile.get_json()["id"]
        resume_response = self.client.post(
            f"/api/candidate-profiles/{profile_id}/resumes",
            json={
                "name": "Alternate base resume",
                "content": "Python developer with documented API and SQL project experience and reliable testing practices.",
                "docx_path": current_profile["resume_docx_template_path"],
                "is_default": True,
            },
        )
        self.assertEqual(resume_response.status_code, 201)
        created = self.client.post(
            "/api/shortlist",
            json={
                "company": "ProfileCo",
                "title": "Python Developer",
                "location": "Toronto",
                "url": "https://example.com/job/profile-selection",
                "job_description": "Python SQL API testing",
                "candidate_profile_id": profile_id,
            },
        )
        self.assertEqual(created.status_code, 201)
        job = created.get_json()
        self.assertEqual(job["resume_generation_status"], "generated")
        self.assertEqual(job["cover_letter_generation_status"], "generated")
        self.assertIn("Alex_Rivera", Path(job["resume_docx_path"]).name)
        cover_text = "\n".join(paragraph.text for paragraph in Document(io.BytesIO(Path(job["cover_letter_docx_path"]).read_bytes())).paragraphs)
        self.assertIn("Alex Rivera", cover_text)
        self.assertNotIn("SWE Resume", cover_text)

    def test_selected_candidate_profile_isolated_from_legacy_and_other_profiles(self):
        self.seed_profile_for_documents(with_template=True)
        legacy = self.client.post(
            "/api/profile",
            json={
                "name": "Legacy Candidate",
                "work_experience": "LegacyCorp maintained legacy systems and legacy customer workflows.",
                "resume_text": "LegacyCorp maintained legacy systems and legacy customer workflows.",
            },
        )
        self.assertEqual(legacy.status_code, 200)
        profiles = []
        for name, evidence in [
            ("Profile Alpha", "Alpha Systems built Python APIs and automated reporting for finance teams with careful validation."),
            ("Profile Beta", "Beta Labs managed unrelated Java services and mobile release operations."),
        ]:
            created_profile = self.client.post("/api/candidate-profiles", json={"name": name, "description": evidence})
            self.assertEqual(created_profile.status_code, 201)
            profile_id = created_profile.get_json()["id"]
            resume_response = self.client.post(
                f"/api/candidate-profiles/{profile_id}/resumes",
                json={
                    "name": f"{name} resume",
                    "content": evidence + " This work included documented tests and reliable handoffs for maintainers.",
                    "docx_path": str(self.build_formatted_resume_fixture()),
                    "is_default": True,
                },
            )
            self.assertEqual(resume_response.status_code, 201)
            profiles.append(profile_id)

        created = self.client.post(
            "/api/shortlist",
            json={
                "company": "Alpha Hiring",
                "title": "Python Developer",
                "location": "Toronto",
                "url": "https://example.com/job/profile-isolation",
                "job_description": "Python APIs validation reporting testing",
                "candidate_profile_id": profiles[0],
            },
        )
        self.assertEqual(created.status_code, 201)
        job = created.get_json()
        resume_text = "\n".join(paragraph.text for paragraph in Document(io.BytesIO(Path(job["resume_docx_path"]).read_bytes())).paragraphs)
        cover_text = "\n".join(paragraph.text for paragraph in Document(io.BytesIO(Path(job["cover_letter_docx_path"]).read_bytes())).paragraphs)
        self.assertIn("Alpha Systems", resume_text + cover_text)
        self.assertNotIn("LegacyCorp", resume_text + cover_text)
        self.assertNotIn("Beta Labs", resume_text + cover_text)

    def test_selected_document_validation_and_preview_are_actionable(self):
        self.seed_profile_for_documents(with_template=True)
        created_profile = self.client.post(
            "/api/candidate-profiles",
            json={"name": "Incomplete profile", "description": "A profile with enough documented evidence for a useful generation error."},
        )
        profile_id = created_profile.get_json()["id"]
        invalid = self.client.post(
            "/api/shortlist",
            json={
                "company": "Invalid Selection Co",
                "title": "Developer",
                "location": "Toronto",
                "job_description": "Python testing",
                "candidate_profile_id": profile_id,
                "resume_id": 999999,
            },
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("resume_id", invalid.get_json()["error"])

        valid = self.client.post(
            "/api/shortlist",
            json={
                "company": "Preview Co",
                "title": "Python Developer",
                "location": "Toronto",
                "job_description": "Python Flask SQL testing",
            },
        )
        self.assertEqual(valid.status_code, 201)
        job = valid.get_json()
        preview = self.client.get(f"/api/shortlist/{job['id']}/preview")
        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview.get_json()["resume"])
        self.assertTrue(preview.get_json()["cover_letter"])

    def test_generated_cover_letter_uses_current_date_and_default_no_dash_preference(self):
        self.seed_profile_for_documents(with_template=True)
        created = self.client.post(
            "/api/shortlist",
            json={
                "company": "Current Date Co",
                "title": "Python Developer",
                "location": "Toronto",
                "job_description": "Python Flask SQL testing",
            },
        )
        self.assertEqual(created.status_code, 201)
        cover_doc = Document(io.BytesIO(Path(created.get_json()["cover_letter_docx_path"]).read_bytes()))
        cover_text = "\n".join(paragraph.text for paragraph in app_module.iter_document_paragraphs(cover_doc))
        self.assertRegex(cover_text, rf"{date.today().strftime('%B')}\s+0?{date.today().day},\s+{date.today().year}")
        self.assertNotRegex(cover_text, r"[-–—]")

    def test_profile_label_does_not_replace_shared_or_distinct_applicant_identity(self):
        self.seed_profile_for_documents(with_template=True)
        shared_profile = self.client.post(
            "/api/candidate-profiles",
            json={"name": "Business Applications", "description": "Python application delivery and testing.", "identity_mode": "shared"},
        ).get_json()
        shared_resume = self.client.post(
            f"/api/candidate-profiles/{shared_profile['id']}/resumes",
            json={"name": "Shared resume", "content": "Python application delivery and testing with documented handoffs.", "docx_path": self.client.get("/api/profile").get_json()["resume_docx_template_path"], "is_default": True},
        )
        self.assertEqual(shared_resume.status_code, 201)
        shared_job = self.client.post(
            "/api/shortlist",
            json={"company": "Shared Co", "title": "Developer", "job_description": "Python testing", "candidate_profile_id": shared_profile["id"]},
        ).get_json()
        shared_cover = "\n".join(paragraph.text for paragraph in Document(io.BytesIO(Path(shared_job["cover_letter_docx_path"]).read_bytes())).paragraphs)
        self.assertIn("Terry Mak", shared_cover)
        self.assertNotIn("Business Applications", shared_cover)

        distinct = self.client.post(
            "/api/candidate-profiles",
            json={"name": "SWE Resume", "description": "Python application delivery and testing.", "identity_mode": "distinct", "applicant_name": "Jordan Lee", "applicant_email": "jordan@example.com"},
        ).get_json()
        distinct_resume = self.client.post(
            f"/api/candidate-profiles/{distinct['id']}/resumes",
            json={"name": "Jordan resume", "content": "Python application delivery and testing with documented handoffs.", "docx_path": self.client.get("/api/profile").get_json()["resume_docx_template_path"], "is_default": True},
        )
        self.assertEqual(distinct_resume.status_code, 201)
        distinct_job = self.client.post(
            "/api/shortlist",
            json={"company": "Distinct Co", "title": "Developer", "job_description": "Python testing", "candidate_profile_id": distinct["id"]},
        ).get_json()
        distinct_cover = "\n".join(paragraph.text for paragraph in Document(io.BytesIO(Path(distinct_job["cover_letter_docx_path"]).read_bytes())).paragraphs)
        distinct_resume_text = "\n".join(paragraph.text for paragraph in Document(io.BytesIO(Path(distinct_job["resume_docx_path"]).read_bytes())).paragraphs)
        self.assertIn("Jordan Lee", distinct_cover + distinct_resume_text)
        self.assertNotIn("SWE Resume", distinct_cover + distinct_resume_text)

    def test_keyword_only_evidence_does_not_create_fabricated_achievements(self):
        self.client.post(
            "/api/profile",
            json={"name": "Evidence Candidate", "resume_text": "Monitoring validation with PostgreSQL and routine reporting.", "work_experience": "Monitoring validation with PostgreSQL and routine reporting."},
        )
        self.upload_master_resume_template()
        created = self.client.post(
            "/api/shortlist",
            json={"company": "Evidence Co", "title": "Developer", "job_description": "monitoring validation PostgreSQL"},
        ).get_json()
        cover = "\n".join(paragraph.text for paragraph in Document(io.BytesIO(Path(created["cover_letter_docx_path"]).read_bytes())).paragraphs)
        self.assertNotIn("300,000", cover)
        self.assertNotIn("90%", cover)
        self.assertNotIn("Harmony 88", cover)
        self.assertIn("Monitoring validation with PostgreSQL", cover)

    def test_preview_matches_successful_docx_and_survives_failed_retry(self):
        self.seed_profile_for_documents(with_template=True)
        created = self.client.post(
            "/api/shortlist",
            json={"company": "Preview Co", "title": "Developer", "location": "Toronto", "job_description": "Python testing"},
        ).get_json()
        preview_before = self.client.get(f"/api/shortlist/{created['id']}/preview").get_json()
        downloaded_resume = self.client.get(f"/api/shortlist/{created['id']}/resume")
        downloaded_cover = self.client.get(f"/api/shortlist/{created['id']}/cover-letter")
        def docx_text(payload: bytes) -> str:
            document = Document(io.BytesIO(payload))
            value = "\n".join(paragraph.text for paragraph in app_module.iter_document_paragraphs(document) if paragraph.text.strip())
            del document
            return value
        self.assertEqual(preview_before["resume_source"], "successful_docx")
        self.assertEqual(preview_before["cover_letter_source"], "successful_docx")
        self.assertEqual(preview_before["resume"], docx_text(downloaded_resume.data))
        self.assertEqual(preview_before["cover_letter"], docx_text(downloaded_cover.data))
        self.assertNotRegex(docx_text(downloaded_cover.data), r"[-–—]")
        with patch.object(app_module, "build_format_preserving_resume", side_effect=RuntimeError("resume retry failed")), patch.object(app_module, "build_format_preserving_cover_letter", side_effect=RuntimeError("cover retry failed")):
            failed = self.client.post(f"/api/shortlist/{created['id']}/regenerate", json={}).get_json()
        self.assertEqual(failed["resume_generation_status"], "failed")
        self.assertEqual(failed["cover_letter_generation_status"], "failed")
        preview_after = self.client.get(f"/api/shortlist/{created['id']}/preview").get_json()
        self.assertEqual(preview_after["resume"], preview_before["resume"])
        self.assertEqual(preview_after["cover_letter"], preview_before["cover_letter"])
        self.assertEqual(self.client.get(f"/api/shortlist/{created['id']}/resume").status_code, 200)
        self.assertEqual(self.client.get(f"/api/shortlist/{created['id']}/cover-letter").status_code, 200)
        gc.collect()

    def test_empty_projects_or_education_do_not_fabricate(self):
        profile = self.rece_profile()
        profile["projects"] = ""
        profile["education"] = ""
        output = app_module.generate_application_materials(self.ece_job(), profile)
        self.assertNotIn("project", output["summary"].lower())
        self.assertNotIn("education", output["summary"].lower())

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

    def seed_profile_for_documents(self, with_template: bool = False, resume_template: str = "formatted"):
        self.client.post(
            "/api/profile",
            json={
                "name": "Terry Mak",
                "preferred_roles": "software developer",
                "preferred_locations": "Toronto, remote",
                "key_skills": "Python, Flask, SQL, React, dashboards, cloud",
                "projects": "Built a Flask job tracker with SQLite, scoring, dashboards, and document generation.",
                "education": "Computer programming diploma, Toronto.",
                "work_experience": "Developer Intern at Northstar from 2024 to 2025. Built Python automation, cloud deployment notes, and SQL reports for operations teams.",
                "resume_text": "Terry Mak. Developer Intern at Northstar from 2024 to 2025. made Python automation, Flask tools, SQL reports, React interfaces, and dashboards. Education: Computer programming diploma.",
            },
        )
        if with_template:
            if resume_template == "no_summary":
                self.upload_resume_template(self.build_resume_without_summary_fixture())
            else:
                self.upload_master_resume_template()

    def seed_python_developer_profile(self):
        self.client.post(
            "/api/profile",
            json={
                "name": "Terry Mak",
                "preferred_roles": "software developer",
                "preferred_locations": "Toronto, remote",
                "key_skills": "Python, SQL, database design, AWS, Linux, testing, debugging, documentation, collaboration, Flask, React, cloud",
                "projects": "Built a Python inventory tool with database design, AWS deployment scripts, Linux server checks, testing, and documentation for a small operations team.",
                "education": "Computer programming diploma, George Brown College.",
                "work_experience": "Software Developer at Northstar Labs from 2021 to 2025. Implemented robust validation, logging, and data cleaning logic to detect malformed inputs and reduce manual data entry errors by 90%. Designed data models and application logic for products, supplier specific items, and pricing records. Built backend integrations with real-time data from Retool and Google Docs for operations reporting and handoffs. Worked with cross-functional teammates to debug issues and document release steps.",
                "resume_text": "Terry Mak. Software Developer at Northstar Labs from 2021 to 2025. Implemented robust validation, logging, and data cleaning logic to detect malformed inputs and reduce manual data entry errors by 90%. Designed data models and application logic for products, supplier specific items, and pricing records. Built backend integrations with real-time data from Retool and Google Docs for operations reporting and handoffs. Worked with cross-functional teammates to debug issues and document release steps. Education: Computer programming diploma, George Brown College.",
            },
        )

    def upload_master_resume_template(self):
        self.upload_resume_template(self.build_formatted_resume_fixture())

    def upload_resume_template(self, master: Path):
        with open(master, "rb") as handle:
            response = self.client.post(
                "/api/profile/upload",
                data={"file": (handle, "master_resume.docx")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("resume_docx_template_path", response.get_json())

    def upload_cover_letter_template(self, master: Path):
        with open(master, "rb") as handle:
            response = self.client.post(
                "/api/profile/upload",
                data={"file": (handle, "cover_letter_template.docx"), "template_kind": "cover_letter"},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("cover_letter_docx_template_path", payload)
        return payload

    def build_formatted_resume_fixture(self):
        path = Path(self.tmpdir.name) / "master_resume_fixture.docx"
        doc = Document()
        section = doc.sections[0]
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.85)
        section.right_margin = Inches(0.85)

        title = doc.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title.add_run("Terry Mak")
        run.bold = True
        run.font.name = "Aptos"
        run.font.size = Pt(18)

        summary_heading = doc.add_paragraph()
        summary_heading.style = "Heading 1"
        summary_heading.add_run("Professional Summary")
        summary = doc.add_paragraph()
        summary_run = summary.add_run("Software developer with Python automation and SQL reporting experience.")
        summary_run.font.name = "Georgia"
        summary_run.font.size = Pt(11)

        experience_heading = doc.add_paragraph()
        experience_heading.style = "Heading 1"
        experience_heading.add_run("Work Experience")
        experience = doc.add_paragraph()
        experience.add_run("Software Developer").bold = True
        experience.add_run(" | Northstar Labs | 2021-2025")

        bullet1 = doc.add_paragraph(style="List Bullet")
        bullet1.add_run("made Python automation, Flask tools, SQL reports, React interfaces, and dashboards.")
        bullet2 = doc.add_paragraph(style="List Bullet")
        bullet2_run1 = bullet2.add_run("Maintained team documentation standards")
        bullet2_run1.italic = True
        bullet2.add_run(" across internal projects.")

        skills_heading = doc.add_paragraph()
        skills_heading.style = "Heading 1"
        skills_heading.add_run("Skills")
        skills = doc.add_paragraph()
        skills.add_run("Skills: ").bold = True
        skills.add_run("React, dashboards, Python, SQL, Flask, cloud")

        categories = doc.add_table(rows=2, cols=3)
        categories.style = "Table Grid"
        categories.cell(0, 0).text = "Languages"
        categories.cell(0, 1).text = "Technologies"
        categories.cell(0, 2).text = "Tools & Platforms"
        categories.cell(1, 0).text = "Python, SQL"
        categories.cell(1, 1).text = "Flask, React"
        categories.cell(1, 2).text = "cloud, dashboards"

        contact = doc.add_paragraph()
        contact.add_run("Portfolio: ")
        self.add_hyperlink(contact, "https://example.com/portfolio", "example.com/portfolio")

        table = doc.add_table(rows=2, cols=2)
        table.style = "Table Grid"
        table.cell(0, 0).text = "Category"
        table.cell(0, 1).text = "Detail"
        table.cell(1, 0).text = "Certification"
        table.cell(1, 1).text = "Computer programming diploma"

        doc.save(path)
        return path

    def build_resume_without_summary_fixture(self):
        path = Path(self.tmpdir.name) / "resume_without_summary_fixture.docx"
        doc = Document()
        section = doc.sections[0]
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.85)
        section.right_margin = Inches(0.85)

        title = doc.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title.add_run("Terry Mak")
        run.bold = True
        run.font.name = "Aptos"
        run.font.size = Pt(18)

        contact = doc.add_paragraph()
        contact.add_run("terry@example.com | LinkedIn | GitHub")

        experience_heading = doc.add_paragraph()
        experience_heading.style = "Heading 1"
        experience_heading.add_run("Work Experience")
        experience = doc.add_paragraph()
        experience.add_run("Software Developer").bold = True
        experience.add_run(" | Northstar Labs | 2021-2025")

        bullet1 = doc.add_paragraph(style="List Bullet")
        bullet1.add_run("made Python automation, Flask tools, SQL reports, React interfaces, and dashboards.")
        bullet2 = doc.add_paragraph(style="List Bullet")
        bullet2.add_run("Maintained team documentation standards across internal projects.")

        education_heading = doc.add_paragraph()
        education_heading.style = "Heading 1"
        education_heading.add_run("Education")
        college = doc.add_paragraph()
        college.add_run("George Brown College")
        diploma = doc.add_paragraph()
        diploma.add_run("Computer programming diploma | 2023")

        skills_heading = doc.add_paragraph()
        skills_heading.style = "Heading 1"
        skills_heading.add_run("Skills")
        skills = doc.add_paragraph()
        skills.add_run("Python, Flask, SQL, React")

        contact_two = doc.add_paragraph()
        contact_two.add_run("Portfolio: example.com/portfolio")

        doc.save(path)
        return path

    def build_python_developer_resume_fixture(self):
        path = Path(self.tmpdir.name) / "python_developer_resume_fixture.docx"
        doc = Document()
        section = doc.sections[0]
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.85)
        section.right_margin = Inches(0.85)

        title = doc.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title.add_run("Terry Mak")
        run.bold = True
        run.font.name = "Aptos"
        run.font.size = Pt(18)

        contact = doc.add_paragraph()
        contact.add_run("terry@example.com | LinkedIn | GitHub")

        summary_heading = doc.add_paragraph()
        summary_heading.style = "Heading 1"
        summary_heading.add_run("Professional Summary")
        summary = doc.add_paragraph()
        summary.add_run("Software developer with Python, SQL, AWS, Linux, and documentation experience.")

        experience_heading = doc.add_paragraph()
        experience_heading.style = "Heading 1"
        experience_heading.add_run("Work Experience")
        experience = doc.add_paragraph()
        experience.add_run("Software Developer").bold = True
        experience.add_run(" | Northstar Labs | 2021-2025")

        bullet1 = doc.add_paragraph(style="List Bullet")
        bullet1.add_run("Implemented robust validation, logging, and data cleaning logic to detect malformed inputs and reduce manual data entry errors by 90%.")
        bullet2 = doc.add_paragraph(style="List Bullet")
        bullet2.add_run("Worked with cross-functional teammates to debug issues and document release steps across Python and SQL tools.")

        projects_heading = doc.add_paragraph()
        projects_heading.style = "Heading 1"
        projects_heading.add_run("Projects")
        project_title = doc.add_paragraph()
        project_title.add_run("Inventory Reconciler").bold = True
        project_title.add_run(" | Personal Project | 2024")
        project_bullet1 = doc.add_paragraph(style="List Bullet")
        project_bullet1.add_run("Designed data models and application logic for products, supplier specific items, and pricing records in an internal tool.")
        project_bullet2 = doc.add_paragraph(style="List Bullet")
        project_bullet2.add_run("Built backend integrations with real-time data from Retool and Google Docs for reporting and handoffs.")

        skills_heading = doc.add_paragraph()
        skills_heading.style = "Heading 1"
        skills_heading.add_run("Skills")
        skills = doc.add_paragraph()
        skills.add_run("Skills: ").bold = True
        skills.add_run("React, dashboards, AWS, Linux, Python, SQL, Flask, documentation, collaboration, testing")

        education_heading = doc.add_paragraph()
        education_heading.style = "Heading 1"
        education_heading.add_run("Education")
        college = doc.add_paragraph()
        college.add_run("George Brown College")
        diploma = doc.add_paragraph()
        diploma.add_run("Computer programming diploma | 2023")

        contact_two = doc.add_paragraph()
        contact_two.add_run("Portfolio: example.com/portfolio")

        doc.save(path)
        return path

    def build_asin_resume_fixture(self):
        path = Path(self.tmpdir.name) / "asin_resume_fixture.docx"
        doc = Document()
        section = doc.sections[0]
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.85)
        section.right_margin = Inches(0.85)

        title = doc.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title.add_run("Terry Mak")
        run.bold = True
        run.font.name = "Aptos"
        run.font.size = Pt(18)

        summary_heading = doc.add_paragraph()
        summary_heading.style = "Heading 1"
        summary_heading.add_run("Professional Summary")
        summary = doc.add_paragraph()
        summary.add_run("Backend developer with PostgreSQL, Python, automation, and reliability experience.")

        experience_heading = doc.add_paragraph()
        experience_heading.style = "Heading 1"
        experience_heading.add_run("Work Experience")
        experience = doc.add_paragraph()
        experience.add_run("Harmony 88 Co.").bold = True
        experience.add_run(" | Backend Developer | 2023-2025")

        bullet1 = doc.add_paragraph(style="List Bullet")
        bullet1.add_run("Built an automated ASIN monitoring system that tracked pricing, rank, and rating trends across 50-250 SKUs per session, delivering hourly insights over custom time frames and storing 300,000+ records in PostgreSQL.")
        bullet2 = doc.add_paragraph(style="List Bullet")
        bullet2.add_run("Implemented robust validation, logging, and data cleaning logic to detect malformed inputs and reduce manual data entry errors by 90%.")
        bullet3 = doc.add_paragraph(style="List Bullet")
        bullet3.add_run("Built backend integrations with real-time data from Retool and Google Docs for operations reporting and handoffs.")

        skills_heading = doc.add_paragraph()
        skills_heading.style = "Heading 1"
        skills_heading.add_run("Skills")
        skills = doc.add_paragraph()
        skills.add_run("Skills: ").bold = True
        skills.add_run("Python, PostgreSQL, Flask, AWS, dashboards, automation, APIs")

        doc.save(path)
        return path

    def build_cover_letter_template_fixture(self):
        path = Path(self.tmpdir.name) / "cover_letter_template_fixture.docx"
        doc = Document()
        section = doc.sections[0]
        section.top_margin = Inches(0.9)
        section.bottom_margin = Inches(0.9)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

        heading = doc.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        heading_run = heading.add_run("Terry Mak")
        heading_run.bold = True
        heading_run.font.name = "Aptos"
        heading_run.font.size = Pt(18)

        date_para = doc.add_paragraph()
        date_run = date_para.add_run("{{DATE}}")
        date_run.font.name = "Georgia"
        date_run.font.size = Pt(11)

        greeting = doc.add_paragraph()
        greeting.add_run("Dear {{HIRING_MANAGER}},")

        opening = doc.add_paragraph()
        opening.add_run("{{OPENING_PARAGRAPH}}")

        experience = doc.add_paragraph()
        experience.add_run("{{EXPERIENCE_PARAGRAPH}}")

        fit = doc.add_paragraph()
        fit.add_run("{{FIT_PARAGRAPH}}")

        closing = doc.add_paragraph()
        closing.add_run("{{CLOSING_PARAGRAPH}}")

        signoff = doc.add_paragraph()
        signoff.add_run("Sincerely,")

        signature = doc.add_paragraph()
        signature.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        signature_run = signature.add_run("Terry Mak")
        signature_run.bold = True

        doc.save(path)
        return path

    def build_retail_cover_letter_fixture(self):
        path = Path(self.tmpdir.name) / "retail_cover_letter_template_fixture.docx"
        doc = Document()
        heading = doc.add_paragraph()
        heading.add_run("Terry Mak")
        doc.add_paragraph("Retail customer service associate with supermarket and cashier experience.")
        doc.add_paragraph("Managed customer service duties, inventory, and merchandising for a busy store.")
        doc.add_paragraph("Sincerely,")
        doc.add_paragraph("Terry Mak")
        doc.save(path)
        return path

    def build_software_cover_letter_fixture(self):
        path = Path(self.tmpdir.name) / "software_cover_letter_template_fixture.docx"
        doc = Document()
        section = doc.sections[0]
        section.top_margin = Inches(0.9)
        section.bottom_margin = Inches(0.9)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

        heading = doc.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        heading.add_run("Terry Mak")

        contact = doc.add_paragraph()
        contact.add_run("terry@example.com | Toronto, ON | linkedin.com/in/terrymak")

        date_para = doc.add_paragraph()
        date_para.add_run("May 1, 2024")

        company_para = doc.add_paragraph()
        company_para.add_run("CentralSquare")

        location_para = doc.add_paragraph()
        location_para.add_run("Toronto, Ontario")

        greeting = doc.add_paragraph()
        greeting.add_run("Dear CentralSquare Hiring Team,")

        opening = doc.add_paragraph()
        opening.add_run("I am excited to apply for the Software Developer co-op role at CentralSquare for an 8/12-month placement.")

        experience = doc.add_paragraph()
        experience.add_run("I supported profile content and ATS-oriented language for the role.")

        fit = doc.add_paragraph()
        fit.add_run("My saved profile matches the posting and I would bring grounded wording.")

        closing = doc.add_paragraph()
        closing.add_run("Thank you for your consideration. I look forward to hearing from you.")

        signoff = doc.add_paragraph()
        signoff.add_run("Sincerely,")

        signature = doc.add_paragraph()
        signature.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        signature.add_run("CentralSquare Applicant")

        doc.save(path)
        return path

    def build_centralsquare_cover_letter_fixture(self):
        path = Path(self.tmpdir.name) / "centralsquare_cover_letter_template_fixture.docx"
        doc = Document()
        section = doc.sections[0]
        section.top_margin = Inches(0.9)
        section.bottom_margin = Inches(0.9)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

        header = section.header.paragraphs[0]
        header.text = "hochitterry.mak@georgebrown.ca | CentralSquare Technologies"

        footer = section.footer.paragraphs[0]
        footer.text = "CentralSquare Technologies | Remote - Ontario"

        heading = doc.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        heading.add_run("Terry Mak")

        contact = doc.add_paragraph()
        contact.add_run("hochitterry.mak@georgebrown.ca | Toronto, Ontario")

        date_para = doc.add_paragraph()
        date_para.add_run("May 1, 2024")

        company_para = doc.add_paragraph()
        company_para.add_run("CentralSquare")

        location_para = doc.add_paragraph()
        location_para.add_run("Remote - Ontario")

        greeting = doc.add_paragraph()
        greeting.add_run("Dear Hiring Manager,")

        subject = doc.add_paragraph()
        subject.add_run("Re: Software Developer Co-op – Remote, Ontario")

        opening = doc.add_paragraph()
        opening.add_run("I am excited to apply for the Software Developer Co-op role at CentralSquare for an 8- or 12-month term.")

        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "CentralSquare Technologies"
        table.cell(0, 1).text = "CentralSquare's technology initiatives"

        experience = doc.add_paragraph()
        experience.add_run("I supported profile content and ATS-oriented language for the role.")

        fit = doc.add_paragraph()
        fit.add_run("My saved profile matches the posting and I would bring grounded wording.")

        closing = doc.add_paragraph()
        closing.add_run("Thank you for your consideration. I look forward to hearing from you.")

        signoff = doc.add_paragraph()
        signoff.add_run("Sincerely,")

        signature = doc.add_paragraph()
        signature.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        signature.add_run("CentralSquare Applicant")

        doc.save(path)
        return path

    def add_hyperlink(self, paragraph, url, text):
        r_id = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
        hyperlink = OxmlElement("w:hyperlink")
        hyperlink.set(qn("r:id"), r_id)
        run = OxmlElement("w:r")
        rPr = OxmlElement("w:rPr")
        color = OxmlElement("w:color")
        color.set(qn("w:val"), "0000FF")
        rPr.append(color)
        underline = OxmlElement("w:u")
        underline.set(qn("w:val"), "single")
        rPr.append(underline)
        run.append(rPr)
        t = OxmlElement("w:t")
        t.text = text
        run.append(t)
        hyperlink.append(run)
        paragraph._p.append(hyperlink)

    def test_shortlist_persistence_generation_safe_names_and_downloads(self):
        self.seed_profile_for_documents(with_template=True)
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

    def test_regenerate_both_serves_fresh_files_and_rewrites_keyword_lists(self):
        self.client.post(
            "/api/profile",
            json={
                "name": "Terry Mak",
                "preferred_roles": "software developer, backend developer",
                "preferred_locations": "Toronto",
                "key_skills": "Python, PostgreSQL, Flask, AWS, automation, dashboards, validation, logging",
                "projects": "Harmony 88 Co. built automated ASIN monitoring for pricing and rating trends with PostgreSQL storage.",
                "work_experience": (
                    "Harmony 88 Co. built an automated ASIN monitoring system that tracked pricing, rank, and rating trends across 50-250 SKUs per session, "
                    "delivering hourly insights over custom time frames and storing 300,000+ records in PostgreSQL. "
                    "Implemented robust validation, logging, and data cleaning logic to detect malformed inputs and reduce manual data entry errors by 90%. "
                    "Built backend integrations with real-time data from Retool and Google Docs for operations reporting and handoffs."
                ),
                "resume_text": (
                    "Terry Mak. Harmony 88 Co. built an automated ASIN monitoring system that tracked pricing, rank, and rating trends across 50-250 SKUs per session, "
                    "delivering hourly insights over custom time frames and storing 300,000+ records in PostgreSQL. "
                    "Implemented robust validation, logging, and data cleaning logic to detect malformed inputs and reduce manual data entry errors by 90%. "
                    "Built backend integrations with real-time data from Retool and Google Docs for operations reporting and handoffs."
                ),
            },
        )
        self.upload_resume_template(self.build_asin_resume_fixture())
        self.upload_cover_letter_template(self.build_cover_letter_template_fixture())

        created = self.client.post(
            "/api/shortlist",
            json={
                "company": "Scotiabank",
                "title": "Software Developer",
                "location": "Toronto",
                "url": "https://example.com/job/scotiabank",
                "job_description": "Python PostgreSQL Flask AWS automation dashboards APIs validation logging documentation cross-functional collaboration",
            },
        ).get_json()
        job_id = created["id"]

        regenerated = self.client.post(f"/api/shortlist/{job_id}/regenerate", json={})
        self.assertEqual(regenerated.status_code, 200)
        job = regenerated.get_json()
        self.assertEqual(job["resume_generation_status"], "generated")
        self.assertEqual(job["cover_letter_generation_status"], "generated")
        self.assertIn("generation_debug", job)
        debug = job["generation_debug"]
        self.assertTrue(debug.get("generated_at"))
        self.assertGreater(debug.get("approved_evidence_count", 0), 0)
        self.assertTrue(debug.get("approved_evidence_ids"))
        self.assertTrue(debug.get("selected_approved_evidence_ids"))
        self.assertTrue(set(debug.get("selected_approved_evidence_ids", [])).issubset(set(debug.get("approved_evidence_ids", []))))
        self.assertTrue(debug.get("matched_evidence_ids"))
        self.assertIn("ollama", debug)
        self.assertIn("called", debug["ollama"])

        resume_path = Path(job["resume_docx_path"])
        cover_path = Path(job["cover_letter_docx_path"])
        self.assertTrue(resume_path.exists())
        self.assertTrue(cover_path.exists())
        generation_debug_path = resume_path.parent / "generation_debug.json"
        self.assertTrue(generation_debug_path.exists())
        self.assertEqual(json.loads(generation_debug_path.read_text(encoding="utf-8"))["generated_at"], debug["generated_at"])

        resume_doc = Document(io.BytesIO(resume_path.read_bytes()))
        cover_doc = Document(io.BytesIO(cover_path.read_bytes()))
        resume_text = "\n".join(paragraph.text for paragraph in resume_doc.paragraphs)
        cover_text = "\n".join(paragraph.text for paragraph in cover_doc.paragraphs)
        cover_paragraphs = [paragraph.text.strip() for paragraph in cover_doc.paragraphs if paragraph.text.strip()]
        cover_body_start = next(index for index, text in enumerate(cover_paragraphs) if text.startswith("I'm excited"))
        cover_body_end = next(index for index, text in enumerate(cover_paragraphs) if text.startswith("Thank you"))
        cover_body = cover_paragraphs[cover_body_start:cover_body_end]

        original_resume_1 = "Built an automated ASIN monitoring system that tracked pricing, rank, and rating trends across 50-250 SKUs per session, delivering hourly insights over custom time frames and storing 300,000+ records in PostgreSQL."
        original_resume_2 = "Implemented robust validation, logging, and data cleaning logic to detect malformed inputs and reduce manual data entry errors by 90%."
        rewritten_resume_1 = "Built a backend ASIN monitoring system that automated pricing, rank, and rating tracking across 50-250 SKUs per session, delivered hourly insights over custom time frames, and stored 300,000+ records reliably in PostgreSQL."
        rewritten_resume_2 = "Strengthened software reliability by implementing validation, logging, and data-cleaning logic that detected malformed inputs and reduced manual data-entry errors by 90%."
        bad_cover_paragraph = "Python, JavaScript, Flask, React, SQL, cloud, AWS, Azure, dashboards, automation, APIs, reporting. This is the kind of work I would bring to Scotiabank."

        self.assertNotIn(original_resume_1, resume_text)
        self.assertNotIn(original_resume_2, resume_text)
        self.assertIn(rewritten_resume_1, resume_text)
        self.assertIn(rewritten_resume_2, resume_text)
        self.assertNotIn("testing", resume_text.lower())
        self.assertNotIn(bad_cover_paragraph, cover_text)
        self.assertEqual(len(cover_body), 3)
        self.assertGreaterEqual(len(" ".join(cover_body).split()), 180)
        self.assertLessEqual(len(" ".join(cover_body).split()), 260)
        self.assertIn("automated ASIN monitoring system", cover_text)
        self.assertIn("PostgreSQL", cover_text)
        self.assertIn("300,000+ records", cover_text)
        self.assertIn("validation, logging, and data cleaning", cover_text)
        self.assertIsNone(app_module.validate_cover_letter_document(cover_doc, self.scotiabank_job(), {"name": "Terry Mak"}))

        download_resume = self.client.get(f"/api/shortlist/{job_id}/resume")
        download_cover = self.client.get(f"/api/shortlist/{job_id}/cover-letter")
        self.assertEqual(download_resume.status_code, 200)
        self.assertEqual(download_cover.status_code, 200)
        self.assertEqual(download_resume.data, resume_path.read_bytes())
        self.assertEqual(download_cover.data, cover_path.read_bytes())

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

    def test_candidate_profile_uploads_are_safe_and_defaults_are_selectable(self):
        created = self.client.post(
            "/api/candidate-profiles",
            json={"name": "Managed Profile", "identity_mode": "distinct", "applicant_name": "QA Applicant"},
        )
        self.assertEqual(created.status_code, 201)
        profile_id = created.get_json()["id"]
        document = Document()
        document.add_paragraph("QA Applicant")
        document.add_paragraph("Documented Python and SQL experience.")
        buffer = io.BytesIO()
        document.save(buffer)
        first = self.client.post(
            f"/api/candidate-profiles/{profile_id}/resumes/upload",
            data={"file": (io.BytesIO(buffer.getvalue()), "first resume.docx"), "is_default": "true"},
            content_type="multipart/form-data",
        )
        second = self.client.post(
            f"/api/candidate-profiles/{profile_id}/resumes/upload",
            data={"file": (io.BytesIO(buffer.getvalue()), "second resume.docx"), "is_default": "true"},
            content_type="multipart/form-data",
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        documents = self.client.get(f"/api/candidate-profiles/{profile_id}/documents").get_json()
        self.assertEqual(sum(item["is_default"] for item in documents["resumes"]), 1)
        self.assertTrue(Path(first.get_json()["path"]).exists())
        self.assertTrue(Path(second.get_json()["path"]).exists())
        selected = next(item for item in documents["resumes"] if item["is_default"])
        self.assertEqual(selected["id"], second.get_json()["id"])
        response = self.client.post(f"/api/candidate-profiles/{profile_id}/resumes/{first.get_json()['id']}/default")
        self.assertEqual(response.status_code, 200)
        documents = self.client.get(f"/api/candidate-profiles/{profile_id}/documents").get_json()
        self.assertEqual([item["id"] for item in documents["resumes"] if item["is_default"]], [first.get_json()["id"]])

    def test_generation_response_exposes_actual_status_for_frontend_feedback(self):
        self.seed_profile_for_documents(with_template=True)
        created = self.client.post("/api/shortlist", json={"company": "Feedback Co", "title": "Developer", "job_description": "Python SQL"}).get_json()
        self.assertEqual(created["generation"]["resume"], "generated")
        self.assertEqual(created["generation"]["cover_letter"], "generated")
        frontend = Path(app_module.BASE_DIR, "static", "app.js").read_text(encoding="utf-8")
        self.assertIn("function showGenerationOutcome", frontend)
        self.assertIn("previous successful document remains available", frontend)

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
        self.seed_profile_for_documents(with_template=True)
        regenerated = self.client.post(f"/api/shortlist/{created['id']}/regenerate", json={})
        self.assertEqual(regenerated.status_code, 200)
        job = regenerated.get_json()
        self.assertEqual(job["resume_generation_status"], "generated")
        self.assertTrue(Path(job["resume_docx_path"]).exists())


if __name__ == "__main__":
    unittest.main()
