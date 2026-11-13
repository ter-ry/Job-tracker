"""Run independent, real JobSpy probes and emit JSON evidence.

This intentionally uses the repository's pinned python-jobspy installation through
the normal adapter. It does not retry, bypass access controls, or treat an empty
successful call as proof that a provider returned jobs.
"""

from __future__ import annotations

import json
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sources.jobspy_source import fetch_jobspy_jobs


CASES = [
    ("toronto_junior_software_developer", "junior software developer", "Toronto, Ontario"),
    ("toronto_software_engineer", "software engineer", "Toronto, Ontario"),
    ("toronto_frontend_developer", "frontend developer", "Toronto, Ontario"),
    ("toronto_rece", "Registered Early Childhood Educator", "Toronto, Ontario"),
    ("mississauga_rece", "RECE", "Mississauga, Ontario"),
    ("canada_remote_software_developer", "software developer", "Canada"),
]
SOURCES = ("linkedin", "indeed", "zip_recruiter", "glassdoor")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true", help="print counts instead of row snapshots")
    args = parser.parse_args()
    evidence = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "jobspy_version": "1.1.82",
        "adapter": "sources.jobspy_source.fetch_jobspy_jobs",
        "requests": [],
    }
    for case_name, keywords, location in CASES:
        for source in SOURCES:
            result = fetch_jobspy_jobs(
                keywords=keywords,
                location=location,
                distance=50,
                results_wanted=10,
                hours_old=168,
                enabled_sources=[source],
                country_indeed="Canada",
                provider_timeout_seconds=20,
            )
            diagnostic = result["source_diagnostics"][source]
            evidence["requests"].append({
                "case": case_name,
                "source": source,
                "request": diagnostic["request_params"],
                "state": diagnostic["state"],
                "error": diagnostic["error"],
                "warning_count": diagnostic["warnings_count"],
                "raw_result_count": diagnostic["raw_records_row_count"],
                "valid_normalized_jobs": diagnostic["valid_normalized_jobs"],
                "unique_jobs": diagnostic["unique_job_count"],
                "duplicate_count": diagnostic["duplicate_count"],
                "returned_jobs": diagnostic["returned_to_frontend_row_count"],
                "original_url_count": diagnostic["original_url_count"],
                "description_complete_count": diagnostic["description_complete_count"],
                "salary_evidence_count": diagnostic["salary_evidence_count"],
                "address_evidence_count": diagnostic["address_evidence_count"],
                "raw_snapshots": result["source_snapshots"].get(source, []),
            })
    if args.summary:
        print(json.dumps([
            {
                "case": item["case"],
                "source": item["source"],
                "state": item["state"],
                "provider_status": item["provider_status"],
                "error": item["error"],
                "raw": item["raw_result_count"],
                "normalized": item["valid_normalized_jobs"],
                "unique": item["unique_jobs"],
                "duplicates": item["duplicate_count"],
                "returned": item["returned_jobs"],
                "urls": item["original_url_count"],
                "descriptions": item["description_complete_count"],
                "salary": item["salary_evidence_count"],
                "addresses": item["address_evidence_count"],
            }
            for item in evidence["requests"]
        ], indent=2))
    else:
        print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
