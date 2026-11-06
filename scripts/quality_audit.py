"""Bounded, reproducible discovery quality audit.

Offline mode reads a SQLite database read-only. Live mode makes one bounded
JobSpy attempt per enabled provider in each of Canada remote and Toronto hybrid.
Captured mode replays records through the actual application pipeline in a
temporary database. It records source URLs but never treats them as verified.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import seniority
from sources.jobspy_source import fetch_jobspy_jobs


TERMS = [
    "Full Stack Developer",
    "Software Developer",
    "Python Developer",
    "React Developer",
    "Junior Software Engineer",
]


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def canonical_key(job: dict[str, Any]) -> str:
    url = clean(job.get("url") or job.get("job_url"))
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    requisition = (query.get("jk") or query.get("jobId") or query.get("job_id") or [""])[0]
    if requisition:
        return f"req:{requisition.lower()}"
    if clean(job.get("source_job_id")):
        return f"source:{clean(job.get('source_job_id')).lower()}"
    parts = [clean(job.get(field)).lower() for field in ("company", "title", "location")]
    return "text:" + "|".join(parts)


def read_jobs(db_path: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute("SELECT * FROM jobs WHERE discovery_first_seen_at <> '' ORDER BY application_priority_score DESC, id ASC")]
    finally:
        connection.close()


def assess_jobs(jobs: list[dict[str, Any]], *, live: bool) -> dict[str, Any]:
    unique: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for job in jobs:
        key = canonical_key(job)
        if key in unique:
            duplicate_count += 1
            continue
        unique[key] = job
    ranked = sorted(unique.values(), key=lambda item: float(item.get("application_priority_score") or 0), reverse=True)
    missing_description = [job for job in ranked if not clean(job.get("job_description"))]
    no_url = [job for job in ranked if not clean(job.get("url") or job.get("job_url"))]
    unknown_eligibility = [job for job in ranked if clean(job.get("remote_eligibility")).lower() in {"", "unknown"}]
    zero_priority = [job for job in ranked if float(job.get("application_priority_score") or 0) <= 0]
    year_counts = Counter()
    parsed_year_jobs = []
    for job in ranked:
        analysis = seniority.analyze_job_seniority(job)
        if analysis.get("required_experience"):
            year_counts["required"] += 1
            parsed_year_jobs.append({"id": job.get("id"), "title": job.get("title"), "source_evidence": analysis["required_experience"].get("source_evidence", "")})
        elif analysis.get("preferred_experience"):
            year_counts["preferred"] += 1
        elif analysis.get("ambiguous_experience"):
            year_counts["ambiguous"] += 1
    top20 = ranked[:20]
    high_rank_suspects = [
        {"id": job.get("id"), "title": job.get("title"), "company": job.get("company"), "priority": job.get("application_priority_score"), "reason": "missing description or zero priority"}
        for job in top20
        if not clean(job.get("job_description")) or float(job.get("application_priority_score") or 0) <= 0
    ]
    categories = Counter(clean(job.get("discovery_result_category")) or "unknown" for job in ranked)
    return {
        "sample_size": len(jobs),
        "unique_postings": len(ranked),
        "duplicate_count": duplicate_count,
        "duplicate_rate": round(duplicate_count / len(jobs), 4) if jobs else None,
        "top20_count": len(top20),
        "top20_precision": None,
        "independently_verified_count": 0,
        "source_url_present_count": len(ranked) - len(no_url),
        "source_verification_coverage": 0.0,
        "missing_description_count": len(missing_description),
        "unknown_eligibility_count": len(unknown_eligibility),
        "zero_priority_count": len(zero_priority),
        "required_year_records_parsed": dict(year_counts),
        "required_year_accuracy": None,
        "mandatory_skill_accuracy": None,
        "eligibility_error_count": None,
        "seniority_confusion_count": None,
        "categories": dict(categories),
        "high_rank_suspects": high_rank_suspects,
        "parsed_year_examples": parsed_year_jobs[:20],
        "live_source_verification": "not performed; URL presence is not original-posting verification" if live else "not performed in offline mode",
        "quality_gate": "INCONCLUSIVE",
    }


def run_live(enabled_sources: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # One bounded attempt per enabled provider in each required scenario.
    scenarios = [
        {"name": "canada_remote", "keywords": "Full Stack Developer Software Developer Python Developer React Developer Junior Software Engineer", "location": "Canada", "remote_preference": "remote"},
        {"name": "toronto_hybrid", "keywords": "Full Stack Developer Software Developer Python Developer React Developer Junior Software Engineer", "location": "Toronto, Ontario", "remote_preference": "hybrid"},
    ]
    jobs: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {}
    for scenario in scenarios:
        result = fetch_jobspy_jobs(
            keywords=scenario["keywords"], location=scenario["location"], distance=50,
            remote_preference=scenario["remote_preference"], results_wanted=10,
            hours_old=720, enabled_sources=enabled_sources,
        )
        diagnostics[scenario["name"]] = result.get("source_diagnostics", {})
        for job in result.get("jobs", []):
            jobs.append({**job, "audit_scenario": scenario["name"]})
    return jobs, diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, help="Read-only SQLite database to audit")
    parser.add_argument("--captured", type=Path, help="Captured live-audit JSON to replay through the application pipeline")
    parser.add_argument("--live", action="store_true", help="Run two bounded live scenarios")
    parser.add_argument(
        "--enabled-sources",
        default="linkedin,indeed",
        help="Comma-separated JobSpy providers for live mode (default: linkedin,indeed)",
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        help="Output file prefix; defaults to a dated .tmpqa audit run directory",
    )
    parser.add_argument("--candidate-profile-id", type=int, default=2)
    parser.add_argument("--resume-id", type=int, default=2)
    args = parser.parse_args()
    if args.output_prefix is None:
        args.output_prefix = Path(".tmpqa") / f"quality-audit-{datetime.now(timezone.utc):%Y%m%d}" / "quality-audit"
    if args.captured:
        if not args.db_path:
            parser.error("--db-path is required with --captured")
        from replay_quality_audit import replay

        report = replay(args.captured, args.db_path, args.output_prefix.with_suffix(".json"), args.candidate_profile_id, args.resume_id)
        print(json.dumps({key: report[key] for key in ("audit_status", "raw_job_count", "raw_unique_count", "persisted_job_count", "persisted_unique_count", "raw_missing_description_count", "persisted_missing_description_count", "duplicate_count_raw", "duplicate_count_persisted")}, indent=2))
        return 0
    enabled_sources = [source.strip() for source in args.enabled_sources.split(",") if source.strip()]
    if args.live:
        jobs, diagnostics = run_live(enabled_sources)
    else:
        db_path = args.db_path or Path(__file__).resolve().parents[1] / "data" / "jobs.sqlite"
        jobs, diagnostics = read_jobs(db_path), {"mode": "offline", "db_path": str(db_path)}
    report = {
        "audit_status": "INCONCLUSIVE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "live": bool(args.live),
        "search_terms": TERMS,
        "scenarios": ["Canada remote", "Toronto hybrid"],
        "enabled_sources": enabled_sources if args.live else [],
        "provider_diagnostics": diagnostics,
        "assessment": assess_jobs(jobs, live=args.live),
        "jobs": [{"canonical_key": canonical_key(job), **job} for job in jobs],
        "limitations": [
            "Original postings were not independently fetched by this command; URL presence is not verification.",
            "Ground-truth precision/recall metrics remain null until an independently adjudicated source sample is available.",
        ],
    }
    report["audit_status"] = "INCONCLUSIVE" if report["assessment"]["independently_verified_count"] < 40 else "PASS"
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.output_prefix.with_suffix(".json")
    md_path = args.output_prefix.with_suffix(".md")
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    assessment = report["assessment"]
    md_path.write_text(
        "# Job Tracker independent quality audit\n\n"
        f"Status: **{report['audit_status']}**\n\n"
        f"Generated: `{report['generated_at']}`\n\n"
        "This report deliberately distinguishes source URL presence from independent original-posting verification.\n\n"
        "## Metrics\n\n"
        f"- Jobs received: {assessment['sample_size']}\n- Unique canonical postings: {assessment['unique_postings']}\n"
        f"- Duplicates: {assessment['duplicate_count']} ({assessment['duplicate_rate']})\n"
        f"- Independently verified originals: {assessment['independently_verified_count']}\n"
        f"- Top-20 precision: {assessment['top20_precision']}\n"
        f"- Required-years accuracy: {assessment['required_year_accuracy']}\n"
        f"- Mandatory-skill accuracy: {assessment['mandatory_skill_accuracy']}\n"
        f"- Eligibility errors: {assessment['eligibility_error_count']}\n"
        f"- Source-verification coverage: {assessment['source_verification_coverage']}\n\n"
        "## High-ranked review candidates\n\n"
        + ("\n".join(f"- {item['company']} — {item['title']} (priority {item['priority']}): {item['reason']}" for item in assessment["high_rank_suspects"]) or "- None identified by automated completeness checks.")
        + "\n\n## Limitations\n\n- Original postings were not independently fetched by this command.\n- Ground-truth accuracy metrics remain INCONCLUSIVE until a source-adjudicated sample is available.\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["audit_status"], "json": str(json_path), "markdown": str(md_path), "metrics": assessment}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
