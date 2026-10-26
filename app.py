from __future__ import annotations

import csv
from collections import Counter
import html
import importlib.metadata
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from urllib.parse import urlencode
import zipfile
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
import platform
import warnings

from docx import Document
from docx.oxml.ns import qn
from flask import Flask, Response, g, has_app_context, jsonify, render_template, request, send_file

from grounding import (
    PDF_CORRUPTION_MESSAGE,
    TECHNICAL_TERMS,
    build_candidate_evidence,
    classify_supported_skills,
    classify_keyword_dump_reason,
    contains_contact_details,
    contains_resume_section_heading,
    build_keywords_score_report,
    build_tailoring_coverage_report,
    apply_tailoring_requirement_overrides,
    evidence_has_generation_source,
    is_corrupted_text,
    job_keywords,
    normalize_keyword,
    normalize_tailoring_requirement,
    stable_hash as grounding_hash,
    supporting_snippets,
    validate_cover_letter_output,
    validate_generated_content,
)
from semantic_matching import MODEL_DOWNLOAD_SIZE, MODEL_NAME, analyze_resume_match
from seniority import DETECTED_LEVELS, SENIORITY_LEVELS, analyze_job_seniority, score_seniority_fit
from ollama_client import OllamaConfig, build_ollama_health_report, ollama_profile_defaults, request_json_completion
from sources.jobspy_source import fetch_jobspy_jobs
from tailoring import generate_tailored_resume_draft
from tailoring_pipeline import (
    build_cover_letter_paragraphs,
    build_tailoring_plan,
    classify_phrase,
    minimal_resume_substitution,
    rank_job_requirements,
    short_join,
    validate_minimal_substitution,
)
from werkzeug.utils import secure_filename
from db.migrations import run_migrations
from profile_store import CandidateProfileStore
from services.document_generation import DocumentGenerationService
from resume_layout import compare_docx_layout, export_docx_to_pdf


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("JOB_TRACKER_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "jobs.sqlite"
MAX_FETCH_BYTES = 1_200_000
DISCOVERY_SOURCES = ["linkedin", "indeed", "google", "zip_recruiter"]
GENERATED_APPLICATIONS_DIRNAME = "generated_applications"
SEMANTIC_CACHE_DIRNAME = "semantic_cache"
RESTORABLE_SHORTLIST_STATUSES = {"Archived", "Rejected", "Saved", "Drafting"}
PREPARATION_STATUSES = {"queued", "preparing", "ready_for_review", "approved", "skipped", "failed"}
PREPARATION_LEASE_MINUTES = 10
PREPARATION_LEASE_RENEW_SECONDS = 30

DISCOVERY_SCORE_WEIGHTS = {
    "skill_match": 35,
    "role_fit": 20,
    "seniority_fit": 10,
    "salary": 10,
    "distance_work_arrangement": 10,
    "recency": 10,
    "source_quality": 5,
}

DISCOVERY_REMOTE_DISTANCE_RULES = {"remote_first", "remote_after_local", "remote_zero"}

DISCOVERY_DATE_WINDOWS = {
    "24h": 1,
    "3d": 3,
    "7d": 7,
    "14d": 14,
    "30d": 30,
    "any": 0,
}

# Keep the public diagnostics field stable for existing API clients.  The
# database itself is now tracked independently by the migration runner.
APP_SCHEMA_VERSION = 1
CURRENT_DB_SCHEMA_VERSION = 9
DISCOVERY_DEBUG_SNAPSHOT_LIMIT = 25
GEOCODING_FAILURE_CACHE_SECONDS = 15 * 60
DISCOVERY_TASK_NAME = "Job Tracker Discovery"
TESTED_DEPENDENCY_VERSIONS = {
    "python-jobspy": "1.1.82",
    "pandas": "2.3.3",
    "numpy": "1.26.3",
}

CANADIAN_POSTAL_CODE_RE = re.compile(r"^[ABCEGHJ-NPRSTV-Z]\d[ABCEGHJ-NPRSTV-Z][ ]?\d[ABCEGHJ-NPRSTV-Z]\d$", re.I)
CANADIAN_POSTAL_CODE_EXTRACT_RE = re.compile(r"\b([ABCEGHJ-NPRSTV-Z]\d[ABCEGHJ-NPRSTV-Z][ ]?\d[ABCEGHJ-NPRSTV-Z]\d)\b", re.I)
PROVINCE_LOOKUP = {
    "ontario": "Ontario",
    "on": "Ontario",
    "quebec": "Quebec",
    "qc": "Quebec",
    "british columbia": "British Columbia",
    "bc": "British Columbia",
    "alberta": "Alberta",
    "ab": "Alberta",
    "manitoba": "Manitoba",
    "mb": "Manitoba",
    "saskatchewan": "Saskatchewan",
    "sk": "Saskatchewan",
    "nova scotia": "Nova Scotia",
    "ns": "Nova Scotia",
    "new brunswick": "New Brunswick",
    "nb": "New Brunswick",
    "newfoundland and labrador": "Newfoundland and Labrador",
    "nl": "Newfoundland and Labrador",
    "pei": "Prince Edward Island",
    "prince edward island": "Prince Edward Island",
    "pe": "Prince Edward Island",
    "yukon": "Yukon",
    "yt": "Yukon",
    "northwest territories": "Northwest Territories",
    "nt": "Northwest Territories",
    "nunavut": "Nunavut",
    "nu": "Nunavut",
}
PROVINCE_CODE_BY_NAME = {
    province.lower(): code.upper()
    for code, province in PROVINCE_LOOKUP.items()
    if len(code) <= 3
}

DISCOVERY_SEARCH_DEPTHS = {
    "quick": {"per_source_cap": 25, "total_cap": 50, "days": 3},
    "standard": {"per_source_cap": 100, "total_cap": 200, "days": 14},
    "thorough": {"per_source_cap": 250, "total_cap": 500, "days": 30},
}

STATUSES = ["Saved", "shortlisted", "Drafting", "Applied", "Interview", "Offer", "Rejected", "Archived"]

ROLE_TYPES = [
    "full-stack developer",
    "software developer",
    "cloud support",
    "technical support engineer",
    "implementation specialist",
    "analyst",
    "intern",
    "new grad",
    "other",
]


def get_package_version(package_name: str) -> str:
    try:
        return importlib.metadata.version(package_name)
    except Exception:
        return ""


def get_git_commit() -> str:
    git_exe = shutil.which("git") or shutil.which("git.exe")
    if not git_exe:
        return ""
    try:
        completed = subprocess.run([git_exe, "-C", str(BASE_DIR), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    except Exception:
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def collect_environment_diagnostics() -> dict[str, Any]:
    git_commit = get_git_commit()
    cwd = os.getcwd()
    return {
        "git_commit": git_commit,
        "active_git_commit": git_commit,
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "os": platform.platform(),
        "jobspy_version": get_package_version("python-jobspy"),
        "pandas_version": get_package_version("pandas"),
        "numpy_version": get_package_version("numpy"),
        "sqlite_db_path": str(DB_PATH),
        "schema_version": APP_SCHEMA_VERSION,
        "active_database_schema_version": CURRENT_DB_SCHEMA_VERSION,
        "cwd": cwd,
        "working_directory": cwd,
        "discovery_cache_path": str(DB_PATH),
        "discovery_debug_path": str(DATA_DIR / "discovery_debug"),
    }


def warn_on_dependency_mismatch() -> None:
    current = collect_environment_diagnostics()
    mismatches = []
    current_key_map = {
        "python-jobspy": "jobspy_version",
        "pandas": "pandas_version",
        "numpy": "numpy_version",
    }
    for package, tested in TESTED_DEPENDENCY_VERSIONS.items():
        installed = current.get(current_key_map.get(package, f"{package.replace('-', '_')}_version"), "")
        if installed and installed != tested:
            mismatches.append(f"{package}={installed} (tested {tested})")
    if mismatches:
        warnings.warn("Dependency version mismatch: " + ", ".join(mismatches), RuntimeWarning, stacklevel=2)

SCORING_WEIGHTS = {
    "skills": 30,
    "responsibilities": 20,
    "location": 15,
    "salary": 10,
    "seniority": 15,
    "role": 10,
}

REWARD_KEYWORDS = [
    "python",
    "javascript",
    "flask",
    "react",
    "sql",
    "cloud",
    "aws",
    "azure",
    "dashboards",
    "dashboard",
    "automation",
    "scraping",
    "apis",
    "api",
    "internal tools",
    "reporting",
    "business systems",
    "technical support engineer",
    "implementation specialist",
    "full-stack developer",
    "full stack developer",
    "cloud support",
    "analyst",
]

ROLE_KEYWORDS = [
    "junior",
    "intern",
    "internship",
    "new grad",
    "entry level",
    "full-stack",
    "full stack",
    "cloud support",
    "technical support engineer",
    "implementation specialist",
    "analyst",
    "software developer",
    "software engineer",
    "developer",
]

LOCATION_KEYWORDS = ["toronto", "remote", "hybrid", "gta", "ontario", "canada"]

PENALTY_KEYWORDS = [
    "senior",
    "5+ years",
    "6+ years",
    "7+ years",
    "advanced algorithms",
    "competitive programming",
    "distributed systems at scale",
    "data structures and algorithms",
    "unpaid",
    "commission only",
    "commission-only",
]

CODING_RISK_KEYWORDS = [
    "leetcode",
    "hackerrank",
    "codility",
    "advanced algorithms",
    "competitive programming",
    "data structures",
    "whiteboard",
]

EFFORT_KEYWORDS = ["portfolio", "take-home", "cover letter required", "assessment", "work sample"]

COMMON_QUESTIONS = [
    "Why are you interested in this role?",
    "Why this company?",
    "Tell us about your relevant experience.",
    "Are you legally authorized to work in Canada?",
    "What are your salary expectations?",
    "When can you start?",
    "Anything else you want us to know?",
]

JOB_COLUMNS = {
    "company": "TEXT NOT NULL DEFAULT ''",
    "title": "TEXT NOT NULL DEFAULT ''",
    "location": "TEXT NOT NULL DEFAULT ''",
    "url": "TEXT NOT NULL DEFAULT ''",
    "source": "TEXT NOT NULL DEFAULT ''",
    "salary": "TEXT NOT NULL DEFAULT ''",
    "salary_original_text": "TEXT NOT NULL DEFAULT ''",
    "salary_midpoint": "INTEGER NOT NULL DEFAULT 0",
    "salary_listed": "INTEGER NOT NULL DEFAULT 0",
    "deadline": "TEXT NOT NULL DEFAULT ''",
    "fit_score": "INTEGER NOT NULL DEFAULT 0",
    "overall_score": "INTEGER NOT NULL DEFAULT 0",
    "status": "TEXT NOT NULL DEFAULT 'Saved'",
    "notes": "TEXT NOT NULL DEFAULT ''",
    "date_added": "TEXT NOT NULL DEFAULT ''",
    "date_applied": "TEXT NOT NULL DEFAULT ''",
    "job_description": "TEXT NOT NULL DEFAULT ''",
    "remote_type": "TEXT NOT NULL DEFAULT ''",
    "role_type": "TEXT NOT NULL DEFAULT ''",
    "seniority_level": "TEXT NOT NULL DEFAULT ''",
    "distance_km": "INTEGER NOT NULL DEFAULT 0",
    "distance_confidence": "INTEGER NOT NULL DEFAULT 0",
    "required_skills": "TEXT NOT NULL DEFAULT ''",
    "preferred_skills": "TEXT NOT NULL DEFAULT ''",
    "responsibilities": "TEXT NOT NULL DEFAULT ''",
    "application_url": "TEXT NOT NULL DEFAULT ''",
    "skills_match_score": "INTEGER NOT NULL DEFAULT 0",
    "role_match_score": "INTEGER NOT NULL DEFAULT 0",
    "location_score": "INTEGER NOT NULL DEFAULT 0",
    "remote_score": "INTEGER NOT NULL DEFAULT 0",
    "salary_score": "INTEGER NOT NULL DEFAULT 0",
    "seniority_score": "INTEGER NOT NULL DEFAULT 0",
    "coding_risk_score": "INTEGER NOT NULL DEFAULT 0",
    "application_effort_score": "INTEGER NOT NULL DEFAULT 0",
    "score_breakdown": "TEXT NOT NULL DEFAULT '{}'",
    "salary_min": "INTEGER NOT NULL DEFAULT 0",
    "salary_max": "INTEGER NOT NULL DEFAULT 0",
    "salary_interval": "TEXT NOT NULL DEFAULT ''",
    "salary_currency": "TEXT NOT NULL DEFAULT 'CAD'",
    "salary_source": "TEXT NOT NULL DEFAULT 'missing'",
    "salary_confidence": "INTEGER NOT NULL DEFAULT 0",
    "source_job_id": "TEXT NOT NULL DEFAULT ''",
    "posted_date": "TEXT NOT NULL DEFAULT ''",
    "date_shortlisted": "TEXT NOT NULL DEFAULT ''",
    "resume_docx_path": "TEXT NOT NULL DEFAULT ''",
    "cover_letter_docx_path": "TEXT NOT NULL DEFAULT ''",
    "resume_generation_status": "TEXT NOT NULL DEFAULT ''",
    "cover_letter_generation_status": "TEXT NOT NULL DEFAULT ''",
    "resume_generation_error": "TEXT NOT NULL DEFAULT ''",
    "cover_letter_generation_error": "TEXT NOT NULL DEFAULT ''",
    "cover_letter_generation_warning": "TEXT NOT NULL DEFAULT ''",
    "generation_error": "TEXT NOT NULL DEFAULT ''",
    "generated_at": "TEXT NOT NULL DEFAULT ''",
    "profile_updated_at": "TEXT NOT NULL DEFAULT ''",
    "discovery_first_seen_at": "TEXT NOT NULL DEFAULT ''",
    "discovery_last_seen_at": "TEXT NOT NULL DEFAULT ''",
    "discovery_seen_count": "INTEGER NOT NULL DEFAULT 0",
    "discovery_state": "TEXT NOT NULL DEFAULT ''",
    "discovery_last_search_id": "INTEGER NOT NULL DEFAULT 0",
    "remote_eligibility": "TEXT NOT NULL DEFAULT 'unknown'",
    "remote_eligibility_explanation": "TEXT NOT NULL DEFAULT ''",
    "discovery_salary_filter_status": "TEXT NOT NULL DEFAULT ''",
}

PROFILE_COLUMNS = {
    "name": "TEXT NOT NULL DEFAULT ''",
    "email": "TEXT NOT NULL DEFAULT ''",
    "phone": "TEXT NOT NULL DEFAULT ''",
    "location": "TEXT NOT NULL DEFAULT ''",
    "home_location_original": "TEXT NOT NULL DEFAULT ''",
    "home_location_normalized": "TEXT NOT NULL DEFAULT ''",
    "home_location_query": "TEXT NOT NULL DEFAULT ''",
    "home_location_latitude": "TEXT NOT NULL DEFAULT ''",
    "home_location_longitude": "TEXT NOT NULL DEFAULT ''",
    "home_location_provider": "TEXT NOT NULL DEFAULT ''",
    "home_location_confidence": "TEXT NOT NULL DEFAULT ''",
    "home_location_precision": "TEXT NOT NULL DEFAULT ''",
    "home_location_geocoded_at": "TEXT NOT NULL DEFAULT ''",
    "home_location_status": "TEXT NOT NULL DEFAULT ''",
    "home_location_error": "TEXT NOT NULL DEFAULT ''",
    "preferred_roles": "TEXT NOT NULL DEFAULT ''",
    "preferred_locations": "TEXT NOT NULL DEFAULT ''",
    "work_authorization": "TEXT NOT NULL DEFAULT ''",
    "key_skills": "TEXT NOT NULL DEFAULT ''",
    "projects": "TEXT NOT NULL DEFAULT ''",
    "education": "TEXT NOT NULL DEFAULT ''",
    "work_experience": "TEXT NOT NULL DEFAULT ''",
    "resume_text": "TEXT NOT NULL DEFAULT ''",
    "resume_docx_template_path": "TEXT NOT NULL DEFAULT ''",
    "cover_letter_template": "TEXT NOT NULL DEFAULT ''",
    "cover_letter_docx_template_path": "TEXT NOT NULL DEFAULT ''",
    "cover_letter_template_status": "TEXT NOT NULL DEFAULT ''",
    "cover_letter_no_dashes": "TEXT NOT NULL DEFAULT 'true'",
    "ollama_enabled": "TEXT NOT NULL DEFAULT 'false'",
    "ollama_base_url": "TEXT NOT NULL DEFAULT 'http://127.0.0.1:11434'",
    "ollama_model": "TEXT NOT NULL DEFAULT 'qwen3:4b'",
    "ollama_timeout_seconds": "TEXT NOT NULL DEFAULT '120'",
    "ollama_max_output_tokens": "TEXT NOT NULL DEFAULT '1200'",
    "ollama_max_prompt_chars": "TEXT NOT NULL DEFAULT '24000'",
    "target_seniority_levels": "TEXT NOT NULL DEFAULT 'entry_level,junior,intermediate'",
    "maximum_required_years": "TEXT NOT NULL DEFAULT '3'",
    "willing_to_apply_to_stretch_roles": "TEXT NOT NULL DEFAULT 'true'",
    "management_roles_allowed": "TEXT NOT NULL DEFAULT 'false'",
}

EVIDENCE_COLUMNS = {
    "source_kind": "TEXT NOT NULL DEFAULT 'profile'",
    "source_field": "TEXT NOT NULL DEFAULT ''",
    "source_label": "TEXT NOT NULL DEFAULT ''",
    "content": "TEXT NOT NULL DEFAULT ''",
    "content_hash": "TEXT NOT NULL DEFAULT ''",
    "approved": "INTEGER NOT NULL DEFAULT 1",
    "review_notes": "TEXT NOT NULL DEFAULT ''",
    "job_id": "INTEGER NOT NULL DEFAULT 0",
}

RESUME_VARIANT_COLUMNS = {
    "job_id": "INTEGER NOT NULL DEFAULT 0",
    "section": "TEXT NOT NULL DEFAULT ''",
    "source_text": "TEXT NOT NULL DEFAULT ''",
    "proposed_text": "TEXT NOT NULL DEFAULT ''",
    "job_requirement": "TEXT NOT NULL DEFAULT ''",
    "confidence": "INTEGER NOT NULL DEFAULT 0",
    "approved": "INTEGER NOT NULL DEFAULT 0",
    "review_notes": "TEXT NOT NULL DEFAULT ''",
}


def create_app() -> Flask:
    app = Flask(__name__)
    warn_on_dependency_mismatch()

    @app.before_request
    def ensure_database() -> None:
        init_db()

    @app.teardown_appcontext
    def close_connection(_: Exception | None = None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.get("/")
    def index() -> str:
        return render_template("index.html", statuses=STATUSES, role_types=ROLE_TYPES)

    @app.get("/api/profile")
    def get_profile() -> Response:
        return jsonify(load_profile())

    @app.get("/api/candidate-profiles")
    def candidate_profiles() -> Response:
        return jsonify(CandidateProfileStore(get_db()).list_profiles())

    @app.post("/api/candidate-profiles")
    def create_candidate_profile() -> Response:
        payload = request.get_json(force=True) or {}
        name = text(payload.get("name"))
        if not name:
            return jsonify({"error": "Profile name is required"}), 400
        profile_id = CandidateProfileStore(get_db()).create_profile(
            name,
            text(payload.get("description")),
            identity_mode=text(payload.get("identity_mode")) or ("distinct" if text(payload.get("applicant_name")) else "shared"),
            applicant_name=text(payload.get("applicant_name")),
            applicant_email=text(payload.get("applicant_email")),
            applicant_phone=text(payload.get("applicant_phone")),
            applicant_location=text(payload.get("applicant_location")),
        )
        return jsonify({"id": profile_id}), 201

    @app.patch("/api/candidate-profiles/<int:profile_id>")
    def update_candidate_profile(profile_id: int) -> Response:
        payload = request.get_json(force=True) or {}
        try:
            profile = CandidateProfileStore(get_db()).update_profile(
                profile_id,
                identity_mode=text(payload.get("identity_mode")) or None,
                applicant_name=text(payload.get("applicant_name")) if "applicant_name" in payload else None,
                applicant_email=text(payload.get("applicant_email")) if "applicant_email" in payload else None,
                applicant_phone=text(payload.get("applicant_phone")) if "applicant_phone" in payload else None,
                applicant_location=text(payload.get("applicant_location")) if "applicant_location" in payload else None,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(profile)

    @app.get("/api/candidate-profiles/<int:profile_id>/documents")
    def candidate_profile_documents(profile_id: int) -> Response:
        return jsonify(CandidateProfileStore(get_db()).documents_for(profile_id))

    @app.post("/api/candidate-profiles/<int:profile_id>/resumes")
    def create_base_resume(profile_id: int) -> Response:
        payload = request.get_json(force=True) or {}
        if not text(payload.get("name")):
            return jsonify({"error": "Resume name is required"}), 400
        resume_id = CandidateProfileStore(get_db()).add_resume(
            profile_id, text(payload.get("name")), text(payload.get("content")), text(payload.get("docx_path")), bool(payload.get("is_default"))
        )
        return jsonify({"id": resume_id}), 201

    @app.post("/api/candidate-profiles/<int:profile_id>/cover-letter-templates")
    def create_cover_letter_template(profile_id: int) -> Response:
        payload = request.get_json(force=True) or {}
        if not text(payload.get("name")):
            return jsonify({"error": "Template name is required"}), 400
        template_id = CandidateProfileStore(get_db()).add_cover_letter_template(
            profile_id, text(payload.get("name")), text(payload.get("content")), text(payload.get("docx_path")), bool(payload.get("is_default"))
        )
        return jsonify({"id": template_id}), 201

    @app.post("/api/candidate-profiles/<int:profile_id>/resumes/upload")
    def upload_candidate_resume(profile_id: int) -> Response:
        uploaded = request.files.get("file")
        if uploaded is None or not uploaded.filename:
            return jsonify({"error": "Choose a DOCX résumé first"}), 400
        if Path(uploaded.filename).suffix.lower() != ".docx":
            return jsonify({"error": "Candidate résumés must be DOCX files"}), 400
        content = uploaded.read()
        if not content:
            return jsonify({"error": "The résumé file is empty"}), 400
        try:
            Document(io.BytesIO(content))
        except (ValueError, zipfile.BadZipFile, KeyError):
            return jsonify({"error": "The résumé is not a readable DOCX file"}), 400
        extracted = extract_uploaded_text(uploaded.filename, content)
        folder = DATA_DIR / "candidate_profiles" / str(profile_id) / "resumes"
        folder.mkdir(parents=True, exist_ok=True)
        filename = f"{safe_filename(Path(uploaded.filename).stem) or 'resume'}_{uuid.uuid4().hex[:10]}.docx"
        path = folder / filename
        path.write_bytes(content)
        name = text(request.form.get("name")) or Path(uploaded.filename).stem
        document_id = CandidateProfileStore(get_db()).add_resume(profile_id, name, extracted, str(path), request.form.get("is_default") == "true")
        return jsonify({"id": document_id, "name": name, "path": str(path)}), 201

    @app.post("/api/candidate-profiles/<int:profile_id>/cover-letter-templates/upload")
    def upload_candidate_cover_letter_template(profile_id: int) -> Response:
        uploaded = request.files.get("file")
        if uploaded is None or not uploaded.filename:
            return jsonify({"error": "Choose a DOCX cover letter template first"}), 400
        if Path(uploaded.filename).suffix.lower() != ".docx":
            return jsonify({"error": "Cover letter templates must be DOCX files"}), 400
        content = uploaded.read()
        if not content:
            return jsonify({"error": "The cover letter file is empty"}), 400
        try:
            Document(io.BytesIO(content))
        except (ValueError, zipfile.BadZipFile, KeyError):
            return jsonify({"error": "The cover letter is not a readable DOCX file"}), 400
        extracted = extract_uploaded_text(uploaded.filename, content)
        folder = DATA_DIR / "candidate_profiles" / str(profile_id) / "cover-letter-templates"
        folder.mkdir(parents=True, exist_ok=True)
        filename = f"{safe_filename(Path(uploaded.filename).stem) or 'cover_letter'}_{uuid.uuid4().hex[:10]}.docx"
        path = folder / filename
        path.write_bytes(content)
        name = text(request.form.get("name")) or Path(uploaded.filename).stem
        document_id = CandidateProfileStore(get_db()).add_cover_letter_template(profile_id, name, extracted, str(path), request.form.get("is_default") == "true")
        return jsonify({"id": document_id, "name": name, "path": str(path)}), 201

    @app.post("/api/candidate-profiles/<int:profile_id>/resumes/<int:document_id>/default")
    def set_candidate_resume_default(profile_id: int, document_id: int) -> Response:
        try:
            return jsonify(CandidateProfileStore(get_db()).set_default(profile_id, "resume", document_id))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/candidate-profiles/<int:profile_id>/cover-letter-templates/<int:document_id>/default")
    def set_candidate_cover_default(profile_id: int, document_id: int) -> Response:
        try:
            return jsonify(CandidateProfileStore(get_db()).set_default(profile_id, "cover_letter_template", document_id))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/tailoring/<int:job_id>/workspace")
    def tailoring_workspace(job_id: int) -> Response:
        row = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        if row is None:
            return jsonify({"error": "Job not found"}), 404
        payload = {key: request.args.get(key) for key in ("candidate_profile_id", "resume_id")}
        try:
            selection = resolve_tailoring_resume_profile(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        job = job_to_dict(row)
        source_text = extract_docx_text(selection["resume_path"].read_bytes())
        draft_row = query_db(
            "SELECT * FROM tailoring_drafts WHERE job_id = ? AND candidate_profile_id = ? AND resume_id = ?",
            [job_id, int(selection["profile_row"]["id"]), int(selection["resume"]["id"])], one=True,
        )
        if draft_row is None:
            cursor = get_db().execute(
                "INSERT INTO tailoring_drafts(job_id, candidate_profile_id, resume_id, source_path, draft_path) VALUES (?, ?, ?, ?, '')",
                [job_id, int(selection["profile_row"]["id"]), int(selection["resume"]["id"]), str(selection["resume_path"])],
            )
            get_db().commit()
            draft_row = query_db("SELECT * FROM tailoring_drafts WHERE id = ?", [cursor.lastrowid], one=True)
        draft = tailoring_draft_to_dict(draft_row)
        draft_text = source_text
        draft_path = safe_local_path(text(draft.get("draft_path")))
        if draft_path and draft_path.is_file():
            draft_text = extract_docx_text(draft_path.read_bytes())
        draft_docx = draft_path if draft_path and draft_path.is_file() else selection["resume_path"]
        current_bullets = tailoring_paragraphs(draft_docx)
        memory_rows = query_db("SELECT * FROM keyword_memory WHERE candidate_profile_id = ? ORDER BY normalized_keyword", [int(selection["profile_row"]["id"])])
        memory = {item["normalized_keyword"]: dict(item) for item in memory_rows}
        for item in memory.values():
            item["source_matches"] = False
            item["matching_paragraph_index"] = None
            if item.get("status") == "yes" and int(item.get("resume_id") or 0) == int(selection["resume"]["id"]) and text(item.get("source_fingerprint")):
                match = next((bullet for bullet in current_bullets if bullet.get("editable") and grounding_hash(normalize_space(bullet.get("text"))) == text(item["source_fingerprint"])), None)
                if match:
                    item["source_matches"] = True
                    item["matching_paragraph_index"] = int(match["paragraph_index"])
        original_report = score_tailoring_text(job, selection["profile"], source_text)
        report = score_tailoring_text(job, selection["profile"], draft_text)
        override_rows = query_db("SELECT normalized_requirement, override FROM tailoring_requirement_overrides WHERE job_id = ?", [job_id])
        overrides = {text(item["normalized_requirement"]): text(item["override"]) for item in override_rows}
        report = apply_tailoring_requirement_overrides(report, overrides)
        report["coverage_improvement_count"] = int(report.get("original_matched_count", report.get("matched_count", 0))) - int(original_report.get("matched_count", 0))
        skill_rows = query_db(
            "SELECT * FROM keyword_memory WHERE candidate_profile_id = ? AND confirmation_source = 'skill_confirmation' ORDER BY normalized_keyword",
            [int(selection["profile_row"]["id"])],
        )
        skill_memory = {row["normalized_keyword"]: dict(row) for row in skill_rows}
        for group in ("matched", "related", "missing"):
            for item in report.get(group, []):
                saved = memory.get(item["normalized"])
                if saved is None:
                    saved = next(
                        (memory.get(normalize_keyword(alias)) for alias in item.get("alternative_terms", ())
                         if memory.get(normalize_keyword(alias))),
                        None,
                    )
                item["memory"] = saved or {}
                item["skill_memory"] = {
                    alias: skill_memory[normalize_keyword(alias)]
                    for alias in item.get("alternative_terms", ())
                    if normalize_keyword(alias) in skill_memory
                }
        skill_inventory = []
        stop_words = {"and", "or", "with", "for", "the", "of", "to", "in", "experience", "using", "such", "as"}
        for group_name in ("matched", "related", "missing"):
            for item in report.get(group_name, []):
                alternatives = list(item.get("alternative_terms") or [item.get("keyword")])
                found_as = normalize_keyword(item.get("found_as"))
                for term in alternatives:
                    term = text(term)
                    term_normalized = normalize_keyword(term)
                    term_match = item.get("match_type", "missing") if found_as and term_normalized == found_as else "missing"
                    term_memory = (item.get("skill_memory") or {}).get(term, {})
                    term_words = [word for word in re.findall(r"[a-z0-9+#.]+", term.lower()) if len(word) > 2 and word not in stop_words]
                    suggestions = []
                    if term_match in {"missing", "partial"}:
                        for bullet in current_bullets:
                            if not bullet.get("editable"):
                                continue
                            bullet_words = set(re.findall(r"[a-z0-9+#.]+", text(bullet.get("text")).lower()))
                            overlap = [word for word in term_words if word in bullet_words]
                            if overlap:
                                suggestions.append({"paragraph_index": bullet["paragraph_index"], "text": bullet["text"], "section": bullet.get("section", "Résumé"), "source_location": f"{bullet.get('section', 'Résumé')} · paragraph {bullet['paragraph_index'] + 1}", "overlap": overlap})
                        suggestions = suggestions[:3]
                    skill_inventory.append({
                        "keyword": term,
                        "normalized": term_normalized,
                        "parent_keyword": item.get("keyword", term),
                        "parent_normalized": item.get("normalized", term_normalized),
                        "semantic_group": item.get("keyword", term),
                        "alternative_terms": alternatives,
                        "requirement_type": item.get("requirement_type", "unclassified"),
                        "match_type": term_match,
                        "parent_match_type": item.get("match_type", "missing"),
                        "found_as": item.get("found_as", "") if term_match != "missing" else "",
                        "source_evidence": item.get("source_evidence", []),
                        "source_sections": item.get("source_sections", []),
                        "evidence": item.get("evidence", "") if term_match != "missing" else "",
                        "source_section": item.get("source_section", "Résumé") if term_match != "missing" else "",
                        "skill_memory": term_memory,
                        "suggested_bullets": suggestions,
                    })
        report["skill_inventory"] = skill_inventory
        return jsonify({
            "job": job,
            "candidate_profile": selection["profile_row"],
            "resume": selection["resume"],
            "draft": draft,
            "bullets": current_bullets,
            "keywords": report,
            "original_keywords": original_report,
            "preview": {"text": draft_text, "layout": draft.get("layout", {}), "approximate": not bool(draft.get("layout", {}).get("available"))},
        })

    @app.post("/api/tailoring/<int:job_id>/requirement-overrides")
    def save_tailoring_requirement_override(job_id: int) -> Response:
        payload = request.get_json(silent=True) or {}
        normalized = normalize_tailoring_requirement(text(payload.get("normalized_requirement") or payload.get("keyword")))
        override = text(payload.get("override"))
        if not normalized or override not in {"yes", "no", "not_a_requirement", "unknown"}:
            return jsonify({"error": "A requirement and a valid override are required."}), 400
        if query_db("SELECT id FROM jobs WHERE id = ?", [job_id], one=True) is None:
            return jsonify({"error": "Job not found"}), 404
        get_db().execute(
            "INSERT INTO tailoring_requirement_overrides(job_id, normalized_requirement, override) VALUES (?, ?, ?) ON CONFLICT(job_id, normalized_requirement) DO UPDATE SET override = excluded.override, updated_at = CURRENT_TIMESTAMP",
            [job_id, normalized, override],
        )
        get_db().commit()
        return jsonify({"job_id": job_id, "normalized_requirement": normalized, "override": override})

    @app.delete("/api/tailoring/<int:job_id>/requirement-overrides/<path:normalized_requirement>")
    def delete_tailoring_requirement_override(job_id: int, normalized_requirement: str) -> Response:
        normalized = normalize_tailoring_requirement(normalized_requirement)
        get_db().execute("DELETE FROM tailoring_requirement_overrides WHERE job_id = ? AND normalized_requirement = ?", [job_id, normalized])
        get_db().commit()
        return jsonify({"job_id": job_id, "normalized_requirement": normalized, "override": ""})

    @app.post("/api/tailoring/<int:job_id>/draft")
    def create_tailoring_draft(job_id: int) -> Response:
        payload = request.get_json(force=True) or {}
        row = query_db("SELECT id FROM jobs WHERE id = ?", [job_id], one=True)
        if row is None:
            return jsonify({"error": "Job not found"}), 404
        try:
            selection = resolve_tailoring_resume_profile(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        existing = query_db("SELECT * FROM tailoring_drafts WHERE job_id = ? AND candidate_profile_id = ? AND resume_id = ?", [job_id, int(selection["profile_row"]["id"]), int(selection["resume"]["id"])], one=True)
        if existing is None:
            cursor = get_db().execute("INSERT INTO tailoring_drafts(job_id, candidate_profile_id, resume_id, source_path) VALUES (?, ?, ?, ?)", [job_id, int(selection["profile_row"]["id"]), int(selection["resume"]["id"]), str(selection["resume_path"])])
            get_db().commit()
            existing = query_db("SELECT * FROM tailoring_drafts WHERE id = ?", [cursor.lastrowid], one=True)
        return jsonify(tailoring_draft_to_dict(existing)), 201 if existing and int(existing["id"]) == int(cursor.lastrowid if 'cursor' in locals() else -1) else 200

    @app.get("/api/tailoring/drafts/<int:draft_id>/download")
    def download_tailoring_draft(draft_id: int) -> Response:
        row = query_db("SELECT draft_path FROM tailoring_drafts WHERE id = ?", [draft_id], one=True)
        if row is None:
            return jsonify({"error": "Tailoring draft was not found"}), 404
        path = safe_local_path(text(row["draft_path"]))
        if path is None or not path.is_file():
            return jsonify({"error": "The copied résumé DOCX is not available until an edit has been applied."}), 404
        return send_file(path, as_attachment=True, download_name="tailored-resume-draft.docx", mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    @app.post("/api/tailoring/drafts/<int:draft_id>/apply")
    def apply_tailoring_draft_change(draft_id: int) -> Response:
        payload = request.get_json(force=True) or {}
        row = query_db("SELECT * FROM tailoring_drafts WHERE id = ?", [draft_id], one=True)
        if row is None:
            return jsonify({"error": "Tailoring draft was not found"}), 404
        changes = parse_json_array(row["changes_json"])
        operation = text(payload.get("operation")) or "replace"
        if operation == "leave_unchanged":
            changes = [item for item in changes if int(item.get("paragraph_index", -1)) != int(payload.get("paragraph_index", -1))]
        else:
            try:
                paragraph_index = int(payload.get("paragraph_index"))
            except (TypeError, ValueError) as exc:
                return jsonify({"error": "Select an existing résumé bullet first"}), 400
            original = text(payload.get("original_text"))
            proposed = text(payload.get("proposed_text"))
            if not original or not proposed:
                return jsonify({"error": "Original and proposed bullet text are required"}), 400
            if operation not in {"edit", "replace"}:
                return jsonify({"error": "This first studio release supports edit, replace or leave unchanged"}), 400
            prior = next((item for item in changes if int(item.get("paragraph_index", -1)) == paragraph_index), None)
            current_path = safe_local_path(text(row["draft_path"])) if row["draft_path"] else None
            current_source = current_path if current_path and current_path.is_file() else safe_local_path(text(row["source_path"]))
            current_text = ""
            if current_source and current_source.is_file():
                paragraphs = list(Document(current_source).paragraphs)
                if paragraph_index < 0 or paragraph_index >= len(paragraphs):
                    return jsonify({"error": "That résumé paragraph no longer exists; refresh the studio before editing it."}), 409
                current_text = normalize_space(paragraphs[paragraph_index].text)
            if current_text and normalize_space(original) != current_text:
                return jsonify({"error": "The displayed bullet is stale. Refresh the studio and review the current wording before applying this edit."}), 409
            change = {"paragraph_index": paragraph_index, "keyword": normalize_keyword(text(payload.get("keyword")) or text(prior.get("keyword") if prior else "")), "original_text": text(prior.get("original_text")) if prior else original, "proposed_text": proposed, "operation": operation}
            changes = [item for item in changes if int(item.get("paragraph_index", -1)) != paragraph_index]
            changes.append(change)
        try:
            result = rebuild_tailoring_draft(draft_id, changes)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"draft_id": draft_id, "changes": changes, **result})

    @app.post("/api/tailoring/drafts/<int:draft_id>/approve")
    def approve_tailoring_draft(draft_id: int) -> Response:
        payload = request.get_json(silent=True) or {}
        row = query_db("SELECT * FROM tailoring_drafts WHERE id = ?", [draft_id], one=True)
        if row is None:
            return jsonify({"error": "Tailoring draft was not found"}), 404
        draft_path = safe_local_path(text(row["draft_path"]))
        if draft_path is None or not draft_path.is_file():
            return jsonify({"error": "Apply at least one valid edit before approving this résumé draft"}), 409
        package_id = int(payload.get("preparation_id") or 0)
        package = query_db("SELECT * FROM application_preparation_queue WHERE id = ?", [package_id], one=True) if package_id else query_db(
            "SELECT * FROM application_preparation_queue WHERE job_id = ? AND candidate_profile_id = ? AND resume_id = ? ORDER BY id DESC LIMIT 1",
            [row["job_id"], row["candidate_profile_id"], row["resume_id"]], one=True,
        )
        if package is None:
            return jsonify({"error": "Queue this job with the same candidate profile and résumé before approving the tailored résumé."}), 409
        if int(package["job_id"]) != int(row["job_id"]) or int(package["candidate_profile_id"]) != int(row["candidate_profile_id"]) or int(package["resume_id"]) != int(row["resume_id"]):
            return jsonify({"error": "This tailoring draft does not belong to the selected application package."}), 409
        if package["status"] == "approved":
            return jsonify({"error": "Approved application packages cannot be changed."}), 409
        target = DATA_DIR / "application_preparations" / str(package["id"]) / f"tailored_resume_draft_{draft_id}.docx"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(draft_path, target)
        now = datetime.now().isoformat(timespec="seconds")
        for change in parse_json_array(row["changes_json"]):
            normalized = normalize_keyword(text(change.get("keyword")))
            if not normalized:
                continue
            get_db().execute(
                """INSERT INTO keyword_memory(candidate_profile_id, normalized_keyword, keyword, status, project_employer, supporting_bullet, source_fingerprint, approved_replacement, resume_id, source_paragraph_index)
                   VALUES (?, ?, ?, 'yes', '', ?, ?, ?, ?, ?)
                   ON CONFLICT(candidate_profile_id, normalized_keyword) DO UPDATE SET keyword=excluded.keyword, status='yes', supporting_bullet=excluded.supporting_bullet, source_fingerprint=excluded.source_fingerprint, approved_replacement=excluded.approved_replacement, resume_id=excluded.resume_id, source_paragraph_index=excluded.source_paragraph_index, updated_at=CURRENT_TIMESTAMP""",
                [row["candidate_profile_id"], normalized, text(change.get("keyword")), text(change.get("original_text")), grounding_hash(normalize_space(text(change.get("original_text")))), text(change.get("proposed_text")), row["resume_id"], int(change.get("paragraph_index") or -1)],
            )
        get_db().execute("UPDATE tailoring_drafts SET status = 'approved', approved_at = ?, approved_tailoring_draft_id = ?, approved_tailored_resume_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", [now, draft_id, str(target), draft_id])
        get_db().execute("UPDATE application_preparation_queue SET approved_tailoring_draft_id = ?, approved_tailored_resume_path = ?, prepared_resume_path = CASE WHEN status = 'ready_for_review' THEN ? ELSE prepared_resume_path END, updated_at = CURRENT_TIMESTAMP WHERE id = ?", [draft_id, str(target), str(target), int(package["id"])])
        get_db().commit()
        return jsonify({"approved": True, "draft": tailoring_draft_to_dict(query_db("SELECT * FROM tailoring_drafts WHERE id = ?", [draft_id], one=True)), "preparation": preparation_queue_to_dict(query_db("SELECT * FROM application_preparation_queue WHERE id = ?", [package["id"]], one=True))})

    @app.post("/api/tailoring/drafts/<int:draft_id>/apply-memory")
    def apply_tailoring_memory(draft_id: int) -> Response:
        payload = request.get_json(silent=True) or {}
        row = query_db("SELECT * FROM tailoring_drafts WHERE id = ?", [draft_id], one=True)
        requested_keyword = text(payload.get("keyword"))
        keyword = normalize_keyword(requested_keyword)
        memory = query_db("SELECT * FROM keyword_memory WHERE candidate_profile_id = ? AND normalized_keyword = ?", [row["candidate_profile_id"] if row else 0, keyword], one=True)
        if memory is None and row is not None:
            job_row = query_db("SELECT * FROM jobs WHERE id = ?", [row["job_id"]], one=True)
            requirement = next(
                (item for item in extract_tailoring_requirements(job_to_dict(job_row))
                 if item["normalized"] == keyword or any(normalize_keyword(alias) == keyword for alias in item.get("alternative_terms", ()))),
                None,
            )
            if requirement:
                for alias in requirement.get("alternative_terms", ()):
                    memory = query_db(
                        "SELECT * FROM keyword_memory WHERE candidate_profile_id = ? AND normalized_keyword = ?",
                        [row["candidate_profile_id"], normalize_keyword(alias)], one=True,
                    )
                    if memory is not None:
                        keyword = text(memory["normalized_keyword"])
                        break
        if row is None or memory is None:
            return jsonify({"error": "No saved approved suggestion exists for this profile and keyword."}), 404
        if memory["status"] != "yes" or not text(memory["approved_replacement"]):
            return jsonify({"error": "This keyword does not have an approved replacement."}), 409
        try:
            paragraph_index = int(payload.get("paragraph_index"))
        except (TypeError, ValueError):
            return jsonify({"error": "Select the résumé bullet that the saved suggestion should replace."}), 400
        draft_path = safe_local_path(text(row["draft_path"])) or safe_local_path(text(row["source_path"]))
        if draft_path is None or not draft_path.is_file():
            return jsonify({"error": "The selected résumé draft is unavailable."}), 409
        paragraphs = list(Document(draft_path).paragraphs)
        if paragraph_index < 0 or paragraph_index >= len(paragraphs):
            return jsonify({"error": "The saved suggestion could not be matched safely to this résumé."}), 409
        current = normalize_space(paragraphs[paragraph_index].text)
        if text(memory["source_fingerprint"]) and text(memory["source_fingerprint"]) != grounding_hash(current):
            return jsonify({"error": "The saved suggestion does not match this résumé bullet; choose a bullet manually."}), 409
        changes = parse_json_array(row["changes_json"])
        prior = next((item for item in changes if int(item.get("paragraph_index", -1)) == paragraph_index), None)
        change = {"paragraph_index": paragraph_index, "keyword": keyword, "original_text": text(prior.get("original_text")) if prior else current, "proposed_text": text(memory["approved_replacement"]), "operation": "edit"}
        changes = [item for item in changes if int(item.get("paragraph_index", -1)) != paragraph_index]
        changes.append(change)
        try:
            result = rebuild_tailoring_draft(draft_id, changes)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"draft_id": draft_id, "changes": changes, "memory_applied": True, **result})

    @app.post("/api/tailoring/drafts/<int:draft_id>/improve")
    def improve_tailoring_draft_change(draft_id: int) -> Response:
        payload = request.get_json(force=True) or {}
        row = query_db("SELECT * FROM tailoring_drafts WHERE id = ?", [draft_id], one=True)
        if row is None:
            return jsonify({"error": "Tailoring draft was not found"}), 404
        job_row = query_db("SELECT * FROM jobs WHERE id = ?", [row["job_id"]], one=True)
        try:
            selection = resolve_tailoring_resume_profile({"candidate_profile_id": row["candidate_profile_id"], "resume_id": row["resume_id"]})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 409
        original = text(payload.get("original_text"))
        if not original:
            return jsonify({"error": "Select an existing résumé bullet before requesting an improvement"}), 400
        config = OllamaConfig.from_mapping(load_profile())
        if not config.enabled:
            return jsonify({"error": "AI improvement is disabled. Enable the configured local Ollama assistant first."}), 503
        target_length = max(120, round(len(original) * 1.2))
        source_context = next((item for item in tailoring_paragraphs(selection["resume_path"]) if normalize_space(item.get("text")) == normalize_space(original)), None)
        prompt = json.dumps({"task": "Improve only this résumé bullet", "job": {"title": job_row["title"], "description": job_row["job_description"]}, "keyword": text(payload.get("keyword")), "source_location": source_context.get("section") if source_context else "Selected résumé bullet", "verified_candidate_evidence": original, "bullet": original, "target_length_characters": target_length, "rules": ["Return JSON with proposed_bullet string only", "Preserve every number, percentage, version, range, plus sign, unit, qualifier, technology, security fact, employer, project and responsibility from the selected bullet", "Do not combine facts from other résumé bullets, projects or employers", "Do not add technologies, integrations, responsibilities or achievements", "Prefer the same length or shorter than the original", "If no safe improvement is possible, return the original bullet unchanged"]})
        response = request_json_completion(config, prompt, system="Return exactly one valid JSON object with a proposed_bullet string. Do not include reasoning, markdown, or commentary.")
        if not response.get("ok") or not text(response.get("data")):
            return jsonify({"error": response.get("error") or "The local AI assistant did not return a usable suggestion."}), 503
        raw_data = response.get("data")
        if isinstance(raw_data, dict):
            proposed = text(raw_data.get("proposed_bullet") or raw_data.get("proposed_text"))
        else:
            proposed = text(raw_data)
        if not proposed:
            return jsonify({"error": "The local AI assistant returned JSON without a proposed_bullet string."}), 422
        if proposed.startswith("```"):
            proposed = proposed.strip("`").replace("text\n", "", 1).strip()
        validation_error = validate_tailoring_bullet_suggestion(original, proposed)
        if validation_error:
            retry_prompt = f"{prompt}\n\nRetry this exact original bullet without changing any quantified fact. Preserve every number, percentage, version, range, plus sign, unit, and qualifier exactly. Return only a professional wording improvement as JSON; if no safe improvement is possible, return the original bullet unchanged. Original bullet: {original}"
            retry_response = request_json_completion(
                config,
                retry_prompt,
                system="Return exactly one valid JSON object with a proposed_bullet string. Preserve all factual and quantified content exactly. Do not include reasoning, markdown, or commentary.",
            )
            retry_data = retry_response.get("data") if retry_response.get("ok") else None
            if isinstance(retry_data, dict):
                retry_proposed = text(retry_data.get("proposed_bullet") or retry_data.get("proposed_text"))
            else:
                retry_proposed = text(retry_data)
            retry_error = validate_tailoring_bullet_suggestion(original, retry_proposed) if retry_proposed else "The retry returned no usable suggestion."
            if not retry_error:
                return jsonify({"original_text": original, "proposed_text": retry_proposed, "applied": False, "retry_attempted": True, "message": "AI suggestion is ready for review and has not been applied."})
            return jsonify({"error": f"AI suggestion rejected after one safety retry: {retry_error}", "original_text": original, "proposed_text": original, "applied": False, "retry_attempted": True}), 422
        return jsonify({"original_text": original, "proposed_text": proposed, "applied": False, "message": "AI suggestion is ready for review and has not been applied."})

    @app.get("/api/tailoring/drafts/<int:draft_id>/preview")
    def preview_tailoring_draft(draft_id: int) -> Response:
        row = query_db("SELECT * FROM tailoring_drafts WHERE id = ?", [draft_id], one=True)
        if row is None:
            return jsonify({"error": "Tailoring draft was not found"}), 404
        draft_path = safe_local_path(text(row["draft_path"])) or safe_local_path(text(row["source_path"])) or tailoring_draft_path(draft_id)
        if draft_path is None or not draft_path.is_file():
            return jsonify({"error": "The current résumé draft DOCX is unavailable."}), 409
        preview_pdf = DATA_DIR / "tailoring_drafts" / str(draft_id) / "preview.pdf"
        preview_pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf = export_docx_to_pdf(draft_path, preview_pdf) if not preview_pdf.is_file() or preview_pdf.stat().st_mtime < draft_path.stat().st_mtime else {"available": True, "path": str(preview_pdf), "cached": True}
        return jsonify({
            "draft_id": draft_id,
            "text": extract_docx_text(draft_path.read_bytes()),
            "layout": parse_json_object(row["layout_json"]),
            "pdf_available": bool(pdf.get("available")),
            "pdf_url": f"/api/tailoring/drafts/{draft_id}/preview.pdf" if pdf.get("available") else "",
            "pdf_reason": text(pdf.get("reason")),
        })

    @app.get("/api/tailoring/drafts/<int:draft_id>/preview.pdf")
    def download_tailoring_preview_pdf(draft_id: int) -> Response:
        row = query_db("SELECT * FROM tailoring_drafts WHERE id = ?", [draft_id], one=True)
        if row is None:
            return jsonify({"error": "Tailoring draft was not found"}), 404
        draft_path = safe_local_path(text(row["draft_path"])) or safe_local_path(text(row["source_path"])) or tailoring_draft_path(draft_id)
        preview_pdf = DATA_DIR / "tailoring_drafts" / str(draft_id) / "preview.pdf" if draft_path else None
        if preview_pdf is None or not preview_pdf.is_file():
            return jsonify({"error": "An accurate PDF preview is unavailable. Download the current DOCX instead."}), 404
        return send_file(preview_pdf, mimetype="application/pdf", as_attachment=False, download_name=f"tailoring-draft-{draft_id}.pdf")

    @app.get("/api/candidate-profiles/<int:profile_id>/keyword-memory")
    def list_keyword_memory(profile_id: int) -> Response:
        return jsonify([dict(row) for row in query_db("SELECT * FROM keyword_memory WHERE candidate_profile_id = ? ORDER BY normalized_keyword", [profile_id])])

    @app.post("/api/candidate-profiles/<int:profile_id>/keyword-memory")
    def save_keyword_memory(profile_id: int) -> Response:
        payload = request.get_json(force=True) or {}
        keyword = text(payload.get("keyword"))
        normalized = normalize_keyword(keyword)
        status = text(payload.get("status")) or "unknown"
        if not normalized or status not in {"yes", "no", "unknown"}:
            return jsonify({"error": "Keyword and status (yes, no or unknown) are required"}), 400
        profile = query_db("SELECT id FROM candidate_profiles WHERE id = ?", [profile_id], one=True)
        if profile is None:
            return jsonify({"error": "Candidate profile was not found"}), 404
        existing = query_db("SELECT * FROM keyword_memory WHERE candidate_profile_id = ? AND normalized_keyword = ?", [profile_id, normalized], one=True)
        values = {
            "keyword": keyword,
            "status": status,
            "project_employer": text(payload.get("project_employer")) or text(existing["project_employer"] if existing else ""),
            "supporting_bullet": text(payload.get("supporting_bullet")) or text(existing["supporting_bullet"] if existing else ""),
            "source_fingerprint": text(payload.get("source_fingerprint")) or text(existing["source_fingerprint"] if existing else ""),
            "approved_replacement": text(payload.get("approved_replacement")) or text(existing["approved_replacement"] if existing else ""),
            "resume_id": int(payload.get("resume_id") or (existing["resume_id"] if existing and "resume_id" in existing.keys() else 0)),
            "source_paragraph_index": int(payload.get("source_paragraph_index") if payload.get("source_paragraph_index") is not None else (existing["source_paragraph_index"] if existing and "source_paragraph_index" in existing.keys() else -1)),
        }
        get_db().execute(
            """INSERT INTO keyword_memory(candidate_profile_id, normalized_keyword, keyword, status, project_employer, supporting_bullet, source_fingerprint, approved_replacement, resume_id, source_paragraph_index)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(candidate_profile_id, normalized_keyword) DO UPDATE SET keyword=excluded.keyword, status=excluded.status, project_employer=excluded.project_employer, supporting_bullet=excluded.supporting_bullet, source_fingerprint=excluded.source_fingerprint, approved_replacement=excluded.approved_replacement, resume_id=excluded.resume_id, source_paragraph_index=excluded.source_paragraph_index, updated_at=CURRENT_TIMESTAMP""",
            [profile_id, normalized, values["keyword"], values["status"], values["project_employer"], values["supporting_bullet"], values["source_fingerprint"], values["approved_replacement"], values["resume_id"], values["source_paragraph_index"]],
        )
        get_db().commit()
        return jsonify(dict(query_db("SELECT * FROM keyword_memory WHERE candidate_profile_id = ? AND normalized_keyword = ?", [profile_id, normalized], one=True)))

    @app.delete("/api/candidate-profiles/<int:profile_id>/keyword-memory/<path:normalized_keyword>")
    def delete_keyword_memory(profile_id: int, normalized_keyword: str) -> Response:
        get_db().execute("DELETE FROM keyword_memory WHERE candidate_profile_id = ? AND normalized_keyword = ?", [profile_id, normalized_keyword])
        get_db().commit()
        return jsonify({"ok": True})

    @app.get("/api/candidate-profiles/<int:profile_id>/skill-memory")
    def list_skill_memory(profile_id: int) -> Response:
        return jsonify([dict(row) for row in query_db(
            "SELECT * FROM keyword_memory WHERE candidate_profile_id = ? AND confirmation_source = 'skill_confirmation' ORDER BY normalized_keyword",
            [profile_id],
        )])

    @app.post("/api/candidate-profiles/<int:profile_id>/skill-memory")
    def save_skill_memory(profile_id: int) -> Response:
        payload = request.get_json(force=True) or {}
        keyword = text(payload.get("keyword"))
        normalized = normalize_keyword(keyword)
        status = text(payload.get("status")) or "unknown"
        if not normalized or status not in {"yes", "no", "unknown"}:
            return jsonify({"error": "Keyword and status (yes, no or unknown) are required"}), 400
        if query_db("SELECT id FROM candidate_profiles WHERE id = ?", [profile_id], one=True) is None:
            return jsonify({"error": "Candidate profile was not found"}), 404
        now = datetime.now().isoformat(timespec="seconds")
        get_db().execute(
            """INSERT INTO keyword_memory(candidate_profile_id, normalized_keyword, keyword, status, project_employer, supporting_bullet, source_fingerprint, approved_replacement, resume_id, source_paragraph_index, confirmation_source, confirmed_at, notes)
               VALUES (?, ?, ?, ?, '', '', '', '', 0, -1, 'skill_confirmation', ?, ?)
               ON CONFLICT(candidate_profile_id, normalized_keyword) DO UPDATE SET keyword=excluded.keyword, status=excluded.status, confirmation_source='skill_confirmation', confirmed_at=excluded.confirmed_at, notes=excluded.notes, updated_at=CURRENT_TIMESTAMP""",
            [profile_id, normalized, keyword, status, now, text(payload.get("notes"))],
        )
        get_db().commit()
        return jsonify(dict(query_db(
            "SELECT * FROM keyword_memory WHERE candidate_profile_id = ? AND normalized_keyword = ?",
            [profile_id, normalized], one=True,
        )))

    @app.delete("/api/candidate-profiles/<int:profile_id>/skill-memory/<path:normalized_skill>")
    def delete_skill_memory(profile_id: int, normalized_skill: str) -> Response:
        normalized = normalize_keyword(normalized_skill)
        get_db().execute(
            "DELETE FROM keyword_memory WHERE candidate_profile_id = ? AND normalized_keyword = ? AND confirmation_source = 'skill_confirmation'",
            [profile_id, normalized],
        )
        get_db().commit()
        return jsonify({"ok": True})

    @app.get("/api/ollama/health")
    def ollama_health() -> Response:
        profile = load_profile()
        config = OllamaConfig.from_mapping(profile)
        return jsonify(build_ollama_health_report(config))

    @app.get("/api/health")
    def health() -> Response:
        diagnostics = collect_environment_diagnostics()
        diagnostics["database_path"] = str(DB_PATH)
        diagnostics["discovery_cache_path"] = str(DB_PATH)
        diagnostics["discovery_debug_path"] = str(DATA_DIR / "discovery_debug")
        diagnostics["profile_loaded"] = bool(load_profile())
        return jsonify(diagnostics)

    @app.post("/api/ollama/suggest")
    def ollama_suggest() -> Response:
        payload = request.get_json(force=True)
        profile = load_profile()
        config = OllamaConfig.from_mapping(profile)
        kind = text(payload.get("kind")) or "cover_letter"
        job = payload.get("job") or {}
        evidence = payload.get("evidence") or build_candidate_evidence(profile)
        prompt = build_ollama_prompt(kind, job, evidence, payload)
        response = request_json_completion(config, prompt, system="Return strict JSON only.")
        if not response.get("ok"):
            fallback = build_local_ollama_fallback(kind, job, evidence)
            return jsonify({"ok": False, "error": response.get("error", ""), "suggestion": fallback, "raw": response.get("raw", "")})
        suggestion = validate_ollama_suggestion(kind, response["data"], job, evidence)
        if suggestion["ok"]:
            return jsonify({"ok": True, "suggestion": suggestion["suggestion"], "raw": response.get("raw", "")})
        return jsonify({"ok": False, "error": suggestion["error"], "suggestion": build_local_ollama_fallback(kind, job, evidence), "raw": response.get("raw", "")})

    @app.get("/api/evidence")
    def list_evidence() -> Response:
        return jsonify(list_evidence_library())

    @app.post("/api/evidence/<int:evidence_id>/review")
    def review_evidence(evidence_id: int) -> Response:
        payload = request.get_json(force=True)
        updated = update_evidence_review(
            evidence_id,
            approved=payload.get("approved"),
            review_notes=text(payload.get("review_notes")),
        )
        if updated is None:
            return jsonify({"error": "Evidence item not found"}), 404
        return jsonify(updated)

    @app.get("/api/jobs/<int:job_id>/analysis")
    def job_evidence_analysis(job_id: int) -> Response:
        job = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        if job is None:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(build_job_evidence_analysis(job_to_dict(job), load_profile()))

    @app.get("/api/jobs/<int:job_id>/resume-variants")
    def job_resume_variants(job_id: int) -> Response:
        job = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        if job is None:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(list_resume_variants(job_id))

    @app.post("/api/resume-variants/<int:variant_id>/review")
    def review_resume_variant(variant_id: int) -> Response:
        payload = request.get_json(force=True)
        updated = update_resume_variant_review(
            variant_id,
            approved=payload.get("approved"),
            review_notes=text(payload.get("review_notes")),
        )
        if updated is None:
            return jsonify({"error": "Variant not found"}), 404
        return jsonify(updated)

    @app.post("/api/profile")
    def save_profile() -> Response:
        payload = request.get_json(force=True)
        profile = normalize_profile_payload(payload, load_profile())
        try:
            profile, location_result = geocode_profile_home_location(profile)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        upsert_profile(profile)
        sync_evidence_library(profile)
        saved = load_profile()
        saved["location_result"] = location_result
        return jsonify(saved)

    @app.post("/api/profile/upload")
    def upload_profile_file() -> Response:
        uploaded = request.files.get("file")
        if not uploaded:
            return jsonify({"error": "No file uploaded"}), 400
        filename = uploaded.filename or "resume.txt"
        template_kind = text(request.form.get("template_kind")).lower()
        suffix = Path(filename).suffix.lower()
        try:
            content = uploaded.read()
            extracted = extract_uploaded_text(filename, content)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        profile = load_profile()
        warning = ""
        status_message = ""
        if template_kind == "cover_letter":
            if suffix != ".docx":
                return jsonify({"error": "Upload a DOCX cover-letter template."}), 400
            template_path = save_master_cover_letter_template(filename, content)
            profile["cover_letter_template"] = extracted
            profile["cover_letter_docx_template_path"] = str(template_path)
            profile["cover_letter_template_status"] = "DOCX template uploaded"
            status_message = "DOCX template uploaded — formatting-preserving generation available"
        else:
            profile["resume_text"] = extracted
            if suffix == ".docx":
                template_path = save_master_resume_template(filename, content)
                profile["resume_docx_template_path"] = str(template_path)
            else:
                profile["resume_docx_template_path"] = ""
                warning = "Upload a DOCX resume to generate a format-preserving tailored resume."
        upsert_profile(profile)
        sync_evidence_library(profile)
        response: dict[str, Any] = {}
        if warning:
            response["warning"] = warning
        else:
            if template_kind == "cover_letter":
                response["cover_letter_template"] = extracted
                response["cover_letter_docx_template_path"] = profile["cover_letter_docx_template_path"]
                response["cover_letter_template_status"] = profile["cover_letter_template_status"]
                response["status_message"] = status_message
            else:
                response["resume_text"] = extracted
                response["resume_docx_template_path"] = profile["resume_docx_template_path"]
        if template_kind != "cover_letter" and "resume_text" not in response:
            response["resume_text"] = extracted
        return jsonify(response)

    @app.get("/api/jobs")
    def list_jobs() -> Response:
        rows = query_db("SELECT * FROM jobs ORDER BY date_added DESC, id DESC")
        return jsonify([job_to_dict(row) for row in rows])

    @app.post("/api/jobs")
    def create_job() -> Response:
        payload = request.get_json(force=True)
        clean = normalize_job_payload(payload)
        db = get_db()
        cursor = db.execute(
            f"""
            INSERT INTO jobs ({', '.join(JOB_COLUMNS.keys())})
            VALUES ({', '.join(['?'] * len(JOB_COLUMNS))})
            """,
            tuple(clean[column] for column in JOB_COLUMNS),
        )
        db.commit()
        job = query_db("SELECT * FROM jobs WHERE id = ?", [cursor.lastrowid], one=True)
        return jsonify(job_to_dict(job)), 201

    @app.put("/api/jobs/<int:job_id>")
    def update_job(job_id: int) -> Response:
        payload = request.get_json(force=True)
        existing = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        if existing is None:
            return jsonify({"error": "Job not found"}), 404
        merged = job_to_dict(existing)
        merged.update(payload)
        clean = normalize_job_payload(merged)
        assignments = ", ".join([f"{column} = ?" for column in JOB_COLUMNS])
        get_db().execute(
            f"UPDATE jobs SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (*[clean[column] for column in JOB_COLUMNS], job_id),
        )
        get_db().commit()
        job = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        return jsonify(job_to_dict(job))

    @app.delete("/api/jobs/<int:job_id>")
    def delete_job(job_id: int) -> Response:
        get_db().execute("DELETE FROM jobs WHERE id = ?", [job_id])
        get_db().commit()
        return jsonify({"ok": True})

    @app.get("/api/shortlist")
    def list_shortlist() -> Response:
        rows = query_db(
            """
            SELECT * FROM jobs
            WHERE status = 'shortlisted'
            ORDER BY date_shortlisted DESC, date_added DESC, id DESC
            """
        )
        return jsonify([job_to_dict(row) for row in rows])

    @app.post("/api/shortlist")
    def create_shortlist_item() -> Response:
        payload = request.get_json(force=True)
        try:
            generation_profile = resolve_generation_profile(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        clean = normalize_job_payload({**payload, "status": "shortlisted"})
        existing = find_existing_shortlist_match(clean)
        if existing is not None:
            existing_dict = job_to_dict(existing)
            if text(existing_dict.get("status")) == "shortlisted":
                return jsonify({**existing_dict, "duplicate": True, "restored": False})
            restore_shortlist_item(existing_dict["id"])
            generation = generate_and_store_shortlist_documents(existing_dict["id"], profile_override=generation_profile)
            job = query_db("SELECT * FROM jobs WHERE id = ?", [existing_dict["id"]], one=True)
            return jsonify({**job_to_dict(job), "generation": generation, "duplicate": False, "restored": True}), 200

        today = date.today().isoformat()
        clean["status"] = "shortlisted"
        clean["date_shortlisted"] = text(clean.get("date_shortlisted")) or today
        clean["date_added"] = text(clean.get("date_added")) or today
        clean["resume_generation_status"] = "pending"
        clean["cover_letter_generation_status"] = "pending"
        clean["resume_generation_error"] = ""
        clean["cover_letter_generation_error"] = ""
        clean["cover_letter_generation_warning"] = ""
        clean["generation_error"] = ""
        db = get_db()
        cursor = db.execute(
            f"""
            INSERT INTO jobs ({', '.join(JOB_COLUMNS.keys())})
            VALUES ({', '.join(['?'] * len(JOB_COLUMNS))})
            """,
            tuple(clean[column] for column in JOB_COLUMNS),
        )
        db.commit()
        job_id = int(cursor.lastrowid)
        generation = generate_and_store_shortlist_documents(job_id, profile_override=generation_profile)
        job = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        return jsonify({**job_to_dict(job), "generation": generation, "duplicate": False, "restored": False}), 201

    @app.post("/api/shortlist/<int:job_id>/regenerate")
    def regenerate_shortlist_documents(job_id: int) -> Response:
        job = query_db("SELECT * FROM jobs WHERE id = ? AND status = 'shortlisted'", [job_id], one=True)
        if job is None:
            return jsonify({"error": "Shortlisted job not found"}), 404
        payload = request.get_json(silent=True) or {}
        try:
            generation_profile = resolve_generation_profile(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        generation = generate_and_store_shortlist_documents(job_id, profile_override=generation_profile)
        refreshed = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        return jsonify({**job_to_dict(refreshed), "generation": generation})

    @app.post("/api/shortlist/<int:job_id>/keyword-score")
    def shortlist_keyword_score(job_id: int) -> Response:
        """Score the selected base résumé without generating or changing documents."""
        row = query_db("SELECT * FROM jobs WHERE id = ? AND status = 'shortlisted'", [job_id], one=True)
        if row is None:
            return jsonify({"error": "Shortlisted job not found"}), 404
        payload = request.get_json(silent=True) or {}
        try:
            selected_profile = resolve_generation_profile(payload)
            profile = selected_profile if selected_profile is not None else load_profile()
            if selected_profile is not None and not text(profile.get("resume_text")):
                raise ValueError("Selected base résumé has no readable text to score")
            if selected_profile is None and not profile_has_generation_source(profile):
                raise ValueError("Complete the Profile page with resume, project, or work-experience details before reviewing Keywords Score")
            job = job_to_dict(row)
            score = build_keywords_score_report(job, profile)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(
            {
                "keywords_score": score,
                "candidate_profile_id": profile.get("_candidate_profile_id", ""),
                "resume_id": payload.get("resume_id", ""),
                "generated": False,
            }
        )

    @app.post("/api/shortlist/<int:job_id>/regenerate-resume")
    def regenerate_shortlist_resume(job_id: int) -> Response:
        job = query_db("SELECT * FROM jobs WHERE id = ? AND status = 'shortlisted'", [job_id], one=True)
        if job is None:
            return jsonify({"error": "Shortlisted job not found"}), 404
        payload = request.get_json(silent=True) or {}
        try:
            generation_profile = resolve_generation_profile(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        generation = generate_and_store_shortlist_documents(job_id, {"resume"}, generation_profile)
        refreshed = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        return jsonify({**job_to_dict(refreshed), "generation": generation})

    @app.post("/api/shortlist/<int:job_id>/regenerate-cover-letter")
    def regenerate_shortlist_cover_letter(job_id: int) -> Response:
        job = query_db("SELECT * FROM jobs WHERE id = ? AND status = 'shortlisted'", [job_id], one=True)
        if job is None:
            return jsonify({"error": "Shortlisted job not found"}), 404
        payload = request.get_json(silent=True) or {}
        try:
            generation_profile = resolve_generation_profile(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        generation = generate_and_store_shortlist_documents(job_id, {"cover_letter"}, generation_profile)
        refreshed = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        return jsonify({**job_to_dict(refreshed), "generation": generation})

    @app.delete("/api/shortlist/<int:job_id>")
    def remove_shortlist_item(job_id: int) -> Response:
        existing = query_db("SELECT * FROM jobs WHERE id = ? AND status = 'shortlisted'", [job_id], one=True)
        if existing is None:
            return jsonify({"error": "Shortlisted job not found"}), 404
        get_db().execute(
            """
            UPDATE jobs
            SET status = 'Saved',
                resume_generation_status = '',
                cover_letter_generation_status = '',
                resume_generation_error = '',
                cover_letter_generation_error = '',
                cover_letter_generation_warning = '',
                generation_error = '',
                resume_docx_path = '',
                cover_letter_docx_path = '',
                generated_at = '',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            [job_id],
        )
        get_db().commit()
        return jsonify({"ok": True, "restored_to_saved": True})

    @app.post("/api/shortlist/<int:job_id>/applied")
    def mark_shortlist_applied(job_id: int) -> Response:
        existing = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        if existing is None:
            return jsonify({"error": "Job not found"}), 404
        get_db().execute(
            "UPDATE jobs SET status = 'Applied', date_applied = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [date.today().isoformat(), job_id],
        )
        get_db().commit()
        return jsonify(job_to_dict(query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)))

    @app.get("/api/shortlist/<int:job_id>/resume")
    def download_shortlist_resume(job_id: int) -> Response:
        return download_shortlist_document(job_id, "resume")

    @app.get("/api/shortlist/<int:job_id>/cover-letter")
    def download_shortlist_cover_letter(job_id: int) -> Response:
        return download_shortlist_document(job_id, "cover_letter")

    @app.get("/api/shortlist/<int:job_id>/preview")
    def preview_shortlist_documents(job_id: int) -> Response:
        row = query_db("SELECT * FROM jobs WHERE id = ? AND status = 'shortlisted'", [job_id], one=True)
        if row is None:
            return jsonify({"error": "Shortlisted job not found"}), 404
        folder = generated_applications_dir() / str(job_id)

        def read_draft(name: str) -> str:
            path = folder / name
            if not path.is_file():
                return ""
            try:
                return path.read_text(encoding="utf-8")
            except OSError:
                return ""

        def read_docx(field: str) -> tuple[str, bool]:
            path = safe_generated_path(row[field])
            if path is None or not path.is_file():
                return "", False
            try:
                document = Document(io.BytesIO(path.read_bytes()))
                value = "\n".join(paragraph.text for paragraph in iter_document_paragraphs(document) if paragraph.text.strip())
                return value, True
            except (OSError, ValueError, zipfile.BadZipFile):
                return "", False

        resume_preview, resume_available = read_docx("resume_docx_path")
        cover_preview, cover_available = read_docx("cover_letter_docx_path")

        return jsonify({
            "resume": resume_preview,
            "cover_letter": cover_preview,
            "resume_draft": read_draft("resume.txt"),
            "cover_letter_draft": read_draft("cover_letter.txt"),
            "resume_source": "successful_docx" if resume_available else "unavailable",
            "cover_letter_source": "successful_docx" if cover_available else "unavailable",
            "resume_status": text(row["resume_generation_status"]),
            "cover_letter_status": text(row["cover_letter_generation_status"]),
            "generation_debug": load_generation_debug(job_id),
        })

    @app.post("/api/jobs/from-description")
    def job_from_description() -> Response:
        payload = request.get_json(force=True)
        description = text(payload.get("job_description"))
        details = extract_job_details(description, text(payload.get("source")) or "Pasted description")
        details["job_description"] = description
        return jsonify(details)

    @app.post("/api/jobs/from-url")
    def job_from_url() -> Response:
        payload = request.get_json(force=True)
        url = text(payload.get("url"))
        if not url:
            return jsonify({"error": "URL is required"}), 400
        try:
            page_text = fetch_public_page_text(url)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        details = extract_job_details(page_text, source_from_url(url))
        details["url"] = url
        details["application_url"] = url
        details["job_description"] = page_text[:20000]
        return jsonify(details)

    @app.post("/api/jobs/import-csv")
    def import_jobs_csv() -> Response:
        uploaded = request.files.get("file")
        if not uploaded:
            return jsonify({"error": "No CSV file uploaded"}), 400
        content = uploaded.read().decode("utf-8-sig", errors="replace")
        imported = import_csv_jobs(content)
        return jsonify({"imported": imported})

    @app.post("/api/discovery/search")
    def discovery_search() -> Response:
        payload = request.get_json(force=True)
        keywords = text(payload.get("keywords"))
        location = text(payload.get("location"))
        rows = query_db(
            """
            SELECT * FROM jobs
            WHERE (? = '' OR lower(title || ' ' || company || ' ' || job_description) LIKE ?)
            AND (? = '' OR lower(location) LIKE ?)
            ORDER BY fit_score DESC, date_added DESC
            """,
            [keywords, f"%{keywords.lower()}%", location, f"%{location.lower()}%"],
        )
        return jsonify(
            {
                "message": "Local saved-job search is active. Public ATS connectors can be added here later.",
                "results": [job_to_dict(row) for row in rows],
            }
        )

    @app.get("/api/discovery/preferences")
    def discovery_preferences_get() -> Response:
        search_key = text(request.args.get("search_key"))
        return jsonify({"search_key": search_key, "preferences": load_discovery_preferences(search_key)})

    @app.post("/api/discovery/preferences")
    def discovery_preferences_set() -> Response:
        payload = request.get_json(force=True)
        search_key = text(payload.get("search_key")) or discovery_search_signature(payload)
        preferences = discovery_preferences_payload(payload.get("preferences") if isinstance(payload.get("preferences"), dict) else payload)
        save_discovery_preferences(search_key, preferences)
        return jsonify({"search_key": search_key, "preferences": preferences})

    @app.get("/api/discovery/searches")
    def saved_discovery_searches() -> Response:
        rows = query_db("SELECT * FROM saved_search_profiles ORDER BY enabled DESC, name COLLATE NOCASE")
        return jsonify([saved_search_to_dict(row) for row in rows])

    @app.post("/api/discovery/searches")
    def create_saved_discovery_search() -> Response:
        try:
            search = normalize_saved_search_payload(request.get_json(force=True) or {})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        try:
            cursor = get_db().execute(
                """INSERT INTO saved_search_profiles
                   (name, keywords, location, remote_preference, seniority, minimum_salary,
                    enabled_sources_json, date_window, distance, interval_minutes, enabled,
                    auto_prepare_enabled, auto_prepare_min_priority, auto_prepare_require_canadian,
                    auto_prepare_candidate_profile_id, auto_prepare_resume_id, auto_prepare_cover_letter_template_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [search["name"], search["keywords"], search["location"], search["remote_preference"], search["seniority"], search["minimum_salary"], dumps_json(search["enabled_sources"]), search["date_window"], search["distance"], search["interval_minutes"], search["enabled"], search["auto_prepare_enabled"], search["auto_prepare_min_priority"], search["auto_prepare_require_canadian"], search["auto_prepare_candidate_profile_id"], search["auto_prepare_resume_id"], search["auto_prepare_cover_letter_template_id"]],
            )
            get_db().commit()
        except sqlite3.IntegrityError:
            return jsonify({"error": "A saved search with that name already exists"}), 409
        return jsonify(saved_search_to_dict(query_db("SELECT * FROM saved_search_profiles WHERE id = ?", [cursor.lastrowid], one=True))), 201

    @app.put("/api/discovery/searches/<int:search_id>")
    def update_saved_discovery_search(search_id: int) -> Response:
        row = query_db("SELECT * FROM saved_search_profiles WHERE id = ?", [search_id], one=True)
        if row is None:
            return jsonify({"error": "Saved search not found"}), 404
        try:
            search = normalize_saved_search_payload(request.get_json(force=True) or {}, saved_search_to_dict(row))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        try:
            get_db().execute(
                """UPDATE saved_search_profiles SET name = ?, keywords = ?, location = ?, remote_preference = ?,
                   seniority = ?, minimum_salary = ?, enabled_sources_json = ?, date_window = ?, distance = ?,
                   interval_minutes = ?, enabled = ?, auto_prepare_enabled = ?, auto_prepare_min_priority = ?,
                   auto_prepare_require_canadian = ?, auto_prepare_candidate_profile_id = ?, auto_prepare_resume_id = ?,
                   auto_prepare_cover_letter_template_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                [search["name"], search["keywords"], search["location"], search["remote_preference"], search["seniority"], search["minimum_salary"], dumps_json(search["enabled_sources"]), search["date_window"], search["distance"], search["interval_minutes"], search["enabled"], search["auto_prepare_enabled"], search["auto_prepare_min_priority"], search["auto_prepare_require_canadian"], search["auto_prepare_candidate_profile_id"], search["auto_prepare_resume_id"], search["auto_prepare_cover_letter_template_id"], search_id],
            )
            get_db().commit()
        except sqlite3.IntegrityError:
            return jsonify({"error": "A saved search with that name already exists"}), 409
        return jsonify(saved_search_to_dict(query_db("SELECT * FROM saved_search_profiles WHERE id = ?", [search_id], one=True)))

    @app.delete("/api/discovery/searches/<int:search_id>")
    def delete_saved_discovery_search(search_id: int) -> Response:
        get_db().execute("DELETE FROM saved_search_profiles WHERE id = ?", [search_id])
        get_db().commit()
        return jsonify({"ok": True})

    @app.get("/api/discovery/inbox")
    def discovery_inbox() -> Response:
        rows = query_db(
            """SELECT * FROM jobs WHERE discovery_first_seen_at <> '' AND discovery_state <> 'ignored'
               ORDER BY discovery_state = 'new' DESC, discovery_last_seen_at DESC, id DESC LIMIT 500"""
        )
        return jsonify([job_to_dict(row) for row in rows])

    @app.post("/api/discovery/inbox/<int:job_id>/review")
    def review_discovery_job(job_id: int) -> Response:
        row = query_db("SELECT * FROM jobs WHERE id = ? AND discovery_first_seen_at <> ''", [job_id], one=True)
        if row is None:
            return jsonify({"error": "Discovered job not found"}), 404
        get_db().execute("UPDATE jobs SET discovery_state = 'reviewed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", [job_id])
        get_db().commit()
        return jsonify(job_to_dict(query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)))

    @app.post("/api/discovery/inbox/<int:job_id>/ignore")
    def ignore_discovery_job(job_id: int) -> Response:
        row = query_db("SELECT * FROM jobs WHERE id = ? AND discovery_first_seen_at <> ''", [job_id], one=True)
        if row is None:
            return jsonify({"error": "Discovered job not found"}), 404
        get_db().execute("UPDATE jobs SET discovery_state = 'ignored', updated_at = CURRENT_TIMESTAMP WHERE id = ?", [job_id])
        get_db().commit()
        return jsonify({"ok": True})

    @app.get("/api/preparation/queue")
    def preparation_queue() -> Response:
        status = normalize_space(text(request.args.get("status")))
        if status and status not in PREPARATION_STATUSES:
            return jsonify({"error": "Unknown preparation status"}), 400
        query = "SELECT * FROM application_preparation_queue"
        args: list[Any] = []
        if status:
            query += " WHERE status = ?"
            args.append(status)
        query += " ORDER BY CASE status WHEN 'ready_for_review' THEN 0 WHEN 'preparing' THEN 1 WHEN 'queued' THEN 2 ELSE 3 END, updated_at DESC, id DESC LIMIT 250"
        return jsonify([preparation_queue_to_dict(row) for row in query_db(query, args)])

    @app.post("/api/preparation/queue")
    def queue_preparation() -> Response:
        payload = request.get_json(force=True) or {}
        try:
            item, duplicate = enqueue_application_preparation(int(payload.get("job_id") or 0), payload=payload)
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({**item, "duplicate": duplicate}), 200 if duplicate else 201

    @app.post("/api/preparation/<int:item_id>/prepare")
    def prepare_queue_item(item_id: int) -> Response:
        try:
            return jsonify(prepare_application_queue_item(item_id, owner=f"manual:{uuid.uuid4()}"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 409

    @app.post("/api/preparation/<int:item_id>/regenerate")
    def regenerate_queue_item(item_id: int) -> Response:
        row = query_db("SELECT * FROM application_preparation_queue WHERE id = ?", [item_id], one=True)
        if row is None:
            return jsonify({"error": "Preparation queue item was not found"}), 404
        try:
            return jsonify(prepare_application_queue_item(item_id, owner=f"manual:{uuid.uuid4()}", allow_regenerate=True))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 409

    @app.post("/api/preparation/<int:item_id>/review")
    def review_preparation_item(item_id: int) -> Response:
        action = text((request.get_json(silent=True) or {}).get("action")).lower()
        transitions = {"approve": ("approved", "approved"), "skip": ("skipped", "skipped"), "reject": ("skipped", "rejected")}
        if action not in transitions:
            return jsonify({"error": "Action must be approve, reject or skip"}), 400
        row = query_db("SELECT * FROM application_preparation_queue WHERE id = ?", [item_id], one=True)
        if row is None:
            return jsonify({"error": "Preparation queue item was not found"}), 404
        status, review_status = transitions[action]
        if action == "approve":
            if row["status"] != "ready_for_review":
                return jsonify({"error": "Only a package in ready_for_review status can be approved"}), 409
            if row["resume_status"] != "generated" or row["cover_letter_status"] != "generated":
                return jsonify({"error": "Both résumé and cover letter must be generated before approval"}), 409
            if not text(row["prepared_resume_path"]) or not text(row["prepared_cover_letter_path"]):
                return jsonify({"error": "This package has no recorded generated documents"}), 409
            if not all(safe_preparation_artifact_path(row[field]) and safe_preparation_artifact_path(row[field]).is_file() for field in ("prepared_resume_path", "prepared_cover_letter_path")):
                return jsonify({"error": "A generated document for this package is no longer available"}), 409
        return jsonify(_update_preparation_item(item_id, status=status, review_status=review_status))

    @app.post("/api/preparation/<int:item_id>/eligibility-review")
    def review_preparation_eligibility(item_id: int) -> Response:
        payload = request.get_json(silent=True) or {}
        row = query_db("SELECT * FROM application_preparation_queue WHERE id = ?", [item_id], one=True)
        if row is None:
            return jsonify({"error": "Preparation queue item was not found"}), 404
        if row["review_status"] != "manual_eligibility":
            return jsonify({"error": "This package does not require an eligibility review"}), 409
        confirmed = as_bool(payload.get("confirmed"))
        if not confirmed:
            return jsonify(_update_preparation_item(item_id, status="skipped", review_status="rejected", eligibility_review_status="rejected", eligibility_note="Canadian eligibility was not confirmed by the user."))
        return jsonify(_update_preparation_item(item_id, status="queued", review_status="pending", eligibility_review_status="confirmed", eligibility_note="Canadian eligibility was manually confirmed; preparation is ready to start."))

    @app.get("/api/preparation/<int:item_id>/preview")
    def preparation_preview(item_id: int) -> Response:
        item = query_db("SELECT * FROM application_preparation_queue WHERE id = ?", [item_id], one=True)
        if item is None:
            return jsonify({"error": "Preparation queue item was not found"}), 404
        job = query_db("SELECT * FROM jobs WHERE id = ?", [item["job_id"]], one=True)
        if job is None:
            return jsonify({"error": "Job not found"}), 404
        values: dict[str, Any] = {}
        for kind, package_field in (("resume", "prepared_resume_path"), ("cover_letter", "prepared_cover_letter_path")):
            path = safe_preparation_artifact_path(item[package_field])
            values[kind] = ""
            if path and path.is_file():
                try:
                    values[kind] = "\n".join(paragraph.text for paragraph in iter_document_paragraphs(Document(io.BytesIO(path.read_bytes()))) if paragraph.text.strip())
                except (OSError, ValueError, zipfile.BadZipFile):
                    values[kind] = ""
        return jsonify({"resume": values["resume"], "cover_letter": values["cover_letter"], "status": item["status"], "job_id": item["job_id"]})

    @app.get("/api/preparation/<int:item_id>/download/<kind>")
    def download_preparation_document(item_id: int, kind: str) -> Response:
        if kind not in {"resume", "cover-letter"}:
            return jsonify({"error": "Document kind must be resume or cover-letter"}), 400
        item = query_db("SELECT * FROM application_preparation_queue WHERE id = ?", [item_id], one=True)
        if item is None:
            return jsonify({"error": "Preparation queue item was not found"}), 404
        field = "prepared_resume_path" if kind == "resume" else "prepared_cover_letter_path"
        path = safe_preparation_artifact_path(item[field])
        if path is None or not path.is_file():
            return jsonify({"error": "The generated document for this package is unavailable"}), 404
        return send_file(path, as_attachment=True, download_name=secure_filename(path.name) or "document.docx", mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    @app.get("/api/discovery/runs")
    def discovery_runs() -> Response:
        rows = query_db("SELECT * FROM discovery_run_history ORDER BY id DESC LIMIT 100")
        return jsonify([dict(row) | {"source_outcomes": parse_json_object(row["source_outcomes_json"])} for row in rows])

    @app.post("/api/discovery/searches/<int:search_id>/run")
    def run_saved_discovery_search(search_id: int) -> Response:
        row = query_db("SELECT * FROM saved_search_profiles WHERE id = ?", [search_id], one=True)
        if row is None:
            return jsonify({"error": "Saved search not found"}), 404
        search = saved_search_to_dict(row)
        owner = f"manual:{uuid.uuid4()}"
        if not acquire_discovery_search_lease(search_id, owner):
            return jsonify({"error": "This saved search is already running; try again when the active run completes."}), 409
        heartbeat_stop, heartbeat_thread = start_discovery_search_lease_heartbeat(search_id, owner)
        run_id = create_discovery_run(search_id, "manual")
        try:
            result = run_discovery_pipeline(saved_search_to_discovery_payload(search), search_id=search_id, run_id=run_id)
            finish_discovery_run(run_id, status="completed", fetched=result["total"], new_count=result["persisted"]["new"], duplicate_count=result["persisted"]["duplicate"], errors=len(result["errors"]), outcomes=result["source_diagnostics"])
            now = datetime.now().isoformat(timespec="seconds")
            next_run = (datetime.now() + timedelta(minutes=int(search["interval_minutes"]))).isoformat(timespec="seconds")
            get_db().execute("UPDATE saved_search_profiles SET last_run_at = ?, next_run_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", [now, next_run, search_id])
            get_db().commit()
            return jsonify({**result, "run_id": run_id, "search": saved_search_to_dict(query_db("SELECT * FROM saved_search_profiles WHERE id = ?", [search_id], one=True))})
        except Exception as exc:
            finish_discovery_run(run_id, status="failed", fetched=0, new_count=0, duplicate_count=0, errors=1, outcomes={}, error=str(exc))
            return jsonify({"error": f"Discovery run failed: {exc}", "run_id": run_id}), 502
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1)
            release_discovery_search_lease(search_id, owner)

    @app.get("/api/discovery/scheduler")
    def discovery_scheduler_get() -> Response:
        row = query_db("SELECT value FROM app_settings WHERE key = 'discovery_scheduler_enabled'", one=True)
        return jsonify({"enabled": bool(row and as_bool(row["value"]))})

    @app.put("/api/discovery/scheduler")
    def discovery_scheduler_set() -> Response:
        enabled = as_bool((request.get_json(silent=True) or {}).get("enabled"))
        get_db().execute("INSERT INTO app_settings (key, value) VALUES ('discovery_scheduler_enabled', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", ["1" if enabled else "0"])
        get_db().commit()
        return jsonify({"enabled": enabled})

    @app.get("/api/discovery/task-status")
    def discovery_task_status() -> Response:
        """Report the optional Windows Task Scheduler registration without changing it."""
        if os.name != "nt":
            return jsonify({"supported": False, "installed": False, "task_name": DISCOVERY_TASK_NAME, "message": "Windows Task Scheduler is available only on Windows."})
        try:
            result = subprocess.run(
                ["schtasks.exe", "/Query", "/TN", DISCOVERY_TASK_NAME, "/FO", "LIST", "/V"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            installed = result.returncode == 0
            output = result.stdout if installed else ""
            return jsonify({"supported": True, "installed": installed, "task_name": DISCOVERY_TASK_NAME, "details": output, "message": "Installed" if installed else "Not installed. Run scripts\\install_discovery_task.ps1 once to opt in."})
        except (OSError, subprocess.TimeoutExpired) as exc:
            return jsonify({"supported": True, "installed": False, "task_name": DISCOVERY_TASK_NAME, "message": f"Task status unavailable: {exc}"})

    @app.get("/api/discovery/results")
    def discovery_results_get() -> Response:
        search_key = text(request.args.get("search_key"))
        run = load_discovery_search_run(search_key)
        if not run:
            return jsonify({"error": "Discovery search not found"}), 404
        return jsonify(run)

    @app.get("/api/discovery/debug/latest")
    def discovery_debug_latest() -> Response:
        latest = load_latest_discovery_debug_run()
        if not latest:
            return jsonify({"error": "No discovery debug runs found"}), 404
        return jsonify(latest)

    @app.post("/api/discovery/jobspy")
    def discovery_jobspy() -> Response:
        payload = request.get_json(force=True)
        keywords = text(payload.get("keywords"))
        if not keywords:
            return jsonify({"error": "Keywords are required"}), 400
        bypass_cache = as_bool(payload.get("bypass_cache"))

        search = discovery_search_config(payload)
        search_key = discovery_search_signature(payload)
        stored_preferences = load_discovery_preferences(search_key)
        preferences = stored_preferences or discovery_preferences_payload({})
        profile = load_profile()
        provider = get_geocoding_provider()
        origin = profile_home_location(profile)
        try:
            location_context = resolve_discovery_location_context(search["location"], profile, provider, use_cache=not bypass_cache)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        search["original_location"] = location_context["original_input"]
        search["normalized_location"] = location_context["normalized_input"]
        search["distance_origin"] = location_context["distance_origin"]
        search["discovery_location"] = location_context["discovery_location"]
        search["location_resolution_method"] = location_context["resolution_method"]
        search["location_geocode"] = location_context["lookup"]

        fetched = fetch_jobspy_jobs(
            keywords=keywords,
            location=search["discovery_location"],
            distance=search["distance"],
            remote_preference=search["remote_preference"],
            job_type=None,
            results_wanted=search["per_source_cap"],
            hours_old=search["hours_old"],
            enabled_sources=search["enabled_sources"],
            country_indeed=text(payload.get("country_indeed")) or "Canada",
        )

        raw_jobs = fetched.get("jobs", [])
        existing_keys = existing_job_dedupe_keys()
        seen_keys: set[str] = set()
        jobs: list[dict[str, Any]] = []
        duplicates = 0
        geocoding_success = 0
        geocoding_cached = 0
        geocoding_unknown = 0
        geocoding_errors: list[str] = []
        for raw_job in raw_jobs:
            payload_job = jobspy_result_to_job_payload(raw_job)
            clean = normalize_job_payload(payload_job)
            clean, geocode_result = geocode_discovery_job(clean, profile, origin, provider, use_cache=not bypass_cache)
            if geocode_result.get("ok"):
                geocoding_success += 1
            if geocode_result.get("cached"):
                geocoding_cached += 1
            if not geocode_result.get("ok"):
                geocoding_errors.append(text(geocode_result.get("error")))
            if clean.get("distance_label") == "unknown":
                geocoding_unknown += 1
            clean = enrich_discovery_job(clean, profile, {"weights": preferences.get("weights", {}), "remote_rule": preferences.get("sort", {}).get("remote_rule")})
            clean["source_job_id"] = text(raw_job.get("source_job_id"))
            clean["posted_date"] = text(raw_job.get("posted_date"))
            clean["description_available"] = bool(clean.get("job_description"))
            clean["score_breakdown"] = parse_json_object(clean.get("score_breakdown"))
            clean["warnings"] = discovery_warning_reasons(clean, keywords, search["location"])
            clean["already_saved"] = False
            clean["duplicate_in_search"] = False
            keys = dedupe_keys(clean, clean.get("source_job_id"))
            duplicate_found = False
            if keys & existing_keys:
                clean["already_saved"] = True
                existing_match = find_existing_job_match(clean)
                if existing_match is not None:
                    clean["saved_job_id"] = int(existing_match["id"])
                    clean["saved_job_status"] = text(existing_match["status"])
                duplicate_found = True
            if keys & seen_keys:
                clean["duplicate_in_search"] = True
                duplicates += 1
                continue
            if duplicate_found:
                duplicates += 1
            seen_keys.update(keys)
            jobs.append(clean)

        source_counts = {source: 0 for source in DISCOVERY_SOURCES}
        source_counts.update({source: int(count or 0) for source, count in fetched.get("source_counts", {}).items()})
        if not fetched.get("source_counts"):
            for job in jobs:
                source = text(job.get("source")).lower()
                if source in source_counts:
                    source_counts[source] += 1

        diagnostics = {
            "bypass_cache": bypass_cache,
            "cache_hit": False,
            "cache_created_at": "",
            "cached_raw_result_count": 0,
            "search_criteria": search,
            "saved_origin": origin,
            "original_location": search.get("original_location"),
            "normalized_location": search.get("normalized_location"),
            "distance_origin": search.get("distance_origin"),
            "discovery_location": search.get("discovery_location"),
            "location_resolution_method": search.get("location_resolution_method"),
            "origin_geocode_status": origin.get("status"),
            "origin_precision": origin.get("precision"),
            "origin_available": discovery_origin_available(profile),
            "jobs_geocoded_successfully": geocoding_success,
            "jobs_using_cached_coordinates": geocoding_cached,
            "jobs_with_unknown_distance": geocoding_unknown,
            "jobs_excluded_by_radius": 0,
            "source_counts": source_counts,
            "source_errors": fetched.get("errors", {}),
            "source_diagnostics": fetched.get("source_diagnostics", {}),
            "duplicates_removed": duplicates,
            "raw_jobs_returned": len(raw_jobs),
            "displayed_jobs": min(len(jobs), search["total_cap"]),
            "cap_reached": len(jobs) > search["total_cap"],
            "geocoding_errors": geocoding_errors,
            "discovery_location": search["discovery_location"],
            "distance_origin": search["distance_origin"],
            "location_resolution_method": search["location_resolution_method"],
        }
        if jobs:
            jobs = sort_discovery_jobs(
                jobs,
                preferences.get("sort", {}).get("field") or "overall_score",
                preferences.get("sort", {}).get("direction") or "desc",
                preferences.get("sort", {}).get("secondary_field") or "",
                preferences.get("sort", {}).get("secondary_direction") or "asc",
                preferences.get("sort", {}).get("remote_rule") or "remote_after_local",
                preferences.get("sort", {}).get("unknown_salary_position") or "last",
            )
        jobs = jobs[: search["total_cap"]]
        diagnostics["jobs_returned_to_frontend"] = len(jobs)
        diagnostics["post_processing_row_count"] = len(jobs)
        save_discovery_search_run(search_key, search, diagnostics, raw_jobs)
        save_discovery_debug_run(
            search_key,
            {"keywords": keywords, **search, "bypass_cache": bypass_cache},
            diagnostics,
            fetched.get("source_snapshots", {}),
        )
        return jsonify(
            {
                "jobs": jobs,
                "errors": fetched.get("errors", {}),
                "source_counts": source_counts,
                "total": len(raw_jobs),
                "visible_total": len(jobs),
                "duplicates": duplicates,
                "search_key": search_key,
                "search": search,
                "raw_jobs_returned": len(raw_jobs),
                "cap_reached": len(raw_jobs) > search["total_cap"],
                "preferences": preferences,
                "bypass_cache": bypass_cache,
                "diagnostics": diagnostics,
            }
        )

    @app.post("/api/discovery/jobspy/test-sources")
    def discovery_jobspy_test_sources() -> Response:
        payload = request.get_json(force=True)
        enabled_sources = normalize_discovery_sources(payload.get("enabled_sources"))
        keywords = text(payload.get("keywords")) or "software developer"
        location_input = text(payload.get("location")) or "Toronto, ON"
        provider = get_geocoding_provider()
        profile = load_profile()
        bypass_value = payload.get("bypass_cache")
        bypass_cache = True if bypass_value in (None, "") else as_bool(bypass_value)
        try:
            location_context = resolve_discovery_location_context(location_input, profile, provider, use_cache=not bypass_cache)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        started = datetime.now().isoformat()
        fetched = fetch_jobspy_jobs(
            keywords=keywords,
            location=location_context["discovery_location"],
            distance=5,
            remote_preference="",
            job_type=None,
            results_wanted=5,
            hours_old=168,
            enabled_sources=enabled_sources,
            country_indeed="Canada",
        )
        return jsonify(
            {
                "ok": True,
                "started_at": started,
                "ended_at": datetime.now().isoformat(),
                "keywords": keywords,
                "input_location": location_input,
                "location_context": location_context,
                "enabled_sources": enabled_sources,
                "source_counts": fetched.get("source_counts", {}),
                "source_diagnostics": fetched.get("source_diagnostics", {}),
                "source_snapshots": fetched.get("source_snapshots", {}),
                "errors": fetched.get("errors", {}),
                "total": len(fetched.get("jobs", [])),
            }
        )

    @app.post("/api/generate")
    def generate_materials() -> Response:
        payload = request.get_json(force=True)
        job = normalize_job_payload(payload)
        profile = load_profile()
        try:
            result = generate_application_materials(job, profile)
        except ValueError as exc:
            return jsonify({"error": str(exc), "validation_error": True}), 400
        job_id = clamp_int(payload.get("id") or payload.get("job_id"), 0, 10**9)
        if job_id:
            save_version(job_id, "resume", result["resume_text"], result["candidate_evidence_hash"], result["job_hash"])
            save_version(job_id, "cover_letter", result["cover_letter"], result["candidate_evidence_hash"], result["job_hash"])
            save_version(job_id, "answers", answers_to_text(result["short_answers"]), result["candidate_evidence_hash"], result["job_hash"])
        return jsonify(result)

    @app.post("/api/jobs/analyse-resume-match")
    def analyse_resume_match_for_payload() -> Response:
        payload = request.get_json(force=True)
        job = normalize_job_payload(payload)
        profile = load_profile()
        semantic = analyze_resume_match(job, profile, cache_dir=semantic_cache_dir(), use_semantic=True)
        seniority_analysis = analyze_job_seniority(job)
        seniority_fit = score_seniority_fit(profile, seniority_analysis)
        scoring = score_job(job, profile, semantic)
        return jsonify(
            {
                "semantic_match": semantic,
                "seniority_analysis": seniority_analysis,
                "seniority_fit": seniority_fit,
                "score_breakdown": scoring,
                "fit_score": scoring["fit_score"],
                "model": MODEL_NAME,
                "model_download_size": MODEL_DOWNLOAD_SIZE,
            }
        )

    @app.post("/api/jobs/<int:job_id>/analyse-resume-match")
    def analyse_resume_match_for_job(job_id: int) -> Response:
        row = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        if row is None:
            return jsonify({"error": "Job not found"}), 404
        return analyse_saved_job(job_to_dict(row))

    @app.post("/api/jobs/<int:job_id>/tailored-draft")
    def tailored_draft_for_job(job_id: int) -> Response:
        row = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        if row is None:
            return jsonify({"error": "Job not found"}), 404
        job = job_to_dict(row)
        profile = load_profile()
        semantic = analyze_resume_match(job, profile, cache_dir=semantic_cache_dir(), use_semantic=True)
        seniority_fit = score_seniority_fit(profile, analyze_job_seniority(job))
        draft = generate_tailored_resume_draft(job, profile, semantic, seniority_fit)
        save_version(job_id, "resume", draft["text"], semantic.get("profile_resume_hash", ""), semantic.get("job_hash", ""))
        return jsonify({"draft": draft})

    @app.post("/api/jobs/rescore")
    def rescore_jobs() -> Response:
        payload = request.get_json(force=True)
        ids = payload.get("job_ids")
        if ids == "all" or ids is None:
            rows = query_db("SELECT * FROM jobs")
        else:
            clean_ids = [clamp_int(item, 0, 10**9) for item in ids if clamp_int(item, 0, 10**9)]
            if not clean_ids:
                return jsonify({"updated": 0})
            placeholders = ",".join(["?"] * len(clean_ids))
            rows = query_db(f"SELECT * FROM jobs WHERE id IN ({placeholders})", clean_ids)
        updated = 0
        profile = load_profile()
        for row in rows:
            job = job_to_dict(row)
            scoring = score_job(job, profile)
            get_db().execute(
                """
                UPDATE jobs
                SET fit_score = ?, skills_match_score = ?, role_match_score = ?, location_score = ?,
                    remote_score = ?, salary_score = ?, seniority_score = ?, coding_risk_score = ?,
                    application_effort_score = ?, score_breakdown = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                [
                    scoring["fit_score"],
                    scoring["skills_match_score"],
                    scoring["role_match_score"],
                    scoring["location_score"],
                    scoring["remote_score"],
                    scoring["salary_score"],
                    scoring["seniority_score"],
                    scoring["coding_risk_score"],
                    scoring["application_effort_score"],
                    json.dumps(scoring["breakdown"]),
                    job["id"],
                ],
            )
            updated += 1
        get_db().commit()
        return jsonify({"updated": updated})

    @app.post("/api/jobs/<int:job_id>/versions")
    def save_job_version(job_id: int) -> Response:
        payload = request.get_json(force=True)
        kind = text(payload.get("kind")) or "note"
        content = text(payload.get("content"))
        version_id = save_version(job_id, kind, content)
        return jsonify({"id": version_id})

    @app.get("/api/jobs/<int:job_id>/versions")
    def list_job_versions(job_id: int) -> Response:
        rows = query_db(
            "SELECT * FROM generated_versions WHERE job_id = ? ORDER BY created_at DESC, id DESC",
            [job_id],
        )
        job_row = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        current_profile_hash = build_candidate_evidence(load_profile())["hash"]
        current_job_hash = generation_job_hash(job_to_dict(job_row)) if job_row else ""
        versions = []
        for row in rows:
            item = dict(row)
            outdated = bool(item.get("profile_hash") and item["profile_hash"] != current_profile_hash)
            outdated = outdated or bool(item.get("job_hash") and current_job_hash and item["job_hash"] != current_job_hash)
            if outdated:
                item["status"] = "Outdated — regenerate using current profile"
            versions.append(item)
        return jsonify(versions)

    @app.post("/api/follow-up")
    def follow_up() -> Response:
        payload = request.get_json(force=True)
        message = generate_follow_up(
            payload.get("company") or "the hiring team",
            payload.get("title") or "the role",
            payload.get("date_applied") or "",
        )
        return jsonify({"message": message})

    @app.get("/api/dashboard")
    def dashboard() -> Response:
        jobs = [job_to_dict(row) for row in query_db("SELECT * FROM jobs")]
        return jsonify(build_dashboard(jobs))

    @app.get("/export.csv")
    def export_csv() -> Response:
        rows = [job_to_dict(row) for row in query_db("SELECT * FROM jobs ORDER BY date_added DESC, id DESC")]
        fields = [
            "company",
            "title",
            "location",
            "remote_type",
            "role_type",
            "url",
            "source",
            "salary",
            "deadline",
            "fit_score",
            "skills_match_score",
            "role_match_score",
            "location_score",
            "remote_score",
            "salary_score",
            "seniority_score",
            "coding_risk_score",
            "application_effort_score",
            "status",
            "notes",
            "date_added",
            "date_applied",
        ]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
        return download_response(output.getvalue(), "job-applications.csv", "text/csv")

    @app.get("/export/<int:job_id>/<kind>.<fmt>")
    def export_generated(job_id: int, kind: str, fmt: str) -> Response:
        if kind not in {"resume", "cover_letter", "answers"} or fmt not in {"txt", "docx"}:
            return jsonify({"error": "Unsupported export type"}), 400
        row = query_db(
            """
            SELECT * FROM generated_versions
            WHERE job_id = ? AND kind = ?
            ORDER BY created_at DESC, id DESC
            """,
            [job_id, kind],
            one=True,
        )
        if row is None:
            return jsonify({"error": "No saved version found. Generate materials first."}), 404
        job_row = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        current_profile = load_profile()
        approved_records = load_approved_evidence_records(job_id)
        selected_records = select_approved_evidence_records(job_to_dict(job_row) if job_row else {}, approved_records, limit=6)
        current_profile_hash = build_candidate_evidence(
            current_profile,
            extra_sections=[
                {
                    "id": record.get("id"),
                    "field": "approved_evidence",
                    "source_kind": text(record.get("source_kind")) or "evidence_library",
                    "source_field": text(record.get("source_field")),
                    "text": text(record.get("content")),
                    "approved": True,
                }
                for record in selected_records
                if text(record.get("content"))
            ],
        )["hash"]
        current_job_hash = generation_job_hash(job_to_dict(job_row)) if job_row else ""
        if row["profile_hash"] and row["profile_hash"] != current_profile_hash:
            return jsonify({"error": "Outdated — regenerate using current profile"}), 409
        if row["job_hash"] and current_job_hash and row["job_hash"] != current_job_hash:
            return jsonify({"error": "Outdated — regenerate using current profile"}), 409
        filename = f"job-{job_id}-{kind}.{fmt}"
        if fmt == "txt":
            return download_response(row["content"], filename, "text/plain")
        return Response(
            make_docx(row["content"]),
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    return app


def normalize_discovery_sources(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["linkedin", "indeed"]
    selected = [text(source).lower() for source in value]
    clean = [source for source in selected if source in DISCOVERY_SOURCES]
    return clean or ["linkedin", "indeed"]


def normalize_saved_search_payload(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = existing or {}
    name = normalize_space(text(payload.get("name", existing.get("name"))))
    keywords = normalize_space(text(payload.get("keywords", existing.get("keywords"))))
    if not name or not keywords:
        raise ValueError("A saved search name and job keywords are required")
    date_window = normalize_choice(payload.get("date_window", existing.get("date_window")), set(DISCOVERY_DATE_WINDOWS)) or "14d"
    remote_preference = normalize_choice(payload.get("remote_preference", existing.get("remote_preference")), {"", "remote", "hybrid", "on-site"})
    interval_minutes = clamp_int_default(payload.get("interval_minutes", existing.get("interval_minutes")), 360, 15, 10080)
    minimum_salary = clamp_int_default(payload.get("minimum_salary", existing.get("minimum_salary")), 0, 0, 1000000)
    distance = clamp_int_default(payload.get("distance", existing.get("distance")), 50, 0, 1000)
    existing_sources = existing.get("enabled_sources")
    if not isinstance(existing_sources, list):
        try:
            existing_sources = json.loads(existing.get("enabled_sources_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            existing_sources = []
    enabled_sources = normalize_discovery_sources(payload.get("enabled_sources", existing_sources))
    auto_prepare_enabled = 1 if as_bool(payload.get("auto_prepare_enabled", existing.get("auto_prepare_enabled", False))) else 0
    auto_prepare_min_priority = clamp_int_default(payload.get("auto_prepare_min_priority", existing.get("auto_prepare_min_priority")), 75, 0, 100)
    auto_prepare_require_canadian = 1 if as_bool(payload.get("auto_prepare_require_canadian", existing.get("auto_prepare_require_canadian", True))) else 0
    auto_prepare_candidate_profile_id = clamp_int_default(payload.get("auto_prepare_candidate_profile_id", existing.get("auto_prepare_candidate_profile_id")), 0, 0, 10**9)
    auto_prepare_resume_id = clamp_int_default(payload.get("auto_prepare_resume_id", existing.get("auto_prepare_resume_id")), 0, 0, 10**9)
    auto_prepare_cover_letter_template_id = clamp_int_default(payload.get("auto_prepare_cover_letter_template_id", existing.get("auto_prepare_cover_letter_template_id")), 0, 0, 10**9)
    return {
        "name": name,
        "keywords": keywords,
        "location": normalize_space(text(payload.get("location", existing.get("location")))),
        "remote_preference": remote_preference,
        "seniority": normalize_space(text(payload.get("seniority", existing.get("seniority")))),
        "minimum_salary": minimum_salary,
        "enabled_sources": enabled_sources,
        "date_window": date_window,
        "distance": distance,
        "interval_minutes": interval_minutes,
        "enabled": 1 if as_bool(payload.get("enabled", existing.get("enabled", False))) else 0,
        "auto_prepare_enabled": auto_prepare_enabled,
        "auto_prepare_min_priority": auto_prepare_min_priority,
        "auto_prepare_require_canadian": auto_prepare_require_canadian,
        "auto_prepare_candidate_profile_id": auto_prepare_candidate_profile_id,
        "auto_prepare_resume_id": auto_prepare_resume_id,
        "auto_prepare_cover_letter_template_id": auto_prepare_cover_letter_template_id,
    }


def saved_search_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    data = dict(row)
    data["enabled"] = bool(data.get("enabled"))
    try:
        sources = json.loads(data.get("enabled_sources_json") or "[]")
    except (TypeError, json.JSONDecodeError):
        sources = []
    data["enabled_sources"] = normalize_discovery_sources(sources)
    data.pop("enabled_sources_json", None)
    return data


def saved_search_to_discovery_payload(search: dict[str, Any]) -> dict[str, Any]:
    return {
        **search,
        "enabled_sources": search.get("enabled_sources") or ["linkedin", "indeed"],
        "search_depth": "standard",
        "total_cap": 500,
        "per_source_cap": 100,
    }


def discovery_remote_eligibility(job: dict[str, Any]) -> tuple[str, str]:
    arrangement = normalize_space(text(job.get("remote_type"))).lower()
    location = normalize_space(text(job.get("location"))).lower()
    description = normalize_space(text(job.get("job_description"))).lower()
    content = " ".join([arrangement, location, description])
    restricted = bool(re.search(
        r"(?:canada|canadian)\s+(?:is\s+)?(?:excluded|not\s+eligible|not\s+allowed)|"
        r"(?:us|u\.s\.|united states)\s+only|must\s+be\s+authorized\s+in\s+(?:the\s+)?(?:us|u\.s\.|united states)",
        content,
    ))
    location_tokens = set(re.findall(r"[a-z]+", location))
    canadian_province_phrases = {
        "ontario", "quebec", "alberta", "manitoba", "saskatchewan", "nova scotia", "new brunswick",
        "newfoundland", "newfoundland and labrador", "british columbia", "yukon", "northwest territories", "nunavut",
    }
    canadian_codes = {"on", "qc", "ab", "mb", "sk", "ns", "nb", "nl", "pe", "yt", "nt", "nu"}
    location_confirms_canada = "canada" in location_tokens or any(phrase in location for phrase in canadian_province_phrases) or bool(location_tokens & canadian_codes)
    explicit_canadian_eligibility = bool(re.search(
        r"(?:remote|work|role|position|employees?|candidates?).{0,45}(?:in|from|within|across|eligible\s+in)\s+(?:the\s+)?canada|"
        r"canadian\s+(?:eligible|candidates?|residents?)|eligible\s+to\s+work\s+in\s+canada",
        description,
    ))
    if restricted:
        return "restricted", "Posting indicates eligibility is restricted outside Canada."
    if location_confirms_canada or explicit_canadian_eligibility:
        return "canadian_eligible", "Remote posting explicitly mentions Canadian eligibility or a Canadian location."
    if "remote" in arrangement:
        return "unknown", "Remote arrangement is known, but country eligibility is not stated."
    return "unknown", "Canadian eligibility is not confirmed by the posting."


def persist_discovery_jobs(jobs: list[dict[str, Any]], search_id: int | None, run_id: int | None) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    counts: dict[str, Any] = {"new": 0, "duplicate": 0, "new_job_ids": []}
    db = get_db()
    for job in jobs:
        match = find_existing_job_match(job)
        if match is not None:
            counts["duplicate"] += 1
            db.execute(
                """UPDATE jobs SET discovery_last_seen_at = ?, discovery_seen_count = discovery_seen_count + 1,
                   discovery_last_search_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                [now, int(search_id or 0), int(match["id"])],
            )
            continue
        clean = {column: job.get(column, "") for column in JOB_COLUMNS}
        clean["status"] = "Saved"
        clean["date_added"] = clean.get("date_added") or date.today().isoformat()
        clean["discovery_first_seen_at"] = now
        clean["discovery_last_seen_at"] = now
        clean["discovery_seen_count"] = 1
        clean["discovery_state"] = "new"
        clean["discovery_last_search_id"] = int(search_id or 0)
        for column, value in list(clean.items()):
            if isinstance(value, (dict, list, tuple)):
                clean[column] = dumps_json(value, sort_keys=True)
        db.execute(
            f"INSERT INTO jobs ({', '.join(JOB_COLUMNS.keys())}) VALUES ({', '.join(['?'] * len(JOB_COLUMNS))})",
            tuple(clean[column] for column in JOB_COLUMNS),
        )
        counts["new"] += 1
        counts["new_job_ids"].append(int(db.execute("SELECT last_insert_rowid()").fetchone()[0]))
    db.commit()
    return counts


def create_discovery_run(search_id: int | None, trigger: str) -> int:
    cursor = get_db().execute("INSERT INTO discovery_run_history (search_id, trigger) VALUES (?, ?)", [search_id, trigger])
    get_db().commit()
    return int(cursor.lastrowid)


def finish_discovery_run(run_id: int, *, status: str, fetched: int, new_count: int, duplicate_count: int, errors: int, outcomes: dict[str, Any], error: str = "") -> None:
    get_db().execute(
        """UPDATE discovery_run_history SET ended_at = CURRENT_TIMESTAMP, status = ?, fetched_count = ?,
           new_count = ?, duplicate_count = ?, error_count = ?, source_outcomes_json = ?, error = ? WHERE id = ?""",
        [status, fetched, new_count, duplicate_count, errors, dumps_json(outcomes, sort_keys=True), error, run_id],
    )
    get_db().commit()


DISCOVERY_LEASE_MINUTES = 10
DISCOVERY_LEASE_RENEW_SECONDS = 30


def acquire_discovery_search_lease(search_id: int, owner: str) -> bool:
    now = datetime.now()
    expires = now + timedelta(minutes=DISCOVERY_LEASE_MINUTES)
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    row = db.execute("SELECT owner, expires_at FROM discovery_search_leases WHERE search_id = ?", [search_id]).fetchone()
    if row and row["owner"] != owner and row["expires_at"] > now.isoformat(timespec="seconds"):
        db.rollback()
        return False
    db.execute(
        """INSERT INTO discovery_search_leases (search_id, owner, acquired_at, expires_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(search_id) DO UPDATE SET owner = excluded.owner, acquired_at = excluded.acquired_at, expires_at = excluded.expires_at""",
        [search_id, owner, now.isoformat(timespec="seconds"), expires.isoformat(timespec="seconds")],
    )
    db.commit()
    return True


def release_discovery_search_lease(search_id: int, owner: str) -> None:
    get_db().execute("DELETE FROM discovery_search_leases WHERE search_id = ? AND owner = ?", [search_id, owner])
    get_db().commit()


def start_discovery_search_lease_heartbeat(search_id: int, owner: str) -> tuple[threading.Event, threading.Thread]:
    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(DISCOVERY_LEASE_RENEW_SECONDS):
            connection = sqlite3.connect(DB_PATH, timeout=5)
            try:
                expires = datetime.now() + timedelta(minutes=DISCOVERY_LEASE_MINUTES)
                connection.execute(
                    "UPDATE discovery_search_leases SET expires_at = ? WHERE search_id = ? AND owner = ?",
                    [expires.isoformat(timespec="seconds"), search_id, owner],
                )
                connection.commit()
            finally:
                connection.close()

    thread = threading.Thread(target=renew, name=f"discovery-lease-{search_id}", daemon=True)
    thread.start()
    return stop, thread


def run_discovery_pipeline(payload: dict[str, Any], *, search_id: int | None = None, run_id: int | None = None) -> dict[str, Any]:
    """Run the existing JobSpy, enrichment, scoring and dedupe pipeline.

    This is deliberately independent of Flask request handling so the worker can
    invoke the same path while the browser is closed.
    """
    keywords = text(payload.get("keywords"))
    if not keywords:
        raise ValueError("Keywords are required")
    search = discovery_search_config(payload)
    search.update({
        "auto_prepare_enabled": payload.get("auto_prepare_enabled", False),
        "auto_prepare_min_priority": payload.get("auto_prepare_min_priority", 75),
        "auto_prepare_require_canadian": payload.get("auto_prepare_require_canadian", True),
        "auto_prepare_candidate_profile_id": payload.get("auto_prepare_candidate_profile_id", 0),
        "auto_prepare_resume_id": payload.get("auto_prepare_resume_id", 0),
        "auto_prepare_cover_letter_template_id": payload.get("auto_prepare_cover_letter_template_id", 0),
    })
    profile = load_profile()
    provider = get_geocoding_provider()
    origin = profile_home_location(profile)
    location_context = resolve_discovery_location_context(search["location"], profile, provider, use_cache=True)
    search.update({
        "original_location": location_context["original_input"],
        "normalized_location": location_context["normalized_input"],
        "distance_origin": location_context["distance_origin"],
        "discovery_location": location_context["discovery_location"],
        "location_resolution_method": location_context["resolution_method"],
        "location_geocode": location_context["lookup"],
    })
    fetched = fetch_jobspy_jobs(
        keywords=keywords,
        location=search["discovery_location"],
        distance=search["distance"],
        remote_preference=search["remote_preference"],
        results_wanted=search["per_source_cap"],
        hours_old=search["hours_old"],
        enabled_sources=search["enabled_sources"],
        country_indeed="Canada",
    )
    existing_keys = existing_job_dedupe_keys()
    seen_keys: set[str] = set()
    jobs: list[dict[str, Any]] = []
    duplicates = 0
    filtered = 0
    for raw_job in fetched.get("jobs", []):
        clean = normalize_job_payload(jobspy_result_to_job_payload(raw_job))
        clean, _ = geocode_discovery_job(clean, profile, origin, provider, use_cache=True)
        clean = enrich_discovery_job(clean, profile, {"remote_rule": "remote_after_local"})
        clean["source_job_id"] = text(raw_job.get("source_job_id"))
        clean["posted_date"] = text(raw_job.get("posted_date"))
        clean["description_available"] = bool(clean.get("job_description"))
        clean["score_breakdown"] = parse_json_object(clean.get("score_breakdown"))
        clean["warnings"] = discovery_warning_reasons(clean, keywords, search["location"])
        clean["remote_eligibility"], clean["remote_eligibility_explanation"] = discovery_remote_eligibility(clean)
        minimum_salary = clamp_int_default(payload.get("minimum_salary"), 0, 0, 1000000)
        salary_source = text(clean.get("salary_source")).lower()
        reliable_salary = salary_source in {"structured", "jobspy_text", "description"} and int(clean.get("salary_listed") or 0) == 1
        clean["discovery_salary_filter_status"] = "not_configured" if not minimum_salary else ("known" if reliable_salary else "unknown")
        if minimum_salary and not reliable_salary:
            clean["warnings"].append("Compensation is missing or estimated; retained for review.")
        if minimum_salary and reliable_salary and int(clean.get("salary_max") or 0) < minimum_salary:
            clean["filtered_reason"] = f"Known salary is below the saved-search minimum of ${minimum_salary:,}."
            filtered += 1
            continue
        seniority_filter = normalize_space(text(payload.get("seniority"))).lower()
        if seniority_filter and text(clean.get("seniority_level")) and not any(term in text(clean.get("seniority_level")).lower() for term in re.split(r"[,;/]+", seniority_filter) if term.strip()):
            clean["filtered_reason"] = "Posting seniority does not match the saved-search seniority preference."
            filtered += 1
            continue
        clean["already_saved"] = bool(dedupe_keys(clean, clean.get("source_job_id")) & existing_keys)
        keys = dedupe_keys(clean, clean.get("source_job_id"))
        if keys & seen_keys:
            duplicates += 1
            continue
        if clean["already_saved"]:
            duplicates += 1
            existing_match = find_existing_job_match(clean)
            if existing_match is not None:
                clean["saved_job_id"] = int(existing_match["id"])
                clean["saved_job_status"] = text(existing_match["status"])
        seen_keys.update(keys)
        jobs.append(clean)
    jobs = sort_discovery_jobs(jobs, "overall_score", "desc", "", "asc", "remote_after_local", "last")[: search["total_cap"]]
    persisted = persist_discovery_jobs(jobs, search_id, run_id)
    auto_preparation_queued = enqueue_auto_preparation(search, persisted.get("new_job_ids", [])) if search_id else 0
    search_key = discovery_search_signature(payload)
    metadata = {
        "search_criteria": search,
        "source_counts": fetched.get("source_counts", {}),
        "source_errors": fetched.get("errors", {}),
        "source_diagnostics": fetched.get("source_diagnostics", {}),
        "duplicates_removed": duplicates,
        "raw_jobs_returned": len(fetched.get("jobs", [])),
        "displayed_jobs": len(jobs),
        "filtered_by_saved_search": filtered,
        "persisted": persisted,
        "auto_preparation_queued": auto_preparation_queued,
        "filtered": filtered,
    }
    save_discovery_search_run(search_key, search, metadata, fetched.get("jobs", []))
    save_discovery_debug_run(search_key, {**payload, "search_id": search_id}, metadata, fetched.get("source_snapshots", {}))
    return {
        "jobs": jobs,
        "errors": fetched.get("errors", {}),
        "source_counts": fetched.get("source_counts", {}),
        "source_diagnostics": fetched.get("source_diagnostics", {}),
        "total": len(fetched.get("jobs", [])),
        "visible_total": len(jobs),
        "duplicates": duplicates,
        "persisted": persisted,
        "search_key": search_key,
        "search": search,
    }


def analyse_saved_job(job: dict[str, Any]) -> Response:
    profile = load_profile()
    semantic = analyze_resume_match(job, profile, cache_dir=semantic_cache_dir(), use_semantic=True)
    seniority_analysis = analyze_job_seniority(job)
    seniority_fit = score_seniority_fit(profile, seniority_analysis)
    scoring = score_job(job, profile, semantic)
    return jsonify(
        {
            "semantic_match": semantic,
            "seniority_analysis": seniority_analysis,
            "seniority_fit": seniority_fit,
            "score_breakdown": scoring,
            "fit_score": scoring["fit_score"],
            "model": MODEL_NAME,
            "model_download_size": MODEL_DOWNLOAD_SIZE,
        }
    )


def normalize_choice(value: Any, allowed: set[str]) -> str:
    clean = text(value).lower()
    return clean if clean in allowed else ""


def normalize_seniority_levels(value: Any) -> str:
    raw = value if isinstance(value, list) else re.split(r"[,;\n]+", text(value))
    selected = []
    aliases = {"entry level": "entry_level", "new grad": "entry_level", "intern": "internship", "mid": "intermediate"}
    for item in raw:
        clean = text(item).lower().replace("-", "_")
        clean = aliases.get(clean.replace("_", " "), clean)
        if clean in SENIORITY_LEVELS and clean not in selected:
            selected.append(clean)
    return ",".join(selected or ["entry_level", "junior", "intermediate"])


def normalize_bool_text(value: Any, default: bool) -> str:
    if value in (None, ""):
        return "true" if default else "false"
    if isinstance(value, bool):
        return "true" if value else "false"
    return "true" if text(value).lower() in {"1", "true", "yes", "on", "allowed"} else "false"


def jobspy_result_to_job_payload(job: dict[str, Any]) -> dict[str, Any]:
    source = text(job.get("source"))
    description = text(job.get("description"))
    role_type = text(job.get("job_type"))
    salary_text = text(job.get("salary_text") or job.get("salary"))
    salary = determine_salary(
        {
            "title": text(job.get("title")),
            "location": text(job.get("location")),
            "role_type": map_jobspy_role_type(role_type),
            "seniority_level": text(job.get("experience_requirement")),
            "job_type": role_type,
            "salary_min": job.get("salary_min"),
            "salary_max": job.get("salary_max"),
            "salary_interval": job.get("salary_interval"),
            "salary_currency": job.get("salary_currency"),
            "salary_text": salary_text,
            "job_description": description,
        }
    )
    salary_listed = salary["salary_source"] not in {"estimated", "missing"}
    return {
        "company": text(job.get("company")) or "Unknown company",
        "title": text(job.get("title")) or "Untitled role",
        "location": text(job.get("location")),
        "url": text(job.get("job_url")),
        "application_url": text(job.get("application_url")) or text(job.get("job_url")),
        "source": source.title() if source else "JobSpy",
        "salary": salary["salary_text"],
        "salary_original_text": salary_text or salary["salary_text"],
        "salary_min": salary["salary_min"],
        "salary_max": salary["salary_max"],
        "salary_midpoint": int(round((salary["salary_min"] + salary["salary_max"]) / 2)) if salary["salary_min"] or salary["salary_max"] else 0,
        "salary_interval": salary["salary_interval"],
        "salary_currency": salary["salary_currency"],
        "salary_source": salary["salary_source"],
        "salary_confidence": salary["salary_confidence"],
        "salary_listed": int(salary_listed),
        "remote_type": text(job.get("remote_type")),
        "role_type": map_jobspy_role_type(role_type),
        "seniority_level": text(job.get("experience_requirement")),
        "required_skills": text(job.get("required_skills")),
        "preferred_skills": text(job.get("preferred_skills")),
        "job_description": description,
        "notes": f"Discovered via JobSpy. Posted: {text(job.get('posted_date'))}".strip(),
        "status": "Saved",
        "source_job_id": text(job.get("source_job_id")),
        "posted_date": text(job.get("posted_date")),
    }


def map_jobspy_role_type(value: str) -> str:
    lowered = value.lower()
    if "intern" in lowered:
        return "intern"
    if "contract" in lowered:
        return "other"
    if "part" in lowered:
        return "other"
    if "full" in lowered:
        return "software developer"
    return ""


def discovery_warning_reasons(job: dict[str, Any], keywords: str, requested_location: str) -> list[str]:
    content = " ".join(
        [
            text(job.get("title")),
            text(job.get("company")),
            text(job.get("location")),
            text(job.get("remote_type")),
            text(job.get("salary")),
            text(job.get("job_description")),
        ]
    ).lower()
    query = keywords.lower()
    warnings = []
    senior_terms = ["senior", "staff", "principal", "director", "architect", "lead", "manager"]
    if any(re.search(rf"\b{re.escape(term)}\b", content) for term in senior_terms) and not any(term in query for term in senior_terms):
        warnings.append("Seniority may be above the requested search.")
    if any(term in content for term in ["unpaid", "commission only", "commission-only"]):
        warnings.append("Compensation appears unpaid or commission-only.")
    if obvious_unrelated_role(content, query):
        warnings.append("Role appears unrelated to the requested keywords.")
    if requested_location and outside_requested_location(job, requested_location):
        warnings.append("Location may be outside the requested area.")
    return warnings


def obvious_unrelated_role(content: str, query: str) -> bool:
    requested_tech = any(term in query for term in ["developer", "engineer", "software", "python", "javascript", "flask", "react", "analyst", "support"])
    unrelated = ["nurse", "driver", "cook", "warehouse", "cashier", "server", "sales representative", "real estate"]
    return requested_tech and any(term in content for term in unrelated)


def outside_requested_location(job: dict[str, Any], requested_location: str) -> bool:
    remote_type = text(job.get("remote_type")).lower()
    if "remote" in remote_type:
        return False
    requested_parts = [part for part in re.split(r"[\s,]+", requested_location.lower()) if len(part) >= 4]
    location = text(job.get("location")).lower()
    if not requested_parts or not location:
        return False
    return not any(part in location for part in requested_parts)


def existing_job_dedupe_keys() -> set[str]:
    keys: set[str] = set()
    for row in query_db("SELECT title, company, location, url, application_url, source FROM jobs"):
        keys.update(dedupe_keys(job_to_dict(row), ""))
    return keys


def find_existing_job_match(job: dict[str, Any]) -> sqlite3.Row | None:
    keys = dedupe_keys(job, job.get("source_job_id"))
    rows = query_db("SELECT * FROM jobs")
    for row in rows:
        existing = job_to_dict(row)
        if text(existing.get("status")) == "shortlisted" and keys & dedupe_keys(existing, existing.get("source_job_id")):
            return row
    for row in rows:
        existing = job_to_dict(row)
        if keys & dedupe_keys(existing, existing.get("source_job_id")):
            return row
    return None


def find_existing_shortlist_match(job: dict[str, Any]) -> sqlite3.Row | None:
    return find_existing_job_match(job)


def restore_shortlist_item(job_id: int) -> None:
    today = date.today().isoformat()
    get_db().execute(
        """
        UPDATE jobs
        SET status = 'shortlisted',
            date_shortlisted = ?,
            resume_generation_status = 'pending',
            cover_letter_generation_status = 'pending',
            resume_generation_error = '',
            cover_letter_generation_error = '',
            cover_letter_generation_warning = '',
            generation_error = '',
            resume_docx_path = '',
            cover_letter_docx_path = '',
            generated_at = '',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        [today, job_id],
    )
    get_db().commit()


def generated_applications_dir() -> Path:
    return DATA_DIR / GENERATED_APPLICATIONS_DIRNAME


def run_document_generation(kind: str, builder: Any) -> dict[str, Any]:
    try:
        result = DocumentGenerationService().generate(kind, builder)
        if not isinstance(result, dict):
            raise TypeError(f"{kind} builder returned an invalid result")
        if result.get("status") == "failed":
            result.setdefault(
                "change_log",
                {
                    f"master_{kind}_path": "",
                    "output_path": "",
                    "applied": [],
                    "skipped": [{"kind": kind, "original": "", "replacement": "", "reason": result.get("error", "Generation failed.")}],
                },
            )
            return result
        if result.get("status") == "generated":
            output_path = text((result.get("change_log") or {}).get("output_path"))
            if not output_path or not Path(output_path).is_file():
                raise RuntimeError(f"{kind} builder reported success without a readable output file")
        return result
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        return {
            "status": "failed",
            "error": error,
            "warning": "",
            "change_log": {
                f"master_{kind}_path": "",
                "output_path": "",
                "applied": [],
                "skipped": [
                    {
                        "kind": kind,
                        "original": "",
                        "replacement": "",
                        "reason": error,
                    }
                ],
            },
        }


def generate_and_store_shortlist_documents(job_id: int, kinds: set[str] | None = None, profile_override: dict[str, Any] | None = None) -> dict[str, Any]:
    job_row = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
    if job_row is None:
        return {"resume": "failed", "cover_letter": "failed", "error": "Job not found"}
    job = job_to_dict(job_row)
    requested_kinds = set(kinds or {"resume", "cover_letter"})
    profile = profile_override or load_profile()
    if not profile_has_generation_source(profile):
        error = "Complete the Profile page with resume, project, or work-experience details before generating documents."
        current_resume_status = text(job.get("resume_generation_status")) or "pending"
        current_cover_status = text(job.get("cover_letter_generation_status")) or "pending"
        resume_status = "failed" if "resume" in requested_kinds else current_resume_status
        cover_status = "failed" if "cover_letter" in requested_kinds else current_cover_status
        resume_error = error if "resume" in requested_kinds else text(job.get("resume_generation_error"))
        cover_error = error if "cover_letter" in requested_kinds else text(job.get("cover_letter_generation_error"))
        update_generation_status(
            job_id,
            resume_status,
            cover_status,
            "" if "resume" in requested_kinds else text(job.get("resume_docx_path")),
            "" if "cover_letter" in requested_kinds else text(job.get("cover_letter_docx_path")),
            error if "resume" in requested_kinds and "cover_letter" in requested_kinds else "; ".join(filter(None, [resume_error, cover_error])),
            resume_error,
            cover_error,
        )
        return {"resume": "failed", "cover_letter": "failed", "error": error}

    output = generate_application_materials(job, profile, raise_on_validation=False)
    sync_resume_variants(job_id, job, profile, output)
    folder = generated_applications_dir() / str(job_id)
    folder.mkdir(parents=True, exist_ok=True)
    base = safe_filename("_".join([profile.get("name") or "Candidate", job.get("company") or "Company", job.get("title") or "Role"]))
    generation_token = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    resume_name = safe_filename(f"{base}_{generation_token}_Resume.docx")
    cover_name = safe_filename(f"{base}_{generation_token}_Cover_Letter.docx")
    resume_path = folder / resume_name
    cover_path = folder / cover_name

    current_resume_status = text(job.get("resume_generation_status")) or "pending"
    current_cover_status = text(job.get("cover_letter_generation_status")) or "pending"
    current_resume_error = text(job.get("resume_generation_error"))
    current_cover_error = text(job.get("cover_letter_generation_error"))
    current_cover_warning = text(job.get("cover_letter_generation_warning"))
    current_resume_path = text(job.get("resume_docx_path"))
    current_cover_path = text(job.get("cover_letter_docx_path"))
    resume_validation = output.get("resume_validation") or {"ok": True, "conflicting_phrases": []}

    resume_result = {
        "status": current_resume_status,
        "error": current_resume_error,
        "warning": "",
        "change_log": {"master_resume_path": "", "output_path": current_resume_path, "applied": [], "skipped": []},
    }
    cover_result = {
        "status": current_cover_status,
        "error": current_cover_error,
        "warning": current_cover_warning,
        "change_log": {"master_cover_letter_path": "", "output_path": current_cover_path, "applied": [], "skipped": []},
    }

    if "resume" in requested_kinds:
        if resume_validation.get("ok"):
            resume_result = run_document_generation(
                "resume",
                lambda: build_format_preserving_resume(job, profile, output, resume_path),
            )
            if resume_result.get("status") == "failed" and resume_path.exists():
                resume_path.unlink()
        else:
            resume_result = {
                "status": "failed",
                "error": f"Generated resume failed grounding validation. Unsupported or conflicting phrases: {', '.join(resume_validation.get('conflicting_phrases', [])) or 'empty or corrupted candidate evidence'}",
                "warning": "",
                "change_log": {
                    "master_resume_path": text(profile.get("resume_docx_template_path")),
                    "output_path": "",
                    "applied": [],
                    "skipped": [
                        {
                            "kind": "resume_validation",
                            "original": "",
                            "replacement": "",
                            "reason": f"Generated resume failed grounding validation. Unsupported or conflicting phrases: {', '.join(resume_validation.get('conflicting_phrases', [])) or 'empty or corrupted candidate evidence'}",
                        }
                    ],
                },
            }

    if "cover_letter" in requested_kinds:
        cover_result = run_document_generation(
            "cover_letter",
            lambda: build_format_preserving_cover_letter(job, profile, output, cover_path),
        )
        if cover_result.get("status") == "failed" and cover_path.exists():
            cover_path.unlink()

    # The initial report is deliberately based on the uploaded evidence.  Once a
    # résumé has been rendered, refresh the after-state from the actual DOCX so a
    # layout-rejected substitution is never reported as an applied improvement.
    if "resume" in requested_kinds and resume_result.get("status") == "generated" and resume_path.is_file():
        try:
            rendered_resume = Document(resume_path)
            final_resume_text = "\n".join(
                paragraph.text.strip()
                for paragraph in iter_document_paragraphs(rendered_resume)
                if paragraph.text.strip()
            )
            del rendered_resume
            output["keyword_coverage"] = build_keyword_coverage_report(
                job,
                profile,
                output.get("semantic_match") or {},
                output.get("tailoring_plan"),
                final_resume_text=final_resume_text,
            )
            output["keywords_score"] = build_keywords_score_report(job, profile, final_resume_text=final_resume_text)
            output["keyword_coverage"]["keywords_score"] = output["keywords_score"]
        except (OSError, ValueError, zipfile.BadZipFile):
            pass

    generation_debug = build_generation_debug_payload(job_id, job, profile, output, resume_result, cover_result, resume_path, cover_path)

    metadata = {
        "job_id": job_id,
        "company": job.get("company"),
        "title": job.get("title"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generation_token": generation_token,
        "matched_keywords": output.get("matched_keywords", []),
        "salary_source": job.get("salary_source"),
        "fit_score": job.get("fit_score"),
        "resume_template_path": profile.get("resume_docx_template_path", ""),
        "cover_letter_template_path": profile.get("cover_letter_docx_template_path", ""),
        "job_hash": output.get("job_hash", ""),
        "candidate_evidence_hash": output.get("candidate_evidence_hash", ""),
        "keyword_coverage": output.get("keyword_coverage", {}),
        "generation_debug": generation_debug,
    }
    (folder / "metadata.json").write_text(dumps_json(metadata, indent=2), encoding="utf-8")
    (folder / "generation_debug.json").write_text(dumps_json(generation_debug, indent=2), encoding="utf-8")
    (folder / "resume.txt").write_text(output["resume_text"], encoding="utf-8")
    (folder / "cover_letter.txt").write_text(output["cover_letter"], encoding="utf-8")
    (folder / "resume_change_log.json").write_text(dumps_json(resume_result["change_log"], indent=2), encoding="utf-8")
    (folder / "cover_letter_change_log.json").write_text(dumps_json(cover_result["change_log"], indent=2), encoding="utf-8")
    resume_status = resume_result["status"] if "resume" in requested_kinds else current_resume_status
    cover_status = cover_result["status"] if "cover_letter" in requested_kinds else current_cover_status
    resume_error = resume_result["error"] if "resume" in requested_kinds else current_resume_error
    cover_error = cover_result["error"] if "cover_letter" in requested_kinds else current_cover_error
    resume_warning = text(resume_result.get("warning")) if "resume" in requested_kinds else ""
    cover_warning = text(cover_result.get("warning")) if "cover_letter" in requested_kinds else current_cover_warning
    update_generation_status(
        job_id,
        resume_status,
        cover_status,
        str(resume_path) if "resume" in requested_kinds and resume_result["status"] == "generated" else (current_resume_path if "resume" in requested_kinds else current_resume_path),
        str(cover_path) if "cover_letter" in requested_kinds and cover_result["status"] == "generated" else (current_cover_path if "cover_letter" in requested_kinds else current_cover_path),
        "; ".join(filter(None, [resume_error, cover_error])),
        resume_error,
        cover_error,
        resume_warning,
        cover_warning,
    )
    return {
        "resume": resume_status,
        "cover_letter": cover_status,
        "error": "; ".join(filter(None, [resume_result["error"], cover_result["error"]])),
        "generation_debug": generation_debug,
    }


def profile_has_generation_source(profile: dict[str, str]) -> bool:
    return evidence_has_generation_source(build_candidate_evidence(profile))


def resolve_generation_profile(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Resolve an optional reusable candidate profile and document selections.

    The legacy profile remains the default. A selected candidate profile supplies
    its chosen base resume and cover-letter template without mutating the user's
    saved profile or the original template files.
    """
    payload = payload or {}
    raw_profile_id = payload.get("candidate_profile_id", payload.get("profile_id"))
    if raw_profile_id in (None, "", 0):
        return None
    try:
        profile_id = int(raw_profile_id)
    except (TypeError, ValueError):
        raise ValueError("candidate_profile_id must be an integer")
    store = CandidateProfileStore(get_db())
    profile_row = next((item for item in store.list_profiles() if int(item["id"]) == profile_id), None)
    if profile_row is None:
        raise ValueError("Selected candidate profile was not found")
    documents = store.documents_for(profile_id)

    def select_document(items: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
        raw_id = payload.get(key)
        if raw_id not in (None, "", 0):
            try:
                selected_id = int(raw_id)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be an integer")
            selected = next((item for item in items if int(item["id"]) == selected_id), None)
            if selected is None:
                raise ValueError(f"Selected {key} was not found for this candidate profile")
            return selected
        return next((item for item in items if item.get("is_default")), None) or (items[0] if items else None)

    resume = select_document(documents["resumes"], "resume_id")
    cover = select_document(documents["cover_letter_templates"], "cover_letter_template_id")
    if resume is None:
        raise ValueError("Selected candidate profile has no base résumé. Add a résumé before generating documents")
    if not text(resume.get("docx_path")):
        raise ValueError("Selected base résumé has no usable DOCX template path. Upload a DOCX résumé for this profile")
    if text(profile_row.get("identity_mode")) == "distinct":
        identity = {
            "name": text(profile_row.get("applicant_name")),
            "email": text(profile_row.get("applicant_email")),
            "phone": text(profile_row.get("applicant_phone")),
            "location": text(profile_row.get("applicant_location")),
        }
        if not identity["name"]:
            raise ValueError("Selected candidate profile uses distinct identity but has no applicant name")
    else:
        shared = load_profile()
        identity = {field: text(shared.get(field)) for field in ["name", "email", "phone", "location"]}
        if not identity["name"]:
            raise ValueError("Selected candidate profile uses shared identity but the active profile has no applicant name")
    profile = {field: "" for field in PROFILE_COLUMNS}
    structured_resume = extract_docx_profile_sections(text(resume.get("docx_path"))) if resume and text(resume.get("docx_path")) else {}
    profile.update({
        **identity,
        "resume_text": text(structured_resume.get("resume_text")) or text((resume or {}).get("content")) or text(profile_row.get("description")),
        "work_experience": text(structured_resume.get("work_experience")) or text((resume or {}).get("content")) or text(profile_row.get("description")),
        "key_skills": text(structured_resume.get("key_skills")),
        "projects": text(structured_resume.get("projects")),
        "education": text(structured_resume.get("education")),
        "resume_docx_template_path": text((resume or {}).get("docx_path")),
        "cover_letter_template": text((cover or {}).get("content")),
        "cover_letter_docx_template_path": text((cover or {}).get("docx_path")),
        "_resume_document_id": int((resume or {}).get("id") or 0),
        "_cover_letter_template_id": int((cover or {}).get("id") or 0),
    })
    if structured_resume.get("summary"):
        profile["_source_summary"] = structured_resume["summary"]
    profile["_resume_sections"] = [
        {"label": label, "text": structured_resume.get(field, "")}
        for field, label in (
            ("summary", "Summary"),
            ("work_experience", "Experience"),
            ("key_skills", "Skills, Technologies"),
            ("projects", "Projects"),
            ("education", "Education"),
        )
        if text(structured_resume.get(field))
    ]
    profile["_candidate_profile_id"] = str(profile_id)
    return profile


def resolve_tailoring_resume_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve only the selected candidate profile and résumé for the studio."""
    raw_profile_id = payload.get("candidate_profile_id")
    if raw_profile_id in (None, "", 0):
        raise ValueError("Select a candidate profile before opening the résumé studio.")
    try:
        profile_id = int(raw_profile_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("candidate_profile_id must be an integer") from exc
    store = CandidateProfileStore(get_db())
    profile_row = next((item for item in store.list_profiles() if int(item["id"]) == profile_id), None)
    if profile_row is None:
        raise ValueError("Selected candidate profile was not found")
    documents = store.documents_for(profile_id)
    raw_resume_id = payload.get("resume_id")
    if raw_resume_id not in (None, "", 0):
        try:
            resume_id = int(raw_resume_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("resume_id must be an integer") from exc
        resume = next((item for item in documents["resumes"] if int(item["id"]) == resume_id), None)
    else:
        resume = next((item for item in documents["resumes"] if item.get("is_default")), None) or (documents["resumes"][0] if documents["resumes"] else None)
    if resume is None:
        raise ValueError("Selected candidate profile has no base résumé. Upload a DOCX résumé first.")
    resume_path = safe_local_path(text(resume.get("docx_path")))
    if resume_path is None or not resume_path.is_file():
        raise ValueError("The selected résumé DOCX is unavailable. Choose another uploaded résumé.")
    if text(profile_row.get("identity_mode")) == "distinct":
        identity = {field: text(profile_row.get(f"applicant_{field}")) for field in ["name", "email", "phone", "location"]}
    else:
        shared = load_profile()
        identity = {field: text(shared.get(field)) for field in ["name", "email", "phone", "location"]}
    profile = {field: "" for field in PROFILE_COLUMNS}
    structured = extract_docx_profile_sections(str(resume_path))
    profile.update({
        **identity,
        "resume_text": text(structured.get("resume_text")) or text(resume.get("content")),
        "work_experience": text(structured.get("work_experience")),
        "key_skills": text(structured.get("key_skills")),
        "projects": text(structured.get("projects")),
        "education": text(structured.get("education")),
        "resume_docx_template_path": str(resume_path),
        "_candidate_profile_id": str(profile_id),
        "_resume_document_id": int(resume.get("id") or 0),
        "_resume_sections": [
            {"label": label, "text": structured.get(field, "")}
            for field, label in (("summary", "Summary"), ("work_experience", "Experience"), ("key_skills", "Skills, Technologies"), ("projects", "Projects"), ("education", "Education"))
            if text(structured.get(field))
        ],
    })
    return {"profile": profile, "profile_row": profile_row, "resume": resume, "resume_path": resume_path}


def tailoring_paragraphs(path: Path) -> list[dict[str, Any]]:
    document = Document(path)
    contexts = collect_resume_paragraph_contexts(document)
    return [
        {
            "paragraph_index": index,
            "text": context["text"],
            "section": context["section"] or "Résumé",
            "style": context["style_name"],
            "editable": bool(context["editable"]),
            "is_bullet": bool(context["is_bullet"]),
        }
        for index, context in enumerate(contexts)
        if context["text"]
    ]


def tailoring_draft_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    item = dict(row)
    item["changes"] = parse_json_array(item.get("changes_json"))
    item["layout"] = parse_json_object(item.get("layout_json"))
    item.pop("changes_json", None)
    item.pop("layout_json", None)
    return item


def tailoring_draft_path(draft_id: int) -> Path:
    return DATA_DIR / "tailoring_drafts" / str(draft_id) / "resume.docx"


def score_tailoring_text(job: dict[str, Any], profile: dict[str, Any], text_value: str) -> dict[str, Any]:
    return build_tailoring_coverage_report(job, text_value)


def rebuild_tailoring_draft(draft_id: int, changes: list[dict[str, Any]]) -> dict[str, Any]:
    row = query_db("SELECT * FROM tailoring_drafts WHERE id = ?", [draft_id], one=True)
    if row is None:
        raise ValueError("Tailoring draft was not found")
    source = safe_local_path(text(row["source_path"]))
    if source is None or not source.is_file():
        raise ValueError("The source résumé DOCX is no longer available")
    output = tailoring_draft_path(draft_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, output)
    document = Document(output)
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    paragraphs = list(document.paragraphs)
    for change in changes:
        index = clamp_int(change.get("paragraph_index"), 0, max(0, len(paragraphs) - 1))
        if index >= len(paragraphs):
            skipped.append({**change, "reason": "Paragraph no longer exists"})
            continue
        paragraph = paragraphs[index]
        original = text(change.get("original_text"))
        proposed = text(change.get("proposed_text"))
        if not is_editable_resume_paragraph(paragraph, "bullet"):
            skipped.append({**change, "reason": "Only editable résumé bullets can be changed"})
            continue
        if normalize_space(paragraph.text) != normalize_space(original):
            skipped.append({**change, "reason": "Source paragraph changed; review the current résumé before applying"})
            continue
        if not proposed:
            skipped.append({**change, "reason": "Replacement text is empty"})
            continue
        replace_paragraph_exact(paragraph, original, proposed)
        applied.append({**change, "applied": True})
    document.save(output)
    layout = compare_docx_layout(source, output)
    text_value = extract_docx_text(output.read_bytes())
    db = get_db()
    db.execute("UPDATE tailoring_drafts SET draft_path = ?, changes_json = ?, layout_json = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", [str(output), dumps_json(changes), dumps_json(layout), "draft", draft_id])
    db.commit()
    return {"applied": applied, "skipped": skipped, "layout": layout, "draft_path": str(output), "text": text_value}


def preparation_queue_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    data = dict(row)
    data["keywords_score"] = parse_json_object(data.pop("keywords_score_json", "{}"))
    job = query_db("SELECT * FROM jobs WHERE id = ?", [data["job_id"]], one=True)
    data["job"] = job_to_dict(job) if job else {}
    return data


def default_candidate_profile_id() -> int:
    profiles = CandidateProfileStore(get_db()).list_profiles()
    confirmed = [profile for profile in profiles if int(profile.get("is_active") or 0) == 1]
    return int(confirmed[0]["id"]) if len(confirmed) == 1 else 0


def queue_profile_payload(payload: dict[str, Any] | None = None, *, search: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    search = search or {}
    automatic = bool(search)
    profile_id = payload.get("candidate_profile_id") or search.get("auto_prepare_candidate_profile_id")
    if not profile_id and not automatic:
        profile_id = default_candidate_profile_id()
    if not profile_id:
        raise ValueError("Select a candidate profile before preparing an application package; automatic preparation cannot choose one implicitly")
    result = {"candidate_profile_id": int(profile_id)}
    resume_id = payload.get("resume_id") or search.get("auto_prepare_resume_id")
    cover_id = payload.get("cover_letter_template_id") or search.get("auto_prepare_cover_letter_template_id")
    if resume_id:
        result["resume_id"] = int(resume_id)
    if cover_id:
        result["cover_letter_template_id"] = int(cover_id)
    return result


def preparation_eligibility(job: dict[str, Any], search: dict[str, Any]) -> tuple[bool, str, str]:
    priority = int(job.get("overall_score") or job.get("fit_score") or 0)
    minimum = int(search.get("auto_prepare_min_priority") or 75)
    if priority < minimum:
        return False, "priority_below_threshold", f"Job Priority {priority} is below the automatic preparation threshold of {minimum}."
    eligibility = text(job.get("remote_eligibility")).lower() or "unknown"
    if eligibility == "restricted":
        return False, "explicitly_restricted", "Posting is explicitly restricted outside Canada."
    if eligibility == "unknown":
        return False, "manual_eligibility_review", "Canadian eligibility is unknown; review this opportunity manually before preparation."
    if eligibility != "canadian_eligible":
        return False, "eligibility_not_confirmed", "Canadian eligibility is not confirmed."
    return True, "eligible", "Meets the saved search priority and eligibility criteria."


def enqueue_application_preparation(job_id: int, payload: dict[str, Any] | None = None, *, search: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
    job_row = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
    if job_row is None:
        raise ValueError("Job not found")
    existing = query_db("SELECT * FROM application_preparation_queue WHERE job_id = ?", [job_id], one=True)
    if existing is not None:
        return preparation_queue_to_dict(existing), True
    selection = queue_profile_payload(payload, search=search)
    profile = resolve_generation_profile(selection)
    if not profile or not safe_local_path(text(profile.get("resume_docx_template_path"))) or not safe_local_path(text(profile.get("resume_docx_template_path"))).is_file():
        raise ValueError("The selected candidate profile résumé template is unavailable")
    if not profile or not safe_local_path(text(profile.get("cover_letter_docx_template_path"))) or not safe_local_path(text(profile.get("cover_letter_docx_template_path"))).is_file():
        raise ValueError("The selected candidate profile cover letter template is unavailable")
    selection["resume_id"] = int(profile.get("_resume_document_id") or selection.get("resume_id") or 0)
    selection["cover_letter_template_id"] = int(profile.get("_cover_letter_template_id") or selection.get("cover_letter_template_id") or 0)
    job = job_to_dict(job_row)
    if search is None:
        eligible, reason, note = preparation_eligibility(job, {"auto_prepare_min_priority": 0})
        if eligible:
            reason, note = "manual", "Queued for manual preparation review."
    else:
        eligible, reason, note = preparation_eligibility(job, search)
    review_status = "manual_eligibility" if reason == "manual_eligibility_review" else "pending"
    keywords = {}
    try:
        keywords = build_keywords_score_report(job, profile)
    except Exception:
        keywords = {}
    cursor = get_db().execute(
        """INSERT INTO application_preparation_queue
           (job_id, status, review_status, eligibility_review_status, candidate_profile_id, resume_id, cover_letter_template_id,
            job_priority, keywords_score_json, eligibility_note)
           VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)""",
        [job_id, review_status, "pending" if reason == "manual_eligibility_review" else "not_required", int(selection["candidate_profile_id"]), int(selection.get("resume_id") or 0), int(selection.get("cover_letter_template_id") or 0), int(job.get("overall_score") or job.get("fit_score") or 0), dumps_json(keywords), note],
    )
    get_db().commit()
    return preparation_queue_to_dict(query_db("SELECT * FROM application_preparation_queue WHERE id = ?", [cursor.lastrowid], one=True)), False


def _update_preparation_item(item_id: int, **fields: Any) -> dict[str, Any]:
    allowed = {"status", "review_status", "eligibility_review_status", "resume_status", "cover_letter_status", "resume_error", "cover_letter_error", "error", "keywords_score_json", "eligibility_note", "lease_owner", "lease_expires_at", "prepared_at", "prepared_resume_path", "prepared_cover_letter_path"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    if updates:
        assignments = ", ".join(f"{key} = ?" for key in updates)
        get_db().execute(f"UPDATE application_preparation_queue SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", [*updates.values(), item_id])
        get_db().commit()
    return preparation_queue_to_dict(query_db("SELECT * FROM application_preparation_queue WHERE id = ?", [item_id], one=True))


def start_preparation_lease_heartbeat(item_id: int, owner: str) -> tuple[threading.Event, threading.Thread]:
    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(PREPARATION_LEASE_RENEW_SECONDS):
            connection = sqlite3.connect(DB_PATH, timeout=5)
            try:
                expires = datetime.now() + timedelta(minutes=PREPARATION_LEASE_MINUTES)
                connection.execute("UPDATE application_preparation_queue SET lease_expires_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'preparing' AND lease_owner = ?", [expires.isoformat(timespec="seconds"), item_id, owner])
                connection.commit()
            finally:
                connection.close()

    thread = threading.Thread(target=renew, name=f"preparation-lease-{item_id}", daemon=True)
    thread.start()
    return stop, thread


def prepare_application_queue_item(item_id: int, *, owner: str = "manual", allow_regenerate: bool = False) -> dict[str, Any]:
    now = datetime.now()
    expires = now + timedelta(minutes=PREPARATION_LEASE_MINUTES)
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    row = db.execute("SELECT * FROM application_preparation_queue WHERE id = ?", [item_id]).fetchone()
    if row is None:
        db.rollback()
        raise ValueError("Preparation queue item was not found")
    if row["status"] == "approved":
        db.rollback()
        raise ValueError("Approved application packages cannot be regenerated")
    if row["review_status"] == "manual_eligibility" or row["eligibility_review_status"] == "pending":
        db.rollback()
        raise ValueError("Confirm Canadian eligibility before preparing this application package")
    allowed_statuses = {"queued", "failed", "ready_for_review", "skipped"} if allow_regenerate else {"queued", "failed"}
    if row["status"] == "preparing" and row["lease_owner"] != owner and row["lease_expires_at"] > now.isoformat(timespec="seconds"):
        db.rollback()
        raise ValueError("This application package is already being prepared")
    if row["status"] != "preparing" and row["status"] not in allowed_statuses:
        db.rollback()
        raise ValueError(f"Cannot prepare an application package in {row['status']} status")
    db.execute("UPDATE application_preparation_queue SET status = 'preparing', lease_owner = ?, lease_expires_at = ?, error = '', updated_at = CURRENT_TIMESTAMP WHERE id = ?", [owner, expires.isoformat(timespec="seconds"), item_id])
    db.commit()
    stop, heartbeat = start_preparation_lease_heartbeat(item_id, owner)
    try:
        row = query_db("SELECT * FROM application_preparation_queue WHERE id = ?", [item_id], one=True)
        job = query_db("SELECT * FROM jobs WHERE id = ?", [row["job_id"]], one=True)
        payload = {"candidate_profile_id": row["candidate_profile_id"]}
        if row["resume_id"]:
            payload["resume_id"] = row["resume_id"]
        if row["cover_letter_template_id"]:
            payload["cover_letter_template_id"] = row["cover_letter_template_id"]
        profile = resolve_generation_profile(payload)
        approved_resume = safe_local_path(text(row["approved_tailored_resume_path"])) if "approved_tailored_resume_path" in row.keys() else None
        if text(row["approved_tailored_resume_path"]) and (approved_resume is None or not approved_resume.is_file()):
            raise ValueError("The approved tailored résumé for this package is unavailable; restore it or explicitly clear the tailoring approval before regenerating.")
        has_approved_resume = bool(approved_resume and approved_resume.is_file())
        # An approved tailored résumé is a package artifact, not a new master
        # résumé. Regeneration may refresh the cover letter, but it must not
        # silently replace the approved résumé with the base template.
        generation_kinds = {"cover_letter"} if has_approved_resume else {"resume", "cover_letter"}
        generation = generate_and_store_shortlist_documents(int(row["job_id"]), generation_kinds, profile)
        refreshed_job = query_db("SELECT * FROM jobs WHERE id = ?", [row["job_id"]], one=True)
        resume_status = "generated" if has_approved_resume else (text(generation.get("resume")) or "failed")
        cover_status = text(generation.get("cover_letter")) or "failed"
        error = text(generation.get("error"))
        score_text = extract_docx_text(approved_resume.read_bytes()) if has_approved_resume else ""
        keywords = build_keywords_score_report(job_to_dict(refreshed_job), profile, final_resume_text=score_text or None)
        resume_path = str(approved_resume) if has_approved_resume else text(refreshed_job["resume_docx_path"])
        cover_path = text(refreshed_job["cover_letter_docx_path"])
        status = "ready_for_review" if resume_status == "generated" and cover_status == "generated" and safe_preparation_artifact_path(resume_path) and safe_preparation_artifact_path(resume_path).is_file() and safe_preparation_artifact_path(cover_path) and safe_preparation_artifact_path(cover_path).is_file() else "failed"
        return _finish_preparation_item(item_id, owner, status=status, review_status="pending", resume_status=resume_status, cover_letter_status=cover_status, resume_error=text(generation.get("resume_error")), cover_letter_error=text(generation.get("cover_letter_error")), error=error, keywords_score_json=dumps_json(keywords), prepared_resume_path=resume_path if status == "ready_for_review" else text(row["prepared_resume_path"]), prepared_cover_letter_path=cover_path if status == "ready_for_review" else text(row["prepared_cover_letter_path"]), lease_owner="", lease_expires_at="", prepared_at=datetime.now().isoformat(timespec="seconds"))
    except Exception as exc:
        return _finish_preparation_item(item_id, owner, status="failed", error=f"{type(exc).__name__}: {exc}", lease_owner="", lease_expires_at="")
    finally:
        stop.set()
        heartbeat.join(timeout=2)


def _finish_preparation_item(item_id: int, owner: str, **fields: Any) -> dict[str, Any]:
    allowed = {"status", "review_status", "eligibility_review_status", "resume_status", "cover_letter_status", "resume_error", "cover_letter_error", "error", "keywords_score_json", "eligibility_note", "lease_owner", "lease_expires_at", "prepared_at", "prepared_resume_path", "prepared_cover_letter_path"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    assignments = ", ".join(f"{key} = ?" for key in updates)
    db = get_db()
    cursor = db.execute(f"UPDATE application_preparation_queue SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'preparing' AND lease_owner = ?", [*updates.values(), item_id, owner])
    db.commit()
    if cursor.rowcount == 0:
        raise ValueError("Preparation lease was lost; stale worker output was not applied")
    return preparation_queue_to_dict(query_db("SELECT * FROM application_preparation_queue WHERE id = ?", [item_id], one=True))


def process_preparation_queue(limit: int = 5, *, owner: str = "worker") -> dict[str, int]:
    now = datetime.now().isoformat(timespec="seconds")
    get_db().execute("UPDATE application_preparation_queue SET status = 'queued', lease_owner = '', lease_expires_at = '', updated_at = CURRENT_TIMESTAMP WHERE status = 'preparing' AND lease_expires_at <> '' AND lease_expires_at <= ?", [now])
    get_db().commit()
    rows = query_db("SELECT id FROM application_preparation_queue WHERE status = 'queued' AND review_status = 'pending' ORDER BY id LIMIT ?", [max(1, int(limit))])
    counts = {"processed": 0, "ready": 0, "failed": 0}
    for row in rows:
        result = prepare_application_queue_item(int(row["id"]), owner=f"{owner}:{row['id']}")
        counts["processed"] += 1
        counts["ready" if result.get("status") == "ready_for_review" else "failed"] += 1
    return counts


def enqueue_auto_preparation(search: dict[str, Any], job_ids: list[int]) -> int:
    if not as_bool(search.get("auto_prepare_enabled")):
        return 0
    created = 0
    for job_id in job_ids:
        row = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        if row is None:
            continue
        eligible, reason, note = preparation_eligibility(job_to_dict(row), search)
        if reason == "explicitly_restricted" or reason == "priority_below_threshold":
            continue
        try:
            item, duplicate = enqueue_application_preparation(job_id, search=search)
            if not duplicate:
                _update_preparation_item(item["id"], eligibility_note=note, review_status="pending" if eligible else "manual_eligibility")
                created += 1
        except ValueError as exc:
            existing = query_db("SELECT id FROM application_preparation_queue WHERE job_id = ?", [job_id], one=True)
            if existing is None:
                get_db().execute(
                    """INSERT INTO application_preparation_queue
                       (job_id, status, review_status, job_priority, error, eligibility_note)
                       VALUES (?, 'failed', 'pending', ?, ?, ?)""",
                    [job_id, int(job_to_dict(row).get("overall_score") or job_to_dict(row).get("fit_score") or 0), str(exc), "Automatic preparation could not select a usable candidate profile or document."],
                )
                get_db().commit()
                created += 1
    return created


def build_format_preserving_resume(
    job: dict[str, Any],
    profile: dict[str, str],
    output: dict[str, Any],
    resume_path: Path,
) -> dict[str, Any]:
    template_raw = text(profile.get("resume_docx_template_path"))
    template_path = safe_local_path(template_raw)
    warning = "Upload a DOCX resume to generate a format-preserving tailored resume."
    if template_path is None or not template_path.exists():
        return {
            "status": "failed",
            "error": warning,
            "change_log": {
                "master_resume_path": template_raw,
                "output_path": str(resume_path),
                "applied": [],
                "skipped": [
                    {
                        "kind": "resume_template",
                        "original": "",
                        "replacement": "",
                        "reason": warning,
                    }
                ],
            },
        }

    candidate_path = resume_path.with_name(f"{resume_path.stem}.layout-check.docx")
    shutil.copyfile(template_path, candidate_path)
    document = Document(candidate_path)
    identity_changed = replace_resume_identity(document, text(profile.get("name")), text(profile.get("email")))
    plan = build_resume_change_plan(document, job, profile, output)
    change_log = apply_resume_change_plan(document, plan)
    if identity_changed:
        change_log.setdefault("applied", []).insert(0, {
            "kind": "identity",
            "original": "",
            "replacement": normalize_space(text(profile.get("name"))),
            "reason": "Updated the selected applicant identity.",
            "applied": True,
        })
    document.save(candidate_path)
    layout_validation = compare_docx_layout(template_path, candidate_path)
    change_log["layout_validation"] = layout_validation
    if layout_validation.get("available") and layout_validation.get("verified"):
        shutil.copyfile(candidate_path, resume_path)
    else:
        # Never silently accept edits whose rendered layout cannot be verified.
        shutil.copyfile(template_path, resume_path)
        identity_candidate = resume_path.with_name(f"{resume_path.stem}.identity-check.docx")
        shutil.copyfile(template_path, identity_candidate)
        identity_document = Document(identity_candidate)
        replace_resume_identity(identity_document, text(profile.get("name")), text(profile.get("email")))
        identity_document.save(identity_candidate)
        identity_validation = compare_docx_layout(template_path, identity_candidate)
        if identity_validation.get("available") and identity_validation.get("verified"):
            shutil.copyfile(identity_candidate, resume_path)
        identity_candidate.unlink(missing_ok=True)
        for item in change_log.get("applied", []):
            item["applied"] = False
            item["skip_reason"] = layout_validation.get("reason") or "Rendered layout changed."
            change_log.setdefault("skipped", []).append(item)
        change_log["applied"] = []
        change_log["layout_warning"] = layout_validation.get("reason") or "Rendered layout could not be verified. Original résumé preserved."
    candidate_path.unlink(missing_ok=True)
    reopened_resume = Document(resume_path)
    _ = "\n".join(paragraph.text for paragraph in reopened_resume.paragraphs)
    meaningful_changes = [
        item for item in change_log.get("applied", [])
        if item.get("kind") != "identity" and item.get("applied", True)
    ]
    change_log["meaningful_customization"] = bool(meaningful_changes)
    change_log["tailoring_message"] = (
        "The original résumé was retained because no safe, layout-preserving customization was available."
        if not meaningful_changes
        else "Meaningful, evidence-grounded résumé customization was applied."
    )
    return {
        "status": "generated",
        "error": "",
        "change_log": {
            "master_resume_path": str(template_path),
            "output_path": str(resume_path),
            **change_log,
        },
    }


def replace_resume_identity(document: Document, applicant_name: str, applicant_email: str = "") -> bool:
    """Replace only the leading name line, never unrelated résumé evidence."""
    applicant_name = normalize_space(applicant_name)
    if not applicant_name:
        return False
    changed = False
    for paragraph in document.paragraphs:
        current = normalize_space(paragraph.text)
        if not current:
            continue
        if len(current.split()) <= 6 and not any(char in current for char in "@|:;•"):
            if current != applicant_name:
                changed = replace_paragraph_text(paragraph, paragraph.text, applicant_name) or changed
            break
        break
    if applicant_email:
        for paragraph in iter_document_paragraphs(document):
            if "@" in (paragraph.text or "") and replace_cover_letter_email(paragraph, applicant_email):
                changed = True
    return changed


def remove_dashes_from_document(document: Document) -> bool:
    changed = False
    for paragraph in iter_document_paragraphs(document):
        for run in paragraph.runs:
            updated = re.sub(r"(?<=\d)[-–—](?=\d)", " to ", run.text)
            updated = re.sub(r"[-–—]", " ", updated)
            updated = re.sub(r"\bhands\s+on\s+experience\b", "practical experience", updated, flags=re.I)
            if updated != run.text:
                run.text = re.sub(r"[ \t]+", " ", updated)
                changed = True
    return changed


EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)


def replace_cover_letter_email(paragraph: Any, replacement: str) -> bool:
    """Replace a contact email atomically, including hyperlink text and target."""
    replacement = normalize_space(replacement)
    if not replacement:
        return False
    changed = False
    hyperlinks = paragraph._p.xpath(".//w:hyperlink")
    for hyperlink in hyperlinks:
        visible = "".join(node.text or "" for node in hyperlink.xpath(".//w:t"))
        relationship_id = hyperlink.get(qn("r:id"))
        relationship = paragraph.part.rels.get(relationship_id) if relationship_id else None
        target = str(getattr(relationship, "target_ref", "") or "") if relationship else ""
        if not EMAIL_PATTERN.search(visible) and not target.lower().startswith("mailto:"):
            continue
        already_current = visible == replacement and target.lower() == f"mailto:{replacement}".lower()
        if already_current:
            continue
        text_nodes = hyperlink.xpath(".//w:t")
        if text_nodes:
            text_nodes[0].text = replacement
            for node in text_nodes[1:]:
                node.text = ""
        if relationship is not None:
            relationship._target = f"mailto:{replacement}"
        changed = True

    value = paragraph.text or ""
    if EMAIL_PATTERN.search(value):
        updated = EMAIL_PATTERN.sub(replacement, value)
        if updated != value and replace_paragraph_text(paragraph, value, updated):
            changed = True
    return changed


def build_format_preserving_cover_letter(
    job: dict[str, Any],
    profile: dict[str, str],
    output: dict[str, Any],
    cover_path: Path,
) -> dict[str, Any]:
    template_raw = text(profile.get("cover_letter_docx_template_path"))
    template_path = safe_local_path(template_raw)
    if not template_raw:
        write_cover_letter_docx(cover_path, output["cover_letter"])
        return {
            "status": "generated",
            "error": "",
            "change_log": {
                "master_cover_letter_path": "",
                "output_path": str(cover_path),
                "applied": [],
                "skipped": [],
                "template_mode": "standard",
            },
        }
    if template_path is None or not template_path.exists():
        return {
            "status": "failed",
            "error": "The selected DOCX cover letter template is unavailable. Upload or select a readable cover letter template before generating.",
            "change_log": {
                "master_cover_letter_path": template_raw,
                "output_path": str(cover_path),
                "applied": [],
                "skipped": [{"kind": "cover_letter_template", "original": "", "replacement": "", "reason": "Selected DOCX template is unavailable."}],
                "template_mode": "template_unavailable",
            },
        }

    shutil.copyfile(template_path, cover_path)
    document = Document(cover_path)
    template_warning = detect_incompatible_cover_letter_template(document)
    structured_template = _has_structured_cover_letter_template(document)
    if _has_cover_letter_stale_content(document) or (template_warning is not None and not structured_template):
        return {
            "status": "failed",
            "error": template_warning or "The selected DOCX cover letter template was rejected because it contains incompatible or stale application content.",
            "warning": template_warning,
            "change_log": {
                "master_cover_letter_path": str(template_path),
                "output_path": str(cover_path),
                "applied": [],
                "skipped": [{"kind": "cover_letter_template", "original": "", "replacement": "", "reason": template_warning or "Template rejected."}],
                "template_mode": "template_rejected",
            },
        }
    change_log = apply_cover_letter_template(document, job, profile, output)
    if not change_log.get("applied"):
        return {
            "status": "failed",
            "error": "The selected DOCX cover letter template could not be adapted safely. No generic replacement was used.",
            "warning": "",
            "change_log": {
                "master_cover_letter_path": str(template_path),
                "output_path": str(cover_path),
                "applied": [],
                "skipped": change_log.get("skipped", [{"kind": "cover_letter_template", "original": "", "replacement": "", "reason": "No safe template adaptation was applied."}]),
                "template_mode": "template_rejected",
            },
        }
    if str(profile.get("cover_letter_no_dashes", "true")).strip().lower() not in {"0", "false", "no", "off"}:
        remove_dashes_from_document(document)
    document.save(cover_path)
    reopened_cover = Document(cover_path)
    if change_log.get("template_mode") != "structured_template" and any(
        classify_keyword_dump_reason(normalize_space(paragraph.text)) is not None
        for paragraph in reopened_cover.paragraphs
    ):
        return {
            "status": "failed",
            "error": "The selected DOCX cover letter template produced an unsafe keyword-dump paragraph. No generic replacement was used.",
            "change_log": {
                "master_cover_letter_path": str(template_path),
                "output_path": str(cover_path),
                "applied": [],
                "skipped": [{"kind": "template_validation", "original": "", "replacement": "", "reason": "Keyword-dump content detected after adaptation."}],
                "template_mode": "template_rejected",
            },
        }
    residual = find_unreplaced_template_content(
        template_path,
        reopened_cover,
        profile,
        preserved_texts=change_log.get("preserved", []),
    )
    if residual:
        return {
            "status": "failed",
            "error": f"The selected DOCX cover letter template could not be fully adapted: {residual}",
            "warning": f"Standard cover-letter formatting was used because template content remained after replacement: {residual}",
            "change_log": {
                "master_cover_letter_path": str(template_path),
                "output_path": str(cover_path),
                "applied": [],
                "skipped": [{"kind": "template_residual", "original": residual, "reason": "Source template content remained in the generated document."}],
                "template_mode": "template_rejected",
            },
        }
    return {
        "status": "generated",
        "error": "",
        "change_log": {
            "master_cover_letter_path": str(template_path),
            "output_path": str(cover_path),
            **change_log,
        },
    }


def _has_structured_cover_letter_template(document: Document) -> bool:
    visible = [normalize_space(paragraph.text).lower() for paragraph in document.paragraphs if normalize_space(paragraph.text)]
    return (
        any(_looks_like_date_text(value) for value in visible)
        and any(value.startswith("dear ") for value in visible)
        and any(value.startswith(("re:", "subject:")) for value in visible)
        and any(value.startswith(("sincerely", "best regards", "kind regards", "regards")) for value in visible)
    )


def _has_cover_letter_stale_content(document: Document) -> bool:
    stale_markers = (
        "centralsquare",
        "software developer co-op",
        "remote - ontario",
        "remote, ontario",
        "8- or 12-month term",
        "8/12-month",
        "central square's technology initiatives",
        "hochitterry.mak@georgebrown.ca",
    )
    containers = [document.paragraphs]
    for section in document.sections:
        containers.extend([section.header.paragraphs, section.footer.paragraphs])
    return any(
        any(marker in normalize_space(paragraph.text).lower() for marker in stale_markers)
        for container in containers
        for paragraph in container
    )


def find_unreplaced_template_content(
    template_path: Path,
    generated: Document,
    profile: dict[str, str],
    preserved_texts: list[dict[str, Any]] | None = None,
) -> str:
    """Find exact source-template text that survived in body, headers, or footers."""
    try:
        source = Document(template_path)
    except (OSError, ValueError, zipfile.BadZipFile):
        return ""
    generated_text = {
        normalize_space(paragraph.text).lower()
        for paragraph in iter_document_paragraphs(generated)
        if normalize_space(paragraph.text)
    }
    allowed = {
        normalize_space(text(profile.get("name"))).lower(),
        normalize_space(text(profile.get("location"))).lower(),
        "hiring manager",
        "sincerely,",
        "best regards,",
        "kind regards,",
        "regards,",
    }
    preserved = {
        normalize_space(item.get("original", "")).lower()
        for item in (preserved_texts or [])
        if normalize_space(item.get("original", ""))
    }
    source_paragraphs = list(iter_document_paragraphs(source))
    subject_seen = False
    for paragraph in source_paragraphs:
        value = normalize_space(paragraph.text)
        lowered = value.lower()
        if not value or lowered in allowed or len(value) < 4:
            continue
        if lowered.startswith(("re:", "subject:")):
            subject_seen = True
            continue
        if not subject_seen:
            # The applicant contact and recipient address are intentionally
            # preserved source content, not stale body prose.
            continue
        if contains_contact_details(value) or _looks_like_date_text(lowered) or "{{" in value:
            continue
        if lowered in preserved:
            continue
        if lowered in generated_text:
            return value[:160]
    return ""


def build_generation_debug_payload(
    job_id: int,
    job: dict[str, Any],
    profile: dict[str, str],
    output: dict[str, Any],
    resume_result: dict[str, Any],
    cover_result: dict[str, Any],
    resume_path: Path,
    cover_path: Path,
) -> dict[str, Any]:
    tailoring_plan = output.get("tailoring_plan") or {}
    approved_records = output.get("approved_evidence_records") or []
    ranked_records = output.get("ranked_approved_evidence_records") or []
    selected_records = output.get("selected_approved_evidence_records") or []
    final_cover_letter_text = text(output.get("cover_letter", ""))
    if cover_path.is_file():
        try:
            rendered_cover = Document(cover_path)
            final_cover_letter_text = "\n".join(
                paragraph.text.strip()
                for paragraph in iter_document_paragraphs(rendered_cover)
                if paragraph.text.strip()
            )
            del rendered_cover
        except (OSError, ValueError, zipfile.BadZipFile):
            pass
    return {
        "job_id": job_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "job_hash": output.get("job_hash", ""),
        "candidate_evidence_hash": output.get("candidate_evidence_hash", ""),
        "approved_evidence_count": len(approved_records),
        "approved_evidence_ids": [clamp_int(item.get("id"), 0, 10**9) for item in approved_records if item.get("id") is not None],
        "ranked_approved_evidence_ids": [clamp_int(item.get("id"), 0, 10**9) for item in ranked_records if item.get("id") is not None],
        "selected_approved_evidence_ids": [clamp_int(item.get("id"), 0, 10**9) for item in selected_records if item.get("id") is not None],
        "matched_evidence_ids": [clamp_int(item.get("evidence_id"), 0, 10**9) for item in tailoring_plan.get("phrase_to_evidence_matches", []) if item.get("evidence_id")],
        "cover_letter_paragraphs": [paragraph for paragraph in final_cover_letter_text.split("\n\n") if paragraph],
        "final_cover_letter_text": final_cover_letter_text,
        "resume_bullets": output.get("resume_bullets", []),
        "resume_variants": tailoring_plan.get("resume_change_blocks", [])[:8],
        "approved_evidence_preview": [
            {
                "id": clamp_int(item.get("id"), 0, 10**9),
                "source_field": text(item.get("source_field")),
                "source_kind": text(item.get("source_kind")),
                "content": text(item.get("content")),
                "score": clamp_int(item.get("score"), -1000, 1000),
            }
            for item in selected_records
        ],
        "ollama": output.get("ollama_debug", {}),
        "resume_result": {
            "status": text(resume_result.get("status")),
            "error": text(resume_result.get("error")),
            "output_path": str(resume_path),
        },
        "cover_result": {
            "status": text(cover_result.get("status")),
            "error": text(cover_result.get("error")),
            "output_path": str(cover_path),
        },
        "profile_hash": build_candidate_evidence(profile)["hash"],
        "job_company": text(job.get("company")),
        "job_title": text(job.get("title")),
    }


def repair_cover_letter_document(
    document: Document,
    template_paragraphs: list[str],
    safe_sections: list[str],
    job: dict[str, Any],
    profile: dict[str, str],
) -> bool:
    repaired = False
    paragraphs = list(iter_document_paragraphs(document))
    section_map = build_cover_letter_section_map(profile, job, [], build_candidate_evidence(profile))
    for index, paragraph in enumerate(paragraphs):
        text_value = normalize_space(paragraph.text)
        if not text_value:
            continue
        if classify_keyword_dump_reason(text_value) is None and not _cover_letter_stale_visible_text(text_value):
            continue
        safe_replacement = safe_sections[index] if index < len(safe_sections) else ""
        if safe_replacement and classify_keyword_dump_reason(safe_replacement) is None and normalize_space(safe_replacement) != text_value:
            if replace_paragraph_exact(paragraph, paragraph.text, safe_replacement):
                repaired = True
                continue
        original_template = template_paragraphs[index] if index < len(template_paragraphs) else ""
        if original_template and normalize_space(original_template) != text_value:
            if replace_paragraph_exact(paragraph, paragraph.text, original_template):
                repaired = True
                continue
        if contains_contact_details(text_value) and replace_paragraph_exact(paragraph, paragraph.text, text(profile.get("name") or "")):
            repaired = True
            continue
        if _cover_letter_stale_visible_text(text_value) and replace_paragraph_exact(paragraph, paragraph.text, ""):
            repaired = True
    if repair_cover_letter_xml_text(document, section_map, job, profile):
        repaired = True
    if dedupe_cover_letter_roles(document, job, profile):
        repaired = True
    if ensure_cover_letter_signature(document, profile):
        repaired = True
    if dedupe_cover_letter_body_roles(document, profile):
        repaired = True
    return repaired


def repair_cover_letter_xml_text(document: Document, section_map: dict[str, str], job: dict[str, Any], profile: dict[str, str]) -> bool:
    repaired = False
    job_title = text(job.get("title")) or "the role"
    replacements = {
        "{{DATE}}": section_map.get("date", ""),
        "{{COMPANY}}": section_map.get("company", ""),
        "{{LOCATION}}": section_map.get("location", ""),
        "{{JOB_TITLE}}": job_title,
        "{{HIRING_MANAGER}}": f"{section_map.get('company', '')} Hiring Team".strip(),
        "{{OPENING_PARAGRAPH}}": section_map.get("opening", ""),
        "{{EXPERIENCE_PARAGRAPH}}": section_map.get("experience", ""),
        "{{FIT_PARAGRAPH}}": section_map.get("fit", ""),
        "{{CLOSING_PARAGRAPH}}": section_map.get("closing", ""),
        "CentralSquare Technologies": section_map.get("company", ""),
        "CentralSquare": section_map.get("company", ""),
        "Software Developer Co-op": job_title,
        "software developer co-op": job_title,
        "Remote - Ontario": section_map.get("location", ""),
        "Remote, Ontario": section_map.get("location", ""),
        "Remote – Ontario": section_map.get("location", ""),
        "Remote — Ontario": section_map.get("location", ""),
        "8- or 12-month term": "",
        "8/12-month placement": "",
        "8/12-month": "",
        "Hiring Manager": f"{section_map.get('company', '')} Hiring Team".strip(),
        "CentralSquare’s technology initiatives": section_map.get("company", ""),
        "CentralSquare's technology initiatives": section_map.get("company", ""),
        "CentralSquare Applicant": text(profile.get("name") or ""),
        "hochitterry.mak@georgebrown.ca": text(profile.get("name") or ""),
    }
    package = getattr(getattr(document, "part", None), "package", None)
    for part in getattr(package, "parts", []) if package is not None else []:
        partname = str(getattr(part, "partname", "")).lower()
        if not partname.endswith(".xml"):
            continue
        if not any(marker in partname for marker in ["/word/document.xml", "/word/header", "/word/footer"]):
            continue
        element = getattr(part, "element", None)
        if element is None:
            continue
        for text_node in element.xpath(".//w:t"):
            current = text_node.text or ""
            updated = current
            for old, new in replacements.items():
                if old and old in updated:
                    updated = updated.replace(old, new)
            if updated != current:
                text_node.text = updated
                repaired = True
    return repaired


def dedupe_cover_letter_roles(document: Document, job: dict[str, Any], profile: dict[str, str]) -> bool:
    repaired = False
    profile_name = text(profile.get("name") or "")
    paragraphs = list(iter_document_paragraphs(document))
    body_paragraph_count = len(document.paragraphs)
    seen_roles: set[str] = set()
    single_use_roles = {"date", "company", "location", "subject", "greeting", "opening", "experience", "fit", "closing", "signoff", "signature"}
    for index, paragraph in enumerate(paragraphs):
        text_value = normalize_space(paragraph.text)
        if not text_value:
            continue
        role = classify_cover_letter_paragraph_role(paragraph, index, len(paragraphs), profile_name)
        if (
            not role
            and profile_name
            and text_value.lower() == profile_name.lower()
            and index < body_paragraph_count
            and index >= max(0, body_paragraph_count - 3)
        ):
            role = "signature"
        if role in single_use_roles:
            if role in seen_roles:
                if replace_paragraph_exact(paragraph, paragraph.text, ""):
                    repaired = True
                continue
                seen_roles.add(role)
    return repaired


def ensure_cover_letter_signature(document: Document, profile: dict[str, str]) -> bool:
    profile_name = text(profile.get("name") or "")
    if not profile_name:
        return False
    paragraphs = list(document.paragraphs)
    if not paragraphs:
        return False
    last_paragraph = paragraphs[-1]
    if normalize_space(last_paragraph.text):
        return False
    return replace_paragraph_exact(last_paragraph, last_paragraph.text, profile_name)


def dedupe_cover_letter_body_roles(document: Document, profile: dict[str, str]) -> bool:
    repaired = False
    profile_name = text(profile.get("name") or "")
    paragraphs = list(document.paragraphs)
    seen_roles: set[str] = set()
    single_use_roles = {"date", "company", "location", "subject", "greeting", "opening", "experience", "fit", "closing", "signoff", "signature"}
    for index, paragraph in enumerate(paragraphs):
        text_value = normalize_space(paragraph.text)
        if not text_value:
            continue
        role = classify_cover_letter_paragraph_role(paragraph, index, len(paragraphs), profile_name)
        if role in single_use_roles:
            if role in seen_roles:
                if replace_paragraph_exact(paragraph, paragraph.text, ""):
                    repaired = True
                continue
            seen_roles.add(role)
    return repaired


def build_cover_letter_section_map(
    profile: dict[str, str],
    job: dict[str, Any],
    focus: list[str],
    candidate_evidence: dict[str, Any],
) -> dict[str, str]:
    company = text(job.get("company")) or "your team"
    location = text(job.get("location")) or ""
    title = text(job.get("title")) or "the role"
    job_text = " ".join(
        [
            text(job.get("title")),
            text(job.get("required_skills")),
            text(job.get("preferred_skills")),
            text(job.get("responsibilities")),
            text(job.get("job_description")),
        ]
    ).lower()
    supported_terms = matching_evidence_terms(job, candidate_evidence, limit=3)
    evidence_paragraphs = select_cover_letter_evidence(profile, job, [*focus, *supported_terms], candidate_evidence)
    evidence_paragraphs = [clean_cover_letter_evidence_sentence(item) for item in evidence_paragraphs if clean_cover_letter_evidence_sentence(item)]
    if not evidence_paragraphs:
        evidence_paragraphs = [select_concrete_evidence_sentence(candidate_evidence)] if select_concrete_evidence_sentence(candidate_evidence) else []
    concrete_example = evidence_paragraphs[0]
    supporting_example = evidence_paragraphs[1] if len(evidence_paragraphs) > 1 else ""
    if supported_terms:
        opening = f"I am pleased to apply for the {title} role at {company}. My experience with {short_join(supported_terms)} includes building and supporting software tools and data workflows relevant to this role."
    else:
        opening = f"I am pleased to apply for the {title} role at {company}. My background includes practical experience relevant to the responsibilities described in this posting."
    motivation = build_job_motivation(job, candidate_evidence)
    return {
        "date": format_cover_letter_date(date.today()),
        "company": company,
        "location": location,
        "title": title,
        "subject": f"Re: Application for {title}",
        "greeting": f"Dear {company} Hiring Team,",
        "opening": opening,
        "experience": as_first_person(concrete_example),
        "experience_secondary": as_first_person(supporting_example),
        "motivation": motivation,
        "fit": f"I would bring the same care to the work at {company}.",
        "closing": "Thank you for your time and consideration.",
        "signoff": "Sincerely,",
        "signature": text(profile.get("name") or ""),
        "applicant_email": text(profile.get("email") or ""),
        "applicant_phone": text(profile.get("phone") or ""),
        "applicant_location": text(profile.get("location") or ""),
    }


def build_job_motivation(job: dict[str, Any], candidate_evidence: dict[str, Any] | None = None) -> str:
    """Use only company or role context explicitly present in the current posting."""
    company = text(job.get("company")) or "the company"
    description = text(job.get("job_description"))
    company_lower = company.lower()
    for sentence in split_sentences(description):
        clean = normalize_space(sentence).rstrip(".")
        if company_lower not in clean.lower() or len(clean.split()) < 8:
            continue
        match = re.match(
            rf"^{re.escape(company)}(?:\s*\([^)]*\))?\s+((?:is|provides|develops|builds|offers|delivers)\s+.+)$",
            clean,
            flags=re.I,
        )
        if match:
            detail = normalize_space(match.group(1))
            return (
                f"I am particularly interested in {company} because the posting states that it {detail}. "
                "I would welcome the opportunity to contribute to that work in a collaborative engineering team."
            )
    if candidate_evidence:
        supported = matching_evidence_terms(job, candidate_evidence, limit=4)
        if supported:
            terms = short_join(supported)
            return (
                f"I am particularly interested in the opportunity at {company} because the posting emphasizes {terms}. "
                "That focus connects directly with my documented experience, and I would welcome the opportunity to contribute to the team."
            )
    return (
        "I am particularly interested in the opportunity to contribute to the responsibilities described in this posting. "
        "I would welcome the chance to support the team with careful, reliable work."
    )


def render_cover_letter_template_without_placeholders(document: Document, section_map: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    ordered_sections = [
        section_map["date"],
        section_map["company"],
        section_map["location"],
        section_map["greeting"],
        section_map["subject"],
        section_map["opening"],
        section_map["experience"],
        section_map["fit"],
        section_map["closing"],
        section_map["signoff"],
        section_map["signature"],
    ]
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    body_paragraphs = [paragraph for paragraph in document.paragraphs if normalize_space(paragraph.text)]
    for index, paragraph in enumerate(body_paragraphs[1:], start=1):
        if index - 1 >= len(ordered_sections):
            break
        original = paragraph.text
        replacement = ordered_sections[index - 1]
        if not replacement or normalize_space(original) == normalize_space(replacement):
            continue
        if replace_paragraph_text(paragraph, original, replacement):
            applied.append(
                {
                    "kind": "paragraph",
                    "original": original,
                    "replacement": replacement,
                    "matched_job_requirement": "template sequence",
                    "supporting_evidence": "",
                    "confidence": 80,
                    "validation_status": "passed",
                }
            )
        else:
            skipped.append({"kind": "paragraph", "original": original, "replacement": replacement, "reason": "Paragraph text did not match."})
    return {"applied": applied, "skipped": skipped, "template_mode": "structured_fallback"}


def paragraph_by_index_text(document: Document, index: int) -> str:
    paragraphs = list(document.paragraphs)
    return paragraphs[index].text if 0 <= index < len(paragraphs) else ""


def adapt_cover_letter_opening(original: str, section_map: dict[str, str]) -> str:
    """Change only the prior application's role and company in its opening."""
    target_title = section_map.get("title") or "the role"
    target_company = section_map.get("company") or "the company"
    pattern = re.compile(r"(apply for (?:the )?)(.+?)( position at )([^.!?]+)([.!?])", re.I)
    adapted = pattern.sub(lambda match: f"{match.group(1)}{target_title}{match.group(3)}{target_company}{match.group(5)}", original, count=1)
    if adapted == original:
        return section_map.get("opening", original)
    return adapted


def refresh_cover_letter_identity(
    document: Document,
    section_map: dict[str, str],
    applied: list[dict[str, Any]],
) -> None:
    """Refresh identity only when the selected profile is distinct."""
    nonempty = [(index, paragraph) for index, paragraph in enumerate(document.paragraphs) if normalize_space(paragraph.text)]
    if not nonempty or not section_map.get("signature"):
        return
    first_index, first = nonempty[0]
    if normalize_space(first.text).lower() != normalize_space(section_map["signature"]).lower():
        original = first.text
        if replace_paragraph_text(first, original, section_map["signature"]):
            applied.append({
                "kind": "identity",
                "original": original,
                "replacement": section_map["signature"],
                "changes": ["applicant name"],
                "reason": "Refreshed the selected distinct applicant identity.",
                "validation_status": "passed",
            })
    for index, paragraph in nonempty:
        value = normalize_space(paragraph.text)
        replacement = ""
        change = ""
        if "@" in value and section_map.get("applicant_email"):
            if replace_cover_letter_email(paragraph, section_map["applicant_email"]):
                applied.append({
                    "kind": "identity",
                    "original": value,
                    "replacement": section_map["applicant_email"],
                    "changes": ["applicant email", "hyperlink display text", "mailto target"],
                    "reason": "Replaced the complete selected applicant email hyperlink atomically.",
                    "validation_status": "passed",
                })
            continue
        elif re.search(r"\d[\d ()+.-]{6,}\d", value) and section_map.get("applicant_phone"):
            replacement, change = section_map["applicant_phone"], "applicant phone"
        if replacement and normalize_space(value) != normalize_space(replacement) and replace_paragraph_text(paragraph, paragraph.text, replacement):
            applied.append({
                "kind": "identity",
                "original": value,
                "replacement": replacement,
                "changes": [change],
                "reason": "Refreshed the selected distinct applicant identity.",
                "validation_status": "passed",
            })
    # Contact blocks can live in headers or tables. Handle those nodes too so
    # an old linked address cannot survive outside the main body paragraphs.
    for paragraph in iter_document_paragraphs(document):
        value = normalize_space(paragraph.text)
        if "@" not in value or not section_map.get("applicant_email"):
            continue
        if replace_cover_letter_email(paragraph, section_map["applicant_email"]):
            applied.append({
                "kind": "identity",
                "original": value,
                "replacement": section_map["applicant_email"],
                "changes": ["applicant email", "hyperlink display text", "mailto target"],
                "reason": "Replaced the complete selected applicant email hyperlink atomically.",
                "validation_status": "passed",
            })


def render_cover_letter_template_by_structure(document: Document, section_map: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    """Refresh a plain cover-letter template while preserving its paragraph layout."""
    paragraphs = list(document.paragraphs)
    nonempty = [(index, paragraph) for index, paragraph in enumerate(paragraphs) if normalize_space(paragraph.text)]
    if not nonempty:
        return {"applied": [], "skipped": [], "template_mode": "structured_fallback"}

    date_index = next((index for index, paragraph in nonempty if _looks_like_date_text(normalize_space(paragraph.text).lower())), None)
    subject_index = next(
        (index for index, paragraph in nonempty if normalize_space(paragraph.text).lower().startswith(("re:", "subject:"))),
        None,
    )
    greeting_index = next(
        (index for index, paragraph in nonempty if normalize_space(paragraph.text).lower().startswith("dear ")),
        None,
    )
    closing_index = next(
        (index for index, paragraph in nonempty if normalize_space(paragraph.text).lower().startswith(("thank you", "i would welcome", "i look forward", "i appreciate"))),
        None,
    )
    signoff_index = next(
        (index for index, paragraph in nonempty if normalize_space(paragraph.text).lower().startswith(("sincerely", "best regards", "kind regards", "regards"))),
        None,
    )
    if subject_index is None or greeting_index is None:
        return {"applied": [], "skipped": [], "template_mode": "structured_fallback"}

    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    replacements: dict[int, str] = {}
    if date_index is not None:
        replacements[date_index] = section_map["date"]
    replacements[greeting_index] = section_map["greeting"]
    replacements[subject_index] = section_map["subject"]
    if closing_index is not None:
        replacements[closing_index] = section_map["closing"]
    if signoff_index is not None:
        replacements[signoff_index] = section_map["signoff"]

    # Preserve the source contact block for the same applicant, but refresh
    # identity fields when a distinct reusable candidate profile is selected.
    first_content_index = next((index for index, _ in nonempty), None)
    if first_content_index is not None and section_map.get("signature"):
        source_name = normalize_space(paragraph_by_index_text(document, first_content_index))
        if source_name and source_name.lower() != normalize_space(section_map["signature"]).lower():
            replacements[first_content_index] = section_map["signature"]
    for index, paragraph in nonempty:
        value = normalize_space(paragraph.text)
        if "@" in value and section_map.get("applicant_email"):
            if replace_cover_letter_email(paragraph, section_map["applicant_email"]):
                applied.append({
                    "kind": "identity",
                    "original": value,
                    "replacement": section_map["applicant_email"],
                    "changes": ["applicant email", "hyperlink display text", "mailto target"],
                    "reason": "Replaced the complete selected applicant email hyperlink atomically.",
                    "validation_status": "passed",
                })
            continue
        elif re.search(r"\d[\d ()+.-]{6,}\d", value) and section_map.get("applicant_phone"):
            replacements[index] = section_map["applicant_phone"]

    # The address block is the nonempty content between the date and subject.
    address_indexes = [index for index, _ in nonempty if date_index is not None and date_index < index < subject_index]
    if len(address_indexes) >= 3:
        # Keep a recipient line such as "Hiring Manager" and refresh the
        # company/location lines that follow it.
        replacements[address_indexes[-2]] = section_map["company"]
        replacements[address_indexes[-1]] = section_map["location"]
    elif address_indexes:
        replacements[address_indexes[0]] = section_map["company"]
        if len(address_indexes) > 1:
            replacements[address_indexes[1]] = section_map["location"]

    body_indexes = [
        index
        for index, _ in nonempty
        if greeting_index < index
        and (closing_index is None or index < closing_index)
        and (signoff_index is None or index < signoff_index)
        and index not in replacements
    ]
    preserved_body: list[dict[str, Any]] = []
    body_replacements: dict[int, tuple[str, str]] = {}
    paragraph_by_index = dict(nonempty)
    if body_indexes:
        opening_index = body_indexes[0]
        opening_original = paragraph_by_index_text(document, opening_index)
        opening = adapt_cover_letter_opening(opening_original, section_map)
        body_replacements[opening_index] = (opening, "Updated the prior application title and company while preserving the source opening.")
    if len(body_indexes) > 1:
        motivation_index = body_indexes[-1]
        motivation_original = paragraph_by_index_text(document, motivation_index)
        body_replacements[motivation_index] = (
            section_map.get("motivation", section_map.get("fit", "")),
            "Replaced the prior employer specific motivation with job description grounded motivation.",
        )
    for index in body_indexes:
        if index not in body_replacements:
            original = paragraph_by_index_text(document, index)
            preserved_body.append(
                {
                    "original": original,
                    "replacement": original,
                    "changes": [],
                    "reason": "Preserved because the paragraph contains candidate evidence that remains factually appropriate.",
                }
            )
    for index, (replacement, reason) in body_replacements.items():
        if replacement:
            replacements[index] = replacement

    # Replace only body text. The first applicant name and contact block remain untouched;
    # the final name is refreshed when it is a distinct signature paragraph.
    if nonempty and signoff_index is not None:
        signature_candidates = [index for index, _ in nonempty if index > signoff_index]
        if signature_candidates:
            replacements[signature_candidates[0]] = section_map["signature"]

    for index, replacement in replacements.items():
        paragraph = paragraph_by_index.get(index)
        if paragraph is None or not replacement or normalize_space(paragraph.text) == normalize_space(replacement):
            continue
        original = paragraph.text
        if replace_paragraph_text(paragraph, original, replacement):
            body_reason = dict(body_replacements).get(index, ("", ""))[1]
            applied.append({
                "kind": "structured_paragraph",
                "original": original,
                "replacement": replacement,
                "changes": ["paragraph text"],
                "reason": body_reason or "Updated a document field required for this application.",
                "matched_job_requirement": "cover letter structure",
                "supporting_evidence": "approved candidate profile and job details",
                "confidence": 90,
                "validation_status": "passed",
            })
        else:
            skipped.append({"kind": "structured_paragraph", "original": original, "replacement": replacement, "reason": "Paragraph text did not match."})
    return {
        "applied": applied,
        "skipped": skipped,
        "preserved": preserved_body,
        "template_mode": "structured_template",
    }


def select_concrete_evidence_sentence(candidate_evidence: dict[str, Any]) -> str:
    sections = candidate_evidence.get("sections") or []
    fallback = ""
    for section in sections:
        if section.get("field") not in {"work_experience", "projects"}:
            continue
        for sentence in split_sentences(section.get("text", "")):
            clean = normalize_space(sentence)
            if not clean or len(clean.split()) < 8:
                continue
            if contains_contact_details(clean) or contains_resume_section_heading(clean) or is_resume_role_heading(clean):
                continue
            if classify_keyword_dump_reason(clean) is not None:
                continue
            if any(char.isdigit() for char in clean) or any(term in clean.lower() for term in ["built", "implemented", "designed", "managed", "maintained", "developed"]):
                return clean if clean.endswith(".") else f"{clean}."
            if not fallback:
                fallback = clean if clean.endswith(".") else f"{clean}."
    return fallback


def as_first_person(value: str) -> str:
    clean = normalize_space(value)
    if not clean:
        return ""
    if clean.lower().startswith("i "):
        return clean
    return f"I {clean[0].lower() + clean[1:]}"


def build_cover_letter_evidence_paragraphs(candidate_evidence: dict[str, Any]) -> list[str]:
    sentences: list[str] = []
    for section in candidate_evidence.get("sections", []):
        if section.get("field") not in {"work_experience", "projects"}:
            continue
        for sentence in split_sentences(section.get("text", "")):
            clean = normalize_space(sentence)
            clean = clean_cover_letter_evidence_sentence(clean)
            if not clean or len(clean.split()) < 8:
                continue
            if contains_contact_details(clean) or contains_resume_section_heading(clean) or is_resume_role_heading(clean):
                continue
            if classify_keyword_dump_reason(clean) is not None:
                continue
            sentences.append(clean if clean.endswith((".", "!", "?")) else f"{clean}.")
            if len(sentences) >= 3:
                break
        if len(sentences) >= 3:
            break
    if not sentences:
        fallback = select_concrete_evidence_sentence(candidate_evidence)
        return [fallback] if fallback else []
    if len(sentences) == 1:
        followup = select_concrete_evidence_sentence(candidate_evidence)
        if followup and followup != sentences[0]:
            sentences.append(followup)
    return [sentence for sentence in dict.fromkeys(sentences) if sentence]


def clean_cover_letter_evidence_sentence(value: str) -> str:
    """Remove flattened résumé headings that precede a supported achievement."""
    clean = normalize_space(value)
    match = re.search(
        r"\b(?:built|designed|developed|implemented|held|configured|added|integrated|used|consolidated)\b",
        clean,
        re.I,
    )
    if match and match.start() > 0:
        prefix = clean[: match.start()]
        if any(marker in prefix.lower() for marker in ("inc.", "co.", "developer", "engineer", "contract", "shopify", "git")):
            clean = clean[match.start() :]
    return normalize_space(clean)


def format_cover_letter_date(value: date) -> str:
    return value.strftime("%B %d, %Y").replace(" 0", " ")


def classify_cover_letter_paragraph_role(paragraph: Any, index: int, total: int, profile_name: str) -> str:
    paragraph_text = normalize_space(paragraph.text)
    lower = paragraph_text.lower()
    if not paragraph_text:
        return ""
    if "{{date}}" in lower or _looks_like_date_text(lower):
        return "date"
    if "{{company}}" in lower:
        return "company"
    if "{{location}}" in lower:
        return "location"
    if "{{job_title}}" in lower:
        return "subject"
    if "{{hiring_manager}}" in lower or lower.startswith("dear "):
        return "greeting"
    if "{{opening_paragraph}}" in lower:
        return "opening"
    if "{{experience_paragraph}}" in lower:
        return "experience"
    if "{{fit_paragraph}}" in lower:
        return "fit"
    if "{{closing_paragraph}}" in lower:
        return "closing"
    if lower.startswith(("thank you", "i would welcome", "i look forward", "i appreciate")):
        return "closing"
    if lower.startswith(("sincerely", "best regards", "regards", "kind regards", "with appreciation")):
        return "signoff"
    if profile_name and normalize_space(profile_name).lower() == lower and index >= max(0, total - 3):
        return "signature"
    if index >= max(0, total - 2) and len(paragraph_text.split()) <= 4 and not contains_contact_details(paragraph_text):
        return "signature"
    if index < 4 and (lower.startswith("re:") or lower.startswith("subject:") or "application" in lower):
        return "subject"
    return ""


def is_cover_letter_template_paragraph_editable(paragraph: Any, index: int) -> bool:
    paragraph_text = normalize_space(paragraph.text)
    if not paragraph_text:
        return False
    style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
    if style_name.lower().startswith("heading"):
        return False
    if index == 0 and len(paragraph_text.split()) <= 4 and not any(ch.isdigit() for ch in paragraph_text) and "{{" not in paragraph_text:
        return False
    return True


def _looks_like_date_text(value: str) -> bool:
    return bool(
        re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", value)
        and re.search(r"\b\d{1,2},?\s+\d{4}\b", value)
    )


def _replacement_for_cover_letter_role(roles: dict[str, str], role: str) -> str:
    return roles.get(role, "")


def apply_cover_letter_template(
    document: Document,
    job: dict[str, Any],
    profile: dict[str, str],
    output: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    tailoring_plan = output.get("tailoring_plan") or build_tailoring_plan(job, profile, output.get("semantic_match", {}))
    generated_sections = tailoring_plan.get("cover_letter_paragraphs") or []
    candidate_evidence = output.get("candidate_evidence") or build_candidate_evidence(profile)
    section_map = build_cover_letter_section_map(profile, job, list(output.get("supported_keywords", [])[:4]), candidate_evidence)
    has_placeholders = any(marker in paragraph.text for paragraph in iter_document_paragraphs(document) for marker in ("{{DATE}}", "{{COMPANY}}", "{{LOCATION}}", "{{JOB_TITLE}}", "{{HIRING_MANAGER}}", "{{OPENING_PARAGRAPH}}", "{{EXPERIENCE_PARAGRAPH}}", "{{FIT_PARAGRAPH}}", "{{CLOSING_PARAGRAPH}}"))
    if generated_sections and has_placeholders:
        if len(generated_sections) > 4:
            section_map["opening"] = generated_sections[4]
        if len(generated_sections) > 5:
            section_map["experience"] = generated_sections[5]
        if len(generated_sections) > 6:
            section_map["fit"] = generated_sections[6]
        if len(generated_sections) > 7:
            section_map["closing"] = generated_sections[7]
    replacements = {
        "{{DATE}}": section_map["date"],
        "{{COMPANY}}": section_map["company"],
        "{{LOCATION}}": section_map["location"],
        "{{JOB_TITLE}}": text(job.get("title")) or "the role",
        "{{HIRING_MANAGER}}": f"{section_map['company']} Hiring Team",
        "{{OPENING_PARAGRAPH}}": section_map["opening"],
        "{{EXPERIENCE_PARAGRAPH}}": section_map["experience"],
        "{{FIT_PARAGRAPH}}": section_map["fit"],
        "{{CLOSING_PARAGRAPH}}": section_map["closing"],
    }
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for paragraph in iter_document_paragraphs(document):
        original = paragraph.text
        if not original.strip():
            continue
        replacement = original
        replaced = False
        for placeholder, resolved in replacements.items():
            if placeholder in original:
                replacement = original.replace(placeholder, resolved)
                replaced = replace_paragraph_text(paragraph, original, replacement)
                if replaced:
                    applied.append(
                        {
                            "kind": "placeholder",
                            "original": original,
                            "replacement": replacement,
                            "matched_job_requirement": placeholder,
                            "supporting_evidence": "",
                            "confidence": 95,
                            "validation_status": "passed",
                        }
                    )
                else:
                    skipped.append({"kind": "placeholder", "original": original, "replacement": replacement, "reason": "Paragraph text did not match."})
                break
        if not replaced and any(marker in original for marker in replacements):
            skipped.append({"kind": "placeholder", "original": original, "replacement": replacement, "reason": "Template marker present but paragraph did not match."})
    refresh_cover_letter_identity(document, section_map, applied)
    if not has_placeholders:
        return render_cover_letter_template_by_structure(document, section_map)
    return {
        "applied": applied,
        "skipped": skipped,
        "template_mode": "placeholder_only",
        "summary": {
            "total_editable_paragraphs": len(list(iter_document_paragraphs(document))),
            "total_proposed_changes": len(applied) + len(skipped),
            "total_applied_changes": len(applied),
            "total_skipped_changes": len(skipped),
        },
    }


SUMMARY_HEADINGS = {
    "summary",
    "professional summary",
    "profile summary",
    "resume summary",
}

SKILLS_HEADINGS = {
    "skills",
    "technical skills",
    "core competencies",
    "skills & competencies",
    "competencies",
}

EXPERIENCE_HEADINGS = {
    "experience",
    "work experience",
    "professional experience",
    "employment history",
}

PROJECTS_HEADINGS = {
    "projects",
    "project experience",
    "selected projects",
    "technical projects",
}

RESUME_HEADING_TO_SECTION = {
    **{heading: "summary" for heading in SUMMARY_HEADINGS},
    **{heading: "skills" for heading in SKILLS_HEADINGS},
    **{heading: "experience" for heading in EXPERIENCE_HEADINGS},
    **{heading: "projects" for heading in PROJECTS_HEADINGS},
}


def build_resume_change_plan(
    document: Document,
    job: dict[str, Any],
    profile: dict[str, str],
    output: dict[str, Any],
) -> list[dict[str, Any]]:
    contexts = collect_resume_paragraph_contexts(document)
    candidate_evidence = build_candidate_evidence(profile)
    job_requirement = normalize_space(
        " ".join(
            [
                text(job.get("required_skills")),
                text(job.get("preferred_skills")),
                text(job.get("responsibilities")),
                text(job.get("job_description")),
                text(job.get("title")),
            ]
        )
    )
    tailoring_plan = output.get("tailoring_plan") or build_tailoring_plan(job, profile, output.get("semantic_match", {}))
    plan: list[dict[str, Any]] = []
    candidate_map: dict[str, dict[str, Any]] = {}

    summary_context = next((ctx for ctx in contexts if ctx["section"] == "summary" and ctx["editable"]), None)
    if summary_context is not None:
        summary_original = summary_context["text"]
        summary_replacement = summary_original
        summary_match = {
            "job_phrase": text(job.get("title")),
            "evidence_text": summary_original,
        }
        summary_replacement, summary_change = minimal_resume_substitution(summary_original, summary_match)
        summary_validation = validate_minimal_substitution(summary_original, summary_replacement, summary_match, candidate_evidence)
        if summary_validation.get("grounded"):
            candidate_map["summary"] = {
                "kind": "summary",
                "paragraph_type": "summary_paragraph",
                "section": "summary",
                "original": summary_original,
                "replacement": summary_replacement,
                "supporting_evidence": summary_original,
                "matched_job_requirement": text(job.get("title")),
                "confidence": 90,
                "validation_status": "pending",
                "priority": 2,
            }
        else:
            plan.append(
                {
                    "kind": "summary",
                    "paragraph_type": "summary_paragraph",
                    "section": "summary",
                    "original": summary_original,
                    "replacement": summary_original,
                    "supporting_evidence": summary_original,
                    "matched_job_requirement": text(job.get("title")),
                    "confidence": 0,
                    "validation_status": "skipped",
                    "reason": summary_validation.get("reason", "No safe minimal summary substitution."),
                }
            )
    else:
        plan.append(
            {
                "kind": "summary",
                "paragraph_type": "summary_paragraph",
                "section": "summary",
                "original": "",
                "replacement": "",
                "supporting_evidence": "",
                "matched_job_requirement": "",
                "confidence": 0,
                "validation_status": "skipped",
                "reason": "Skipped summary tailoring: no existing summary section",
                "priority": 2,
            }
        )

    skills_context = next((ctx for ctx in contexts if ctx["section"] == "skills" and ctx["editable"]), None)
    skills_block = next((item for item in tailoring_plan.get("resume_change_blocks", []) if item.get("section") == "skills"), None)
    if skills_context is not None:
        skill_pool = [
            skill.strip()
            for skill in re.split(r"[,;\n]+", str(profile.get("key_skills") or ""))
            if skill.strip()
        ]
        job_lower = job_requirement.lower()
        phrase_order = [str(phrase.get("phrase", "")).lower() for phrase in tailoring_plan.get("extracted_job_phrases", [])]
        supported_skills = [
            skill
            for skill in skill_pool
            if skill.lower() in job_lower
            or skill.lower() in candidate_evidence["full_text"].lower()
            or any(
                skill.lower() in str(phrase.get("phrase", "")).lower() or str(phrase.get("phrase", "")).lower() in skill.lower()
                for phrase in tailoring_plan.get("extracted_job_phrases", [])
            )
        ]
        if any(term in job_lower for term in ["aws", "linux", "testing", "debugging", "documentation", "collaboration", "database design"]):
            priority_terms = [
                "Python",
                "SQL",
                "AWS",
                "Linux",
                "testing",
                "debugging",
                "documentation",
                "collaboration",
                "Flask",
                "React",
                "cloud",
                "dashboards",
            ]
        else:
            priority_terms = [
                "Python",
                "Flask",
                "SQL",
                "React",
                "dashboards",
                "cloud",
            ]
        ordered_skills: list[str] = []
        for term in priority_terms:
            for skill in supported_skills:
                if skill in ordered_skills:
                    continue
                lower_skill = skill.lower()
                lower_term = term.lower()
                if lower_skill == lower_term or lower_term in lower_skill or lower_skill in lower_term:
                    ordered_skills.append(skill)
        for skill in supported_skills:
            if skill not in ordered_skills:
                ordered_skills.append(skill)
        supported_skills = ordered_skills
        if skills_block is not None:
            replacement = reorder_skills_text(skills_context["text"], supported_skills)
            confidence = clamp_int(skills_block.get("confidence"), 0, 100)
            supporting_evidence = text(skills_block.get("supporting_evidence"))
            matched_job_requirement = text(skills_block.get("matched_job_phrase"))
        else:
            replacement = reorder_skills_text(skills_context["text"], supported_skills)
            confidence = 70 if normalize_space(replacement) != normalize_space(skills_context["text"]) else 40
            supporting_evidence = ", ".join(supported_skills[:8])
            matched_job_requirement = "Supported skills already present in the saved profile and posting"
        if ":" in skills_context["text"]:
            prefix = skills_context["text"].split(":", 1)[0].strip() or "Skills"
            remainder = replacement.split(":", 1)[1].strip() if ":" in replacement else replacement.strip()
            replacement = f"{prefix}: {remainder}"
        elif not replacement.lower().startswith("skills:"):
            replacement = f"Skills: {replacement.strip()}"
        if is_cosmetic_only_change(skills_context["text"], replacement):
            plan.append(
                {
                    "kind": "skills",
                    "paragraph_type": "skills_paragraph",
                    "section": "skills",
                    "original": skills_context["text"],
                    "replacement": skills_context["text"],
                    "supporting_evidence": supporting_evidence,
                    "matched_job_requirement": matched_job_requirement,
                    "confidence": confidence,
                    "validation_status": "skipped",
                    "reason": "Cosmetic-only skill reordering was rejected.",
                    "priority": 3,
                }
            )
        elif normalize_space(replacement) != normalize_space(skills_context["text"]):
            candidate_map["skills"] = {
                "kind": "skills",
                "paragraph_type": "skills_paragraph",
                "section": "skills",
                "original": skills_context["text"],
                "replacement": replacement,
                "supporting_evidence": supporting_evidence,
                "matched_job_requirement": matched_job_requirement,
                "confidence": confidence,
                "validation_status": "pending",
                "priority": 3,
            }
        else:
            plan.append(
                {
                    "kind": "skills",
                    "paragraph_type": "skills_paragraph",
                    "section": "skills",
                    "original": skills_context["text"],
                    "replacement": skills_context["text"],
                    "supporting_evidence": supporting_evidence,
                    "matched_job_requirement": matched_job_requirement,
                    "confidence": confidence,
                    "validation_status": "skipped",
                    "reason": "No ATS benefit: skill order already matches the job-relevant priority.",
                    "priority": 3,
                }
            )

    for block in tailoring_plan.get("resume_change_blocks", []):
        original = normalize_space(text(block.get("original_text")))
        replacement = normalize_space(text(block.get("proposed_text")))
        confidence = clamp_int(block.get("confidence"), 0, 100)
        if not original or not replacement:
            continue
        context = next((ctx for ctx in contexts if normalize_space(ctx["text"]) == original and ctx["editable"]), None)
        if context is None:
            plan.append(
                {
                    "kind": "bullet",
                    "paragraph_type": "bullet_paragraph",
                    "section": text(block.get("section")),
                    "original": original,
                    "replacement": replacement,
                    "supporting_evidence": text(block.get("supporting_evidence")),
                    "matched_job_requirement": text(block.get("matched_job_phrase")),
                    "confidence": confidence,
                    "validation_status": "skipped",
                    "reason": "Exact text not found in an editable paragraph.",
                    "priority": 9,
                    "source": "shared-plan",
                }
            )
            continue
        if context["section"] not in {"experience", "projects"}:
            plan.append(
                {
                    "kind": "bullet",
                    "paragraph_type": "bullet_paragraph",
                    "section": context["section"],
                    "original": original,
                    "replacement": replacement,
                    "supporting_evidence": text(block.get("supporting_evidence")),
                    "matched_job_requirement": text(block.get("matched_job_phrase")),
                    "confidence": confidence,
                    "validation_status": "skipped",
                    "reason": "Protected paragraph.",
                    "priority": 9,
                    "source": "shared-plan",
                }
            )
            continue
        if confidence < 60:
            plan.append(
                {
                    "kind": "bullet",
                    "paragraph_type": "bullet_paragraph",
                    "section": context["section"],
                    "original": original,
                    "replacement": replacement,
                    "supporting_evidence": text(block.get("supporting_evidence")),
                    "matched_job_requirement": text(block.get("matched_job_phrase")),
                    "confidence": confidence,
                    "validation_status": "skipped",
                    "reason": "Low semantic relevance.",
                    "priority": 0 if context["section"] == "experience" else 1,
                    "source": "shared-plan",
                }
            )
            continue
        candidate_map[normalize_space(original)] = {
            "kind": "bullet",
            "paragraph_type": "bullet_paragraph",
            "section": context["section"],
            "original": original,
            "replacement": replacement,
            "supporting_evidence": text(block.get("supporting_evidence")),
            "matched_job_requirement": text(block.get("matched_job_phrase")),
            "confidence": confidence,
            "validation_status": "pending",
            "priority": 0 if context["section"] == "experience" else 1,
            "source": "shared-plan",
        }

    pending_candidates = sorted(
        candidate_map.values(),
        key=lambda item: (item["priority"], -int(item["confidence"]), item["section"], item["original"]),
    )
    selected_candidates = pending_candidates[:6]
    for item in pending_candidates[6:]:
        plan.append(
            {
                **item,
                "validation_status": "skipped",
                "reason": "Lower ranked than selected changes.",
            }
        )
    plan.extend(selected_candidates)
    return plan


def resume_change_confidence(original: str, replacement: str, requirement: str, evidence_text: str) -> int:
    original_terms = {term for term in extract_rewrite_terms(original)}
    replacement_terms = {term for term in extract_rewrite_terms(replacement)}
    requirement_terms = {term for term in extract_rewrite_terms(requirement)}
    evidence_terms = {term for term in extract_rewrite_terms(evidence_text)}
    shared_terms = (original_terms | replacement_terms) & (requirement_terms | evidence_terms)
    score = 55 + min(20, len(shared_terms) * 4)
    if any(term in replacement.lower() for term in ["database", "testing", "documentation", "collaboration", "python", "aws", "linux"]):
        score += 5
    length_ratio = len(replacement) / max(1, len(original))
    if 0.75 <= length_ratio <= 1.25:
        score += 5
    if len(shared_terms) >= 2:
        score += 5
    return clamp_int(score, 0, 100)


def extract_rewrite_terms(content: str) -> list[str]:
    return [
        term
        for term in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{1,}", content.lower())
        if term not in {"and", "the", "for", "with", "from", "that", "this", "into", "using", "built"}
    ]


def supporting_snippet_for_plan(candidate_evidence: dict[str, Any], output: dict[str, Any], job: dict[str, Any]) -> str:
    snippets = supporting_snippets(output.get("supported_keywords", [])[:4], candidate_evidence, limit=1)
    if snippets:
        return snippets[0]
    return text(job.get("job_description"))[:160]


def apply_resume_change_plan(document: Document, plan: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    paragraphs = list(iter_document_paragraphs(document))
    editable_paragraph_count = sum(
        1 for paragraph in paragraphs if any(
            [
                is_editable_resume_paragraph(paragraph, "summary"),
                is_editable_resume_paragraph(paragraph, "skills"),
                is_editable_resume_paragraph(paragraph, "bullet"),
            ]
        )
    )
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in plan:
        item = dict(item)
        if item.get("validation_status") == "skipped":
            skipped.append({**item, "applied": False, "skip_reason": item.get("reason", "Skipped.")})
            continue
        kind = item["kind"]
        if kind in {"summary", "skills"}:
            target = find_section_paragraph(paragraphs, SUMMARY_HEADINGS if kind == "summary" else SKILLS_HEADINGS)
            if target is None:
                skipped.append({**item, "applied": False, "skip_reason": f"No {kind} section found in master resume."})
                continue
            if kind == "summary" and not is_editable_resume_paragraph(target, "summary"):
                skipped.append({**item, "applied": False, "skip_reason": "Summary paragraph is protected or not editable."})
                continue
            if kind == "skills" and not is_editable_resume_paragraph(target, "skills"):
                skipped.append({**item, "applied": False, "skip_reason": "Skills paragraph is protected or not editable."})
                continue
            if replace_paragraph_exact(target, item["original"], item["replacement"]):
                applied.append({**item, "applied": True})
            else:
                skipped.append({**item, "applied": False, "skip_reason": "Exact paragraph text was not found."})
            continue

        matched = False
        for paragraph in paragraphs:
            if not is_editable_resume_paragraph(paragraph, "bullet"):
                continue
            if replace_paragraph_exact(paragraph, item["original"], item["replacement"]):
                applied.append({**item, "applied": True})
                matched = True
                break
        if not matched:
            skipped.append({**item, "applied": False, "skip_reason": "Exact bullet text was not found."})
    return {
        "summary": {
            "total_editable_paragraphs": editable_paragraph_count,
            "total_proposed_changes": len(plan),
            "total_applied_changes": len(applied),
            "total_skipped_changes": len(skipped),
        },
        "applied": applied,
        "skipped": skipped,
    }


def find_section_paragraph(paragraphs: list[Any], headings: set[str]) -> Any | None:
    for index, paragraph in enumerate(paragraphs):
        if not is_section_heading(paragraph, headings):
            continue
        for following in paragraphs[index + 1 :]:
            if normalize_space(following.text):
                return following
        return None
    return None


def is_section_heading(paragraph: Any, headings: set[str]) -> bool:
    text_value = normalize_space(paragraph.text).lower().rstrip(":")
    if not text_value:
        return False
    return text_value in headings


def paragraph_resume_section(paragraph: Any) -> str:
    text_value = normalize_space(paragraph.text).lower().rstrip(":")
    return RESUME_HEADING_TO_SECTION.get(text_value, "")


def collect_resume_paragraph_contexts(document: Document) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    current_section = ""
    for paragraph in document.paragraphs:
        section = paragraph_resume_section(paragraph)
        if section:
            current_section = section
        paragraph_text = normalize_space(paragraph.text)
        style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
        is_bullet = style_name.lower().startswith("list") or paragraph_text.startswith(("-", "â€¢", "*"))
        editable = False
        if current_section == "summary":
            editable = is_editable_resume_paragraph(paragraph, "summary")
        elif current_section == "skills":
            editable = is_editable_resume_paragraph(paragraph, "skills")
        elif current_section in {"experience", "projects"} and is_bullet:
            editable = is_editable_resume_paragraph(paragraph, "bullet")
        contexts.append(
            {
                "paragraph": paragraph,
                "text": paragraph_text,
                "section": current_section,
                "style_name": style_name,
                "editable": editable,
                "is_bullet": is_bullet,
                "is_heading": bool(section),
            }
        )
    return contexts


def iter_document_paragraphs(document: Document) -> list[Any]:
    paragraphs: list[Any] = []
    for paragraph in document.paragraphs:
        paragraphs.append(paragraph)
    for table in document.tables:
        paragraphs.extend(iter_table_paragraphs(table))
    for section in document.sections:
        paragraphs.extend(iter_container_paragraphs(section.header))
        paragraphs.extend(iter_container_paragraphs(section.footer))
    return paragraphs


def iter_container_paragraphs(container: Any) -> list[Any]:
    paragraphs: list[Any] = []
    if hasattr(container, "paragraphs"):
        paragraphs.extend(list(container.paragraphs))
    if hasattr(container, "tables"):
        for table in container.tables:
            paragraphs.extend(iter_table_paragraphs(table))
    return paragraphs


def iter_table_paragraphs(table: Any) -> list[Any]:
    paragraphs: list[Any] = []
    for row in table.rows:
        for cell in row.cells:
            paragraphs.extend(iter_container_paragraphs(cell))
    return paragraphs


def replace_paragraph_exact(paragraph: Any, original: str, replacement: str) -> bool:
    if normalize_space(paragraph.text) != normalize_space(original):
        return False
    runs = list(paragraph.runs)
    if not runs:
        paragraph.add_run(replacement)
        return True
    first_run = next((run for run in runs if text(run.text)), runs[0])
    first_run.text = replacement
    for run in runs:
        if run is not first_run:
            run.text = ""
    return True


def replace_paragraph_text(paragraph: Any, original: str, replacement: str) -> bool:
    return replace_paragraph_exact(paragraph, original, replacement)


def is_editable_resume_paragraph(paragraph: Any, kind: str) -> bool:
    paragraph_text = normalize_space(paragraph.text)
    if not paragraph_text:
        return False
    style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
    if style_name.lower().startswith("heading"):
        return False
    if contains_contact_details(paragraph_text):
        return False
    if kind == "bullet":
        return style_name.lower().startswith("list") or paragraph_text.startswith(("-", "•", "*"))
    if kind in {"summary", "skills"}:
        return not paragraph_text.lower().startswith(("dear ", "sincerely", "best regards"))
    return True


def is_editable_cover_letter_paragraph(paragraph: Any) -> bool:
    paragraph_text = normalize_space(paragraph.text)
    if not paragraph_text:
        return False
    lower = paragraph_text.lower()
    style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
    if style_name.lower().startswith("heading"):
        return False
    if contains_resume_section_heading(paragraph_text) or contains_contact_details(paragraph_text):
        return False
    if lower.startswith(("dear ", "sincerely", "best regards", "regards", "thank you")):
        return False
    if "{{" in paragraph_text and "}}" in paragraph_text:
        return False
    if len(paragraph_text) <= 40 and len(paragraph_text.split()) <= 5 and "." not in paragraph_text and "," not in paragraph_text:
        return False
    return True


def reorder_skills_text(original: str, supported_skills: list[str]) -> str:
    text_value = original.strip()
    if not text_value:
        return text_value
    prefix = ""
    rest = text_value
    if ":" in text_value:
        prefix, rest = text_value.split(":", 1)
        prefix = prefix.strip()
        rest = rest.strip()
    items = [item.strip() for item in re.split(r"[,;|/]+", rest) if item.strip()]
    if not items:
        return text_value
    ordered: list[str] = []
    remaining = items[:]
    for supported in supported_skills:
        for item in list(remaining):
            if item.lower() == supported.lower() or contains_phrase(item, supported) or contains_phrase(supported, item):
                ordered.append(item)
                remaining.remove(item)
                break
    if not ordered:
        return text_value
    combined = ", ".join([*ordered, *remaining])
    return f"{prefix}: {combined}" if prefix else combined


def is_cosmetic_only_change(original: str, proposed: str) -> bool:
    original_tokens = re.findall(r"[a-z0-9]+", normalize_space(original).lower())
    proposed_tokens = re.findall(r"[a-z0-9]+", normalize_space(proposed).lower())
    if not original_tokens or not proposed_tokens:
        return False
    if original_tokens == proposed_tokens:
        return True
    return "".join(original_tokens) == "".join(proposed_tokens)


def safe_local_path(value: str) -> Path | None:
    raw = text(value)
    if not raw:
        return None
    try:
        path = Path(raw).resolve()
    except (OSError, RuntimeError):
        return None
    root = DATA_DIR.resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def save_master_resume_template(filename: str, content: bytes) -> Path:
    suffix = Path(filename).suffix.lower() or ".docx"
    stem = safe_filename(Path(filename).stem or "resume")
    folder = DATA_DIR / "resume_templates"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stem}_{uuid.uuid4().hex[:10]}{suffix}"
    path.write_bytes(content)
    return path


def save_master_cover_letter_template(filename: str, content: bytes) -> Path:
    suffix = Path(filename).suffix.lower() or ".docx"
    stem = safe_filename(Path(filename).stem or "cover_letter")
    folder = DATA_DIR / "cover_letter_templates"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stem}_{uuid.uuid4().hex[:10]}{suffix}"
    path.write_bytes(content)
    return path


def update_generation_status(
    job_id: int,
    resume_status: str,
    cover_status: str,
    resume_path: str,
    cover_path: str,
    generation_error: str,
    resume_error: str,
    cover_error: str,
    resume_warning: str = "",
    cover_warning: str = "",
) -> None:
    generated_at = datetime.now().isoformat(timespec="seconds") if resume_status == "generated" or cover_status == "generated" else ""
    profile_updated = text(load_profile().get("updated_at"))
    get_db().execute(
        """
        UPDATE jobs
        SET resume_generation_status = ?,
            cover_letter_generation_status = ?,
            resume_docx_path = ?,
            cover_letter_docx_path = ?,
            resume_generation_error = ?,
            cover_letter_generation_error = ?,
            cover_letter_generation_warning = ?,
            generation_error = ?,
            generated_at = ?,
            profile_updated_at = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        [
            resume_status,
            cover_status,
            resume_path,
            cover_path,
            resume_error,
            cover_error,
            cover_warning,
            generation_error,
            generated_at,
            profile_updated,
            job_id,
        ],
    )
    get_db().commit()


INCOMPATIBLE_COVER_TEMPLATE_TERMS = [
    "customer service",
    "customer-support",
    "retail",
    "supermarket",
    "cashier",
    "sales associate",
    "store manager",
    "food service",
    "restaurant",
    "hospitality",
    "merchandising",
    "inventory",
    "stockroom",
]

GENERIC_COVER_PHRASES = [
    "practical experience that aligns",
    "my background includes practical experience",
    "together, these examples",
    "my background lines up",
    "careful delivery matters",
    "staying true to my background",
    "reliability, documentation, and collaboration",
    "quality, clear communication, and steady delivery",
]


def write_docx(path: Path, title: str, body: str) -> None:
    document = Document()
    document.add_heading(title, level=1)
    for block in body.split("\n\n"):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if len(lines) == 1:
            document.add_paragraph(lines[0])
        else:
            document.add_paragraph(lines[0])
            for line in lines[1:]:
                document.add_paragraph(line.lstrip("- "), style="List Bullet" if line.strip().startswith("-") else None)
    document.save(path)


def write_cover_letter_docx(path: Path, body: str) -> None:
    document = Document()
    for block in body.split("\n\n"):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if len(lines) == 1:
            document.add_paragraph(lines[0])
        else:
            document.add_paragraph(lines[0])
            for line in lines[1:]:
                document.add_paragraph(line)
    document.save(path)


def detect_incompatible_cover_letter_template(document: Document) -> str | None:
    for paragraph in iter_document_paragraphs(document):
        content = normalize_space(paragraph.text).lower()
        if not content:
            continue
        if contains_resume_section_heading(content) or contains_contact_details(content):
            continue
        for term in INCOMPATIBLE_COVER_TEMPLATE_TERMS:
            if term in content:
                return f"Standard cover-letter formatting was used because the uploaded template contained incompatible role-specific content: {term}."
    return None


def validate_cover_letter_document(document: Document, job: dict[str, Any], profile: dict[str, str]) -> str | None:
    profile_name = normalize_space(text(profile.get("name") or ""))
    date_count = 0
    greeting_count = 0
    closing_count = 0
    signoff_count = 0
    signature_count = 0
    stale_terms = [
        "centralsquare",
        "centralsquare technologies",
        "software developer co-op",
        "remote - ontario",
        "8- or 12-month term",
        "8/12-month",
        "8 or 12 month",
        "hiring manager",
        "central square's technology initiatives",
        "postgraduate student",
        "grounded wording",
        "saved profile",
        "hochitterry.mak@georgebrown.ca",
        "ats-oriented language",
        "truthful, relevant detail",
    ]
    paragraphs = list(iter_document_paragraphs(document))
    body_paragraphs = list(document.paragraphs)
    body_markers = ["dear ", "i'm excited", "thank you", "sincerely", "i would welcome", "role at", "experience", "documentation"]

    stale_hit = find_cover_letter_stale_hit(document, stale_terms)
    if stale_hit is not None:
        return f"Stale template content remained after replacement: {stale_hit}"

    for index, paragraph in enumerate(body_paragraphs):
        content = normalize_space(paragraph.text)
        lower = content.lower()
        if not content:
            continue
        if _looks_like_date_text(lower):
            date_count += 1
        if lower.startswith("dear "):
            greeting_count += 1
        if lower.startswith(("thank you", "i would welcome", "i look forward", "i appreciate")):
            closing_count += 1
        if lower.startswith(("sincerely,", "best regards,", "regards,", "kind regards,", "with appreciation,")):
            signoff_count += 1
        if profile_name and lower == profile_name.lower() and index >= max(0, len(body_paragraphs) - 3):
            signature_count += 1

    if date_count > 1:
        return "Duplicate date lines remained after replacement."
    if greeting_count > 1:
        return "Duplicate greetings remained after replacement."
    if closing_count > 1:
        return "Duplicate closings remained after replacement."
    if signoff_count > 1:
        return "Duplicate closings remained after replacement."
    if signature_count > 1:
        return "Duplicate signature lines remained after replacement."

    for section in document.sections:
        for paragraph in iter_container_paragraphs(section.header):
            content = normalize_space(paragraph.text)
            lower = content.lower()
            if not content or contains_contact_details(content):
                continue
            if len(content.split()) >= 10 and any(marker in lower for marker in body_markers):
                return "Body text leaked into the header."
    return None


def find_cover_letter_stale_hit(document: Document, stale_terms: list[str]) -> str | None:
    visible_locations = []
    for index, paragraph in enumerate(document.paragraphs):
        content = normalize_space(paragraph.text)
        lower = content.lower()
        if not content:
            continue
        for term in stale_terms:
            if term in lower:
                visible_locations.append(f"body paragraph {index + 1}")
                return f"{term} in {visible_locations[-1]}"

    for section_index, section in enumerate(document.sections, start=1):
        for paragraph_index, paragraph in enumerate(section.header.paragraphs, start=1):
            content = normalize_space(paragraph.text).lower()
            if not content:
                continue
            for term in stale_terms:
                if term in content:
                    return f"{term} in header section {section_index} paragraph {paragraph_index}"
        for paragraph_index, paragraph in enumerate(section.footer.paragraphs, start=1):
            content = normalize_space(paragraph.text).lower()
            if not content:
                continue
            for term in stale_terms:
                if term in content:
                    return f"{term} in footer section {section_index} paragraph {paragraph_index}"

    package = getattr(getattr(document, "part", None), "package", None)
    parts = getattr(package, "parts", []) if package is not None else []
    for part in parts:
        partname = str(getattr(part, "partname", ""))
        if not partname.endswith(".xml"):
            continue
        blob = getattr(part, "blob", b"")
        if not blob:
            continue
        try:
            text = blob.decode("utf-8", errors="ignore").lower()
        except Exception:
            continue
        for term in stale_terms:
            idx = text.find(term)
            if idx == -1:
                continue
            if "docprops" in partname.lower():
                location = f"metadata part {partname.lstrip('/')}"
            elif "customxml" in partname.lower():
                location = f"custom XML part {partname}"
            elif "header" in partname.lower():
                location = f"header XML part {partname}"
            elif "footer" in partname.lower():
                location = f"footer XML part {partname}"
            elif "document.xml" in partname.lower():
                snippet = text[max(0, idx - 120) : idx + 120]
                if "txbxcontent" in snippet or "textbox" in snippet or "shape" in snippet:
                    location = f"text box or shape content in {partname}"
                else:
                    location = f"XML part {partname}"
            else:
                location = f"XML part {partname}"
            return f"{term} in {location.lstrip('/')}"
    return None


def _cover_letter_stale_visible_text(content: str) -> bool:
    lower = normalize_space(content).lower()
    if not lower:
        return False
    stale_terms = [
        "centralsquare",
        "centralsquare technologies",
        "software developer co-op",
        "remote - ontario",
        "remote, ontario",
        "8- or 12-month term",
        "8/12-month",
        "8 or 12 month",
        "hiring manager",
        "central square's technology initiatives",
        "hochitterry.mak@georgebrown.ca",
    ]
    return any(term in lower for term in stale_terms)


def safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    return (cleaned or "document")[:160]


def download_shortlist_document(job_id: int, kind: str) -> Response:
    row = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
    if row is None:
        return jsonify({"error": "Job not found"}), 404
    job = job_to_dict(row)
    status_field = "resume_generation_status" if kind == "resume" else "cover_letter_generation_status"
    if str(job.get(status_field, "")).startswith("Outdated"):
        return jsonify({"error": "Outdated — regenerate using current profile"}), 409
    field = "resume_docx_path" if kind == "resume" else "cover_letter_docx_path"
    path = safe_generated_path(job.get(field))
    if path is None or not path.exists():
        return jsonify({"error": "Generated document is unavailable"}), 404
    return send_file(
        path,
        as_attachment=True,
        download_name=secure_filename(path.name) or "document.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def safe_generated_path(value: Any) -> Path | None:
    raw = text(value)
    if not raw:
        return None
    root = generated_applications_dir().resolve()
    path = Path(raw).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def safe_preparation_artifact_path(value: Any) -> Path | None:
    raw = text(value)
    if not raw:
        return None
    path = Path(raw).resolve()
    roots = [generated_applications_dir().resolve(), (DATA_DIR / "application_preparations").resolve()]
    if any(path == root or root in path.parents for root in roots):
        return path
    return None


def dedupe_keys(job: dict[str, Any], source_job_id: Any = "") -> set[str]:
    keys = set()
    for field in ["url", "application_url"]:
        canonical = canonical_url(text(job.get(field)))
        if canonical:
            keys.add(f"url:{canonical}")
    composite = "|".join(
        [
            normalize_dedupe_text(job.get("company")),
            normalize_dedupe_text(job.get("title")),
            normalize_dedupe_text(job.get("location")),
        ]
    )
    if composite.replace("|", ""):
        keys.add(f"ctl:{composite}")
    source_id = normalize_dedupe_text(source_job_id)
    source = normalize_dedupe_text(job.get("source"))
    if source_id:
        keys.add(f"source:{source}:{source_id}")
    return keys


def canonical_url(value: str) -> str:
    if not value:
        return ""
    lowered = value.strip().lower()
    lowered = re.sub(r"#.*$", "", lowered)
    lowered = re.sub(r"[?&](utm_[^=&]+|source|ref)=[^&]+", "", lowered)
    lowered = lowered.rstrip("?&/")
    return lowered


def normalize_dedupe_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text(value).lower()).strip()


def determine_salary(job: dict[str, Any]) -> dict[str, Any]:
    structured = structured_salary(job)
    if structured["salary_source"] != "missing":
        return structured

    salary_text = text(job.get("salary_text") or job.get("salary"))
    if salary_text and not looks_like_estimate(salary_text):
        parsed = parse_salary_text(salary_text)
        if parsed["salary_source"] != "missing":
            parsed["salary_source"] = "jobspy_text"
            parsed["salary_confidence"] = max(parsed["salary_confidence"], 82)
            return parsed

    parsed_description = parse_salary_text(text(job.get("job_description")))
    if parsed_description["salary_source"] != "missing":
        parsed_description["salary_source"] = "description"
        parsed_description["salary_confidence"] = max(parsed_description["salary_confidence"], 72)
        return parsed_description

    estimate = estimate_market_salary(job)
    return estimate


def structured_salary(job: dict[str, Any]) -> dict[str, Any]:
    minimum = money_number(job.get("salary_min") or job.get("min_amount"))
    maximum = money_number(job.get("salary_max") or job.get("max_amount"))
    interval = normalize_salary_interval(text(job.get("salary_interval") or job.get("interval")))
    currency = normalize_currency(text(job.get("salary_currency") or job.get("currency")))
    if minimum is None and maximum is None:
        return missing_salary()
    if maximum is None:
        maximum = minimum
    if minimum is None:
        minimum = maximum
    annual_min, annual_max = annualize_salary(minimum or 0, maximum or 0, interval)
    original = salary_range_label(minimum or 0, maximum or 0, interval, currency)
    return {
        "salary_min": int(annual_min),
        "salary_max": int(annual_max),
        "salary_interval": interval or "yearly",
        "salary_currency": currency,
        "salary_text": original,
        "salary_source": "structured",
        "salary_confidence": 95,
    }


def parse_salary_text(value: str) -> dict[str, Any]:
    content = normalize_space(value)
    if not content:
        return missing_salary()
    ranges = split_salary_contexts(content)
    best = missing_salary()
    for context in ranges:
        if false_salary_context(context):
            continue
        currency = normalize_currency(context)
        interval = infer_salary_interval(context)
        numbers = salary_numbers(context)
        if not numbers:
            continue
        minimum = numbers[0]
        maximum = numbers[1] if len(numbers) > 1 else numbers[0]
        if "up to" in context.lower() and len(numbers) == 1:
            minimum = 0
        if "from" in context.lower() and len(numbers) == 1:
            maximum = numbers[0]
        if not plausible_base_salary(minimum, maximum, interval):
            continue
        annual_min, annual_max = annualize_salary(minimum, maximum, interval)
        best = {
            "salary_min": int(annual_min),
            "salary_max": int(annual_max),
            "salary_interval": interval,
            "salary_currency": currency,
            "salary_text": context.strip(" .;"),
            "salary_source": "description",
            "salary_confidence": 70,
        }
        break
    return best


def split_salary_contexts(content: str) -> list[str]:
    contexts = []
    salary_words = r"(salary|compensation|pay|wage|range|from|up to|cad|\$)"
    for match in re.finditer(salary_words, content, re.I):
        start = max(0, match.start() - 35)
        end = min(len(content), match.end() + 130)
        contexts.append(content[start:end])
    return contexts or [content[:180]]


def salary_numbers(context: str) -> list[float]:
    pattern = r"(?:CAD\s*)?\$?\s*(\d{2,3}k|\d{2,3}(?:,\d{3})?|\d{2,3})(?:\s*(?:-|to|–|—)\s*(?:CAD\s*)?\$?\s*(\d{2,3}k|\d{2,3}(?:,\d{3})?|\d{2,3}))?"
    match = re.search(pattern, context, re.I)
    if not match:
        return []
    numbers = [money_number(part) for part in match.groups() if part]
    return [number for number in numbers if number is not None]


def money_number(value: Any) -> float | None:
    raw = text(value).lower().replace("$", "").replace(",", "").replace("cad", "").strip()
    if not raw:
        return None
    multiplier = 1000 if raw.endswith("k") else 1
    raw = raw.rstrip("k")
    try:
        return float(raw) * multiplier
    except ValueError:
        return None


def infer_salary_interval(context: str) -> str:
    lowered = context.lower()
    if any(term in lowered for term in ["hour", "/hr", "hourly", "/hour"]):
        return "hourly"
    if "week" in lowered:
        return "weekly"
    if "month" in lowered:
        return "monthly"
    if "contract" in lowered or "day rate" in lowered:
        return "contract"
    return "yearly"


def normalize_salary_interval(value: str) -> str:
    lowered = value.lower()
    if any(term in lowered for term in ["hour", "hr"]):
        return "hourly"
    if "week" in lowered:
        return "weekly"
    if "month" in lowered:
        return "monthly"
    if "contract" in lowered:
        return "contract"
    return "yearly" if lowered or not value else ""


def normalize_currency(value: str) -> str:
    lowered = value.lower()
    if "usd" in lowered:
        return "USD"
    return "CAD"


def annualize_salary(minimum: float, maximum: float, interval: str) -> tuple[float, float]:
    multiplier = {
        "hourly": 40 * 52,
        "weekly": 52,
        "monthly": 12,
        "contract": 1,
        "yearly": 1,
    }.get(interval or "yearly", 1)
    return minimum * multiplier, maximum * multiplier


def plausible_base_salary(minimum: float, maximum: float, interval: str) -> bool:
    high = max(minimum, maximum)
    if interval == "hourly":
        return 15 <= high <= 250
    if interval == "weekly":
        return 400 <= high <= 7000
    if interval == "monthly":
        return 1500 <= high <= 30000
    return 25000 <= high <= 350000


def false_salary_context(context: str) -> bool:
    lowered = context.lower()
    blocked = ["bonus", "signing", "benefit", "allowance", "expense", "revenue", "budget", "equity", "stock", "rrsp", "401k"]
    return any(term in lowered for term in blocked) and not any(term in lowered for term in ["salary", "compensation range", "pay range"])


def looks_like_estimate(value: str) -> bool:
    return "estimated market range" in value.lower()


def estimate_market_salary(job: dict[str, Any]) -> dict[str, Any]:
    role = text(job.get("role_type")) or guess_role_type(f"{text(job.get('title'))} {text(job.get('job_description'))}")
    seniority = text(job.get("seniority_level")).lower()
    location = text(job.get("location")).lower()
    base_ranges = {
        "software developer": (65000, 90000),
        "full-stack developer": (70000, 95000),
        "cloud support": (55000, 76000),
        "technical support engineer": (58000, 80000),
        "implementation specialist": (56000, 78000),
        "analyst": (55000, 76000),
        "intern": (42000, 55000),
        "new grad": (55000, 70000),
        "other": (52000, 72000),
    }
    minimum, maximum = base_ranges.get(role, base_ranges["other"])
    if any(term in seniority for term in ["senior", "lead", "principal"]):
        minimum += 25000
        maximum += 40000
    if any(term in seniority for term in ["intern", "junior", "new grad"]):
        minimum -= 8000
        maximum -= 10000
    if any(term in location for term in ["toronto", "gta", "vancouver"]):
        minimum += 5000
        maximum += 7000
    minimum = max(35000, minimum)
    maximum = max(minimum + 8000, maximum)
    return {
        "salary_min": int(minimum),
        "salary_max": int(maximum),
        "salary_interval": "yearly",
        "salary_currency": "CAD",
        "salary_text": f"Estimated market range: CAD ${minimum:,}-${maximum:,} per year",
        "salary_source": "estimated",
        "salary_confidence": 38,
    }


def missing_salary() -> dict[str, Any]:
    return {
        "salary_min": 0,
        "salary_max": 0,
        "salary_interval": "",
        "salary_currency": "CAD",
        "salary_text": "",
        "salary_source": "missing",
        "salary_confidence": 0,
    }


def salary_range_label(minimum: float, maximum: float, interval: str, currency: str) -> str:
    left = f"{currency} ${int(minimum):,}"
    right = f"{currency} ${int(maximum):,}"
    cadence = {
        "hourly": "an hour",
        "weekly": "per week",
        "monthly": "per month",
        "contract": "contract",
        "yearly": "per year",
    }.get(interval or "yearly", "per year")
    return f"{left}-{right} {cadence}" if minimum != maximum else f"{left} {cadence}"


DISCOVERY_CITY_COORDS = {
    "toronto": (43.6532, -79.3832),
    "mississauga": (43.589, -79.6441),
    "brampton": (43.7315, -79.7624),
    "markham": (43.8561, -79.337),
    "scarborough": (43.7764, -79.2318),
    "north york": (43.7615, -79.4111),
    "gta": (43.6532, -79.3832),
    "hamilton": (43.2557, -79.8711),
    "oakville": (43.4675, -79.6877),
    "burlington": (43.3255, -79.799),
    "waterloo": (43.4643, -80.5204),
    "kitchener": (43.4516, -80.4925),
    "london": (42.9849, -81.2453),
    "ottawa": (45.4215, -75.6972),
    "montreal": (45.5017, -73.5673),
    "quebec city": (46.8139, -71.208),
    "winnipeg": (49.8951, -97.1384),
    "calgary": (51.0447, -114.0719),
    "edmonton": (53.5461, -113.4938),
    "vancouver": (49.2827, -123.1207),
    "victoria": (48.4284, -123.3656),
    "halifax": (44.6488, -63.5752),
    "remote": (0.0, 0.0),
}


def discovery_search_signature(payload: dict[str, Any]) -> str:
    search = discovery_search_config(payload)
    relevant = {
        "keywords": search["keywords"],
        "location": search["location"],
        "distance": search["distance"],
        "enabled_sources": search["enabled_sources"],
        "remote_preference": search["remote_preference"],
        "search_depth": search["search_depth"],
        "date_window": search["date_window"],
        "per_source_cap": search["per_source_cap"],
        "total_cap": search["total_cap"],
    }
    return grounding_hash(dumps_json(relevant, sort_keys=True))


def load_discovery_preferences(search_key: str) -> dict[str, Any]:
    if not search_key:
        return {}
    row = query_db("SELECT preferences_json FROM discovery_preferences WHERE search_key = ?", [search_key], one=True)
    if row is None:
        return {}
    return parse_json_object(text(row["preferences_json"]))


def save_discovery_preferences(search_key: str, preferences: dict[str, Any]) -> None:
    if not search_key:
        return
    get_db().execute(
        """
        INSERT INTO discovery_preferences (search_key, preferences_json, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(search_key) DO UPDATE SET preferences_json = excluded.preferences_json, updated_at = CURRENT_TIMESTAMP
        """,
        [search_key, dumps_json(preferences, sort_keys=True)],
    )
    get_db().commit()


def discovery_search_defaults(depth: str = "standard") -> dict[str, Any]:
    preset = DISCOVERY_SEARCH_DEPTHS.get(depth, DISCOVERY_SEARCH_DEPTHS["standard"])
    return {
        "search_depth": depth if depth in DISCOVERY_SEARCH_DEPTHS else "standard",
        "date_window": f"{preset['days']}d" if preset["days"] else "any",
        "per_source_cap": preset["per_source_cap"],
        "total_cap": preset["total_cap"],
        "remote_preference": "",
        "distance": 50,
    }


def discovery_search_config(payload: dict[str, Any]) -> dict[str, Any]:
    depth = normalize_choice(payload.get("search_depth"), set(DISCOVERY_SEARCH_DEPTHS)) or "standard"
    preset = DISCOVERY_SEARCH_DEPTHS[depth]
    date_window = normalize_choice(payload.get("date_window"), set(DISCOVERY_DATE_WINDOWS)) or f"{preset['days']}d"
    per_source_cap = clamp_int_default(payload.get("per_source_cap"), preset["per_source_cap"], 1, 1000)
    total_cap = clamp_int_default(payload.get("total_cap"), preset["total_cap"], 1, 5000)
    distance = clamp_int_default(payload.get("distance"), 50, 0, 1000)
    if total_cap < per_source_cap:
        total_cap = max(total_cap, per_source_cap)
    return {
        "search_depth": depth,
        "date_window": date_window,
        "hours_old": None if date_window == "any" else DISCOVERY_DATE_WINDOWS.get(date_window, preset["days"]) * 24,
        "per_source_cap": per_source_cap,
        "total_cap": total_cap,
        "remote_preference": normalize_choice(payload.get("remote_preference"), {"remote", "hybrid", "on-site"}),
        "keywords": text(payload.get("keywords")),
        "location": text(payload.get("location")),
        "distance": distance,
        "enabled_sources": normalize_discovery_sources(payload.get("enabled_sources")),
    }


def save_discovery_search_run(search_key: str, search_json: dict[str, Any], metadata_json: dict[str, Any], raw_jobs: list[dict[str, Any]]) -> None:
    if not search_key:
        return
    get_db().execute(
        """
        INSERT INTO discovery_search_runs (search_key, search_json, metadata_json, raw_jobs_json, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(search_key) DO UPDATE SET
            search_json = excluded.search_json,
            metadata_json = excluded.metadata_json,
            raw_jobs_json = excluded.raw_jobs_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        [search_key, dumps_json(search_json, sort_keys=True), dumps_json(metadata_json, sort_keys=True), dumps_json(raw_jobs, sort_keys=True)],
    )
    get_db().commit()


def load_discovery_search_run(search_key: str) -> dict[str, Any]:
    if not search_key:
        return {}
    row = query_db("SELECT * FROM discovery_search_runs WHERE search_key = ?", [search_key], one=True)
    if row is None:
        return {}
    raw_jobs = parse_json_array(row["raw_jobs_json"])
    return {
        "search_key": search_key,
        "search": parse_json_object(row["search_json"]),
        "metadata": parse_json_object(row["metadata_json"]),
        "jobs": raw_jobs,
        "cache_hit": True,
        "cache_created_at": text(row["created_at"]),
        "cache_updated_at": text(row["updated_at"]),
        "cached_raw_result_count": len(raw_jobs),
    }


def save_discovery_debug_run(search_key: str, request_json: dict[str, Any], metadata_json: dict[str, Any], source_snapshot_json: dict[str, Any]) -> None:
    if not search_key:
        return
    get_db().execute(
        """
        INSERT INTO discovery_debug_runs (search_key, request_json, metadata_json, source_snapshot_json, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(search_key) DO UPDATE SET
            request_json = excluded.request_json,
            metadata_json = excluded.metadata_json,
            source_snapshot_json = excluded.source_snapshot_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        [search_key, dumps_json(request_json, sort_keys=True), dumps_json(metadata_json, sort_keys=True), dumps_json(source_snapshot_json, sort_keys=True)],
    )
    get_db().commit()


def load_latest_discovery_debug_run() -> dict[str, Any]:
    row = query_db("SELECT * FROM discovery_debug_runs ORDER BY updated_at DESC, id DESC LIMIT 1", one=True)
    if row is None:
        return {}
    return {
        "search_key": text(row["search_key"]),
        "request": parse_json_object(row["request_json"]),
        "metadata": parse_json_object(row["metadata_json"]),
        "source_snapshots": parse_json_object(row["source_snapshot_json"]),
        "created_at": text(row["updated_at"]),
    }


def normalize_canadian_postal_code(value: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9]", "", normalize_space(value)).upper()
    if len(compact) != 6:
        return ""
    candidate = f"{compact[:3]} {compact[3:]}"
    return candidate if CANADIAN_POSTAL_CODE_RE.match(candidate) else ""


def extract_canadian_postal_code(value: str) -> str:
    match = CANADIAN_POSTAL_CODE_EXTRACT_RE.search(normalize_space(value).upper())
    return normalize_canadian_postal_code(match.group(1)) if match else ""


def infer_province_from_text(value: str) -> str:
    lowered = normalize_space(value).lower()
    for key, province in PROVINCE_LOOKUP.items():
        if re.search(rf"\b{re.escape(key)}\b", lowered):
            return province
    return ""


def classify_location_input(value: str) -> str:
    raw = normalize_space(value)
    if not raw:
        return "empty"
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    postal = extract_canadian_postal_code(raw)
    if postal:
        compact = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
        if compact == postal.replace(" ", ""):
            return "postal_code"
        return "street_address"
    lowered = raw.lower()
    if len(parts) >= 2 and province_code_from_text(parts[-1]):
        return "city_region"
    if infer_province_from_text(raw) and len(parts) == 1:
        return "province"
    if "," in raw or " " in raw:
        if any(token in lowered for token in ["st ", "street", "ave", "avenue", "rd ", "road", "blvd", "drive", "dr ", "suite", "unit"]):
            return "street_address"
    return "city"


def build_location_lookup_candidates(raw_value: str, profile: dict[str, str] | None = None) -> list[dict[str, Any]]:
    raw = normalize_space(raw_value)
    if not raw:
        return []
    province = infer_province_from_text(raw) or infer_province_from_text(text((profile or {}).get("preferred_locations"))) or "Ontario"
    province_code = province_code_from_text(raw) or province_code_from_text(text((profile or {}).get("preferred_locations")))
    if not province_code:
        province_code = PROVINCE_CODE_BY_NAME.get(province.lower(), "ON")
    postal = extract_canadian_postal_code(raw)
    kind = classify_location_input(raw)
    candidates: list[dict[str, Any]] = []
    if postal:
        normalized_postal = normalize_canadian_postal_code(postal)
        if kind == "street_address":
            candidates.append(
                {
                    "query": f"{raw}, Canada",
                    "normalized_query": raw,
                    "precision": "street address",
                    "confidence": 90,
                    "used_postal_fallback": False,
                }
            )
            candidates.append(
                {
                    "query": f"{normalized_postal}, Canada",
                    "normalized_query": f"{normalized_postal}, Canada",
                    "precision": "postal code",
                    "confidence": 95,
                    "used_postal_fallback": True,
                }
            )
        else:
            candidates.append(
                {
                    "query": f"{normalized_postal}, Canada",
                    "normalized_query": f"{normalized_postal}, Canada",
                    "precision": "postal code",
                    "confidence": 95,
                    "used_postal_fallback": False,
                }
            )
    elif kind == "city_region":
        city = normalize_space(raw.split(",")[0].strip())
        province_name = province
        candidates.append(
            {
                "query": f"{city}, {province_name}, Canada",
                "normalized_query": f"{city}, {province_code}",
                "precision": "city",
                "confidence": 82,
                "used_postal_fallback": False,
            }
        )
    elif kind == "province":
        candidates.append(
            {
                "query": f"{province}, Canada",
                "normalized_query": f"{province}, Canada",
                "precision": "approximate",
                "confidence": 45,
                "used_postal_fallback": False,
            }
        )
    elif raw.lower() == "toronto":
        candidates.append(
            {
                "query": "Toronto, Ontario, Canada",
                "normalized_query": "Toronto, ON",
                "precision": "city",
                "confidence": 75,
                "used_postal_fallback": False,
            }
        )
    else:
        city = raw.split(",")[0].strip()
        if city and city.lower() == "toronto":
            city = "Toronto"
        normalized_query = f"{city}, {province_code}" if city and province_code and "," in raw else f"{raw}, Canada" if "," not in raw else f"{raw}"
        if city and city.lower() == "toronto" and "ontario" not in raw.lower():
            normalized_query = "Toronto, ON"
            candidates.append(
                {
                    "query": "Toronto, Ontario, Canada",
                    "normalized_query": normalized_query,
                    "precision": "city",
                    "confidence": 75,
                    "used_postal_fallback": False,
                }
            )
        else:
            candidates.append(
                {
                    "query": f"{raw}, Canada" if "," not in raw else f"{raw}",
                    "normalized_query": normalized_query,
                    "precision": "approximate",
                    "confidence": 60,
                    "used_postal_fallback": False,
                }
            )
        if raw.lower() != normalized_query.lower():
            candidates.append(
                {
                    "query": f"{province}, Canada" if kind == "province" else f"{raw.split(',')[0].strip()}, Canada",
                    "normalized_query": f"{province}, Canada" if kind == "province" else f"{raw.split(',')[0].strip()}, Canada",
                    "precision": "approximate" if kind != "city" else "city",
                    "confidence": 55 if kind != "city" else 70,
                    "used_postal_fallback": False,
                }
            )
    return candidates


def geocoding_cache_key(lookup_type: str, query_text: str, normalized_query: str) -> str:
    payload = {"lookup_type": lookup_type, "query_text": normalize_space(query_text).lower(), "normalized_query": normalize_space(normalized_query).lower()}
    return grounding_hash(dumps_json(payload, sort_keys=True))


def load_geocoding_cache(cache_key: str) -> dict[str, Any] | None:
    if not cache_key:
        return None
    if not has_app_context():
        return None
    row = query_db("SELECT * FROM geocoding_cache WHERE cache_key = ?", [cache_key], one=True)
    if row is None:
        return None
    success = bool(int(row["success"] or 0))
    updated_at = text(row["updated_at"])
    if not success and updated_at:
        try:
            age = (datetime.now() - datetime.fromisoformat(updated_at)).total_seconds()
            if age >= GEOCODING_FAILURE_CACHE_SECONDS:
                return None
        except ValueError:
            return None
    return {
        "cache_key": cache_key,
        "lookup_type": text(row["lookup_type"]),
        "query_text": text(row["query_text"]),
        "normalized_query": text(row["normalized_query"]),
        "provider": text(row["provider"]),
        "success": success,
        "updated_at": updated_at,
        "result": parse_json_object(row["result_json"]),
    }


def save_geocoding_cache(cache_key: str, lookup_type: str, query_text: str, normalized_query: str, provider: str, result: dict[str, Any], success: bool) -> None:
    if not cache_key:
        return
    if not has_app_context():
        return
    get_db().execute(
        """
        INSERT INTO geocoding_cache (cache_key, lookup_type, query_text, normalized_query, provider, result_json, success, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(cache_key) DO UPDATE SET
            lookup_type = excluded.lookup_type,
            query_text = excluded.query_text,
            normalized_query = excluded.normalized_query,
            provider = excluded.provider,
            result_json = excluded.result_json,
            success = excluded.success,
            updated_at = CURRENT_TIMESTAMP
        """,
        [cache_key, lookup_type, query_text, normalized_query, provider, dumps_json(result, sort_keys=True), 1 if success else 0],
    )
    get_db().commit()


class GeocodingProvider:
    name = "base"

    def geocode(self, query: str, *, country: str = "Canada") -> dict[str, Any]:
        raise NotImplementedError


class NominatimGeocodingProvider(GeocodingProvider):
    name = "nominatim"

    def geocode(self, query: str, *, country: str = "Canada") -> dict[str, Any]:
        params = {"format": "jsonv2", "limit": 5, "q": query}
        if country.lower() == "canada":
            params["countrycodes"] = "ca"
        url = f"https://nominatim.openstreetmap.org/search?{urlencode(params)}"
        request_obj = urllib.request.Request(url, headers={"User-Agent": "Job Tracker/1.0 (local geocoding)"})
        with urllib.request.urlopen(request_obj, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list) or not payload:
            raise ValueError("No geocoding match found")
        match = payload[0]
        return {
            "latitude": float(match.get("lat")),
            "longitude": float(match.get("lon")),
            "display_name": text(match.get("display_name")),
            "raw": match,
        }


class DisabledGeocodingProvider(GeocodingProvider):
    name = "disabled"

    def geocode(self, query: str, *, country: str = "Canada") -> dict[str, Any]:
        raise RuntimeError("Geocoding is disabled by configuration")


def get_geocoding_provider() -> GeocodingProvider:
    if text(os.environ.get("JOB_TRACKER_GEOCODING_PROVIDER")).lower() in {"none", "disabled", "off"}:
        return DisabledGeocodingProvider()
    return NominatimGeocodingProvider()


def geocode_location_value(
    raw_value: str,
    *,
    lookup_type: str,
    profile: dict[str, str] | None = None,
    provider: GeocodingProvider | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    profile = profile or {}
    provider = provider or get_geocoding_provider()
    raw = normalize_space(raw_value)
    if not raw:
        return {
            "ok": False,
            "status": "missing",
            "original_input": "",
            "normalized_query": "",
            "latitude": "",
            "longitude": "",
            "provider": provider.name,
            "confidence": 0,
            "precision": "",
            "geocoded_at": "",
            "error": "",
            "used_fallback": False,
            "cached": False,
        }

    candidates = build_location_lookup_candidates(raw, profile)
    if not candidates:
        return {
            "ok": False,
            "status": "missing",
            "original_input": raw,
            "normalized_query": "",
            "latitude": "",
            "longitude": "",
            "provider": provider.name,
            "confidence": 0,
            "precision": "",
            "geocoded_at": "",
            "error": "No location candidate could be constructed.",
            "used_fallback": False,
            "cached": False,
        }

    errors: list[str] = []
    for candidate in candidates:
        cache_key = geocoding_cache_key(lookup_type, candidate["query"], candidate["normalized_query"])
        cached = load_geocoding_cache(cache_key) if use_cache else None
        if cached is not None:
            cached_result = dict(cached["result"])
            cached_result.update(
                {
                    "ok": cached["success"],
                    "status": "cached" if cached["success"] else text(cached_result.get("status") or "failed"),
                    "original_input": raw,
                    "normalized_query": text(cached_result.get("normalized_query") or candidate["normalized_query"]),
                    "provider": text(cached_result.get("provider") or cached["provider"] or provider.name),
                    "cached": True,
                }
            )
            if cached_result.get("ok"):
                return cached_result
            errors.append(text(cached_result.get("error")) or "Cached geocoding failure.")
            if cached_result.get("status") == "rate_limited":
                break
            continue
        try:
            lookup = provider.geocode(candidate["query"], country="Canada")
            latitude = lookup.get("latitude")
            longitude = lookup.get("longitude")
            if latitude in [None, ""] or longitude in [None, ""]:
                raise ValueError("No geocoding coordinates returned.")
            result = {
                "ok": True,
                "status": "saved",
                "original_input": raw,
                "normalized_query": candidate["normalized_query"],
                "latitude": float(latitude),
                "longitude": float(longitude),
                "provider": provider.name,
                "confidence": int(candidate["confidence"]),
                "precision": candidate["precision"],
                "geocoded_at": datetime.now().isoformat(timespec="seconds"),
                "error": "",
                "used_fallback": bool(candidate["used_postal_fallback"]),
                "display_name": text(lookup.get("display_name")),
                "cached": False,
            }
            if use_cache:
                save_geocoding_cache(cache_key, lookup_type, candidate["query"], candidate["normalized_query"], provider.name, result, True)
            return result
        except urllib.error.HTTPError as exc:
            rate_limited = exc.code == 429
            error_message = "The location service is temporarily rate limited." if rate_limited else f"HTTP {exc.code}: geocoding unavailable."
            failure = {
                "ok": False, "status": "rate_limited" if rate_limited else "failed", "original_input": raw,
                "normalized_query": candidate["normalized_query"], "latitude": "", "longitude": "",
                "provider": provider.name, "confidence": 0, "precision": candidate["precision"],
                "geocoded_at": datetime.now().isoformat(timespec="seconds"), "error": error_message,
                "used_fallback": bool(candidate["used_postal_fallback"]), "cached": False,
            }
            if use_cache:
                save_geocoding_cache(cache_key, lookup_type, candidate["query"], candidate["normalized_query"], provider.name, failure, False)
            errors.append(error_message)
            if rate_limited:
                break
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"
            failure = {
                "ok": False,
                "status": "failed",
                "original_input": raw,
                "normalized_query": candidate["normalized_query"],
                "latitude": "",
                "longitude": "",
                "provider": provider.name,
                "confidence": 0,
                "precision": candidate["precision"],
                "geocoded_at": datetime.now().isoformat(timespec="seconds"),
                "error": error_message,
                "used_fallback": bool(candidate["used_postal_fallback"]),
                "cached": False,
            }
            if use_cache:
                save_geocoding_cache(cache_key, lookup_type, candidate["query"], candidate["normalized_query"], provider.name, failure, False)
            errors.append(error_message)
    return {
        "ok": False,
        "status": "rate_limited" if any("rate limited" in error.lower() for error in errors) else "failed",
        "original_input": raw,
        "normalized_query": candidates[-1]["normalized_query"],
        "latitude": "",
        "longitude": "",
        "provider": provider.name,
        "confidence": 0,
        "precision": candidates[-1]["precision"],
        "geocoded_at": datetime.now().isoformat(timespec="seconds"),
        "error": "The location service is temporarily rate limited." if any("rate limited" in error.lower() for error in errors) else ("Location enrichment is unavailable; distance remains unknown." if errors else "Location could not be geocoded."),
        "used_fallback": bool(candidates[-1]["used_postal_fallback"]),
        "cached": False,
    }


def geocode_discovery_job(
    job: dict[str, Any],
    profile: dict[str, str],
    origin: dict[str, Any],
    provider: GeocodingProvider | None = None,
    use_cache: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    provider = provider or get_geocoding_provider()
    raw_location = text(job.get("location"))
    geocode = geocode_location_value(raw_location, lookup_type="job", profile=profile, provider=provider, use_cache=use_cache)
    job["location_original"] = raw_location
    job["normalized_location"] = text(geocode.get("normalized_query")) or raw_location
    job["location_provider"] = text(geocode.get("provider"))
    job["location_confidence"] = clamp_int(geocode.get("confidence"), 0, 100)
    job["location_precision"] = text(geocode.get("precision"))
    job["location_geocoded_at"] = text(geocode.get("geocoded_at"))
    job["location_geocoding_error"] = text(geocode.get("error"))
    job["location_cached"] = bool(geocode.get("cached"))
    job["location_geocode_status"] = text(geocode.get("status"))
    job["location_latitude"] = geocode.get("latitude")
    job["location_longitude"] = geocode.get("longitude")
    distance = location_distance_snapshot(origin, raw_location, text(job.get("remote_type")), "remote_after_local", geocode)
    job["distance_km"] = distance["distance_km"]
    job["distance_confidence"] = distance["confidence"]
    job["distance_label"] = distance["distance_label"]
    job["distance_note"] = distance.get("distance_note", "")
    job["distance_origin_label"] = distance.get("origin_label", "")
    job["distance_cached"] = bool(geocode.get("cached"))
    return job, geocode


def profile_home_location(profile: dict[str, str]) -> dict[str, Any]:
    normalized = text(profile.get("home_location_normalized")) or text(profile.get("location"))
    lat = profile.get("home_location_latitude")
    lon = profile.get("home_location_longitude")
    status = text(profile.get("home_location_status"))
    return {
        "input": text(profile.get("home_location_original") or profile.get("location")),
        "normalized": normalized,
        "latitude": float(lat) if text(lat) else None,
        "longitude": float(lon) if text(lon) else None,
        "provider": text(profile.get("home_location_provider")),
        "confidence": clamp_int(profile.get("home_location_confidence"), 0, 100),
        "precision": text(profile.get("home_location_precision")),
        "geocoded_at": text(profile.get("home_location_geocoded_at")),
        "status": status or ("saved" if normalized else "missing"),
        "error": text(profile.get("home_location_error")),
    }


def discovery_origin_available(profile: dict[str, str]) -> bool:
    origin = profile_home_location(profile)
    return origin["latitude"] is not None and origin["longitude"] is not None and origin["status"] in {"saved", "cached"}


def looks_like_invalid_postal_code(raw_value: str) -> bool:
    raw = normalize_space(raw_value)
    compact = re.sub(r"[^A-Za-z0-9]", "", raw)
    if len(compact) > 7 or len(compact) < 5:
        return False
    if not any(char.isalpha() for char in compact) or not any(char.isdigit() for char in compact):
        return False
    return extract_canadian_postal_code(raw) == ""


def geocode_profile_home_location(profile: dict[str, str], provider: GeocodingProvider | None = None) -> tuple[dict[str, str], dict[str, Any]]:
    raw = text(profile.get("location"))
    if raw and looks_like_invalid_postal_code(raw):
        raise ValueError("Invalid Canadian postal code. Use a format like M5V 2T6.")

    if not raw:
        profile.update(
            {
                "home_location_original": "",
                "home_location_normalized": "",
                "home_location_query": "",
                "home_location_latitude": "",
                "home_location_longitude": "",
                "home_location_provider": "",
                "home_location_confidence": "",
                "home_location_precision": "",
                "home_location_geocoded_at": "",
                "home_location_status": "missing",
                "home_location_error": "",
            }
        )
        return profile, {
            "ok": False,
            "status": "missing",
            "message": "Location not configured.",
            "display": "",
        }

    result = geocode_location_value(raw, lookup_type="profile", profile=profile, provider=provider)
    profile.update(
        {
            "home_location_original": raw,
            "home_location_normalized": text(result.get("normalized_query")),
            "home_location_query": text(result.get("normalized_query")),
            "home_location_latitude": text(result.get("latitude")),
            "home_location_longitude": text(result.get("longitude")),
            "home_location_provider": text(result.get("provider")),
            "home_location_confidence": str(clamp_int(result.get("confidence"), 0, 100)) if result.get("ok") else "",
            "home_location_precision": text(result.get("precision")),
            "home_location_geocoded_at": text(result.get("geocoded_at")),
            "home_location_status": text(result.get("status")),
            "home_location_error": text(result.get("error")),
        }
    )
    display = text(result.get("normalized_query")) or raw
    message = (
        f"Location saved: {display} — {text(result.get('precision')) or 'unknown'}"
        + (f", {text(result.get('status'))}." if text(result.get("status")) else ".")
    )
    return profile, {"ok": bool(result.get("ok")), "status": text(result.get("status")), "message": message, "display": display, "precision": text(result.get("precision")), "result": result}


def province_code_from_text(value: str) -> str:
    lowered = normalize_space(value).lower()
    if not lowered:
        return ""
    for key, province in sorted(PROVINCE_LOOKUP.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", lowered):
            return PROVINCE_CODE_BY_NAME.get(province.lower(), key.upper())
    return ""


def normalize_discovery_city_region(display_name: str, fallback: str = "") -> str:
    raw = normalize_space(display_name) or normalize_space(fallback)
    if not raw:
        return ""
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    province_code = ""
    for part in reversed(parts):
        code = province_code_from_text(part)
        if code:
            province_code = code
            break
    city = ""
    if province_code:
        for part in parts:
            if province_code_from_text(part):
                break
            if part.lower() == "canada" or extract_canadian_postal_code(part):
                continue
            city = part
        city = normalize_space(city or fallback)
    else:
        city = normalize_space(parts[0] if parts else fallback)
    if city and province_code:
        return f"{city}, {province_code}"
    return city or raw


def resolve_discovery_location_context(
    raw_location: str,
    profile: dict[str, str] | None = None,
    provider: GeocodingProvider | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    profile = profile or {}
    provider = provider or get_geocoding_provider()
    original_input = text(raw_location)
    normalized_input = normalize_space(original_input)
    postal = extract_canadian_postal_code(original_input)
    normalized_postal = normalize_canadian_postal_code(postal) if postal else ""
    distance_origin = normalized_postal or normalized_input
    lookup_input = normalized_postal or normalized_input
    lookup_result: dict[str, Any]
    postal_fallback_location = ""
    if postal:
        profile_location = text(profile.get("home_location_normalized"))
        if profile_location:
            postal_fallback_location = normalize_discovery_city_region(profile_location, fallback=profile_location)
        elif normalized_postal.startswith("M"):
            postal_fallback_location = "Toronto, ON"
    if lookup_input:
        lookup_result = geocode_location_value(lookup_input, lookup_type="search", profile=profile, provider=provider, use_cache=use_cache)
    else:
        lookup_result = {
            "ok": False,
            "status": "missing",
            "normalized_query": "",
            "latitude": "",
            "longitude": "",
            "provider": provider.name,
            "confidence": 0,
            "precision": "",
            "geocoded_at": "",
            "error": "",
            "cached": False,
        }
    discovery_location = ""
    resolution_method = "raw"
    if lookup_result.get("ok"):
        if postal:
            if postal_fallback_location:
                discovery_location = postal_fallback_location
                resolution_method = "profile_city_fallback" if text(profile.get("home_location_normalized")) else "postal_code_prefix_fallback"
            else:
                discovery_location = normalize_discovery_city_region(
                    text(lookup_result.get("display_name")) or text(lookup_result.get("normalized_query")),
                    fallback=normalized_input,
                )
                resolution_method = "postal_code_to_city_region"
        elif province_code_from_text(normalized_input.split(",")[-1] if normalized_input else ""):
            discovery_location = normalize_discovery_city_region(normalized_input, fallback=normalized_input)
            resolution_method = "normalized_city_region"
        else:
            discovery_location = normalize_discovery_city_region(
                text(lookup_result.get("display_name")) or text(lookup_result.get("normalized_query")),
                fallback=normalized_input,
            )
            resolution_method = "geocoded_city_region" if discovery_location != normalized_input else "normalized_city_region"
    elif postal:
        if postal_fallback_location:
            discovery_location = postal_fallback_location
            resolution_method = "profile_city_fallback" if text(profile.get("home_location_normalized")) else "postal_code_prefix_fallback"
        else:
            raise ValueError("Could not resolve the postal code to a discovery city or region.")
    else:
        discovery_location = normalized_input
        resolution_method = "normalized_city_region" if normalized_input else "raw"
    return {
        "original_input": original_input,
        "normalized_input": normalized_postal or normalized_input,
        "distance_origin": distance_origin,
        "discovery_location": discovery_location,
        "resolution_method": resolution_method,
        "lookup": lookup_result,
    }


def discovery_city_coordinates(location: str) -> tuple[float, float] | None:
    lowered = normalize_space(location).lower()
    if not lowered:
        return None
    for key, coords in DISCOVERY_CITY_COORDS.items():
        if key != "remote" and key in lowered:
            return coords
    return None


def location_distance_snapshot(
    origin: dict[str, Any] | None,
    job_location: str,
    remote_type: str = "",
    remote_rule: str = "remote_after_local",
    job_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    origin = origin or {}
    job_record = job_record or {}
    job_loc = normalize_space(job_location)
    remote = normalize_space(remote_type).lower()
    if "remote" in remote or "remote" in job_loc.lower():
        if remote_rule == "remote_zero":
            return {"distance_km": 0, "confidence": 95, "distance_label": "remote", "distance_note": "Remote", "origin_label": text(origin.get("normalized"))}
        if remote_rule == "remote_first":
            return {"distance_km": -1, "confidence": 95, "distance_label": "remote", "distance_note": "Remote", "origin_label": text(origin.get("normalized"))}
        return {"distance_km": 9999, "confidence": 95, "distance_label": "remote", "distance_note": "Remote", "origin_label": text(origin.get("normalized"))}
    if not origin.get("latitude") or not origin.get("longitude"):
        return {"distance_km": 9999, "confidence": 0, "distance_label": "unknown", "distance_note": "Distance unavailable", "origin_label": text(origin.get("normalized"))}
    job_lat = job_record.get("latitude")
    job_lon = job_record.get("longitude")
    if job_lat in [None, ""] or job_lon in [None, ""]:
        return {"distance_km": 9999, "confidence": 0, "distance_label": "unknown", "distance_note": "Distance unavailable", "origin_label": text(origin.get("normalized"))}
    job_precision = text(job_record.get("precision"))
    origin_precision = text(origin.get("precision"))
    if job_precision in {"province", "unknown"}:
        return {"distance_km": 9999, "confidence": 20, "distance_label": "unknown", "distance_note": "Distance unavailable", "origin_label": text(origin.get("normalized"))}
    if origin_precision in {"province", "unknown"}:
        return {"distance_km": 9999, "confidence": 20, "distance_label": "unknown", "distance_note": "Distance unavailable", "origin_label": text(origin.get("normalized"))}
    try:
        distance_km = haversine_distance_km((float(origin["latitude"]), float(origin["longitude"])), (float(job_lat), float(job_lon)))
    except Exception:
        return {"distance_km": 9999, "confidence": 0, "distance_label": "unknown", "distance_note": "Distance unavailable", "origin_label": text(origin.get("normalized"))}
    confidence = min(clamp_int(origin.get("confidence"), 0, 100), clamp_int(job_record.get("confidence"), 0, 100))
    if "city" in {origin_precision, job_precision}:
        confidence = min(confidence or 75, 78)
    if "street address" in {origin_precision, job_precision} or "postal code" in {origin_precision, job_precision}:
        confidence = max(confidence, 85)
    distance_label = "approximate"
    origin_label = text(origin.get("normalized")) or text(origin.get("input"))
    distance_note = f"Approx. distance from {origin_label or 'saved origin'}"
    if origin_precision == "city" and origin_label:
        distance_note = f"Approx. distance from {origin_label} city centre"
    return {"distance_km": distance_km, "confidence": confidence or 70, "distance_label": distance_label, "distance_note": distance_note, "origin_label": origin_label}


def haversine_distance_km(origin: tuple[float, float], destination: tuple[float, float]) -> int:
    from math import asin, cos, radians, sin, sqrt

    lat1, lon1 = origin
    lat2, lon2 = destination
    if (lat1, lon1) == (0.0, 0.0) or (lat2, lon2) == (0.0, 0.0):
        return 0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return int(round(6371 * 2 * asin(min(1, sqrt(a)))))


def approximate_distance_from_home(job_location: str, home_location: str, remote_type: str = "", remote_rule: str = "remote_after_local") -> dict[str, Any]:
    job_loc = normalize_space(job_location)
    home_loc = normalize_space(home_location)
    remote = normalize_space(remote_type).lower()
    if "remote" in remote or "remote" in job_loc.lower():
        if remote_rule == "remote_zero":
            return {"distance_km": 0, "confidence": 95, "distance_label": "remote"}
        if remote_rule == "remote_first":
            return {"distance_km": -1, "confidence": 95, "distance_label": "remote"}
        return {"distance_km": 9999, "confidence": 95, "distance_label": "remote"}
    if not job_loc or not home_loc:
        return {"distance_km": 9999, "confidence": 0, "distance_label": "unknown"}
    if job_loc.lower() == home_loc.lower():
        return {"distance_km": 0, "confidence": 100, "distance_label": "local"}
    job_coords = discovery_city_coordinates(job_loc)
    home_coords = discovery_city_coordinates(home_loc)
    if job_coords and home_coords:
        return {"distance_km": haversine_distance_km(home_coords, job_coords), "confidence": 88, "distance_label": "approximate"}
    home_tokens = set(re.findall(r"[a-z0-9]+", home_loc.lower()))
    job_tokens = set(re.findall(r"[a-z0-9]+", job_loc.lower()))
    overlap = len(home_tokens & job_tokens)
    if overlap:
        return {"distance_km": 0, "confidence": 70, "distance_label": "approximate"}
    return {"distance_km": 9999, "confidence": 25, "distance_label": "unknown"}


def normalize_salary_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    salary_min = clamp_int(job.get("salary_min"), 0, 1_000_000)
    salary_max = clamp_int(job.get("salary_max"), 0, 1_000_000)
    salary_midpoint = clamp_int(job.get("salary_midpoint"), 0, 1_000_000)
    if not salary_midpoint and (salary_min or salary_max):
        salary_midpoint = int(round((salary_min + salary_max) / 2))
    return {
        "salary_original_text": text(job.get("salary_original_text") or job.get("salary") or job.get("salary_text")),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_midpoint": salary_midpoint,
        "salary_interval": text(job.get("salary_interval")),
        "salary_currency": text(job.get("salary_currency")) or "CAD",
        "salary_source": text(job.get("salary_source")) or "missing",
        "salary_confidence": clamp_int(job.get("salary_confidence"), 0, 100),
        "salary_listed": bool(text(job.get("salary_source")) and text(job.get("salary_source")) != "estimated" and text(job.get("salary_source")) != "missing"),
    }


def discovery_salary_score(job: dict[str, Any], profile: dict[str, str]) -> int:
    salary_min = clamp_int(job.get("salary_min"), 0, 1_000_000)
    salary_max = clamp_int(job.get("salary_max"), 0, 1_000_000)
    source = text(job.get("salary_source"))
    confidence = clamp_int(job.get("salary_confidence"), 0, 100)
    if not salary_max:
        return 45 if text(job.get("salary")) else 38
    target = desired_min_salary(profile)
    midpoint = clamp_int(job.get("salary_midpoint"), 0, 1_000_000) or int(round((salary_min + salary_max) / 2))
    score = 50
    if midpoint >= target:
        score += 22
    if salary_min >= target:
        score += 10
    if salary_max >= target + 15000:
        score += 8
    if source == "estimated":
        score -= 10
    if confidence < 60:
        score -= 6
    return clamp_int(score, 0, 100)


def discovery_recency_score(job: dict[str, Any]) -> int:
    posted = text(job.get("posted_date"))
    if not posted:
        return 42
    try:
        days = max(0, (date.today() - parse_date(posted)).days)
    except Exception:
        return 42
    if days <= 1:
        return 100
    if days <= 3:
        return 92
    if days <= 7:
        return 84
    if days <= 14:
        return 72
    if days <= 30:
        return 58
    return 35


def discovery_source_quality_score(job: dict[str, Any]) -> int:
    source = text(job.get("source")).lower()
    score = {
        "linkedin": 90,
        "indeed": 82,
        "google": 76,
        "zip_recruiter": 74,
    }.get(source, 65)
    if text(job.get("job_description")):
        score += 6
    if text(job.get("application_url")) and text(job.get("application_url")) != text(job.get("url")):
        score += 4
    if text(job.get("posted_date")):
        score += 2
    return clamp_int(score, 0, 100)


def discovery_completion_score(job: dict[str, Any]) -> tuple[int, list[str]]:
    missing = []
    score = 100
    if not text(job.get("location")):
        score -= 12
        missing.append("location")
    if not text(job.get("salary")):
        score -= 8
        missing.append("salary")
    if not text(job.get("posted_date")):
        score -= 8
        missing.append("posted date")
    if not text(job.get("job_description")):
        score -= 6
        missing.append("description")
    return clamp_int(score, 0, 100), missing


def discovery_distance_score(distance_km: int, remote_type: str, remote_rule: str = "remote_after_local") -> int:
    remote = normalize_space(remote_type).lower()
    if "remote" in remote:
        return 100 if remote_rule == "remote_zero" else (92 if remote_rule == "remote_first" else 72)
    if distance_km <= 5:
        return 100
    if distance_km <= 25:
        return 90
    if distance_km <= 50:
        return 82
    if distance_km <= 100:
        return 72
    if distance_km <= 250:
        return 58
    if distance_km >= 9999:
        return 24
    return 48


def discovery_work_arrangement_label(remote_type: str) -> str:
    lowered = normalize_space(remote_type).lower()
    if "remote" in lowered:
        return "Remote"
    if "hybrid" in lowered:
        return "Hybrid"
    if "on-site" in lowered or "onsite" in lowered:
        return "On-site"
    return "Unknown"


def discovery_score_breakdown(job: dict[str, Any], profile: dict[str, str], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or {}
    weights = {**DISCOVERY_SCORE_WEIGHTS, **parse_json_object(settings.get("weights"))}
    semantic = analyze_resume_match(job, profile, cache_dir=semantic_cache_dir(), use_semantic=False)
    skill_match = clamp_int(max(
        semantic.get("scores", {}).get("required_skills", 0),
        semantic.get("scores", {}).get("preferred_skills", 0),
        len(keyword_hits(" ".join([text(job.get("title")), text(job.get("job_description")), text(job.get("required_skills")), text(job.get("preferred_skills"))]).lower(), REWARD_KEYWORDS)) * 7,
    ), 0, 100)
    role_fit = clamp_int(max(semantic.get("scores", {}).get("role_title", 0), 40 + len(keyword_hits(text(job.get("title")), ROLE_KEYWORDS)) * 8), 0, 100)
    seniority_fit = clamp_int(score_seniority_fit(profile, analyze_job_seniority(job)).get("score", 0), 0, 100)
    salary_snapshot = normalize_salary_snapshot(job)
    salary_score = discovery_salary_score({**job, **salary_snapshot}, profile)
    origin = profile_home_location(profile)
    distance_rule = normalize_choice(settings.get("remote_rule") or settings.get("remote_distance_rule"), DISCOVERY_REMOTE_DISTANCE_RULES) or "remote_after_local"
    job_location_record = {
        "latitude": job.get("location_latitude"),
        "longitude": job.get("location_longitude"),
        "confidence": job.get("location_confidence"),
        "precision": text(job.get("location_precision")),
        "normalized": text(job.get("normalized_location")) or text(job.get("location")),
        "input": text(job.get("location")),
    }
    distance_snapshot = location_distance_snapshot(origin, text(job.get("location")), text(job.get("remote_type")), distance_rule, job_location_record)
    distance_score = discovery_distance_score(distance_snapshot["distance_km"], text(job.get("remote_type")), distance_rule)
    unknown_location_penalty = 4 if distance_snapshot["distance_km"] >= 9999 and not "remote" in text(job.get("remote_type")).lower() else 0
    recency_score = discovery_recency_score(job)
    source_score = discovery_source_quality_score(job)
    data_quality_score, missing_fields = discovery_completion_score(job)
    penalty_terms = keyword_hits(" ".join([text(job.get("title")), text(job.get("job_description")), text(job.get("responsibilities"))]).lower(), PENALTY_KEYWORDS)
    excluded_penalty = len(penalty_terms) * 6
    missing_penalty = len(missing_fields) * 4
    total = round(
        skill_match * (weights["skill_match"] / 100)
        + role_fit * (weights["role_fit"] / 100)
        + seniority_fit * (weights["seniority_fit"] / 100)
        + salary_score * (weights["salary"] / 100)
        + max(distance_score, 0) * (weights["distance_work_arrangement"] / 100)
        + recency_score * (weights["recency"] / 100)
        + source_score * (weights["source_quality"] / 100)
        - excluded_penalty
        - missing_penalty
        - unknown_location_penalty
    )
    components = [
        {"label": "Skill match", "score": round(skill_match * weights["skill_match"] / 100), "max": weights["skill_match"]},
        {"label": "Role fit", "score": round(role_fit * weights["role_fit"] / 100), "max": weights["role_fit"]},
        {"label": "Seniority fit", "score": round(seniority_fit * weights["seniority_fit"] / 100), "max": weights["seniority_fit"]},
        {"label": "Salary", "score": round(salary_score * weights["salary"] / 100), "max": weights["salary"]},
        {"label": "Distance/work arrangement", "score": round(distance_score * weights["distance_work_arrangement"] / 100), "max": weights["distance_work_arrangement"]},
        {"label": "Recency", "score": round(recency_score * weights["recency"] / 100), "max": weights["recency"]},
        {"label": "Data quality", "score": round(source_score * weights["source_quality"] / 100), "max": weights["source_quality"]},
    ]
    penalties = []
    if missing_fields:
        penalties.append({"label": "Missing data", "items": missing_fields, "points": missing_penalty})
    if penalty_terms:
        penalties.append({"label": "Excluded keywords", "items": penalty_terms, "points": excluded_penalty})
    if unknown_location_penalty:
        penalties.append({"label": "Unknown location", "items": ["location unknown"], "points": 4})
    return {
        "overall_score": clamp_int(total, 0, 100),
        "components": components,
        "penalties": penalties,
        "weights": weights,
        "salary": salary_snapshot,
        "distance": distance_snapshot,
        "recency": {"posted_date": text(job.get("posted_date")), "score": recency_score},
        "source_quality": source_score,
        "data_quality": data_quality_score,
        "skill_match": skill_match,
        "role_fit": role_fit,
        "seniority_fit": seniority_fit,
        "salary_score": salary_score,
        "distance_score": distance_score,
        "recency_score": recency_score,
        "source_score": source_score,
        "missing_fields": missing_fields,
        "excluded_keywords": penalty_terms,
        "remote_rule": distance_rule,
        "semantic_model": semantic.get("model", "keyword-fallback"),
        "semantic_model_available": semantic.get("model_available", False),
        "semantic_scores": semantic.get("scores", {}),
    }


def enrich_discovery_job(job: dict[str, Any], profile: dict[str, str], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    salary_snapshot = normalize_salary_snapshot(job)
    scoring = discovery_score_breakdown({**job, **salary_snapshot}, profile, settings)
    remote_label = discovery_work_arrangement_label(text(job.get("remote_type")))
    enriched = {
        **job,
        **salary_snapshot,
        "distance_km": scoring["distance"]["distance_km"],
        "distance_confidence": scoring["distance"]["confidence"],
        "distance_label": scoring["distance"]["distance_label"],
        "overall_score": scoring["overall_score"],
        "match_score": scoring["skill_match"],
        "score_breakdown": {
            "overall_score": scoring["overall_score"],
            "weights": scoring["weights"],
            "components": scoring["components"],
            "penalties": scoring["penalties"],
            "salary": scoring["salary"],
            "distance": scoring["distance"],
            "recency": scoring["recency"],
            "source_quality": scoring["source_quality"],
            "data_quality": scoring["data_quality"],
            "skill_match": scoring["skill_match"],
            "role_fit": scoring["role_fit"],
            "seniority_fit": scoring["seniority_fit"],
            "salary_score": scoring["salary_score"],
            "distance_score": scoring["distance_score"],
            "recency_score": scoring["recency_score"],
            "source_score": scoring["source_score"],
            "missing_fields": scoring["missing_fields"],
            "excluded_keywords": scoring["excluded_keywords"],
            "remote_rule": scoring["remote_rule"],
            "semantic_model": scoring["semantic_model"],
            "semantic_model_available": scoring["semantic_model_available"],
            "semantic_scores": scoring["semantic_scores"],
        },
        "work_arrangement": remote_label,
        "posted_date_sort": text(job.get("posted_date")) or "9999-12-31",
        "distance_sort": scoring["distance"]["distance_km"],
    }
    if "salary_listed" not in enriched:
        enriched["salary_listed"] = int(salary_snapshot["salary_listed"])
    return enriched


def discovery_sort_value(job: dict[str, Any], field: str, direction: str = "desc", remote_rule: str = "remote_after_local", unknown_salary_position: str = "last") -> tuple[Any, ...]:
    field = normalize_space(field or "overall_score")
    direction = "asc" if str(direction).lower() == "asc" else "desc"
    salary_known = 1 if int(job.get("salary_listed") or 0) else 0
    salary_value = clamp_int(job.get("salary_midpoint") or job.get("salary_max") or job.get("salary_min"), 0, 1_000_000)
    distance_value = clamp_int(job.get("distance_km"), 0, 9999)
    remote_label = discovery_work_arrangement_label(text(job.get("remote_type")))
    if field == "salary":
        missing_marker = 1 if not salary_known else 0
        if direction == "desc":
            return (missing_marker, -salary_value, normalize_space(text(job.get("company"))).lower(), normalize_space(text(job.get("title"))).lower())
        if missing_marker:
            return ((-1 if unknown_salary_position == "first" else 1), 0, normalize_space(text(job.get("company"))).lower(), normalize_space(text(job.get("title"))).lower())
        return (0, salary_value, normalize_space(text(job.get("company"))).lower(), normalize_space(text(job.get("title"))).lower())
    if field == "distance":
        if remote_label == "Remote":
            if remote_rule == "remote_first":
                distance_value = -1
            elif remote_rule == "remote_zero":
                distance_value = 0
            else:
                distance_value = 9999
        unknown_location = 1 if distance_value >= 9999 and remote_label != "Remote" else 0
        location_conf = clamp_int(job.get("distance_confidence"), 0, 100)
        return (
            unknown_location,
            distance_value if direction == "asc" else -distance_value,
            -location_conf,
            normalize_space(text(job.get("company"))).lower(),
            normalize_space(text(job.get("title"))).lower(),
        )
    if field == "posted_date":
        posted = text(job.get("posted_date")) or "9999-12-31"
        return (posted if direction == "asc" else "".join(chr(255 - ord(ch)) for ch in posted), normalize_space(text(job.get("company"))).lower(), normalize_space(text(job.get("title"))).lower())
    if field == "company":
        return (normalize_space(text(job.get("company"))).lower(), normalize_space(text(job.get("title"))).lower())
    if field == "title":
        return (normalize_space(text(job.get("title"))).lower(), normalize_space(text(job.get("company"))).lower())
    if field == "source":
        return (normalize_space(text(job.get("source"))).lower(), normalize_space(text(job.get("company"))).lower())
    if field == "work_arrangement":
        order = {"Remote": 0, "Hybrid": 1, "On-site": 2, "Unknown": 3}
        return (order.get(remote_label, 3), normalize_space(text(job.get("company"))).lower())
    if field == "seniority":
        return (normalize_space(text(job.get("seniority_level"))).lower(), normalize_space(text(job.get("company"))).lower())
    if field in {"match_score", "overall_score", "score"}:
        score_value = clamp_int(job.get("match_score") if field == "match_score" else job.get("overall_score"), 0, 100)
        return ((-score_value if direction == "desc" else score_value), normalize_space(text(job.get("company"))).lower(), normalize_space(text(job.get("title"))).lower())
    if field == "deadline":
        deadline = text(job.get("deadline")) or "9999-12-31"
        return (deadline if direction == "asc" else "".join(chr(255 - ord(ch)) for ch in deadline), normalize_space(text(job.get("company"))).lower())
    return ((-clamp_int(job.get("overall_score"), 0, 100) if direction == "desc" else clamp_int(job.get("overall_score"), 0, 100)), normalize_space(text(job.get("company"))).lower(), normalize_space(text(job.get("title"))).lower())


def sort_discovery_jobs(
    jobs: list[dict[str, Any]],
    sort_field: str,
    sort_direction: str = "desc",
    secondary_field: str = "",
    secondary_direction: str = "asc",
    remote_rule: str = "remote_after_local",
    unknown_salary_position: str = "last",
) -> list[dict[str, Any]]:
    primary = normalize_space(sort_field or "overall_score")
    secondary = normalize_space(secondary_field)
    primary_direction = "asc" if str(sort_direction).lower() == "asc" else "desc"
    secondary_direction = "asc" if str(secondary_direction).lower() == "asc" else "desc"
    ordered = list(jobs)
    if secondary:
        ordered.sort(key=lambda job: discovery_sort_value(job, secondary, secondary_direction, remote_rule, unknown_salary_position))
    ordered.sort(key=lambda job: discovery_sort_value(job, primary, primary_direction, remote_rule, unknown_salary_position))
    return ordered


def discovery_preferences_payload(payload: dict[str, Any]) -> dict[str, Any]:
    def as_bool(value: Any) -> bool:
        return text(value).lower() in {"1", "true", "yes", "on", "allowed"}

    sort_payload = parse_json_object(payload.get("sort")) if isinstance(payload.get("sort"), dict) else parse_json_object(payload.get("sort"))
    secondary_payload = parse_json_object(payload.get("secondary_sort")) if isinstance(payload.get("secondary_sort"), dict) else parse_json_object(payload.get("secondary_sort"))
    filters_payload = parse_json_object(payload.get("filters")) if isinstance(payload.get("filters"), dict) else parse_json_object(payload.get("filters"))
    weights_payload = parse_json_object(payload.get("weights")) if isinstance(payload.get("weights"), dict) else parse_json_object(payload.get("weights"))
    preferences = {
        "sort": {
            "field": normalize_space(text(sort_payload.get("field") or payload.get("sort_field") or payload.get("primary_sort_field") or "overall_score")),
            "direction": "asc" if text(sort_payload.get("direction") or payload.get("sort_direction") or payload.get("primary_sort_direction")).lower() == "asc" else "desc",
            "secondary_field": normalize_space(text(secondary_payload.get("field") or payload.get("secondary_sort_field") or "")),
            "secondary_direction": "asc" if text(secondary_payload.get("direction") or payload.get("secondary_sort_direction") or "asc").lower() == "asc" else "desc",
            "unknown_salary_position": normalize_choice(
                sort_payload.get("unknown_salary_position") or payload.get("unknown_salary_position"),
                {"first", "last"},
            )
            or "last",
            "remote_rule": normalize_choice(
                sort_payload.get("remote_rule") or payload.get("remote_rule") or payload.get("remote_distance_rule"),
                DISCOVERY_REMOTE_DISTANCE_RULES,
            )
            or "remote_after_local",
        },
        "filters": {
            "salary_min": clamp_int_default(filters_payload.get("salary_min") or payload.get("salary_min"), 0, 0, 1_000_000),
            "max_distance": clamp_int_default(filters_payload.get("max_distance") or payload.get("max_distance"), 0, 0, 10_000),
            "overall_score_min": clamp_int_default(filters_payload.get("overall_score_min") or payload.get("overall_score_min"), 0, 0, 100),
            "posted_within": clamp_int_default(filters_payload.get("posted_within") or payload.get("posted_within"), 0, 0, 3650),
            "remote_type": normalize_space(text(filters_payload.get("remote_type") or payload.get("remote_type") or "")),
            "source": normalize_space(text(filters_payload.get("source") or payload.get("source") or "")),
            "job_field": normalize_space(text(filters_payload.get("job_field") or payload.get("job_field") or "")),
            "seniority": normalize_space(text(filters_payload.get("seniority") or payload.get("seniority") or "")),
            "known_salary_only": as_bool(filters_payload.get("known_salary_only") if "known_salary_only" in filters_payload else payload.get("known_salary_only")),
            "known_location_only": as_bool(filters_payload.get("known_location_only") if "known_location_only" in filters_payload else payload.get("known_location_only")),
            "exact_date_only": as_bool(filters_payload.get("exact_date_only") if "exact_date_only" in filters_payload else payload.get("exact_date_only")),
            "company": normalize_space(text(filters_payload.get("company") or payload.get("company") or "")),
            "title_keywords": normalize_space(text(filters_payload.get("title_keywords") or payload.get("title_keywords") or "")),
        },
        "weights": {
            key: clamp_int_default(weights_payload.get(key) or payload.get(key), default, 0, 100)
            for key, default in DISCOVERY_SCORE_WEIGHTS.items()
        },
    }
    return preferences


def apply_discovery_filters(job: dict[str, Any], filters: dict[str, Any]) -> bool:
    filters = filters or {}
    if clamp_int_default(filters.get("salary_min"), 0, 0, 1_000_000) and clamp_int(job.get("salary_max"), 0, 1_000_000) < clamp_int_default(filters.get("salary_min"), 0, 0, 1_000_000):
        return False
    if clamp_int_default(filters.get("max_distance"), 0, 0, 10_000) and clamp_int(job.get("distance_km"), 0, 9999) > clamp_int_default(filters.get("max_distance"), 0, 0, 10_000):
        return False
    if clamp_int_default(filters.get("overall_score_min"), 0, 0, 100) and clamp_int(job.get("overall_score"), 0, 100) < clamp_int_default(filters.get("overall_score_min"), 0, 0, 100):
        return False
    if text(filters.get("posted_within")):
        posted = text(job.get("posted_date"))
        if not posted:
            return False
        try:
            days = (date.today() - parse_date(posted)).days
        except Exception:
            days = 9999
        if days > clamp_int_default(filters.get("posted_within"), 9999, 0, 3650):
            return False
    remote_filter = normalize_space(text(filters.get("remote_type") or filters.get("remote") or filters.get("work_arrangement"))).lower()
    if remote_filter and remote_filter != "any":
        job_remote = text(job.get("remote_type")).lower()
        job_arrangement = text(job.get("work_arrangement")).lower()
        if remote_filter not in job_remote and remote_filter not in job_arrangement:
            return False
    source = normalize_space(text(filters.get("source")))
    if source and source.lower() != "any" and source.lower() != text(job.get("source")).lower():
        return False
    job_field = normalize_space(text(filters.get("job_field"))).lower()
    if job_field and job_field != "any":
        content = " ".join([text(job.get("title")), text(job.get("job_description")), text(job.get("required_skills")), text(job.get("preferred_skills"))]).lower()
        if job_field not in content:
            return False
    seniority = normalize_space(text(filters.get("seniority"))).lower()
    if seniority and seniority != "any" and seniority not in text(job.get("seniority_level")).lower():
        return False
    if filters.get("known_salary_only") and not int(job.get("salary_listed") or 0):
        return False
    if filters.get("known_location_only") and not text(job.get("location")):
        return False
    if filters.get("exact_date_only") and not text(job.get("posted_date")):
        return False
    company = normalize_space(text(filters.get("company"))).lower()
    if company and company not in text(job.get("company")).lower():
        return False
    title_keywords = normalize_space(text(filters.get("title_keywords"))).lower()
    if title_keywords and title_keywords not in text(job.get("title")).lower():
        return False
    return True


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        DATA_DIR.mkdir(exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def init_db() -> None:
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    ensure_columns("jobs", JOB_COLUMNS)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    ensure_columns("profile", PROFILE_COLUMNS)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS evidence_library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    ensure_columns("evidence_library", EVIDENCE_COLUMNS)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    ensure_columns("resume_variants", RESUME_VARIANT_COLUMNS)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS generated_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            content TEXT NOT NULL,
            profile_hash TEXT NOT NULL DEFAULT '',
            job_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'current',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
        """
    )
    ensure_columns(
        "generated_versions",
        {
            "profile_hash": "TEXT NOT NULL DEFAULT ''",
            "job_hash": "TEXT NOT NULL DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT 'current'",
        },
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS discovery_preferences (
            search_key TEXT PRIMARY KEY,
            preferences_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    ensure_columns(
        "discovery_preferences",
        {
            "preferences_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS discovery_search_runs (
            search_key TEXT PRIMARY KEY,
            search_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            raw_jobs_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    ensure_columns(
        "discovery_search_runs",
        {
            "search_json": "TEXT NOT NULL DEFAULT '{}'",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            "raw_jobs_json": "TEXT NOT NULL DEFAULT '[]'",
        },
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS discovery_debug_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_key TEXT NOT NULL DEFAULT '',
            request_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            source_snapshot_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    ensure_columns(
        "discovery_debug_runs",
        {
            "request_json": "TEXT NOT NULL DEFAULT '{}'",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            "source_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS discovery_debug_runs_search_key_idx
        ON discovery_debug_runs(search_key)
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_search_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            keywords TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            remote_preference TEXT NOT NULL DEFAULT '',
            seniority TEXT NOT NULL DEFAULT '',
            minimum_salary INTEGER NOT NULL DEFAULT 0,
            enabled_sources_json TEXT NOT NULL DEFAULT '["linkedin", "indeed"]',
            date_window TEXT NOT NULL DEFAULT '14d',
            distance INTEGER NOT NULL DEFAULT 50,
            interval_minutes INTEGER NOT NULL DEFAULT 360,
            enabled INTEGER NOT NULL DEFAULT 0,
            last_run_at TEXT NOT NULL DEFAULT '',
            next_run_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS discovery_run_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_id INTEGER,
            trigger TEXT NOT NULL DEFAULT 'manual',
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ended_at TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'running',
            fetched_count INTEGER NOT NULL DEFAULT 0,
            new_count INTEGER NOT NULL DEFAULT 0,
            duplicate_count INTEGER NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0,
            source_outcomes_json TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(search_id) REFERENCES saved_search_profiles(id) ON DELETE SET NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS discovery_worker_leases (
            name TEXT PRIMARY KEY,
            owner TEXT NOT NULL DEFAULT '',
            acquired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS discovery_search_leases (
            search_id INTEGER PRIMARY KEY,
            owner TEXT NOT NULL DEFAULT '',
            acquired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(search_id) REFERENCES saved_search_profiles(id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    ensure_columns(
        "saved_search_profiles",
        {
            "seniority": "TEXT NOT NULL DEFAULT ''",
            "minimum_salary": "INTEGER NOT NULL DEFAULT 0",
            "enabled_sources_json": "TEXT NOT NULL DEFAULT '[\"linkedin\", \"indeed\"]'",
            "date_window": "TEXT NOT NULL DEFAULT '14d'",
            "distance": "INTEGER NOT NULL DEFAULT 50",
            "interval_minutes": "INTEGER NOT NULL DEFAULT 360",
            "enabled": "INTEGER NOT NULL DEFAULT 0",
            "last_run_at": "TEXT NOT NULL DEFAULT ''",
            "next_run_at": "TEXT NOT NULL DEFAULT ''",
            "auto_prepare_enabled": "INTEGER NOT NULL DEFAULT 0",
            "auto_prepare_min_priority": "INTEGER NOT NULL DEFAULT 75",
            "auto_prepare_require_canadian": "INTEGER NOT NULL DEFAULT 1",
            "auto_prepare_candidate_profile_id": "INTEGER NOT NULL DEFAULT 0",
            "auto_prepare_resume_id": "INTEGER NOT NULL DEFAULT 0",
            "auto_prepare_cover_letter_template_id": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS application_preparation_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'queued',
            review_status TEXT NOT NULL DEFAULT 'pending',
            eligibility_review_status TEXT NOT NULL DEFAULT 'not_required',
            candidate_profile_id INTEGER NOT NULL DEFAULT 0,
            resume_id INTEGER NOT NULL DEFAULT 0,
            cover_letter_template_id INTEGER NOT NULL DEFAULT 0,
            job_priority INTEGER NOT NULL DEFAULT 0,
            keywords_score_json TEXT NOT NULL DEFAULT '{}',
            resume_status TEXT NOT NULL DEFAULT 'pending',
            cover_letter_status TEXT NOT NULL DEFAULT 'pending',
            resume_error TEXT NOT NULL DEFAULT '',
            cover_letter_error TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            eligibility_note TEXT NOT NULL DEFAULT '',
            lease_owner TEXT NOT NULL DEFAULT '',
            lease_expires_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            prepared_at TEXT NOT NULL DEFAULT '',
            prepared_resume_path TEXT NOT NULL DEFAULT '',
            prepared_cover_letter_path TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
        """
    )
    ensure_columns(
        "application_preparation_queue",
        {
            "eligibility_review_status": "TEXT NOT NULL DEFAULT 'not_required'",
            "prepared_resume_path": "TEXT NOT NULL DEFAULT ''",
            "prepared_cover_letter_path": "TEXT NOT NULL DEFAULT ''",
        },
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS geocoding_cache (
            cache_key TEXT PRIMARY KEY,
            lookup_type TEXT NOT NULL DEFAULT '',
            query_text TEXT NOT NULL DEFAULT '',
            normalized_query TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT '',
            result_json TEXT NOT NULL DEFAULT '{}',
            success INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    ensure_columns(
        "geocoding_cache",
        {
            "lookup_type": "TEXT NOT NULL DEFAULT ''",
            "query_text": "TEXT NOT NULL DEFAULT ''",
            "normalized_query": "TEXT NOT NULL DEFAULT ''",
            "provider": "TEXT NOT NULL DEFAULT ''",
            "result_json": "TEXT NOT NULL DEFAULT '{}'",
            "success": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    run_migrations(db)
    db.execute(f"PRAGMA user_version = {CURRENT_DB_SCHEMA_VERSION}")
    db.commit()


def ensure_columns(table: str, columns: dict[str, str]) -> None:
    db = get_db()
    existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
    for name, definition in columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def query_db(query: str, args: list[Any] | None = None, one: bool = False) -> Any:
    cursor = get_db().execute(query, args or [])
    rows = cursor.fetchall()
    cursor.close()
    return (rows[0] if rows else None) if one else rows


def json_value_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return text(value)


def dumps_json(value: Any, **kwargs: Any) -> str:
    kwargs.setdefault("default", json_value_default)
    return json.dumps(value, **kwargs)


def normalize_profile_payload(payload: dict[str, Any], existing: dict[str, str] | None = None) -> dict[str, str]:
    existing = existing or {}
    profile = {field: text(payload.get(field, existing.get(field))) for field in PROFILE_COLUMNS}
    profile["target_seniority_levels"] = normalize_seniority_levels(payload.get("target_seniority_levels"))
    profile["maximum_required_years"] = text(payload.get("maximum_required_years")) or "3"
    profile["willing_to_apply_to_stretch_roles"] = normalize_bool_text(payload.get("willing_to_apply_to_stretch_roles"), True)
    profile["management_roles_allowed"] = normalize_bool_text(payload.get("management_roles_allowed"), False)
    ollama_defaults = ollama_profile_defaults()
    for field, default_value in ollama_defaults.items():
        if not profile.get(field):
            profile[field] = default_value
    if "resume_docx_template_path" not in payload and existing.get("resume_docx_template_path"):
        profile["resume_docx_template_path"] = text(existing.get("resume_docx_template_path"))
    if "cover_letter_docx_template_path" not in payload and existing.get("cover_letter_docx_template_path"):
        profile["cover_letter_docx_template_path"] = text(existing.get("cover_letter_docx_template_path"))
    if "cover_letter_template_status" not in payload and existing.get("cover_letter_template_status"):
        profile["cover_letter_template_status"] = text(existing.get("cover_letter_template_status"))
    return profile


def load_profile() -> dict[str, str]:
    row = query_db("SELECT * FROM profile WHERE id = 1", one=True)
    if row is None:
        profile = normalize_profile_payload({})
        upsert_profile(profile)
        sync_evidence_library(profile)
        return profile
    profile = normalize_profile_payload(dict(row))
    profile["updated_at"] = text(dict(row).get("updated_at"))
    return profile


def upsert_profile(profile: dict[str, str]) -> None:
    fields = list(normalize_profile_payload(profile).keys())
    values = [profile.get(field, "") for field in fields]
    assignments = ", ".join([f"{field} = excluded.{field}" for field in fields])
    get_db().execute(
        f"""
        INSERT INTO profile (id, {', '.join(fields)})
        VALUES (1, {', '.join(['?'] * len(fields))})
        ON CONFLICT(id) DO UPDATE SET {assignments}, updated_at = CURRENT_TIMESTAMP
        """,
        values,
    )
    get_db().commit()


def sync_evidence_library(profile: dict[str, str]) -> None:
    db = get_db()
    db.execute("DELETE FROM evidence_library WHERE source_kind IN ('profile', 'resume_import')")
    rows: list[dict[str, Any]] = []
    for field, label in [
        ("work_experience", "Work experience"),
        ("projects", "Projects"),
        ("education", "Education"),
        ("key_skills", "Key skills"),
        ("resume_text", "Resume text"),
    ]:
        content = normalize_space(text(profile.get(field)))
        if not content:
            continue
        if field == "resume_text":
            for sentence in split_sentences(content):
                clean = normalize_space(sentence)
                if len(clean) < 20:
                    continue
                rows.append(
                    {
                        "source_kind": "resume_import",
                        "source_field": field,
                        "source_label": label,
                        "content": clean,
                        "content_hash": grounding_hash(clean),
                        "approved": 1,
                        "review_notes": "",
                        "job_id": 0,
                    }
                )
        else:
            rows.append(
                {
                    "source_kind": "profile",
                    "source_field": field,
                    "source_label": label,
                    "content": content,
                    "content_hash": grounding_hash(content),
                    "approved": 1,
                    "review_notes": "",
                    "job_id": 0,
                }
            )
    for row in rows:
        db.execute(
            f"""
            INSERT INTO evidence_library ({', '.join(EVIDENCE_COLUMNS.keys())})
            VALUES ({', '.join(['?'] * len(EVIDENCE_COLUMNS))})
            """,
            tuple(row[column] for column in EVIDENCE_COLUMNS),
        )
    db.commit()


def list_evidence_library() -> list[dict[str, Any]]:
    rows = query_db("SELECT * FROM evidence_library ORDER BY approved DESC, updated_at DESC, id DESC")
    return [evidence_row_to_dict(row) for row in rows]


def load_approved_evidence_records(job_id: int | None = None) -> list[dict[str, Any]]:
    if job_id is None:
        rows = query_db("SELECT * FROM evidence_library WHERE approved = 1 ORDER BY updated_at DESC, id DESC")
    else:
        rows = query_db(
            """
            SELECT * FROM evidence_library
            WHERE approved = 1 AND (job_id = 0 OR job_id = ? OR job_id IS NULL)
            ORDER BY updated_at DESC, id DESC
            """,
            [job_id],
        )
    return [evidence_row_to_dict(row) for row in rows]


def evidence_row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    data = dict(row)
    data["approved"] = bool(int(data.get("approved") or 0))
    return data


def update_evidence_review(evidence_id: int, approved: Any = None, review_notes: str = "") -> dict[str, Any] | None:
    existing = query_db("SELECT * FROM evidence_library WHERE id = ?", [evidence_id], one=True)
    if existing is None:
        return None
    if approved is None:
        approved_value = int(existing["approved"])
    else:
        approved_value = 1 if str(approved).lower() in {"1", "true", "yes", "approved"} else 0
    get_db().execute(
        "UPDATE evidence_library SET approved = ?, review_notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [approved_value, review_notes, evidence_id],
    )
    get_db().commit()
    return evidence_row_to_dict(query_db("SELECT * FROM evidence_library WHERE id = ?", [evidence_id], one=True))


def rank_approved_evidence_records(job: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    job_terms = job_keywords(job)
    keywords = {
        "python",
        "flask",
        "postgresql",
        "postgres",
        "sql",
        "validation",
        "logging",
        "data cleaning",
        "data-cleaning",
        "backend",
        "integrations",
        "documentation",
        "monitoring",
        "automation",
        "api",
        "apis",
        "dashboard",
        "dashboards",
        "reliability",
        "records",
        "90%",
        "300,000",
    }
    ranked: list[dict[str, Any]] = []
    for record in records:
        content = text(record.get("content"))
        lowered = content.lower()
        tokens = set(re.findall(r"[a-z0-9+#.-]+", lowered))
        overlap = [term for term in job_terms if term.lower() in lowered]
        score = 0
        source_field = text(record.get("source_field"))
        source_kind = text(record.get("source_kind"))
        if source_field == "work_experience":
            score += 45
        elif source_field == "resume_text":
            score += 28
        elif source_field == "projects":
            score += 12
        elif source_field == "key_skills":
            score += 8
        elif source_field == "education":
            score += 4
        if source_kind == "profile":
            score += 5
        if len(overlap) >= 2:
            score += 10
        score += min(30, len(overlap) * 4)
        if any(term in lowered for term in ["python", "flask", "postgresql", "postgres", "sql", "backend", "validation", "logging", "documentation", "automation", "monitoring"]):
            score += 8
        if any(term in lowered for term in ["reliability", "data cleaning", "data-cleaning", "data entry", "error", "errors"]):
            score += 8
        if any(term in lowered for term in ["retail", "customer service", "sales associate", "cashier", "support"]):
            score -= 12
        if any(re.search(pattern, lowered) for pattern in [r"\b\d{1,3}(?:,\d{3})+\b", r"\b\d{2,3}%\b", r"\b\d+\+\s*(?:records|skus|users|items|events)\b"]):
            score += 18
        if any(term in lowered for term in ["at ", "co.", "inc.", "ltd.", "labs", "company"]):
            score += 8
        if any(term in lowered for term in ["collaboration", "delivery", "alignment", "fit", "quality"]) and not any(term in lowered for term in ["python", "flask", "postgresql", "records", "validation", "logging"]):
            score -= 8
        if any(keyword in lowered for keyword in keywords):
            score += 6
        ranked.append(
            {
                **record,
                "score": score,
                "matched_terms": overlap,
                "token_count": len(tokens),
            }
        )
    ranked.sort(
        key=lambda item: (
            int(item.get("score", 0)),
            len(text(item.get("content"))),
            -clamp_int(item.get("id"), 0, 10**9),
        ),
        reverse=True,
    )
    return ranked


def select_approved_evidence_records(job: dict[str, Any], records: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    ranked = rank_approved_evidence_records(job, records)
    selected = ranked[:limit]
    return selected


def build_job_evidence_analysis(job: dict[str, Any], profile: dict[str, str]) -> dict[str, Any]:
    evidence_rows = [row for row in list_evidence_library() if row.get("approved")]
    job_terms = job_keywords(job)
    matches: list[dict[str, Any]] = []
    for row in evidence_rows:
        content = text(row.get("content"))
        content_terms = sorted(set(re.findall(r"[a-z0-9+#.-]+", content.lower())))
        overlap = sorted(set(job_terms) & set(content_terms))
        if overlap:
            matches.append(
                {
                    **row,
                    "matched_terms": overlap[:8],
                    "match_score": len(overlap),
                }
            )
    matches.sort(key=lambda item: (int(item.get("match_score", 0)), len(text(item.get("content")))), reverse=True)
    return {
        "job_id": job.get("id", 0),
        "job_terms": job_terms[:20],
        "approved_evidence_count": len(evidence_rows),
        "matched_evidence": matches[:10],
        "missing_terms": [term for term in job_terms if term not in {t for item in matches for t in item.get("matched_terms", [])}],
        "profile_hash": build_candidate_evidence(profile)["hash"],
    }


def sync_resume_variants(job_id: int, job: dict[str, Any], profile: dict[str, str], output: dict[str, Any]) -> None:
    db = get_db()
    db.execute("DELETE FROM resume_variants WHERE job_id = ?", [job_id])
    for block in output.get("tailoring_plan", {}).get("resume_change_blocks", []):
        source_text = text(block.get("original_text"))
        proposed_text = text(block.get("proposed_text"))
        if not source_text or not proposed_text:
            continue
        approved = 1 if block.get("grounded") and block.get("validation_status") == "passed" else 0
        db.execute(
            f"""
            INSERT INTO resume_variants ({', '.join(RESUME_VARIANT_COLUMNS.keys())})
            VALUES ({', '.join(['?'] * len(RESUME_VARIANT_COLUMNS))})
            """,
            (
                job_id,
                text(block.get("section")),
                source_text,
                proposed_text,
                text(block.get("matched_job_phrase")),
                clamp_int(block.get("confidence"), 0, 100),
                approved,
                text(block.get("reason")) or ("Approved grounded variant" if approved else "Pending review"),
            ),
        )
    db.commit()


def list_resume_variants(job_id: int) -> list[dict[str, Any]]:
    rows = query_db("SELECT * FROM resume_variants WHERE job_id = ? ORDER BY approved DESC, confidence DESC, id DESC", [job_id])
    return [resume_variant_to_dict(row) for row in rows]


def resume_variant_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    data = dict(row)
    data["approved"] = bool(int(data.get("approved") or 0))
    return data


def update_resume_variant_review(variant_id: int, approved: Any = None, review_notes: str = "") -> dict[str, Any] | None:
    existing = query_db("SELECT * FROM resume_variants WHERE id = ?", [variant_id], one=True)
    if existing is None:
        return None
    if approved is None:
        approved_value = int(existing["approved"])
    else:
        approved_value = 1 if str(approved).lower() in {"1", "true", "yes", "approved"} else 0
    get_db().execute(
        "UPDATE resume_variants SET approved = ?, review_notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [approved_value, review_notes, variant_id],
    )
    get_db().commit()
    return resume_variant_to_dict(query_db("SELECT * FROM resume_variants WHERE id = ?", [variant_id], one=True))


def normalize_job_payload(payload: dict[str, Any]) -> dict[str, Any]:
    today = date.today().isoformat()
    supplied_description = text(payload.get("job_description")) or text(payload.get("paste_description")) or text(payload.get("description"))
    payload_for_extraction = {**payload, "job_description": supplied_description}
    extracted = extract_job_details(
        supplied_description,
        text(payload.get("source")),
        existing=payload_for_extraction,
    )
    clean = {column: text(payload_for_extraction.get(column, extracted.get(column, ""))) for column in JOB_COLUMNS}
    clean["date_added"] = text(payload.get("date_added")) or today
    clean["status"] = clean["status"] if clean["status"] in STATUSES else "Saved"
    clean["fit_score"] = clamp_int(payload.get("fit_score"), 0, 100)
    salary = determine_salary({**payload, **extracted, **clean})
    for field in ["salary_min", "salary_max", "salary_interval", "salary_currency", "salary_source", "salary_confidence"]:
        clean[field] = salary[field]
    clean["salary"] = salary["salary_text"]
    clean["salary_original_text"] = text(payload.get("salary_original_text") or payload.get("salary") or salary["salary_text"])
    clean["salary_midpoint"] = int(round((clean["salary_min"] + clean["salary_max"]) / 2)) if clean["salary_min"] or clean["salary_max"] else 0
    clean["salary_listed"] = 0 if clean["salary_source"] in {"estimated", "missing"} else 1

    scoring = score_job(
        {
            **extracted,
            **clean,
            "title": clean["title"],
            "location": clean["location"],
            "salary": clean["salary"],
            "job_description": clean["job_description"],
        },
        load_profile(),
    )
    for key, value in scoring.items():
        if key.endswith("_score") or key == "fit_score":
            clean[key] = value
    clean["score_breakdown"] = dumps_json(scoring["breakdown"], sort_keys=True)
    return clean


def job_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    data = dict(row)
    data["description_completeness"] = classify_job_description_completeness(data.get("job_description"))
    data["score_breakdown"] = parse_json_object(data.get("score_breakdown"))
    if "profile_updated_at" in data and data.get("profile_updated_at"):
        profile_row = query_db("SELECT updated_at FROM profile WHERE id = 1", one=True)
        current_profile_updated = text(profile_row["updated_at"]) if profile_row else ""
        if current_profile_updated and data["profile_updated_at"] != current_profile_updated:
            if data.get("resume_generation_status") == "generated":
                data["resume_generation_status"] = "Outdated — regenerate using current profile"
            if data.get("cover_letter_generation_status") == "generated":
                data["cover_letter_generation_status"] = "Outdated — regenerate using current profile"
    job_id = clamp_int(data.get("id"), 0, 10**9)
    if job_id:
        data["tailoring_changes"] = load_tailoring_changes(job_id)
        data["generation_debug"] = load_generation_debug(job_id)
        data.update(build_qualification_fit(data))
        preparation = query_db(
            "SELECT status FROM application_preparation_queue WHERE job_id = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
            [job_id],
            one=True,
        )
        data["preparation_status"] = text(preparation["status"]) if preparation else ""
    return data


def classify_job_description_completeness(value: Any) -> str:
    """Label stored description availability without inventing provider content."""
    description = normalize_space(text(value))
    if not description:
        return "missing"
    if len(description) < 800:
        return "partial"
    return "complete"


def build_qualification_fit(job: dict[str, Any]) -> dict[str, Any]:
    """Expose a transparent qualification view without changing Job Priority."""
    try:
        profile = load_profile()
        semantic = analyze_resume_match(job, profile, cache_dir=semantic_cache_dir(), use_semantic=False)
        analysis = analyze_job_seniority(job)
        seniority = score_seniority_fit(profile, analysis)
    except Exception:
        return {"qualification_fit_score": 0, "qualification_fit_label": "Review required", "qualification_fit_reasons": ["Qualification fit could not be assessed."]}

    profile_text = " ".join(text(profile.get(field)) for field in ("resume_text", "work_experience", "projects", "key_skills", "education")).lower()
    raw_required = [normalize_space(item) for item in re.split(r"[,;\n]+", text(job.get("required_skills"))) if normalize_space(item)]
    required_terms = raw_required if len(raw_required) > 1 else [item for item in job_keywords(job) if len(item) > 2]
    required_terms = list(dict.fromkeys(required_terms))
    matched = [term for term in required_terms if contains_phrase(profile_text, term)]
    missing = [term for term in required_terms if term not in matched]
    skill_score = round((len(matched) / len(required_terms)) * 100) if required_terms else clamp_int(semantic.get("scores", {}).get("required_skills"), 0, 100)
    responsibility_score = clamp_int(semantic.get("scores", {}).get("responsibilities"), 0, 100)
    score = round(skill_score * 0.5 + seniority.get("score", 0) * 0.35 + responsibility_score * 0.15)
    required = analysis.get("required_experience") or {}
    max_profile = None
    try:
        max_profile = float(text(profile.get("maximum_required_years")))
    except (TypeError, ValueError):
        pass
    if required.get("maximum") and max_profile is not None and float(required["maximum"]) > max_profile:
        score = min(score, 69)
        seniority["stretch_role"] = True
    reasons = []
    if matched:
        reasons.append(f"Supported requirements: {', '.join(matched[:5])}.")
    if missing:
        reasons.append(f"Not demonstrated in the selected profile: {', '.join(missing[:5])}.")
    if required:
        reasons.append(f"Posting experience requirement: {required.get('text', 'explicit experience requirement')}.")
    if seniority.get("explanation"):
        reasons.append(seniority["explanation"])
    if seniority.get("stretch_role"):
        reasons.append("Stretch opportunity: the posting expects more experience or seniority than the selected profile establishes.")
    label = "Strong qualification match" if score >= 75 and not seniority.get("stretch_role") else "Stretch opportunity" if seniority.get("stretch_role") or score < 60 else "Review qualification fit"
    return {
        "qualification_fit_score": clamp_int(score, 0, 100),
        "qualification_fit_label": label,
        "qualification_fit_reasons": reasons or ["Review the full posting and résumé evidence before applying."],
        "qualification_fit_matched_requirements": matched,
        "qualification_fit_missing_requirements": missing,
        "qualification_fit_seniority": seniority,
    }


def load_tailoring_changes(job_id: int) -> dict[str, Any]:
    folder = generated_applications_dir() / str(job_id)
    return {
        "resume": load_tailoring_change_log(folder / "resume_change_log.json"),
        "cover_letter": load_tailoring_change_log(folder / "cover_letter_change_log.json"),
    }


def load_tailoring_change_log(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"template_mode": "", "summary": {}, "applied": [], "skipped": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"template_mode": "", "summary": {}, "applied": [], "skipped": []}
    applied = raw.get("applied") if isinstance(raw.get("applied"), list) else []
    skipped = raw.get("skipped") if isinstance(raw.get("skipped"), list) else []
    return {
        "template_mode": text(raw.get("template_mode")),
        "summary": raw.get("summary") if isinstance(raw.get("summary"), dict) else {},
        "applied": [summarize_tailoring_change(item) for item in applied[:5] if isinstance(item, dict)],
        "skipped": [summarize_tailoring_change(item) for item in skipped[:5] if isinstance(item, dict)],
    }


def load_generation_debug(job_id: int) -> dict[str, Any]:
    folder = generated_applications_dir() / str(job_id)
    debug_path = folder / "generation_debug.json"
    metadata_path = folder / "metadata.json"
    raw: dict[str, Any] = {}
    for path in [debug_path, metadata_path]:
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            break
        except (OSError, json.JSONDecodeError):
            continue
    if not raw:
        return {}
    raw["generated_at"] = text(raw.get("generated_at"))
    raw["generation_token"] = text(raw.get("generation_token"))
    raw["job_hash"] = text(raw.get("job_hash"))
    raw["candidate_evidence_hash"] = text(raw.get("candidate_evidence_hash"))
    return raw


def summarize_tailoring_change(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": text(item.get("kind")),
        "original": text(item.get("original")),
        "replacement": text(item.get("replacement")),
        "reason": text(item.get("reason")),
        "matched_job_requirement": text(item.get("matched_job_requirement")),
        "supporting_evidence": text(item.get("supporting_evidence")),
        "confidence": clamp_int(item.get("confidence"), 0, 100),
        "validation_status": text(item.get("validation_status")),
        "skip_reason": text(item.get("skip_reason")),
    }


def text(value: Any) -> str:
    return str(value or "").strip()


def clamp_int(value: Any, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = low
    return max(low, min(high, number))


def clamp_int_default(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return date.min


def parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def parse_json_array(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    try:
        parsed = json.loads(value or "[]")
        return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def tokenize(content: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.-]+", content.lower()))


def contains_phrase(content: str, phrase: str) -> bool:
    return phrase.lower() in content.lower()


def keyword_hits(content: str, keywords: list[str]) -> list[str]:
    seen = []
    for keyword in keywords:
        if contains_phrase(content, keyword) and keyword not in seen:
            seen.append(keyword)
    return seen


def extract_job_details(content: str, source: str = "", existing: dict[str, Any] | None = None) -> dict[str, str]:
    existing = existing or {}
    compact = normalize_space(content)
    lines = [line.strip(" -*\t") for line in content.splitlines() if line.strip()]
    title = text(existing.get("title")) or guess_title(lines)
    company = text(existing.get("company")) or guess_company(lines)
    location = text(existing.get("location")) or guess_location(compact)
    salary = text(existing.get("salary")) or guess_salary(compact)
    remote_type = text(existing.get("remote_type")) or guess_remote_type(compact)
    role_type = text(existing.get("role_type")) or guess_role_type(f"{title} {compact}")
    seniority = text(existing.get("seniority_level")) or guess_seniority(f"{title} {compact}")
    skills = keyword_hits(compact, REWARD_KEYWORDS)
    required = extract_section(content, ["requirements", "required qualifications", "what you bring"])
    preferred = extract_section(content, ["preferred", "nice to have", "bonus"])
    responsibilities = extract_section(content, ["responsibilities", "what you will do", "about the role"])
    return {
        "company": company,
        "title": title,
        "location": location,
        "remote_type": remote_type,
        "salary": salary,
        "required_skills": ", ".join(skills) if not required else trim(required, 1200),
        "preferred_skills": trim(preferred, 1200),
        "responsibilities": trim(responsibilities, 1600),
        "seniority_level": seniority,
        "application_url": text(existing.get("application_url")) or text(existing.get("url")),
        "source": source or text(existing.get("source")),
        "role_type": role_type,
    }


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def as_bool(value: Any) -> bool:
    return text(value).lower() in {"1", "true", "yes", "on", "allowed"}


def guess_title(lines: list[str]) -> str:
    for line in lines[:8]:
        if 4 <= len(line) <= 90 and any(word in line.lower() for word in ["developer", "engineer", "analyst", "support", "specialist", "intern"]):
            return line
    return lines[0][:90] if lines else ""


def guess_company(lines: list[str]) -> str:
    for line in lines[:10]:
        match = re.search(r"(?:company|employer)[:\-]\s*(.+)", line, re.I)
        if match:
            return match.group(1)[:80]
    return ""


def guess_location(content: str) -> str:
    for keyword in LOCATION_KEYWORDS:
        if contains_phrase(content, keyword):
            return "Toronto / GTA" if keyword in {"toronto", "gta"} else keyword.title()
    return ""


def guess_salary(content: str) -> str:
    patterns = [
        r"\$ ?\d{2,3}(?:,\d{3})?(?:k|K)?\s*(?:-|to|–)\s*\$? ?\d{2,3}(?:,\d{3})?(?:k|K)?",
        r"\$ ?\d{2,3},\d{3}",
        r"\$ ?\d{2,3}k",
    ]
    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            return match.group(0)
    return ""


def guess_remote_type(content: str) -> str:
    lowered = content.lower()
    if "hybrid" in lowered:
        return "Hybrid"
    if "remote" in lowered:
        return "Remote"
    if "on-site" in lowered or "onsite" in lowered:
        return "On-site"
    return ""


def guess_role_type(content: str) -> str:
    lowered = content.lower()
    for role_type in ROLE_TYPES:
        if role_type != "other" and role_type in lowered:
            return role_type
    if "full stack" in lowered or "full-stack" in lowered:
        return "full-stack developer"
    if "support" in lowered and "cloud" in lowered:
        return "cloud support"
    return "other"


def guess_seniority(content: str) -> str:
    lowered = content.lower()
    if any(term in lowered for term in ["intern", "internship"]):
        return "Intern"
    if any(term in lowered for term in ["junior", "new grad", "entry level"]):
        return "Junior/New Grad"
    if "senior" in lowered or re.search(r"\b[5-9]\+ years", lowered):
        return "Senior"
    if "lead" in lowered or "principal" in lowered:
        return "Lead"
    return "Not specified"


def extract_section(content: str, headings: list[str]) -> str:
    lines = [line.rstrip() for line in content.splitlines()]
    capture: list[str] = []
    active = False
    for line in lines:
        lower = line.lower().strip(" :")
        if any(heading in lower for heading in headings):
            active = True
            continue
        if active and len(capture) > 2 and re.match(r"^[A-Z][A-Za-z /&-]{3,40}:?$", line.strip()):
            break
        if active:
            capture.append(line.strip())
        if len(capture) >= 10:
            break
    return "\n".join([line for line in capture if line])


def trim(value: str, limit: int) -> str:
    return normalize_space(value)[:limit]


def score_job(job: dict[str, Any], profile: dict[str, str], semantic_result: dict[str, Any] | None = None) -> dict[str, Any]:
    content = " ".join(
        [
            text(job.get("title")),
            text(job.get("location")),
            text(job.get("remote_type")),
            text(job.get("salary")),
            text(job.get("required_skills")),
            text(job.get("preferred_skills")),
            text(job.get("responsibilities")),
            text(job.get("job_description")),
        ]
    ).lower()
    profile_text = " ".join(text(value) for key, value in profile.items() if not str(key).startswith("_")).lower()
    skill_hits = keyword_hits(content, REWARD_KEYWORDS)
    supported_hits = [hit for hit in skill_hits if contains_phrase(profile_text, hit)]
    penalties = keyword_hits(content, PENALTY_KEYWORDS)
    coding_hits = keyword_hits(content, CODING_RISK_KEYWORDS)
    effort_hits = keyword_hits(content, EFFORT_KEYWORDS)

    semantic_result = semantic_result or analyze_resume_match(job, profile, cache_dir=semantic_cache_dir(), use_semantic=False)
    semantic_scores = semantic_result.get("scores", {})
    legacy_skills_score = 35 + len(supported_hits) * 8 - len(penalties) * 4
    semantic_skills_score = round((semantic_scores.get("required_skills", 0) * 0.7) + (semantic_scores.get("preferred_skills", 0) * 0.3))
    skills_score = clamp_int(max(legacy_skills_score, semantic_skills_score), 0, 100)
    responsibility_score = clamp_int(max(semantic_scores.get("responsibilities", 0), 48 + len(supported_hits) * 5), 0, 100)
    role_hits = keyword_hits(content, ROLE_KEYWORDS)
    preferred_roles = profile.get("preferred_roles", "").lower()
    role_score = clamp_int(semantic_scores.get("role_title", 0) or (45 + len(role_hits) * 7 + sum(8 for role in ROLE_TYPES if role in content and role in preferred_roles)), 0, 100)
    location_score = score_location(content, profile, job)
    remote_score = score_remote(content)
    salary_score = score_salary(job, profile, content)
    seniority_analysis = analyze_job_seniority(job)
    seniority_fit = score_seniority_fit(profile, seniority_analysis)
    seniority_score = seniority_fit["score"]
    coding_risk_score = clamp_int(100 - len(coding_hits) * 22, 0, 100)
    effort_score = clamp_int(92 - len(effort_hits) * 12, 0, 100)
    suspicion_penalty = 12 if suspicious_job(content, text(job.get("company")), text(job.get("salary"))) else 0
    warnings = []
    rejections = []
    if int(job.get("salary_confidence") or 0) < 50:
        warnings.append("Salary is estimated, not employer-provided.")
    if salary_score <= 25:
        rejections.append("Compensation appears below the saved minimum or is unpaid/commission-only.")
    if location_score <= 35:
        rejections.append("Location or remote setup appears outside saved preferences.")
    if remote_score <= 45:
        warnings.append("Remote preference may not match.")

    overall = round(
        skills_score * (SCORING_WEIGHTS["skills"] / 100)
        + responsibility_score * (SCORING_WEIGHTS["responsibilities"] / 100)
        + location_score * (SCORING_WEIGHTS["location"] / 100)
        + salary_score * (SCORING_WEIGHTS["salary"] / 100)
        + seniority_score * (SCORING_WEIGHTS["seniority"] / 100)
        + role_score * (SCORING_WEIGHTS["role"] / 100)
        - suspicion_penalty
    )
    breakdown = {
        "matched_keywords": skill_hits,
        "penalty_keywords": penalties,
        "coding_risk_keywords": coding_hits,
        "application_effort_flags": effort_hits,
        "salary_source": text(job.get("salary_source")) or "missing",
        "salary_confidence": clamp_int(job.get("salary_confidence"), 0, 100),
        "salary_range": {
            "min": clamp_int(job.get("salary_min"), 0, 1_000_000),
            "max": clamp_int(job.get("salary_max"), 0, 1_000_000),
            "currency": text(job.get("salary_currency")) or "CAD",
            "interval": text(job.get("salary_interval")),
        },
        "warnings": warnings,
        "rejection_reasons": rejections,
        "weights": SCORING_WEIGHTS,
        "previous_formula": "salary 30%, location 30%, role 15%, skills 15%, simple seniority 10%, minus suspicious-posting penalty",
        "new_formula": "required/preferred skills 30%, responsibilities/experience 20%, location/work arrangement 15%, salary 10%, target seniority and years 15%, role/title relevance 10%, minus visible risk penalties",
        "semantic_model": semantic_result.get("model", "keyword-fallback"),
        "semantic_model_available": semantic_result.get("model_available", False),
        "semantic_fallback": "Exact keyword and lexical overlap are used when Sentence Transformers is unavailable or not requested.",
        "semantic_scores": semantic_scores,
        "direct_resume_matches": semantic_result.get("direct_matches", [])[:5],
        "transferable_resume_matches": semantic_result.get("transferable_matches", [])[:5],
        "missing_requirements": semantic_result.get("missing_requirements", [])[:8],
        "unsupported_requirements": semantic_result.get("unsupported_requirements", [])[:8],
        "seniority_analysis": seniority_analysis,
        "seniority_fit": seniority_fit,
        "notes": score_notes(skill_hits, penalties, coding_hits, effort_hits, suspicion_penalty, seniority_fit),
    }
    return {
        "skills_match_score": skills_score,
        "role_match_score": role_score,
        "location_score": location_score,
        "remote_score": remote_score,
        "salary_score": salary_score,
        "seniority_score": seniority_score,
        "responsibility_match_score": responsibility_score,
        "coding_risk_score": coding_risk_score,
        "application_effort_score": effort_score,
        "fit_score": clamp_int(overall, 0, 100),
        "breakdown": breakdown,
    }


def score_location(content: str, profile: dict[str, str], job: dict[str, Any] | None = None) -> int:
    prefs = profile.get("preferred_locations", "").lower()
    job = job or {}
    remote_type = text(job.get("remote_type")).lower()
    location = text(job.get("location")).lower()
    if prefs and location and "remote" not in remote_type and not any(part in location for part in preferred_location_terms(prefs)):
        return 35
    if "remote" in content:
        return 96
    if "toronto" in content or "gta" in content:
        return 94
    if "hybrid" in content and any(term in prefs for term in ["toronto", "ontario", "hybrid"]):
        return 88
    if "ontario" in content or "canada" in content:
        return 78
    return 55


def preferred_location_terms(prefs: str) -> list[str]:
    terms = [term.strip() for term in re.split(r"[,/]| or | and ", prefs.lower()) if len(term.strip()) >= 4]
    expanded = []
    for term in terms:
        expanded.extend([part for part in re.split(r"\s+", term) if len(part) >= 4])
    return list(dict.fromkeys([*terms, *expanded]))


def score_remote(content: str) -> int:
    if "remote" in content:
        return 96
    if "hybrid" in content:
        return 88
    if "on-site" in content or "onsite" in content:
        return 55
    return 70


def score_salary(job: dict[str, Any], profile: dict[str, str], content: str) -> int:
    salary = text(job.get("salary"))
    lowered = f"{salary} {content}".lower()
    if "unpaid" in lowered or "commission only" in lowered or "commission-only" in lowered:
        return 5
    maximum = clamp_int(job.get("salary_max"), 0, 1_000_000)
    minimum = clamp_int(job.get("salary_min"), 0, 1_000_000)
    source = text(job.get("salary_source"))
    confidence = clamp_int(job.get("salary_confidence"), 0, 100)
    if not maximum and salary:
        parsed = parse_salary_text(salary)
        maximum = parsed["salary_max"]
        minimum = parsed["salary_min"]
        source = parsed["salary_source"]
        confidence = parsed["salary_confidence"]
    if not maximum:
        return 58
    target_min = desired_min_salary(profile)
    if target_min and maximum < target_min:
        return 18 if source != "estimated" else 34
    score = 70
    if target_min and minimum >= target_min:
        score += 12
    if maximum >= max(70000, target_min or 0):
        score += 8
    if maximum >= max(90000, (target_min or 0) + 15000):
        score += 8
    if source == "estimated":
        score -= 14
    if confidence < 60:
        score -= 8
    return clamp_int(score, 0, 100)


def desired_min_salary(profile: dict[str, str]) -> int:
    content = " ".join([profile.get("resume_text", ""), profile.get("preferred_roles", ""), profile.get("cover_letter_template", "")])
    match = re.search(r"(?:minimum|min|target|salary expectations?)[^\d$]{0,25}\$?\s*(\d{2,3}(?:,\d{3})?|\d{2,3}k)", content, re.I)
    if not match:
        return 60000
    number = money_number(match.group(1))
    return int(number or 60000)


def score_seniority(content: str) -> int:
    return score_seniority_fit({}, analyze_job_seniority({"job_description": content}))["score"]


def suspicious_job(content: str, company: str, salary: str) -> bool:
    return (not company and not salary) or "vague company" in content or "commission only" in content


def score_notes(
    matches: list[str],
    penalties: list[str],
    coding_hits: list[str],
    effort_hits: list[str],
    suspicion_penalty: int,
    seniority_fit: dict[str, Any] | None = None,
) -> list[str]:
    notes = []
    if matches:
        notes.append(f"Rewarded matches: {', '.join(matches[:8])}")
    if penalties:
        notes.append(f"Penalized risk terms: {', '.join(penalties[:5])}")
    if coding_hits:
        notes.append(f"Coding assessment risk: {', '.join(coding_hits[:5])}")
    if effort_hits:
        notes.append(f"Application effort flags: {', '.join(effort_hits[:5])}")
    if suspicion_penalty:
        notes.append("Penalized vague company or suspicious compensation signals")
    if seniority_fit and seniority_fit.get("explanation"):
        notes.append(f"Seniority: {seniority_fit['explanation']}")
    if seniority_fit and seniority_fit.get("stretch_role"):
        notes.append("Stretch-role warning: this posting is above saved target seniority or experience settings.")
    if seniority_fit and seniority_fit.get("management_role"):
        notes.append("Management warning: the posting includes people-management signals.")
    return notes


def semantic_cache_dir() -> Path:
    path = DATA_DIR / SEMANTIC_CACHE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def generate_application_materials(
    job: dict[str, Any],
    profile: dict[str, str],
    raise_on_validation: bool = True,
) -> dict[str, Any]:
    job_id = clamp_int(job.get("id"), 0, 10**9) or None
    approved_evidence_records = (
        [] if profile.get("_candidate_profile_id") else load_approved_evidence_records(job_id) if has_app_context() else []
    )
    ranked_approved_evidence = rank_approved_evidence_records(job, approved_evidence_records)
    selected_approved_evidence = select_approved_evidence_records(job, approved_evidence_records, limit=6)
    approved_sections = [
        {
            "id": record.get("id"),
            "field": "approved_evidence",
            "source_kind": text(record.get("source_kind")) or "evidence_library",
            "source_field": text(record.get("source_field")),
            "text": text(record.get("content")),
            "approved": True,
        }
        for record in selected_approved_evidence
        if text(record.get("content"))
    ]
    candidate_evidence = build_candidate_evidence(profile, extra_sections=approved_sections)
    if not evidence_has_generation_source(candidate_evidence):
        raise ValueError("Complete the Profile page with resume, project, or work-experience details before generating documents.")
    job_text = " ".join([text(job.get("title")), text(job.get("job_description")), text(job.get("required_skills"))])
    semantic = analyze_resume_match(job, profile, cache_dir=semantic_cache_dir(), use_semantic=False)
    semantic["candidate_evidence"] = candidate_evidence
    semantic["approved_evidence_records"] = approved_evidence_records
    semantic["selected_approved_evidence"] = selected_approved_evidence
    seniority_analysis = analyze_job_seniority(job)
    seniority_fit = score_seniority_fit(profile, seniority_analysis)
    scoring = score_job(job, profile, semantic)
    tailored = generate_tailored_resume_draft(job, profile, semantic, seniority_fit)
    tailoring_plan = tailored.get("tailoring_plan") or build_tailoring_plan(job, profile, semantic)
    tailoring_plan["candidate_evidence"] = candidate_evidence
    skill_groups = classify_supported_skills(job, candidate_evidence)
    matched = job_keywords(job)
    supported = skill_groups["supported_relevant"]
    unsupported = skill_groups["unsupported_job_keywords"]
    transferable = skill_groups["transferable_supported"]
    focus = supported[:4]
    resume_lines = [item["proposed_bullet"] for item in tailored["rewrite_suggestions"]]
    if not resume_lines:
        resume_lines = [
            item["text"]
            for item in semantic.get("evidence", [])
            if item.get("evidence_type") in {"professional experience", "project"}
        ]
    grounded_resume_lines = [block["proposed_text"] for block in tailoring_plan.get("resume_change_blocks", []) if block.get("grounded")]
    summary = build_summary(profile, job, focus, candidate_evidence)
    skills_section = format_skills_guidance(skill_groups)
    refreshed_cover_letter_paragraphs = build_cover_letter_paragraphs(
        job,
        profile,
        tailoring_plan.get("selected_cover_letter_blocks", []),
        candidate_evidence,
    )
    if refreshed_cover_letter_paragraphs:
        tailoring_plan["cover_letter_paragraphs"] = refreshed_cover_letter_paragraphs
        tailoring_plan["cover_letter_text"] = "\n\n".join(refreshed_cover_letter_paragraphs)
    cover_letter = tailoring_plan.get("cover_letter_text") or build_cover_letter(profile, job, focus, candidate_evidence)
    tailoring_plan["cover_letter_text"] = cover_letter
    tailoring_plan["cover_letter_paragraphs"] = [paragraph for paragraph in cover_letter.split("\n\n") if paragraph]
    cover_validation = validate_cover_letter_output(cover_letter, candidate_evidence, job)
    ollama_config = OllamaConfig.from_mapping(profile)
    ollama_debug: dict[str, Any] = {
        "enabled": ollama_config.enabled,
        "called": False,
        "model": ollama_config.model,
        "used_fallback": True,
        "status": "disabled" if not ollama_config.enabled else "not_called",
        "error": "",
        "suggestion_ok": False,
        "validation_error": "",
        "raw_length": 0,
    }
    if ollama_config.enabled:
        ollama_debug["called"] = True
        prompt_payload = {
            "max_output_tokens": ollama_config.max_output_tokens,
            "selected_evidence_ids": [text(item.get("id")) for item in selected_approved_evidence if item.get("id") is not None],
        }
        ollama_response = request_json_completion(
            ollama_config,
            build_ollama_prompt("cover_letter", job, candidate_evidence, prompt_payload),
            system="Return strict JSON only.",
        )
        ollama_debug["status"] = "ok" if ollama_response.get("ok") else "error"
        ollama_debug["error"] = text(ollama_response.get("error"))
        ollama_debug["raw_length"] = len(text(ollama_response.get("raw")))
        if ollama_response.get("ok"):
            ollama_validation = validate_ollama_suggestion("cover_letter", ollama_response.get("data", {}), job, candidate_evidence)
            ollama_debug["suggestion_ok"] = bool(ollama_validation.get("ok"))
            ollama_debug["validation_error"] = text(ollama_validation.get("error"))
            ollama_debug["used_fallback"] = not bool(ollama_validation.get("ok"))
            if ollama_validation.get("ok"):
                suggestion = text(ollama_validation.get("suggestion"))
                if suggestion:
                    cover_letter = suggestion
                    cover_validation = validate_cover_letter_output(cover_letter, candidate_evidence, job)
    if str(profile.get("cover_letter_no_dashes", "true")).strip().lower() not in {"0", "false", "no", "off"}:
        cover_letter = re.sub(r"(?<=\d)[-–—](?=\d)", " to ", cover_letter)
        cover_letter = re.sub(r"[-–—]", " ", cover_letter)
        cover_letter = re.sub(r"[ \t]+", " ", cover_letter)
        cover_letter = re.sub(r" +\n", "\n", cover_letter)
        tailoring_plan["cover_letter_text"] = cover_letter
        tailoring_plan["cover_letter_paragraphs"] = [paragraph for paragraph in cover_letter.split("\n\n") if paragraph]
    answers = build_answers(profile, job, focus, candidate_evidence)
    resume_text = (
        f"Suggested summary\n{summary}\n\n"
        f"Suggested skills guidance\n{skills_section}\n\n"
        f"Suggested bullet rewrites\n" + "\n".join([f"- {line}" for line in (grounded_resume_lines or resume_lines)]) + "\n\n"
        f"Unsupported job keywords - do not add\n{', '.join(unsupported) or 'None from the current posting.'}"
    )
    local_tailored_text = tailored["text"]
    resume_validation = validate_generated_content("\n\n".join([resume_text, answers_to_text(answers)]), candidate_evidence, job)
    validation = {
        "ok": resume_validation["ok"] and cover_validation["ok"],
        "conflicting_phrases": list(dict.fromkeys([*resume_validation["conflicting_phrases"], *cover_validation["conflicting_phrases"]])),
        "empty_or_corrupted_evidence": resume_validation["empty_or_corrupted_evidence"] or cover_validation["empty_or_corrupted_evidence"],
        "resume_ok": resume_validation["ok"],
        "cover_letter_ok": cover_validation["ok"],
    }
    keyword_coverage = build_keyword_coverage_report(job, profile, semantic, tailoring_plan)
    keywords_score = build_keywords_score_report(job, profile)
    keyword_coverage["keywords_score"] = keywords_score
    if raise_on_validation:
        if not resume_validation["ok"]:
            conflicts = ", ".join(resume_validation["conflicting_phrases"]) or "empty or corrupted candidate evidence"
            raise ValueError(f"Generated resume failed grounding validation. Unsupported or conflicting phrases: {conflicts}")
    return {
        "fit_score": scoring["fit_score"],
        "score_breakdown": scoring,
        "matched_keywords": matched,
        "supported_keywords": supported,
        "missing_keywords": transferable,
        "unsupported_keywords": unsupported,
        "skill_guidance": skill_groups,
        "candidate_evidence_hash": candidate_evidence["hash"],
        "candidate_evidence": candidate_evidence,
        "approved_evidence_records": approved_evidence_records,
        "selected_approved_evidence_records": selected_approved_evidence,
        "ranked_approved_evidence_records": ranked_approved_evidence,
        "job_hash": generation_job_hash(job),
        "validation": validation,
        "keyword_coverage": keyword_coverage,
        "keywords_score": keywords_score,
        "summary": summary,
        "skills_section": skills_section,
        "resume_bullets": grounded_resume_lines or resume_lines,
        "resume_text": resume_text,
        "local_tailored_draft": tailored,
        "local_tailored_text": local_tailored_text,
        "semantic_match": semantic,
        "seniority_analysis": seniority_analysis,
        "seniority_fit": seniority_fit,
        "cover_letter": cover_letter,
        "cover_validation": cover_validation,
        "resume_validation": resume_validation,
        "ollama_debug": ollama_debug,
        "short_answers": answers,
        "tailoring_plan": tailoring_plan,
        "tailoring_review": {
            "extracted_job_phrases": tailoring_plan.get("extracted_job_phrases", []),
            "matching_resume_evidence": tailoring_plan.get("phrase_to_evidence_matches", []),
            "proposed_resume_changes": tailoring_plan.get("resume_change_blocks", []),
            "applied_resume_changes": tailoring_plan.get("change_log", {}).get("applied_changes", []),
            "skipped_resume_changes": tailoring_plan.get("change_log", {}).get("skipped_changes", []),
            "cover_letter_evidence_blocks": tailoring_plan.get("selected_cover_letter_blocks", []),
            "final_cover_letter_preview": tailoring_plan.get("cover_letter_text", ""),
        },
    }


def build_keyword_coverage_report(
    job: dict[str, Any],
    profile: dict[str, Any],
    semantic_result: dict[str, Any],
    tailoring_plan: dict[str, Any] | None = None,
    final_resume_text: str | None = None,
) -> dict[str, Any]:
    """Return baseline and final-DOCX coverage as transparent review heuristics."""
    matches = semantic_result.get("matches", []) or []
    required_categories = {"required_skill", "responsibility", "role_title"}
    preferred_categories = {"preferred_skill"}
    aliases = {
        "nodejs": "node.js",
        "java script": "javascript",
        "postgres": "postgresql",
        "restful apis": "rest apis",
    }

    def normalize_requirement(value: Any) -> str:
        result = normalize_space(str(value or "")).lower()
        for source, target in aliases.items():
            result = re.sub(rf"\b{re.escape(source)}\b", target, result)
        return result

    def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        output: list[dict[str, Any]] = []
        for item in items:
            key = normalize_requirement(item.get("job_requirement"))
            if not key or key in seen:
                continue
            if any(key in existing or existing in key for existing in seen):
                continue
            seen.add(key)
            output.append(item)
        return output

    title = normalize_requirement(job.get("title"))
    company = normalize_requirement(job.get("company"))
    location = normalize_requirement(job.get("location"))

    def meaningful_requirement(item: dict[str, Any]) -> bool:
        requirement = normalize_requirement(item.get("job_requirement"))
        if not requirement or len(requirement) > 80:
            return False
        if requirement in {company, location, "full-time", "apply now", "job details"}:
            return False
        if any(term in requirement for term in [
            "paid time off", "vision care", "dental care", "life insurance",
            "employee assistance", "disability insurance", "$",
        ]):
            return False
        if re.search(r"\b\d{3,}\b", requirement) and not re.search(r"\b(?:api|sql|python|java|c\+\+|years?)\b", requirement):
            return False
        important_technical_terms = {
            *(term.lower() for term in TECHNICAL_TERMS),
            "kubernetes", "jira", "rmq", "gps", "figma", "windows", "linux",
            "java", "c++", "c#", ".net", "video analytics", "thermal cameras",
        }
        known_technical = any(term in requirement for term in important_technical_terms)
        if item.get("category") == "required_skill" and classify_phrase(requirement) == "domain terminology" and requirement != title and not known_technical:
            return False
        return True

    def raw_description_field(field: str) -> bool:
        value = normalize_requirement(job.get(field))
        description = normalize_requirement(job.get("job_description"))
        return bool(value and description and value == description)

    def description_classification(requirement: str) -> str:
        """Only classify explicit JD requirements; incidental prose is not mandatory."""
        description = text(job.get("job_description"))
        lowered = description.lower()
        needle = normalize_requirement(requirement)
        index = lowered.find(needle)
        if index < 0:
            return "mentioned"
        # Include the labelled phrase itself: a heading such as
        # "Requirements: Node.js experience" begins at the same position as
        # the extracted phrase, not before it.
        context = lowered[max(0, index - 260):index + len(needle)]
        if re.search(r"\b(preferred|nice to have|bonus|asset)\b", context):
            return "preferred_skill"
        if re.search(r"\b(required|requirements|must have|minimum qualifications|qualifications)\b", context):
            return "required_skill"
        return "mentioned"

    ranked = (tailoring_plan or {}).get("ranked_requirements") or rank_job_requirements(job)
    requirement_items: list[dict[str, Any]] = []
    for item in ranked:
        source_field = item.get("source_field")
        if source_field == "preferred_skills" and not raw_description_field("preferred_skills"):
            category = "preferred_skill"
        elif source_field in {"required_skills", "responsibilities"} and not raw_description_field(source_field):
            category = "required_skill"
        elif source_field == "title":
            category = "required_skill"
        else:
            category = description_classification(str(item.get("phrase") or ""))
        if category == "mentioned":
            continue
        requirement_items.append({
            "job_requirement": item.get("phrase", ""),
            "category": category,
            "source_field": source_field,
        })
    known_requirements = {normalize_requirement(item.get("job_requirement")) for item in requirement_items}
    requirement_items.extend(
        item for item in matches
        if normalize_requirement(item.get("job_requirement")) not in known_requirements
    )

    required = dedupe([item for item in requirement_items if item.get("category") in required_categories and meaningful_requirement(item)])
    preferred = dedupe([item for item in requirement_items if item.get("category") in preferred_categories and meaningful_requirement(item)])

    match_by_requirement = {normalize_requirement(item.get("job_requirement")): item for item in matches}

    def evidence_for_text(source_text: str) -> tuple[str, list[str]]:
        normalized = normalize_requirement(source_text)
        # Keep short skill lines such as "SQL, Node.js".  The general sentence
        # splitter intentionally drops short prose fragments, but doing so here
        # would under-report what is visibly present in the final DOCX.
        paragraph_lines = [normalize_space(line) for line in source_text.splitlines() if normalize_space(line)]
        lines = list(dict.fromkeys([*paragraph_lines, *split_sentences(source_text)])) or ([normalize_space(source_text)] if source_text else [])
        return normalized, lines

    baseline_text = " ".join(text(profile.get(field)) for field in ["work_experience", "key_skills", "education", "projects", "resume_text"])

    def enrich(items: list[dict[str, Any]], source_text: str, permit_semantic_evidence: bool) -> list[dict[str, Any]]:
        profile_text, evidence_lines = evidence_for_text(source_text)
        enriched: list[dict[str, Any]] = []
        for item in items:
            requirement = item.get("job_requirement", "")
            normalized = normalize_requirement(requirement)
            source_match = match_by_requirement.get(normalized, {})
            evidence = ""
            direct_lexical_match = False
            if normalized and normalized in profile_text:
                evidence = next((line for line in evidence_lines if normalized in normalize_requirement(line)), "")
                direct_lexical_match = bool(evidence)
            # Requirement sentences often include a generic suffix such as
            # "experience".  Count an exact supported technical term in that
            # sentence without requiring the entire sentence to appear in a
            # résumé.
            if not evidence:
                technical_terms = sorted({normalize_requirement(term) for term in TECHNICAL_TERMS} | set(aliases.values()), key=len, reverse=True)
                direct_term = next((term for term in technical_terms if term and term in normalized and term in profile_text), "")
                if direct_term:
                    evidence = next((line for line in evidence_lines if direct_term in normalize_requirement(line)), "")
                    direct_lexical_match = bool(evidence)
            if not evidence and permit_semantic_evidence:
                evidence = normalize_space(source_match.get("matched_resume_evidence"))
            enriched.append({
                **item,
                "matched_resume_evidence": evidence,
                "confidence": 100 if direct_lexical_match else source_match.get("confidence", 0),
                "match_type": "direct" if direct_lexical_match else source_match.get("match_type", "missing"),
            })
        return enriched

    def snapshot(source_text: str, permit_semantic_evidence: bool) -> dict[str, Any]:
        required_items = enrich(required, source_text, permit_semantic_evidence)
        preferred_items = enrich(preferred, source_text, permit_semantic_evidence)
        required_covered, required_potential, required_unsupported = classify(required_items)
        preferred_covered, preferred_potential, preferred_unsupported = classify(preferred_items)
        required_total = len(required_items)
        required_coverage = round((len(required_covered) / required_total) * 100) if required_total else 100
        return {
            "required": {
                "covered": required_covered,
                "potential_safe_substitutions": required_potential,
                "unsupported": required_unsupported,
                "coverage_percent": required_coverage,
                "total": required_total,
            },
            "preferred": {
                "covered": preferred_covered,
                "potential_safe_substitutions": preferred_potential,
                "unsupported": preferred_unsupported,
                "coverage_percent": round((len(preferred_covered) / len(preferred_items)) * 100) if preferred_items else 100,
                "total": len(preferred_items),
            },
        }

    def classify(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        covered: list[dict[str, Any]] = []
        potential: list[dict[str, Any]] = []
        unsupported: list[dict[str, Any]] = []
        for item in items:
            evidence = normalize_space(item.get("matched_resume_evidence"))
            confidence = int(item.get("confidence") or 0)
            record = {
                "requirement": item.get("job_requirement", ""),
                "evidence": evidence,
                "confidence": confidence,
                "match_type": item.get("match_type", "missing"),
                "category": item.get("category", ""),
                "group": classify_phrase(str(item.get("job_requirement") or "")),
            }
            if evidence and item.get("match_type") == "direct" and confidence >= 40:
                covered.append(record)
            elif evidence and confidence >= 40:
                potential.append(record)
            else:
                unsupported.append(record)
        return covered, potential, unsupported

    before = snapshot(baseline_text, True)
    after = snapshot(final_resume_text or baseline_text, not bool(final_resume_text))
    required_unsupported = after["required"]["unsupported"]
    critical_groups = {item["group"] for item in required_unsupported if item.get("group")}
    warnings: list[str] = []
    if after["required"]["total"] and after["required"]["coverage_percent"] < 60:
        warnings.append("Review job fit: required-skill coverage is below 60%.")
    if len(critical_groups) >= 3:
        warnings.append("Review job fit: at least 3 critical required-skill groups are unsupported.")

    job_text = normalize_requirement(" ".join(text(job.get(field)) for field in ["title", "required_skills", "preferred_skills", "responsibilities", "job_description"]))
    profile_text = normalize_requirement(final_resume_text or baseline_text)
    eligibility: list[dict[str, str]] = []
    if any(term in job_text for term in ["in person", "commute", "relocate", "on-site", "onsite"]):
        if not any(term in profile_text for term in ["toronto", "abbotsford", "relocate", "commute"]):
            eligibility.append({"type": "location", "message": "Confirm commute, relocation, or in-person availability."})
    if any(term in job_text for term in ["authorized to work", "work authorization", "legally authorized"]):
        if not any(term in profile_text for term in ["authorized", "authorization"]):
            eligibility.append({"type": "authorization", "message": "Work authorization is not established in the résumé."})
    if re.search(r"\b(?:3|4|5|7|10)\+?\s+years?", job_text) and not re.search(r"\b(?:3|4|5|7|10)\+?\s+years?", profile_text):
        eligibility.append({"type": "experience", "message": "Required years of experience are not explicitly established in the résumé."})

    return {
        # Top-level fields remain the final rendered-DOCX view for existing API clients.
        **after,
        "before": before,
        "after": after,
        "warnings": warnings,
        "review_job_fit": bool(warnings),
        "critical_unsupported_groups": sorted(critical_groups),
        "eligibility_concerns": eligibility,
        "heuristic_note": "Coverage is a review heuristic, not an ATS score or hiring decision.",
    }


def source_backed_bullets(profile: dict[str, str], focus: list[str]) -> list[str]:
    source = normalize_space(" ".join([profile.get("projects", ""), profile.get("work_experience", ""), profile.get("resume_text", "")]))
    snippets = split_sentences(source)
    if not snippets:
        return ["Add project or work-experience detail in Profile first so rewrites stay grounded in your real experience."]
    bullets = []
    for snippet in snippets[:5]:
        if focus:
            keyword = next((item for item in focus if contains_phrase(snippet, item)), focus[0])
            bullets.append(f"Reframe existing experience around {keyword}: {snippet}")
        else:
            bullets.append(snippet)
    return bullets


def split_sentences(value: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", value)
    return [part.strip(" -") for part in parts if len(part.strip()) > 30]


def build_summary(profile: dict[str, str], job: dict[str, Any], focus: list[str], candidate_evidence: dict[str, Any]) -> str:
    source_summary = normalize_space(text(profile.get("_source_summary")))
    if source_summary:
        return source_summary
    return source_backed_summary_fallback(profile)


def source_backed_summary_fallback(profile: dict[str, str]) -> str:
    for field in ("work_experience", "projects", "education"):
        sentence = first_meaningful_sentence(text(profile.get(field)))
        if sentence:
            return sentence
    return ""


def first_meaningful_sentence(value: str) -> str:
    for sentence in split_sentences(value):
        clean = normalize_space(sentence)
        if clean and not is_resume_role_heading(clean) and not contains_contact_details(clean) and not contains_resume_section_heading(clean):
            return clean if clean.endswith((".", "!", "?")) else f"{clean}."
    return ""


def infer_documented_role(candidate_evidence: dict[str, Any]) -> str:
    for section in candidate_evidence.get("sections", []):
        if section.get("field") != "work_experience":
            continue
        for line in str(section.get("text") or "").splitlines():
            clean = normalize_space(line)
            if "—" in clean or "|" in clean:
                parts = [normalize_space(part) for part in re.split(r"—|\|", clean) if normalize_space(part)]
                if len(parts) >= 2 and len(parts[-1].split()) <= 6:
                    return parts[-1]
    return ""


def first_narrative_evidence_sentence(candidate_evidence: dict[str, Any]) -> str:
    for field in ("work_experience", "projects"):
        for section in candidate_evidence.get("sections", []):
            if section.get("field") != field:
                continue
            for sentence in split_sentences(section.get("text", "")):
                clean = normalize_space(sentence)
                if clean and not is_resume_role_heading(clean) and not contains_contact_details(clean) and not contains_resume_section_heading(clean):
                    return clean if clean.endswith((".", "!", "?")) else f"{clean}."
    return ""


def is_resume_role_heading(value: str) -> bool:
    clean = normalize_space(value)
    return len(clean.split()) <= 10 and ("—" in clean or "|" in clean) and not any(char in clean for char in "!?;")


def matching_evidence_terms(job: dict[str, Any], candidate_evidence: dict[str, Any], limit: int = 3) -> list[str]:
    job_lower = normalize_space(" ".join(text(job.get(field)) for field in ["title", "required_skills", "preferred_skills", "responsibilities", "job_description"])).lower()
    evidence_lower = text(candidate_evidence.get("full_text")).lower()
    terms: list[str] = []
    for term in ["Python", "Flask", "PostgreSQL", "SQL", "JavaScript", "React", "API", "testing", "validation", "documentation", "reporting", "automation"]:
        if term.lower() in job_lower and term.lower() in evidence_lower and term.lower() not in {item.lower() for item in terms}:
            terms.append(term)
        if len(terms) >= limit:
            break
    return terms


def format_skills_guidance(skill_groups: dict[str, list[str]]) -> str:
    return "\n".join(
        [
            "Supported and relevant skills",
            ", ".join(skill_groups["supported_relevant"]) or "None found in both the posting and saved profile.",
            "",
            "Transferable supported skills",
            ", ".join(skill_groups["transferable_supported"]) or "None found.",
            "",
            "Unsupported job keywords - do not add",
            ", ".join(skill_groups["unsupported_job_keywords"]) or "None found.",
        ]
    )


def first_supported_role(profile: dict[str, str], candidate_evidence: dict[str, Any]) -> str:
    roles = [role for role in str(profile.get("preferred_roles") or "").split(",") if role.strip()]
    for role in roles:
        clean = role.strip()
        if clean and clean.lower() in str(candidate_evidence.get("full_text") or "").lower():
            return clean
    return roles[0].strip() if roles else ""


def generation_job_hash(job: dict[str, Any]) -> str:
    relevant = {
        field: text(job.get(field))
        for field in ["company", "title", "required_skills", "preferred_skills", "responsibilities", "job_description"]
    }
    return grounding_hash(json.dumps(relevant, sort_keys=True))


def build_cover_letter(profile: dict[str, str], job: dict[str, Any], focus: list[str], candidate_evidence: dict[str, Any]) -> str:
    return "\n\n".join(build_cover_letter_sections(profile, job, focus, candidate_evidence))


def build_cover_letter_sections(
    profile: dict[str, str],
    job: dict[str, Any],
    focus: list[str],
    candidate_evidence: dict[str, Any],
) -> list[str]:
    section_map = build_cover_letter_section_map(profile, job, focus, candidate_evidence)
    employer_line = section_map["company"] if not section_map["location"] else f"{section_map['company']}, {section_map['location']}"
    sections = [
        section_map["date"],
        employer_line,
        section_map["greeting"],
        section_map["subject"],
        section_map["opening"],
        section_map["experience"],
        section_map["fit"],
        section_map["closing"],
        section_map["signoff"],
        section_map["signature"],
    ]
    return [section for section in sections if normalize_space(section)]


def select_cover_letter_evidence(
    profile: dict[str, str],
    job: dict[str, Any],
    focus: list[str],
    candidate_evidence: dict[str, Any],
) -> list[str]:
    terms = list(dict.fromkeys([*focus, *matching_evidence_terms(job, candidate_evidence, limit=5)]))[:8]
    scored_snippets: list[tuple[int, int, str]] = []
    fallback_snippets: list[str] = []
    order = 0
    for section in candidate_evidence.get("sections", []):
        if section.get("field") == "resume_text":
            continue
        for sentence in split_sentences(section["text"]):
            clean = clean_cover_letter_evidence_sentence(sentence)
            if not clean or len(clean) > 400:
                continue
            if contains_resume_section_heading(clean) or contains_contact_details(clean) or is_resume_role_heading(clean):
                continue
            if classify_keyword_dump_reason(clean) is not None:
                continue
            fallback_snippets.append(trim_cover_letter_evidence(clean))
            score = 0
            lowered = clean.lower()
            if any(term in lowered for term in ["database", "data model", "data models", "schema"]):
                score += 4
            if any(term in lowered for term in ["validation", "testing", "logging", "quality", "reliability"]):
                score += 4
            if any(term in lowered for term in ["workflow", "automation", "integration", "integrations", "report", "reporting"]):
                score += 3
            if "documentation" in lowered or "documented" in lowered:
                score += 2
            if terms and any(contains_phrase(clean, term) or contains_phrase(term, clean) for term in terms):
                score += 3
            if section.get("field") == "projects":
                score += 2
            if any(char.isdigit() for char in clean):
                score += 2
            if 8 <= len(clean.split()) <= 30:
                score += 1
            scored_snippets.append((score, order, trim_cover_letter_evidence(clean)))
            order += 1
    if scored_snippets:
        ranked = [item[2] for item in sorted(scored_snippets, key=lambda item: (-item[0], item[1])) if item[0] > 0]
        if ranked:
            return ranked[:3]
    if fallback_snippets:
        return fallback_snippets[:3]
    if profile.get("projects"):
        project = text(profile.get("projects"))
        if project:
            return [trim_cover_letter_evidence(trim(project, 180))]
    return []


def trim_cover_letter_evidence(value: str, limit: int = 260) -> str:
    clean = normalize_space(value)
    if len(clean) <= limit:
        return clean
    boundary = max(clean.rfind(".", 0, limit), clean.rfind("!", 0, limit), clean.rfind("?", 0, limit))
    if boundary >= 80:
        return clean[: boundary + 1]
    return clean[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + "."


def truncate_text(value: str, limit: int) -> str:
    value = normalize_space(value)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def first_job_responsibility(job: dict[str, Any]) -> str:
    for field in ["responsibilities", "job_description"]:
        snippets = split_sentences(text(job.get(field)))
        if snippets:
            return trim(snippets[0], 140)
    return ""


def build_answers(profile: dict[str, str], job: dict[str, Any], focus: list[str], candidate_evidence: dict[str, Any]) -> list[dict[str, str]]:
    company = text(job.get("company")) or "the company"
    title = text(job.get("title")) or "this role"
    auth = profile.get("work_authorization") or "Yes, I am legally authorized to work in Canada."
    role = first_supported_role(profile, candidate_evidence) or "background"
    skill_phrase = ", ".join(focus[:3]) if focus else "my saved experience"
    snippets = supporting_snippets(focus, candidate_evidence, limit=1)
    evidence_line = snippets[0] if snippets else "My saved profile contains the supporting details for this application."
    return [
        {"question": COMMON_QUESTIONS[0], "answer": f"I am interested in {title} because it connects with my {role} experience and {skill_phrase}."},
        {"question": COMMON_QUESTIONS[1], "answer": f"{company} stood out because the role responsibilities appear aligned with the experience and skills saved in my profile."},
        {"question": COMMON_QUESTIONS[2], "answer": f"My relevant experience includes: {evidence_line}"},
        {"question": COMMON_QUESTIONS[3], "answer": auth},
        {"question": COMMON_QUESTIONS[4], "answer": "I am open to discussing compensation based on the scope of the role, growth expectations, and total package."},
        {"question": COMMON_QUESTIONS[5], "answer": "I can discuss a start date based on the interview timeline and team needs."},
        {"question": COMMON_QUESTIONS[6], "answer": "I would be glad to provide any additional details that help confirm fit for the role."},
    ]


def extract_quantified_tokens(value: str) -> Counter[str]:
    """Extract factual numeric tokens without treating ordinary word digits as claims."""
    normalized = text(value).replace("−", "-").replace("–", "-").replace("—", "-")
    tokens = re.findall(r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)?(?:\s*[%+])?(?![A-Za-z0-9])", normalized)
    return Counter(re.sub(r"\s+", "", token).lower() for token in tokens)


AI_CLAIM_TERMS = tuple(dict.fromkeys([
    *TECHNICAL_TERMS,
    "oauth", "google docs", "amazon", "idempotent", "idempotency", "real-time synchronization",
    "external platforms", "product pricing", "inventory systems", "relational data models",
    "role-based access", "tenant isolation", "audit trails", "database migrations",
]))


def _claim_term_present(value: str, term: str) -> bool:
    normalized_value = normalize_keyword(value)
    normalized_term = normalize_keyword(term)
    return bool(normalized_term and re.search(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])", normalized_value))


def _resume_claim_terms(value: str) -> set[str]:
    return {term for term in AI_CLAIM_TERMS if _claim_term_present(value, term)}


def validate_tailoring_bullet_suggestion(original: str, proposed: str) -> str:
    if not proposed:
        return "The AI assistant returned no proposed bullet."
    if extract_quantified_tokens(original) != extract_quantified_tokens(proposed):
        return "The suggestion changed quantified facts, versions, ranges, or percentages."
    original_terms = _resume_claim_terms(original)
    proposed_terms = _resume_claim_terms(proposed)
    omitted = sorted(term for term in original_terms if not _claim_term_present(proposed, term))
    introduced = sorted(term for term in proposed_terms if term not in original_terms)
    fact_errors = []
    if omitted:
        fact_errors.append(f"The suggestion omitted supported résumé facts: {', '.join(omitted[:4])}.")
    if introduced:
        fact_errors.append(f"The suggestion introduced unsupported résumé claims: {', '.join(introduced[:4])}.")
    if fact_errors:
        return " ".join(fact_errors)
    if contains_contact_details(proposed):
        return "The suggestion included contact details that do not belong in a résumé bullet."
    target_length = max(120, round(len(original) * 1.2))
    if len(proposed) > target_length:
        return f"The suggestion exceeded the target length budget of {target_length} characters."
    return ""

def build_ollama_prompt(kind: str, job: dict[str, Any], evidence: dict[str, Any], payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "kind": kind,
            "job": {
                "company": text(job.get("company")),
                "title": text(job.get("title")),
                "location": text(job.get("location")),
                "required_skills": text(job.get("required_skills")),
                "responsibilities": text(job.get("responsibilities")),
            },
            "evidence": [item.get("text", "") for item in evidence.get("sections", [])][:8],
            "constraints": {
                "no_new_facts": True,
                "json_only": True,
                "max_output_tokens": payload.get("max_output_tokens", 1200),
            },
        },
        indent=2,
    )


def validate_ollama_suggestion(kind: str, data: dict[str, Any], job: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    suggestion = text(data.get("suggestion") or data.get("text") or "")
    if not suggestion:
        return {"ok": False, "error": "Ollama returned no suggestion.", "suggestion": ""}
    if classify_keyword_dump_reason(suggestion) is not None:
        return {"ok": False, "error": "Ollama suggestion looked like a keyword dump.", "suggestion": ""}
    if kind == "cover_letter" and not any(term in suggestion.lower() for term in [text(job.get("company")).lower(), text(job.get("title")).lower()]):
        return {"ok": False, "error": "Ollama suggestion missed the job context.", "suggestion": ""}
    if not any(char.isdigit() for char in suggestion) and not any(term in suggestion.lower() for term in ["built", "implemented", "designed", "managed", "maintained", "developed"]):
        return {"ok": False, "error": "Ollama suggestion was not evidence-based enough.", "suggestion": ""}
    if evidence.get("full_text") and len(evidence["full_text"]) > 0 and not any(term in evidence["full_text"].lower() for term in re.findall(r"[a-z0-9+#.-]+", suggestion.lower())[:12]):
        return {"ok": False, "error": "Ollama suggestion introduced unsupported details.", "suggestion": ""}
    return {"ok": True, "error": "", "suggestion": suggestion}


def build_local_ollama_fallback(kind: str, job: dict[str, Any], evidence: dict[str, Any]) -> str:
    if kind == "cover_letter":
        section_map = build_cover_letter_section_map(load_profile(), job, [], evidence)
        return "\n\n".join([section_map["greeting"], section_map["opening"], section_map["experience"], section_map["fit"], section_map["closing"]])
    return build_summary(load_profile(), job, [], evidence)


def answers_to_text(answers: list[dict[str, str]]) -> str:
    return "\n\n".join([f"{item['question']}\n{item['answer']}" for item in answers])


def save_version(job_id: int, kind: str, content: str, profile_hash: str = "", job_hash: str = "") -> int:
    cursor = get_db().execute(
        """
        INSERT INTO generated_versions (job_id, kind, content, profile_hash, job_hash, status)
        VALUES (?, ?, ?, ?, ?, 'current')
        """,
        [job_id, kind, content, profile_hash, job_hash],
    )
    get_db().commit()
    return int(cursor.lastrowid)


def generate_follow_up(company: str, title: str, date_applied: str) -> str:
    date_line = f" I applied on {date_applied}." if date_applied else ""
    return (
        f"Subject: Following up on {title}\n\n"
        f"Hello {company} Hiring Team,\n\n"
        f"I hope you are doing well.{date_line} I wanted to follow up on my application for the "
        f"{title} role and reaffirm my interest. The role looks aligned with the experience and "
        f"skills in my saved profile.\n\n"
        f"Please let me know if there is any additional information I can provide.\n\n"
        f"Best,\n"
    )


def build_dashboard(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    applied = [job for job in jobs if job["status"] == "Applied"]
    interviews = [job for job in jobs if job["status"] == "Interview"]
    rejected = [job for job in jobs if job["status"] == "Rejected"]
    by_role = count_by(jobs, "role_type")
    by_source = count_by(jobs, "source")
    return {
        "jobs_saved": len(jobs),
        "applications_this_week": sum(1 for job in jobs if job["date_applied"] and parse_date(job["date_applied"]) >= week_start),
        "follow_ups_needed": sum(1 for job in applied if job["date_applied"] and parse_date(job["date_applied"]) <= today - timedelta(days=7)),
        "high_fit": sum(1 for job in jobs if int(job["fit_score"] or 0) >= 75),
        "average_fit_score": round(sum(int(job["fit_score"] or 0) for job in jobs) / len(jobs), 1) if jobs else 0,
        "by_role_type": by_role,
        "by_source": by_source,
        "interview_rate": round(len(interviews) / len(applied) * 100, 1) if applied else 0,
        "rejection_rate": round(len(rejected) / len(applied) * 100, 1) if applied else 0,
        "missing_salary": sum(1 for job in jobs if not job["salary"]),
        "high_coding_risk": sum(1 for job in jobs if int(job["coding_risk_score"] or 100) < 60),
        "pending": sum(1 for job in jobs if job["status"] in {"Saved", "Drafting", "Applied", "Interview"}),
    }


def count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = text(row.get(field)) or "Unspecified"
        counts[key] = counts.get(key, 0) + 1
    return counts


def fetch_public_page_text(url: str) -> str:
    if not re.match(r"^https?://", url):
        raise ValueError("Only http and https URLs are supported.")
    blocked_hosts = ["linkedin.com", "indeed.com"]
    if any(host in url.lower() for host in blocked_hosts):
        raise ValueError("Direct scraping of restricted job platforms is intentionally disabled. Paste the job text or import a CSV link instead.")
    request_obj = urllib.request.Request(url, headers={"User-Agent": "LocalJobAssistant/1.0"})
    try:
        with urllib.request.urlopen(request_obj, timeout=8) as response:
            content_type = response.headers.get("Content-Type", "")
            raw = response.read(MAX_FETCH_BYTES)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ValueError(f"Could not read that public URL: {exc}") from exc
    if "text/html" not in content_type and "text/plain" not in content_type:
        raise ValueError("That URL did not return readable text or HTML.")
    html_text = raw.decode("utf-8", errors="replace")
    return html_to_text(html_text)


def html_to_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", markup)
    markup = re.sub(r"(?i)<br\s*/?>", "\n", markup)
    markup = re.sub(r"(?i)</(p|div|li|h[1-6])>", "\n", markup)
    return normalize_space(html.unescape(re.sub(r"<[^>]+>", " ", markup)))


def source_from_url(url: str) -> str:
    match = re.search(r"https?://(?:www\.)?([^/]+)", url)
    return match.group(1) if match else "Public URL"


def import_csv_jobs(content: str) -> int:
    reader = csv.DictReader(io.StringIO(content))
    imported = 0
    for row in reader:
        if not any(row.values()):
            continue
        payload = {
            "company": row.get("company") or row.get("Company") or "",
            "title": row.get("title") or row.get("Title") or "",
            "location": row.get("location") or row.get("Location") or "",
            "url": row.get("url") or row.get("URL") or row.get("link") or row.get("Link") or "",
            "source": row.get("source") or row.get("Source") or "CSV import",
            "salary": row.get("salary") or row.get("Salary") or "",
            "job_description": row.get("job_description") or row.get("description") or "",
        }
        clean = normalize_job_payload(payload)
        get_db().execute(
            f"INSERT INTO jobs ({', '.join(JOB_COLUMNS.keys())}) VALUES ({', '.join(['?'] * len(JOB_COLUMNS))})",
            tuple(clean[column] for column in JOB_COLUMNS),
        )
        imported += 1
    get_db().commit()
    return imported


def extract_uploaded_text(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".txt":
        return content.decode("utf-8", errors="replace")
    if suffix == ".docx":
        return extract_docx_text(content)
    if suffix == ".pdf":
        return extract_pdf_text(content)
    raise ValueError("Supported uploads are .txt, .docx, and basic text-readable .pdf files.")


def extract_docx_text(content: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise ValueError("Could not read that .docx file.") from exc
    root = ElementTree.fromstring(xml)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for paragraph in root.iter(f"{namespace}p"):
        texts = [node.text or "" for node in paragraph.iter(f"{namespace}t")]
        if texts:
            paragraphs.append("".join(texts))
    return "\n".join(paragraphs)


def extract_docx_profile_sections(path_value: str) -> dict[str, str]:
    """Extract résumé content by section without treating tables as prose."""
    path = safe_local_path(path_value)
    if path is None or not path.is_file():
        return {}
    try:
        document = Document(path)
    except (OSError, ValueError, zipfile.BadZipFile):
        return {}
    sections = {"summary": [], "work_experience": [], "key_skills": [], "projects": [], "education": []}
    heading_map = {
        "summary": "summary", "professional summary": "summary", "profile summary": "summary", "resume summary": "summary",
        "experience": "work_experience", "work experience": "work_experience", "professional experience": "work_experience",
        "skills": "key_skills", "technical skills": "key_skills", "core skills": "key_skills",
        "projects": "projects", "selected projects": "projects", "education": "education",
    }
    current = ""
    for paragraph in document.paragraphs:
        value = normalize_space(paragraph.text)
        if not value:
            continue
        heading = value.lower().rstrip(":")
        style_name = normalize_space(getattr(getattr(paragraph, "style", None), "name", "")).lower()
        if heading in heading_map:
            current = heading_map[heading]
            continue
        if not current or contains_contact_details(value) or value == value.upper() and len(value.split()) <= 5:
            continue
        if current == "work_experience" and not value.endswith((".", "!", "?")) and (style_name.startswith("heading") or "—" in value or "|" in value):
            value = f"{value}."
        sections[current].append(value)
    if current == "key_skills":
        for table in document.tables:
            for row in table.rows:
                values = [normalize_space(cell.text) for cell in row.cells]
                values = [value for value in values if value]
                if not values or all(value.lower() in {"area", "tools and practices", "skill", "skills"} for value in values):
                    continue
                line = ": ".join(values)
                if line not in sections["key_skills"]:
                    sections["key_skills"].append(line)
    cleaned = {key: "\n".join(dict.fromkeys(value for value in values if value)) for key, values in sections.items()}
    ordered = [cleaned[key] for key in ["summary", "work_experience", "key_skills", "projects", "education"] if cleaned[key]]
    cleaned["resume_text"] = "\n".join(ordered)
    return cleaned


def extract_pdf_text(content: bytes) -> str:
    cleaned = extract_pdf_text_with_library(content) or extract_pdf_text_basic(content)
    if not cleaned.strip() or is_corrupted_text(cleaned):
        raise ValueError(PDF_CORRUPTION_MESSAGE)
    return cleaned


def extract_pdf_text_with_library(content: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except Exception:
            return ""
    try:
        reader = PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages[:10]]
    except Exception:
        return ""
    return normalize_space("\n".join(pages))


def extract_pdf_text_basic(content: bytes) -> str:
    decoded = content.decode("latin-1", errors="ignore")
    chunks = re.findall(r"\(([^()]{2,})\)\s*Tj", decoded)
    if not chunks:
        chunks = re.findall(r"\[(.*?)\]\s*TJ", decoded, flags=re.S)
    if not chunks:
        chunks = re.findall(r"\(([^()]{2,})\)", decoded)
    cleaned_chunks = []
    for chunk in chunks:
        pieces = re.findall(r"\(([^()]*)\)", chunk) or [chunk]
        cleaned_chunks.extend(
            html.unescape(piece.replace("\\n", "\n").replace("\\(", "(").replace("\\)", ")").replace("\\r", "\n"))
            for piece in pieces
        )
    return normalize_space("\n".join(cleaned_chunks))


def download_response(content: str, filename: str, mimetype: str) -> Response:
    return Response(
        content,
        mimetype=mimetype,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def make_docx(content: str) -> bytes:
    paragraphs = "".join(
        f"<w:p><w:r><w:t xml:space=\"preserve\">{html.escape(line)}</w:t></w:r></w:p>"
        for line in content.splitlines()
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{paragraphs}</w:body></w:document>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", DOCX_CONTENT_TYPES)
        archive.writestr("_rels/.rels", DOCX_RELS)
        archive.writestr("word/document.xml", document)
    return output.getvalue()


DOCX_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

DOCX_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
