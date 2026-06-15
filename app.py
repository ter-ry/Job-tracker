from __future__ import annotations

import csv
import html
import io
import json
import os
import re
import shutil
import sqlite3
import urllib.error
import urllib.request
import zipfile
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from docx import Document
from flask import Flask, Response, g, jsonify, render_template, request, send_file

from grounding import (
    PDF_CORRUPTION_MESSAGE,
    build_candidate_evidence,
    classify_supported_skills,
    contains_contact_details,
    contains_resume_section_heading,
    evidence_has_generation_source,
    is_corrupted_text,
    job_keywords,
    stable_hash as grounding_hash,
    supporting_snippets,
    validate_cover_letter_output,
    validate_generated_content,
)
from semantic_matching import MODEL_DOWNLOAD_SIZE, MODEL_NAME, analyze_resume_match
from seniority import DETECTED_LEVELS, SENIORITY_LEVELS, analyze_job_seniority, score_seniority_fit
from sources.jobspy_source import fetch_jobspy_jobs
from tailoring import controlled_rewrite, generate_tailored_resume_draft
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("JOB_TRACKER_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "jobs.sqlite"
MAX_FETCH_BYTES = 1_200_000
DISCOVERY_SOURCES = ["linkedin", "indeed", "google", "zip_recruiter"]
GENERATED_APPLICATIONS_DIRNAME = "generated_applications"
SEMANTIC_CACHE_DIRNAME = "semantic_cache"

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
    "deadline": "TEXT NOT NULL DEFAULT ''",
    "fit_score": "INTEGER NOT NULL DEFAULT 0",
    "status": "TEXT NOT NULL DEFAULT 'Saved'",
    "notes": "TEXT NOT NULL DEFAULT ''",
    "date_added": "TEXT NOT NULL DEFAULT ''",
    "date_applied": "TEXT NOT NULL DEFAULT ''",
    "job_description": "TEXT NOT NULL DEFAULT ''",
    "remote_type": "TEXT NOT NULL DEFAULT ''",
    "role_type": "TEXT NOT NULL DEFAULT ''",
    "seniority_level": "TEXT NOT NULL DEFAULT ''",
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
    "generation_error": "TEXT NOT NULL DEFAULT ''",
    "generated_at": "TEXT NOT NULL DEFAULT ''",
    "profile_updated_at": "TEXT NOT NULL DEFAULT ''",
}

PROFILE_COLUMNS = {
    "name": "TEXT NOT NULL DEFAULT ''",
    "email": "TEXT NOT NULL DEFAULT ''",
    "phone": "TEXT NOT NULL DEFAULT ''",
    "location": "TEXT NOT NULL DEFAULT ''",
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
    "target_seniority_levels": "TEXT NOT NULL DEFAULT 'entry_level,junior,intermediate'",
    "maximum_required_years": "TEXT NOT NULL DEFAULT '3'",
    "willing_to_apply_to_stretch_roles": "TEXT NOT NULL DEFAULT 'true'",
    "management_roles_allowed": "TEXT NOT NULL DEFAULT 'false'",
}


