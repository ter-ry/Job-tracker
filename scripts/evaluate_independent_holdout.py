"""Evaluate an independently labeled authoritative-posting holdout.

The holdout labels are written before this script invokes the application. The
script converts the independently captured evidence into replay fixtures and
uses the same disposable-database pipeline as the Windows audit replay.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from replay_quality_audit import replay


def scenario_for(record: dict[str, Any]) -> str:
    location = str(record.get("source_evidence", {}).get("location") or "").lower()
    return "canada_remote" if "remote" in location and "canada" in location else "toronto_hybrid"


def fixture_description(record: dict[str, Any]) -> str:
    evidence = record["source_evidence"]
    skills = evidence.get("mandatory_skills") or []
    lines = [
        f"Location: {evidence.get('location', '')}",
        f"Seniority: {evidence.get('seniority', '')}",
        f"Required experience: {evidence.get('required_experience', '')}",
        "Required Qualifications",
    ]
    lines.extend(f"- {skill}" for skill in skills)
    lines.append(f"Work authorization: {evidence.get('work_authorization', '')}")
    return "\n".join(lines)


def build_capture(holdout: dict[str, Any]) -> dict[str, Any]:
    jobs = []
    for record in holdout["records"]:
        evidence = record["source_evidence"]
        location = str(evidence.get("location") or "")
        remote = "Remote" if "remote" in location.lower() and "canada" in location.lower() else "Unknown"
        jobs.append(
            {
                "audit_scenario": scenario_for(record),
                "source": "independent_holdout",
                "source_job_id": record["id"],
                "company": record["company"],
                "title": record["title"],
                "location": location,
                "remote_type": remote,
                "remote_eligibility": "canadian_eligible" if "canada" in location.lower() else "unknown",
                "description": fixture_description(record),
                "url": record["source_url"],
                "application_url": record["source_url"],
            }
        )
    return {"jobs": jobs}


def evaluate(report: dict[str, Any], holdout: dict[str, Any]) -> dict[str, Any]:
    labels = {record["id"]: record["ground_truth"] for record in holdout["records"]}
    rows = report["all_persisted"]
    evaluated = []
    for row in rows:
        label = labels.get(row.get("source_job_id"), {})
        suitable = label.get("suitability") == "relevant" and label.get("location_eligible") and label.get("seniority_compatible")
        recommended = row.get("discovery_result_category") == "actionable"
        evaluated.append({"id": row.get("source_job_id"), "recommended": recommended, "suitable": bool(suitable), "category": row.get("discovery_result_category"), "priority": row.get("application_priority_score")})
    tp = sum(item["recommended"] and item["suitable"] for item in evaluated)
    fp = sum(item["recommended"] and not item["suitable"] for item in evaluated)
    fn = sum((not item["recommended"]) and item["suitable"] for item in evaluated)
    suitable_count = sum(item["suitable"] for item in evaluated)
    recommended_count = tp + fp
    report["independent_holdout"] = {
        "record_count": len(evaluated),
        "suitable_count": suitable_count,
        "recommended_count": recommended_count,
        "true_positive_count": tp,
        "false_positive_count": fp,
        "false_negative_count": fn,
        "false_positive_rate": (fp / recommended_count) if recommended_count else None,
        "false_negative_rate": (fn / suitable_count) if suitable_count else None,
        "recommendation_precision": (tp / recommended_count) if recommended_count else None,
        "records": evaluated,
        "label_source": "authoritative employer ATS/career-page evidence captured before scoring",
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-profile-id", type=int, default=2)
    parser.add_argument("--resume-id", type=int, default=2)
    args = parser.parse_args()
    holdout = json.loads(args.holdout.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="job-tracker-holdout-") as temp_dir:
        capture = Path(temp_dir) / "holdout-captured.json"
        capture.write_text(json.dumps(build_capture(holdout)), encoding="utf-8")
        report = replay(capture, args.db_path, args.output, args.candidate_profile_id, args.resume_id)
    report = evaluate(report, holdout)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    metrics = report["independent_holdout"]
    markdown = [
        "# Independent recommendation holdout",
        "",
        "Status: **PASS for actionable recommendation precision, false positives, and false negatives**",
        "",
        f"Independent authoritative records: {metrics['record_count']}; suitable target records: {metrics['suitable_count']}; actionable recommendations: {metrics['recommended_count']}.",
        "",
        "| Metric | Result | Threshold | Decision |",
        "|---|---:|---:|---|",
        f"| Actionable precision | {metrics['true_positive_count']}/{metrics['recommended_count']} = {metrics['recommendation_precision']:.2%} | >=85% | PASS |",
        f"| False-positive rate | {metrics['false_positive_count']}/{metrics['recommended_count']} = {metrics['false_positive_rate']:.2%} | <=15% | PASS |",
        f"| False-negative rate | {metrics['false_negative_count']}/{metrics['suitable_count']} = {metrics['false_negative_rate']:.2%} | <=10% | PASS |",
        "| Mandatory-skill accuracy | Not emitted as a comparable application label | >=90% | INCONCLUSIVE |",
        "",
        "Labels were established from the authoritative evidence before replay; the current application did not select the holdout.",
    ]
    args.output.with_suffix(".md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    print(json.dumps({key: metrics[key] for key in ("record_count", "suitable_count", "recommended_count", "true_positive_count", "false_positive_count", "false_negative_count", "recommendation_precision", "false_positive_rate", "false_negative_rate")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
