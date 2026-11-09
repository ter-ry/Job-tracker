"""Compare authoritative required-skill labels with persisted application extraction."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ALIASES = {
    "javascript": "javascript",
    "java script": "javascript",
    "nodejs": "node",
    "node js": "node",
    "postgresql": "postgres",
    "golang": "go",
    "c / c++": "c++",
    "c/c++": "c++",
    "rest apis": "apis",
    "web apis": "apis",
    "websocket apis": "apis",
    "llm apis": "apis",
    "graphql": "graphql",
}


def canon(value: str) -> str:
    value = re.sub(r"[^a-z0-9+#]+", " ", str(value or "").lower()).strip()
    value = re.sub(r"\s+", " ", value)
    return ALIASES.get(value, value)


def matches(gold: str, predicted: str) -> bool:
    left, right = canon(gold), canon(predicted)
    if left == right:
        return True
    if left in right or right in left:
        return len(left) >= 4 or left in {"go", "c++", "node", "apis"}
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    replay = json.loads(args.replay.read_text(encoding="utf-8"))
    label_map = {row["id"]: row for row in labels["records"]}
    rows = {row["source_job_id"]: row for row in replay.get("all_persisted", [])}
    evaluated = []
    tp = fp = fn = 0
    for record_id, label in label_map.items():
        row = rows.get(record_id, {})
        predicted = []
        for requirement in row.get("qualification_requirements") or []:
            if str(requirement.get("importance") or "").lower() != "required":
                continue
            if str(requirement.get("category") or "").lower() != "technical":
                continue
            value = requirement.get("normalized") or requirement.get("requirement")
            if canon(value) in {"engineering", "software engineer", "years", "experience"}:
                continue
            if value and value not in predicted:
                predicted.append(value)
        gold = label["required_skills"]
        matched_gold = [item for item in gold if any(matches(item, candidate) for candidate in predicted)]
        matched_predicted = [item for item in predicted if any(matches(item, candidate) for candidate in gold)]
        row_tp, row_fp, row_fn = len(matched_gold), len(predicted) - len(matched_predicted), len(gold) - len(matched_gold)
        tp += row_tp
        fp += row_fp
        fn += row_fn
        evaluated.append({"id": record_id, "authoritative_required_skills": gold, "application_required_skills": predicted, "matched": matched_gold, "true_positive_count": row_tp, "false_positive_count": row_fp, "false_negative_count": row_fn})
    denominator = tp + fn
    predicted_denominator = tp + fp
    report = {
        "label_policy": labels["label_policy"],
        "evaluated_postings": len(evaluated),
        "authoritative_required_skill_labels": denominator,
        "application_required_skill_labels": predicted_denominator,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": tp / predicted_denominator if predicted_denominator else None,
        "recall": tp / denominator if denominator else None,
        "accuracy": tp / denominator if denominator else None,
        "minimum_evaluable_denominator": 5,
        "decision": "PASS" if denominator >= 5 and tp / denominator >= 0.90 else "FAIL" if denominator >= 5 else "INCONCLUSIVE",
        "records": evaluated,
    }
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown = [
        "# Mandatory-skill extraction evaluation",
        "",
        f"Status: **{report['decision']}**",
        "",
        report["label_policy"],
        "",
        "| Metric | Numerator / denominator | Result | Threshold |",
        "|---|---:|---:|---:|",
        f"| Precision | {tp}/{predicted_denominator} | {report['precision']:.2%} | Reported |",
        f"| Recall | {tp}/{denominator} | {report['recall']:.2%} | Reported |",
        f"| Accuracy (correct required labels / authoritative required labels) | {tp}/{denominator} | {report['accuracy']:.2%} | >=90% |",
        "",
        "Preferred, optional, example, degree, internship, experience, authorization, and ownership statements were excluded from the required-skill denominator.",
    ]
    args.output.with_suffix(".md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("evaluated_postings", "authoritative_required_skill_labels", "application_required_skill_labels", "true_positive", "false_positive", "false_negative", "precision", "recall", "accuracy", "decision")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