def create_app() -> Flask:
    app = Flask(__name__)

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

    @app.post("/api/profile")
    def save_profile() -> Response:
        payload = request.get_json(force=True)
        profile = normalize_profile_payload(payload, load_profile())
        upsert_profile(profile)
        return jsonify(load_profile())

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
        clean = normalize_job_payload({**payload, "status": "shortlisted"})
        existing = find_existing_shortlist(clean)
        if existing is not None:
            return jsonify({**job_to_dict(existing), "duplicate": True})

        today = date.today().isoformat()
        clean["status"] = "shortlisted"
        clean["date_shortlisted"] = text(clean.get("date_shortlisted")) or today
        clean["date_added"] = text(clean.get("date_added")) or today
        clean["resume_generation_status"] = "pending"
        clean["cover_letter_generation_status"] = "pending"
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
        generation = generate_and_store_shortlist_documents(job_id)
        job = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        return jsonify({**job_to_dict(job), "generation": generation, "duplicate": False}), 201

    @app.post("/api/shortlist/<int:job_id>/regenerate")
    def regenerate_shortlist_documents(job_id: int) -> Response:
        job = query_db("SELECT * FROM jobs WHERE id = ? AND status = 'shortlisted'", [job_id], one=True)
        if job is None:
            return jsonify({"error": "Shortlisted job not found"}), 404
        generation = generate_and_store_shortlist_documents(job_id)
        refreshed = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
        return jsonify({**job_to_dict(refreshed), "generation": generation})

    @app.delete("/api/shortlist/<int:job_id>")
    def remove_shortlist_item(job_id: int) -> Response:
        existing = query_db("SELECT * FROM jobs WHERE id = ? AND status = 'shortlisted'", [job_id], one=True)
        if existing is None:
            return jsonify({"error": "Shortlisted job not found"}), 404
        get_db().execute("UPDATE jobs SET status = 'Archived', updated_at = CURRENT_TIMESTAMP WHERE id = ?", [job_id])
        get_db().commit()
        return jsonify({"ok": True})

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

    @app.post("/api/discovery/jobspy")
    def discovery_jobspy() -> Response:
        payload = request.get_json(force=True)
        keywords = text(payload.get("keywords"))
        if not keywords:
            return jsonify({"error": "Keywords are required"}), 400

        location = text(payload.get("location"))
        enabled_sources = normalize_discovery_sources(payload.get("enabled_sources"))
        results_wanted = clamp_int_default(payload.get("results_wanted"), 10, 1, 25)
        hours_old = clamp_int_default(payload.get("hours_old"), 168, 1, 24 * 30)
        distance = clamp_int_default(payload.get("distance"), 50, 0, 500)
        remote_preference = normalize_choice(payload.get("remote_preference"), {"remote", "hybrid", "on-site"})
        job_type = normalize_choice(payload.get("job_type"), {"fulltime", "parttime", "contract", "internship"})
        country_indeed = text(payload.get("country_indeed")) or "Canada"

        fetched = fetch_jobspy_jobs(
            keywords=keywords,
            location=location,
            distance=distance,
            remote_preference=remote_preference,
            job_type=job_type,
            results_wanted=results_wanted,
            hours_old=hours_old,
            enabled_sources=enabled_sources,
            country_indeed=country_indeed,
        )

        existing_keys = existing_job_dedupe_keys()
        seen_keys: set[str] = set()
        jobs: list[dict[str, Any]] = []
        duplicates = 0
        for raw_job in fetched.get("jobs", []):
            payload_job = jobspy_result_to_job_payload(raw_job)
            clean = normalize_job_payload(payload_job)
            clean["source_job_id"] = text(raw_job.get("source_job_id"))
            clean["posted_date"] = text(raw_job.get("posted_date"))
            clean["description_available"] = bool(clean.get("job_description"))
            clean["score_breakdown"] = parse_json_object(clean.get("score_breakdown"))
            clean["warnings"] = discovery_warning_reasons(clean, keywords, location)
            clean["already_saved"] = False
            clean["duplicate_in_search"] = False
            keys = dedupe_keys(clean, clean.get("source_job_id"))
            duplicate_found = False
            if keys & existing_keys:
                clean["already_saved"] = True
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

        jobs.sort(key=lambda job: int(job.get("fit_score") or 0), reverse=True)
        return jsonify(
            {
                "jobs": jobs,
                "errors": fetched.get("errors", {}),
                "source_counts": source_counts,
                "total": len(jobs),
                "duplicates": duplicates,
            }
        )

    @app.post("/api/generate")
    def generate_materials() -> Response:
        payload = request.get_json(force=True)
        job = normalize_job_payload(payload)
        profile = load_profile()
        result = generate_application_materials(job, profile)
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
        current_profile_hash = build_candidate_evidence(load_profile())["hash"]
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
            "salary_text": job.get("salary_text"),
            "job_description": description,
        }
    )
    return {
        "company": text(job.get("company")) or "Unknown company",
        "title": text(job.get("title")) or "Untitled role",
        "location": text(job.get("location")),
        "url": text(job.get("job_url")),
        "application_url": text(job.get("application_url")) or text(job.get("job_url")),
        "source": source.title() if source else "JobSpy",
        "salary": salary["salary_text"],
        "salary_min": salary["salary_min"],
        "salary_max": salary["salary_max"],
        "salary_interval": salary["salary_interval"],
        "salary_currency": salary["salary_currency"],
        "salary_source": salary["salary_source"],
        "salary_confidence": salary["salary_confidence"],
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


def find_existing_shortlist(job: dict[str, Any]) -> sqlite3.Row | None:
    keys = dedupe_keys(job, job.get("source_job_id"))
    rows = query_db("SELECT * FROM jobs WHERE status = 'shortlisted'")
    for row in rows:
        existing = job_to_dict(row)
        if keys & dedupe_keys(existing, existing.get("source_job_id")):
            return row
    return None


def generated_applications_dir() -> Path:
    return DATA_DIR / GENERATED_APPLICATIONS_DIRNAME


def generate_and_store_shortlist_documents(job_id: int) -> dict[str, Any]:
    job_row = query_db("SELECT * FROM jobs WHERE id = ?", [job_id], one=True)
    if job_row is None:
        return {"resume": "failed", "cover_letter": "failed", "error": "Job not found"}
    job = job_to_dict(job_row)
    profile = load_profile()
    if not profile_has_generation_source(profile):
        error = "Complete the Profile page with resume, project, or work-experience details before generating documents."
        update_generation_status(job_id, "failed", "failed", "", "", error)
        return {"resume": "failed", "cover_letter": "failed", "error": error}

    try:
        output = generate_application_materials(job, profile)
        folder = generated_applications_dir() / str(job_id)
        folder.mkdir(parents=True, exist_ok=True)
        base = safe_filename("_".join([profile.get("name") or "Candidate", job.get("company") or "Company", job.get("title") or "Role"]))
        resume_name = safe_filename(f"{base}_Resume.docx")
        cover_name = safe_filename(f"{base}_Cover_Letter.docx")
        resume_path = folder / resume_name
        cover_path = folder / cover_name
        resume_result = build_format_preserving_resume(job, profile, output, resume_path)
        cover_result = build_format_preserving_cover_letter(job, profile, output, cover_path)
        metadata = {
            "job_id": job_id,
            "company": job.get("company"),
            "title": job.get("title"),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "matched_keywords": output.get("matched_keywords", []),
            "salary_source": job.get("salary_source"),
            "fit_score": job.get("fit_score"),
            "resume_template_path": profile.get("resume_docx_template_path", ""),
            "cover_letter_template_path": profile.get("cover_letter_docx_template_path", ""),
        }
        (folder / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        (folder / "resume.txt").write_text(output["resume_text"], encoding="utf-8")
        (folder / "cover_letter.txt").write_text(output["cover_letter"], encoding="utf-8")
        (folder / "resume_change_log.json").write_text(json.dumps(resume_result["change_log"], indent=2), encoding="utf-8")
        (folder / "cover_letter_change_log.json").write_text(json.dumps(cover_result["change_log"], indent=2), encoding="utf-8")
        update_generation_status(
            job_id,
            resume_result["status"],
            cover_result["status"],
            str(resume_path) if resume_result["status"] == "generated" else "",
            str(cover_path) if cover_result["status"] == "generated" else "",
            "; ".join(filter(None, [resume_result["error"], cover_result["error"]])),
        )
        return {
            "resume": resume_result["status"],
            "cover_letter": cover_result["status"],
            "error": "; ".join(filter(None, [resume_result["error"], cover_result["error"]])),
        }
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        update_generation_status(job_id, "failed", "failed", "", "", error)
        return {"resume": "failed", "cover_letter": "failed", "error": error}


def profile_has_generation_source(profile: dict[str, str]) -> bool:
    return evidence_has_generation_source(build_candidate_evidence(profile))


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

    shutil.copyfile(template_path, resume_path)
    document = Document(resume_path)
    plan = build_resume_change_plan(document, job, profile, output)
    change_log = apply_resume_change_plan(document, plan)
    document.save(resume_path)
    return {
        "status": "generated",
        "error": "",
        "change_log": {
            "master_resume_path": str(template_path),
            "output_path": str(resume_path),
            **change_log,
        },
    }


def build_format_preserving_cover_letter(
    job: dict[str, Any],
    profile: dict[str, str],
    output: dict[str, Any],
    cover_path: Path,
) -> dict[str, Any]:
    template_raw = text(profile.get("cover_letter_docx_template_path"))
    template_path = safe_local_path(template_raw)
    warning = ""
    if template_path is None or not template_path.exists():
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

    shutil.copyfile(template_path, cover_path)
    document = Document(cover_path)
    change_log = apply_cover_letter_template(document, job, profile, output)
    document.save(cover_path)
    return {
        "status": "generated",
        "error": warning,
        "change_log": {
            "master_cover_letter_path": str(template_path),
            "output_path": str(cover_path),
            **change_log,
        },
    }


def apply_cover_letter_template(
    document: Document,
    job: dict[str, Any],
    profile: dict[str, str],
    output: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    paragraphs = list(iter_document_paragraphs(document))
    focus = list(output.get("supported_keywords", [])[:4])
    generated_sections = build_cover_letter_sections(profile, job, focus, build_candidate_evidence(profile))
    replacements = {
        "{{DATE}}": date.today().isoformat(),
        "{{COMPANY}}": text(job.get("company")) or "your team",
        "{{JOB_TITLE}}": text(job.get("title")) or "the role",
        "{{HIRING_MANAGER}}": f"{text(job.get('company')) or 'the company'} Hiring Team",
        "{{OPENING_PARAGRAPH}}": generated_sections[1],
        "{{EXPERIENCE_PARAGRAPH}}": generated_sections[2],
        "{{FIT_PARAGRAPH}}": generated_sections[3],
        "{{CLOSING_PARAGRAPH}}": "\n\n".join(generated_sections[4:6]),
    }
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    placeholder_hits = 0

    for paragraph in paragraphs:
        original = paragraph.text
        if not original.strip():
            continue
        replaced = False
        for placeholder, replacement in replacements.items():
            if placeholder in original:
                if replace_paragraph_text(paragraph, original, original.replace(placeholder, replacement)):
                    applied.append(
                        {
                            "kind": "placeholder",
                            "original": original,
                            "replacement": original.replace(placeholder, replacement),
                            "matched_job_requirement": placeholder,
                            "supporting_evidence": "",
                            "confidence": 95,
                            "validation_status": "passed",
                        }
                    )
                    placeholder_hits += 1
                    replaced = True
                break
        if replaced:
            continue

    if placeholder_hits:
        return {"applied": applied, "skipped": skipped, "template_mode": "placeholder"}

    editable_sections = generated_sections[1:5]
    editable_paragraphs = [paragraph for paragraph in paragraphs if is_editable_cover_letter_paragraph(paragraph)]
    for paragraph, replacement in zip(editable_paragraphs, editable_sections):
        original = paragraph.text
        if not original.strip():
            continue
        if replace_paragraph_text(paragraph, original, replacement):
            applied.append(
                {
                    "kind": "paragraph",
                    "original": original,
                    "replacement": replacement,
                    "matched_job_requirement": text(job.get("title")) or "",
                    "supporting_evidence": "",
                    "confidence": 80,
                    "validation_status": "passed",
                }
            )
        else:
            skipped.append({"kind": "paragraph", "original": original, "replacement": replacement, "reason": "Paragraph text did not match."})
    return {"applied": applied, "skipped": skipped, "template_mode": "fallback"}


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


def build_resume_change_plan(
    document: Document,
    job: dict[str, Any],
    profile: dict[str, str],
    output: dict[str, Any],
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    paragraphs = list(iter_document_paragraphs(document))
    candidate_evidence = build_candidate_evidence(profile)
    summary_paragraph = find_section_paragraph(paragraphs, SUMMARY_HEADINGS)
    if summary_paragraph is not None:
        plan.append(
            {
                "kind": "summary",
                "paragraph_type": "summary_paragraph",
                "original": summary_paragraph.text,
                "replacement": output.get("summary", ""),
                "supporting_evidence": supporting_snippet_for_plan(candidate_evidence, output, job),
                "matched_job_requirement": text(job.get("title")),
                "confidence": 90,
                "validation_status": "passed",
            }
        )
    else:
        plan.append(
            {
                "kind": "summary",
                "paragraph_type": "summary_paragraph",
                "original": "",
                "replacement": "",
                "supporting_evidence": "",
                "matched_job_requirement": "",
                "confidence": 0,
                "validation_status": "skipped",
                "reason": "Skipped summary tailoring: no existing summary section",
            }
        )

    skills_paragraph = find_section_paragraph(paragraphs, SKILLS_HEADINGS)
    supported_skills = output.get("skill_guidance", {}).get("supported_relevant", [])
    if skills_paragraph is not None and supported_skills:
        replacement = reorder_skills_text(skills_paragraph.text, supported_skills)
        if normalize_space(replacement) != normalize_space(skills_paragraph.text):
            plan.append(
                {
                    "kind": "skills",
                    "paragraph_type": "skills_paragraph",
                    "original": skills_paragraph.text,
                    "replacement": replacement,
                    "supporting_evidence": ", ".join(supported_skills[:8]),
                    "matched_job_requirement": "Supported skills already present in the saved profile and posting",
                    "confidence": 75,
                    "validation_status": "passed",
                }
            )

    for suggestion in output.get("local_tailored_draft", {}).get("rewrite_suggestions", []):
        original = text(suggestion.get("original_bullet"))
        replacement = text(suggestion.get("proposed_bullet"))
        confidence = clamp_int(suggestion.get("confidence"), 0, 100)
        if not original or not replacement:
            continue
        if confidence < 60:
            continue
        plan.append(
            {
                "kind": "bullet",
                "paragraph_type": "bullet_paragraph",
                "original": original,
                "replacement": replacement,
                "supporting_evidence": text(suggestion.get("supporting_evidence")),
                "matched_job_requirement": text(suggestion.get("matched_job_requirement")),
                "confidence": confidence,
                "validation_status": "pending",
            }
        )

    planned_originals = {item["original"] for item in plan if item.get("original")}
    job_requirement = text(job.get("required_skills")) or text(job.get("job_description")) or text(job.get("title"))
    for paragraph in paragraphs:
        if not is_editable_resume_paragraph(paragraph, "bullet"):
            continue
        original = normalize_space(paragraph.text)
        if not original or original in planned_originals:
            continue
        replacement = controlled_rewrite(original, job_requirement)
        if normalize_space(replacement) == original:
            continue
        plan.append(
            {
                "kind": "bullet",
                "paragraph_type": "bullet_paragraph",
                "original": original,
                "replacement": replacement,
                "supporting_evidence": original,
                "matched_job_requirement": job_requirement,
                "confidence": 70,
                "validation_status": "pending",
            }
        )
        planned_originals.add(original)
    return plan


def supporting_snippet_for_plan(candidate_evidence: dict[str, Any], output: dict[str, Any], job: dict[str, Any]) -> str:
    snippets = supporting_snippets(output.get("supported_keywords", [])[:4], candidate_evidence, limit=1)
    if snippets:
        return snippets[0]
    return text(job.get("job_description"))[:160]


def apply_resume_change_plan(document: Document, plan: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    paragraphs = list(iter_document_paragraphs(document))
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in plan:
        if item.get("validation_status") == "skipped":
            skipped.append(item)
            continue
        kind = item["kind"]
        if kind in {"summary", "skills"}:
            target = find_section_paragraph(paragraphs, SUMMARY_HEADINGS if kind == "summary" else SKILLS_HEADINGS)
            if target is None:
                skipped.append({**item, "reason": f"No {kind} section found in master resume."})
                continue
            if kind == "summary" and not is_editable_resume_paragraph(target, "summary"):
                skipped.append({**item, "reason": "Summary paragraph is protected or not editable."})
                continue
            if kind == "skills" and not is_editable_resume_paragraph(target, "skills"):
                skipped.append({**item, "reason": "Skills paragraph is protected or not editable."})
                continue
            if replace_paragraph_exact(target, item["original"], item["replacement"]):
                applied.append(item)
            else:
                skipped.append({**item, "reason": "Exact paragraph text was not found."})
            continue

        matched = False
        for paragraph in paragraphs:
            if not is_editable_resume_paragraph(paragraph, "bullet"):
                continue
            if replace_paragraph_exact(paragraph, item["original"], item["replacement"]):
                applied.append(item)
                matched = True
                break
        if not matched:
            skipped.append({**item, "reason": "Exact bullet text was not found."})
    return {"applied": applied, "skipped": skipped}


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
    error: str,
) -> None:
    generated_at = datetime.now().isoformat(timespec="seconds") if resume_status == "generated" or cover_status == "generated" else ""
    profile_updated = text(load_profile().get("updated_at"))
    get_db().execute(
        """
        UPDATE jobs
        SET resume_generation_status = ?,
            cover_letter_generation_status = ?,
            resume_docx_path = COALESCE(NULLIF(?, ''), resume_docx_path),
            cover_letter_docx_path = COALESCE(NULLIF(?, ''), cover_letter_docx_path),
            generation_error = ?,
            generated_at = ?,
            profile_updated_at = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        [resume_status, cover_status, resume_path, cover_path, error, generated_at, profile_updated, job_id],
    )
    get_db().commit()


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


def normalize_profile_payload(payload: dict[str, Any], existing: dict[str, str] | None = None) -> dict[str, str]:
    existing = existing or {}
    profile = {field: text(payload.get(field, existing.get(field))) for field in PROFILE_COLUMNS}
    profile["target_seniority_levels"] = normalize_seniority_levels(payload.get("target_seniority_levels"))
    profile["maximum_required_years"] = text(payload.get("maximum_required_years")) or "3"
    profile["willing_to_apply_to_stretch_roles"] = normalize_bool_text(payload.get("willing_to_apply_to_stretch_roles"), True)
    profile["management_roles_allowed"] = normalize_bool_text(payload.get("management_roles_allowed"), False)
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


def normalize_job_payload(payload: dict[str, Any]) -> dict[str, Any]:
    today = date.today().isoformat()
    extracted = extract_job_details(
        text(payload.get("job_description")),
        text(payload.get("source")),
        existing=payload,
    )
    clean = {column: text(payload.get(column, extracted.get(column, ""))) for column in JOB_COLUMNS}
    clean["date_added"] = text(payload.get("date_added")) or today
    clean["status"] = clean["status"] if clean["status"] in STATUSES else "Saved"
    clean["fit_score"] = clamp_int(payload.get("fit_score"), 0, 100)
    salary = determine_salary({**payload, **extracted, **clean})
    for field in ["salary_min", "salary_max", "salary_interval", "salary_currency", "salary_source", "salary_confidence"]:
        clean[field] = salary[field]
    clean["salary"] = salary["salary_text"]

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
    clean["score_breakdown"] = json.dumps(scoring["breakdown"])
    return clean


def job_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    data = dict(row)
    data["score_breakdown"] = parse_json_object(data.get("score_breakdown"))
    if "profile_updated_at" in data and data.get("profile_updated_at"):
        profile_row = query_db("SELECT updated_at FROM profile WHERE id = 1", one=True)
        current_profile_updated = text(profile_row["updated_at"]) if profile_row else ""
        if current_profile_updated and data["profile_updated_at"] != current_profile_updated:
            if data.get("resume_generation_status") == "generated":
                data["resume_generation_status"] = "Outdated — regenerate using current profile"
            if data.get("cover_letter_generation_status") == "generated":
                data["cover_letter_generation_status"] = "Outdated — regenerate using current profile"
    return data


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
    profile_text = " ".join(profile.values()).lower()
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


def generate_application_materials(job: dict[str, Any], profile: dict[str, str]) -> dict[str, Any]:
    candidate_evidence = build_candidate_evidence(profile)
    if not evidence_has_generation_source(candidate_evidence):
        raise ValueError("Complete the Profile page with resume, project, or work-experience details before generating documents.")
    job_text = " ".join([text(job.get("title")), text(job.get("job_description")), text(job.get("required_skills"))])
    semantic = analyze_resume_match(job, profile, cache_dir=semantic_cache_dir(), use_semantic=False)
    seniority_analysis = analyze_job_seniority(job)
    seniority_fit = score_seniority_fit(profile, seniority_analysis)
    scoring = score_job(job, profile, semantic)
    tailored = generate_tailored_resume_draft(job, profile, semantic, seniority_fit)
    skill_groups = classify_supported_skills(job, candidate_evidence)
    matched = job_keywords(job)
    supported = skill_groups["supported_relevant"]
    unsupported = skill_groups["unsupported_job_keywords"]
    transferable = skill_groups["transferable_supported"]
    focus = supported[:4]
    resume_lines = [item["proposed_bullet"] for item in tailored["rewrite_suggestions"]] or source_backed_bullets(profile, focus)
    summary = build_summary(profile, job, focus, candidate_evidence)
    skills_section = format_skills_guidance(skill_groups)
    cover_letter = build_cover_letter(profile, job, focus, candidate_evidence)
    cover_validation = validate_cover_letter_output(cover_letter, candidate_evidence, job)
    if not cover_validation["ok"]:
        conflicts = ", ".join(cover_validation["conflicting_phrases"]) or "empty or corrupted candidate evidence"
        raise ValueError(f"Generated cover letter failed grounding validation. Unsupported or conflicting phrases: {conflicts}")
    answers = build_answers(profile, job, focus, candidate_evidence)
    resume_text = (
        f"Suggested summary\n{summary}\n\n"
        f"Suggested skills guidance\n{skills_section}\n\n"
        f"Suggested bullet rewrites\n" + "\n".join([f"- {line}" for line in resume_lines]) + "\n\n"
        f"Unsupported job keywords - do not add\n{', '.join(unsupported) or 'None from the current posting.'}"
    )
    local_tailored_text = tailored["text"]
    validation = validate_generated_content("\n\n".join([resume_text, cover_letter, answers_to_text(answers)]), candidate_evidence, job)
    if not validation["ok"]:
        conflicts = ", ".join(validation["conflicting_phrases"]) or "empty or corrupted candidate evidence"
        raise ValueError(f"Generated content failed grounding validation. Unsupported or conflicting phrases: {conflicts}")
    return {
        "fit_score": scoring["fit_score"],
        "score_breakdown": scoring,
        "matched_keywords": matched,
        "supported_keywords": supported,
        "missing_keywords": transferable,
        "unsupported_keywords": unsupported,
        "skill_guidance": skill_groups,
        "candidate_evidence_hash": candidate_evidence["hash"],
        "job_hash": generation_job_hash(job),
        "validation": validation,
        "summary": summary,
        "skills_section": skills_section,
        "resume_bullets": resume_lines,
        "resume_text": resume_text,
        "local_tailored_draft": tailored,
        "local_tailored_text": local_tailored_text,
        "semantic_match": semantic,
        "seniority_analysis": seniority_analysis,
        "seniority_fit": seniority_fit,
        "cover_letter": cover_letter,
        "short_answers": answers,
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
    target = text(job.get("title")) or "target role"
    role = first_supported_role(profile, candidate_evidence)
    snippets = supporting_snippets(focus, candidate_evidence, limit=2)
    skill_phrase = ", ".join(focus[:4]) if focus else "documented profile experience"
    base = f"{role or 'Candidate'} for {target} with supported experience in {skill_phrase}."
    if snippets:
        return f"{base} Evidence includes {snippets[0]}"
    return f"{base} Summary kept conservative because saved evidence is limited."


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
    company = text(job.get("company")) or "your team"
    title = text(job.get("title")) or "the role"
    role = first_supported_role(profile, candidate_evidence) or "candidate"
    evidence_items = select_cover_letter_evidence(profile, job, focus, candidate_evidence)
    skill_phrase = ", ".join(focus[:4]) if focus else "the experience saved in my profile"
    greeting = f"Dear {company} Hiring Team,"
    opening = (
        f"I’m excited to apply for the {title} role at {company}. My background as a {role} aligns with the position "
        f"through {skill_phrase}, and I’m drawn to opportunities where careful execution and practical problem-solving "
        f"matter as much as technical breadth."
    )

    if evidence_items:
        evidence_text = evidence_items[0]
    else:
        evidence_text = "My saved profile contains the relevant experience and project detail for this application."
    experience = (
        f"In recent experience, {evidence_text} This kind of work has helped me build careful habits around practical checks, "
        f"documentation, and clear communication with business users and teammates."
    )

    fit = (
        f"I would bring that same focus to {company}, especially where the role values {skill_phrase} and dependable follow-through, "
        f"clear communication with business users or teammates, and steady attention to documented results rather than keyword-heavy claims."
    )

    closing = (
        f"Thank you for your time and consideration. I would welcome the chance to discuss how my background can support "
        f"{company} in the {title} role."
    )
    signature = f"Sincerely,\n{profile.get('name', '')}"
    return [greeting, opening, experience, fit, closing, signature]


def select_cover_letter_evidence(
    profile: dict[str, str],
    job: dict[str, Any],
    focus: list[str],
    candidate_evidence: dict[str, Any],
) -> list[str]:
    snippets: list[str] = []
    terms = focus[:4] or []
    for section in candidate_evidence.get("sections", []):
        for sentence in split_sentences(section["text"]):
            clean = normalize_space(sentence)
            if not clean or len(clean) > 400:
                continue
            if contains_resume_section_heading(clean) or contains_contact_details(clean):
                continue
            if terms and not any(contains_phrase(clean, term) or contains_phrase(term, clean) for term in terms):
                continue
            snippets.append(trim_cover_letter_evidence(clean))
            if len(snippets) >= 3:
                return snippets
    if not snippets:
        fallback_terms = [term for term in terms if term]
        for section in candidate_evidence.get("sections", []):
            for sentence in split_sentences(section["text"]):
                clean = normalize_space(sentence)
                if not clean or len(clean) > 400:
                    continue
                if contains_resume_section_heading(clean) or contains_contact_details(clean):
                    continue
                if fallback_terms and any(contains_phrase(clean, term) or contains_phrase(term, clean) for term in fallback_terms):
                    snippets.append(trim_cover_letter_evidence(clean))
                    if len(snippets) >= 3:
                        return snippets
    if not snippets:
        project = text(profile.get("projects"))
        if project:
            snippets.append(trim_cover_letter_evidence(trim(project, 180)))
    return snippets[:3]


def trim_cover_letter_evidence(value: str, limit: int = 180) -> str:
    clean = normalize_space(value)
    if len(clean) <= limit:
        return clean
    return trim(clean, limit)


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
