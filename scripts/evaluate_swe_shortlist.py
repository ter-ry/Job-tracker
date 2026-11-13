"""Compare SWE shortlist decisions with independently reviewed real postings.

Usage: python scripts/evaluate_swe_shortlist.py candidate.json postings.json
Both files must remain outside the repository. No input or result is persisted.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import build_qualification_fit  # noqa: E402

LABELS = {"strong", "stretch", "gaps", "insufficient"}


def decision_label(value: str) -> str:
    if value == "Strong technical match":
        return "strong"
    if value == "Significant gaps":
        return "gaps"
    if value.startswith("Possible / stretch"):
        return "stretch"
    return "insufficient"


def evaluate(candidate: dict, postings: list[dict]) -> dict:
    if len(postings) < 15:
        raise ValueError("At least 15 authentic postings are required")
    results = []
    for posting in postings:
        if not all(posting.get(field) for field in ("source_url", "title", "job_description", "reviewed_label")):
            raise ValueError("Each posting needs source_url, title, job_description and independently reviewed_label")
        if posting["reviewed_label"] not in LABELS:
            raise ValueError(f"Invalid reviewed_label: {posting['reviewed_label']}")
        fit = build_qualification_fit(posting, evidence_profile=candidate)
        technical = fit.get("technical_compatibility") or {}
        predicted = decision_label(technical.get("decision", ""))
        reviewed = posting["reviewed_label"]
        results.append({
            "source_url": posting["source_url"], "title": posting["title"],
            "reviewed": reviewed, "predicted": predicted,
            "correct": predicted == reviewed,
            "false_positive": predicted == "strong" and reviewed != "strong",
            "false_negative": reviewed == "strong" and predicted != "strong",
            "required_demonstrated": technical.get("required_demonstrated", []),
            "required_no_experience": technical.get("required_no_experience", []),
            "required_unverified": technical.get("required_unverified", []),
            "requirements": fit.get("qualification_requirements", []),
        })
    return {
        "count": len(results), "correct": sum(item["correct"] for item in results),
        "false_positives": sum(item["false_positive"] for item in results),
        "false_negatives": sum(item["false_negative"] for item in results),
        "results": results,
    }


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: evaluate_swe_shortlist.py <candidate.json> <postings.json>")
    candidate = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    postings = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    print(json.dumps(evaluate(candidate, postings), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
