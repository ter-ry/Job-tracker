"""Replay captured JobSpy results through the real discovery pipeline.

This command never writes the supplied database. It copies the isolated QA
database to a disposable directory, replays each captured scenario through the
same Flask discovery endpoint used by the browser, and emits the persisted,
qualified, scored rows for audit inspection.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sqlite3
import tempfile
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module


CITY_COORDINATES = {
    "toronto": (43.6532, -79.3832),
    "mississauga": (43.5890, -79.6441),
    "oshawa": (43.8971, -78.8658),
    "ottawa": (45.4215, -75.6972),
    "calgary": (51.0447, -114.0719),
    "montreal": (45.5019, -73.5674),
    "halifax": (44.6488, -63.5752),
}


class ReplayGeocoder:
    name = "quality-audit-replay"

    def geocode(self, query: str, *, country: str = "Canada") -> dict[str, Any]:
        lowered = str(query or "").lower()
        for city, (latitude, longitude) in CITY_COORDINATES.items():
            if city in lowered:
                return {
                    "latitude": latitude,
                    "longitude": longitude,
                    "display_name": f"{city.title()}, Canada",
                }
        raise ValueError(f"Replay geocoder has no fixture for {query!r}")


def canonical_key(job: dict[str, Any]) -> str:
    url = str(job.get("url") or job.get("job_url") or "").strip()
    source_id = str(job.get("source_job_id") or "").strip().lower()
    if "jk=" in url:
        return "req:" + url.split("jk=", 1)[1].split("&", 1)[0].lower()
    if "/jobs/view/" in url:
        return "req:" + url.rsplit("/jobs/view/", 1)[1].split("/", 1)[0].lower()
    if source_id:
        return "source:" + source_id
    return "text:" + "|".join(str(job.get(field) or "").strip().lower() for field in ("company", "title", "location"))


def source_counts(jobs: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(job.get("source") or "").lower() for job in jobs))


def compact_job(job: dict[str, Any], scenarios: list[str]) -> dict[str, Any]:
    experience = job.get("experience_requirements") or {}
    qualification_requirements = job.get("qualification_requirements") or []
    return {
        "id": job.get("id"),
        "source_job_id": job.get("source_job_id"),
        "canonical_key": canonical_key(job),
        "scenarios": scenarios,
        "source": job.get("source"),
        "title": job.get("title"),
        "company": job.get("company"),
        "location": job.get("location"),
        "remote_type": job.get("remote_type"),
        "role_type": job.get("role_type"),
        "job_description": job.get("job_description"),
        "source_url": job.get("url"),
        "application_url": job.get("application_url"),
        "description_available": bool(job.get("job_description")),
        "required_experience": experience.get("required"),
        "preferred_experience": experience.get("preferred"),
        "ambiguous_experience": experience.get("ambiguous", []),
        "qualification_requirements": qualification_requirements,
        "qualification_match_score": job.get("qualification_match_score"),
        "qualification_fit_label": job.get("qualification_fit_label"),
        "qualification_evidence_confidence": job.get("qualification_evidence_confidence"),
        "seniority": job.get("qualification_fit_seniority"),
        "remote_eligibility": job.get("remote_eligibility"),
        "remote_search_eligible": job.get("remote_search_eligible"),
        "discovery_result_category": job.get("discovery_result_category"),
        "discovery_result_reason": job.get("discovery_result_reason"),
        "application_priority_score": job.get("application_priority_score"),
        "application_priority_reasons": job.get("application_priority_reasons", []),
        "overall_score": job.get("overall_score"),
        "score_breakdown": job.get("score_breakdown"),
        "warnings": job.get("warnings", []),
    }


def replay(captured_path: Path, database_path: Path, output_path: Path, profile_id: int, resume_id: int) -> dict[str, Any]:
    captured = json.loads(captured_path.read_text(encoding="utf-8"))
    captured_jobs = captured.get("jobs", [])
    scenario_jobs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_scenarios: dict[str, set[str]] = defaultdict(set)
    for job in captured_jobs:
        scenario = str(job.get("audit_scenario") or "unknown")
        scenario_jobs[scenario].append(job)
        source_scenarios[str(job.get("source_job_id") or "")].add(scenario)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="job-tracker-quality-replay-") as temp_dir:
        temp_root = Path(temp_dir)
        temp_db = temp_root / "jobs.sqlite"
        shutil.copy2(database_path, temp_db)
        source_root = database_path.parent.resolve()
        for folder_name in ("candidate_profiles", "resume_templates", "cover_letter_templates"):
            source_folder = source_root / folder_name
            if source_folder.exists():
                for source_file in source_folder.rglob("*"):
                    if not source_file.is_file():
                        continue
                    destination = temp_root / source_file.relative_to(source_root)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(source_file, destination)
                    except OSError:
                        # Some old QA document paths are stale; the selected
                        # résumé is validated by resolve_tailoring_resume_profile.
                        continue
        connection = sqlite3.connect(temp_db)
        try:
            for table, columns in {
                "base_resumes": ("docx_path",),
                "cover_letter_templates": ("docx_path",),
                "profile": ("resume_docx_template_path", "cover_letter_docx_template_path"),
            }.items():
                for column in columns:
                    connection.execute(
                        f"UPDATE {table} SET {column} = REPLACE({column}, ?, ?) WHERE {column} LIKE ?",
                        (str(source_root), str(temp_root), f"%{source_root}%"),
                    )
            connection.commit()
        finally:
            connection.close()
        app_module.DATA_DIR = temp_root
        app_module.DB_PATH = temp_db
        with app_module.app.app_context():
            app_module.init_db()
        app_module._QUALIFICATION_CACHE.clear()
        app_module._RESUME_EVIDENCE_CACHE.clear()
        app_module._QUALIFICATION_TERMS_CACHE.clear()
        app_module._EVIDENCE_MATCH_CACHE.clear()

        calls = iter(scenario_jobs.items())

        def replay_fetch(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                _, jobs = next(calls)
            except StopIteration:
                jobs = []
            return {
                "jobs": copy.deepcopy(jobs),
                "errors": {},
                "source_counts": source_counts(jobs),
                "source_diagnostics": {},
                "source_snapshots": {},
            }

        payload_common = {
            "keywords": "Full Stack Developer Software Developer Python Developer React Developer Junior Software Engineer",
            "enabled_sources": ["linkedin", "indeed"],
            "search_depth": "standard",
            "date_window": "any",
            "per_source_cap": 100,
            "total_cap": 100,
            "distance": 50,
            "candidate_profile_id": profile_id,
            "resume_id": resume_id,
            "bypass_cache": True,
        }
        responses: list[dict[str, Any]] = []
        with patch.object(app_module, "fetch_discovery_jobs_for_search", side_effect=replay_fetch), patch.object(app_module, "get_geocoding_provider", return_value=ReplayGeocoder()):
            with app_module.app.test_client() as client:
                for scenario, _jobs in scenario_jobs.items():
                    payload = {
                        **payload_common,
                        "location": "Canada" if scenario == "canada_remote" else "Toronto, Ontario",
                        "remote_preference": "remote" if scenario == "canada_remote" else "hybrid",
                    }
                    response = client.post("/api/discovery/jobspy", json=payload)
                    body = response.get_json()
                    if response.status_code != 200:
                        raise RuntimeError(f"Replay failed for {scenario}: {response.status_code} {body}")
                    responses.append({"scenario": scenario, "diagnostics": body.get("diagnostics", {}), "returned_count": len(body.get("jobs", []))})
                rows = client.get(f"/api/jobs?candidate_profile_id={profile_id}&resume_id={resume_id}").get_json()

        source_ids = set(source_scenarios)
        persisted = [row for row in rows if str(row.get("source_job_id") or "") in source_ids]
        persisted.sort(key=lambda row: (-int(row.get("application_priority_score") or 0), int(row.get("id") or 0)))
        scenario_map = {source_id: sorted(values) for source_id, values in source_scenarios.items()}
        compact = [compact_job(row, scenario_map.get(str(row.get("source_job_id") or ""), [])) for row in persisted]
        raw_unique = {canonical_key(job) for job in captured_jobs}
        persisted_unique = {canonical_key(job) for job in persisted}
        report = {
            "audit_status": "INCONCLUSIVE",
            "mode": "deterministic_offline_pipeline_replay",
            "captured_path": str(captured_path),
            "source_database": str(database_path),
            "isolated_database": "temporary copy; removed after replay",
            "candidate_profile_id": profile_id,
            "resume_id": resume_id,
            "raw_job_count": len(captured_jobs),
            "raw_unique_count": len(raw_unique),
            "raw_missing_description_count": sum(1 for job in captured_jobs if not str(job.get("description") or "").strip()),
            "persisted_job_count": len(persisted),
            "persisted_unique_count": len(persisted_unique),
            "persisted_missing_description_count": sum(1 for job in persisted if not str(job.get("job_description") or "").strip()),
            "duplicate_count_raw": len(captured_jobs) - len(raw_unique),
            "duplicate_count_persisted": len(persisted) - len(persisted_unique),
            "independently_verified_count": 0,
            "top20_precision": None,
            "required_year_accuracy": None,
            "mandatory_skill_accuracy": None,
            "eligibility_error_count": None,
            "seniority_confusion_count": None,
            "responses": responses,
            "top20": compact[:20],
            "all_persisted": compact,
            "limitations": [
                "Captured provider records were replayed but original postings were not independently adjudicated.",
                "URL presence and stored descriptions are not source verification.",
            ],
        }
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    markdown = [
        "# Job Tracker pipeline replay audit",
        "",
        "Status: **INCONCLUSIVE**",
        "",
        f"Raw captured jobs: {report['raw_job_count']} ({report['raw_unique_count']} unique); persisted through the application pipeline: {report['persisted_job_count']} ({report['persisted_unique_count']} unique).",
        f"Description availability: raw {report['raw_job_count'] - report['raw_missing_description_count']}/{report['raw_job_count']}; persisted {report['persisted_job_count'] - report['persisted_missing_description_count']}/{report['persisted_job_count']}.",
        f"Duplicates: raw {report['duplicate_count_raw']}; persisted {report['duplicate_count_persisted']}.",
        "",
        "## Actual application ranking",
        "",
        "| Rank | Company | Title | Location | Priority | Qualification | Category | Required experience |",
        "|---:|---|---|---|---:|---:|---|---|",
    ]
    for rank, job in enumerate(report["top20"], 1):
        required = (job.get("required_experience") or {}).get("text") or "—"
        markdown.append(f"| {rank} | {job.get('company','')} | {job.get('title','')} | {job.get('location','')} | {job.get('application_priority_score') or 0} | {job.get('qualification_match_score') or 0} | {job.get('discovery_result_category','')} | {required} |")
    markdown.extend([
        "",
        "## Limitations",
        "",
        "No original posting was independently fetched and adjudicated. Accuracy metrics therefore remain unavailable and the audit gate is INCONCLUSIVE.",
    ])
    output_path.with_suffix(".md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captured", type=Path, required=True)
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-profile-id", type=int, default=2)
    parser.add_argument("--resume-id", type=int, default=2)
    args = parser.parse_args()
    report = replay(args.captured, args.db_path, args.output, args.candidate_profile_id, args.resume_id)
    print(json.dumps({key: report[key] for key in ("audit_status", "raw_job_count", "raw_unique_count", "persisted_job_count", "persisted_unique_count", "raw_missing_description_count", "persisted_missing_description_count", "duplicate_count_raw", "duplicate_count_persisted")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
