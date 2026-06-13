from __future__ import annotations

import re
from typing import Any


LABEL = "Rule-based local tailored draft - manual review required"

ACTION_VERBS = {
    "made": "Built",
    "worked on": "Supported",
    "helped": "Supported",
    "did": "Delivered",
    "created": "Created",
    "built": "Built",
}


def generate_tailored_resume_draft(
    job: dict[str, Any],
    profile: dict[str, Any],
    match_result: dict[str, Any],
    seniority_result: dict[str, Any],
) -> dict[str, Any]:
    evidence = match_result.get("evidence", [])
    matches = match_result.get("matches", [])
    ranked_evidence = rank_evidence(evidence, matches)
    supported_skills = prioritized_skills(profile, matches)
    suggestions = build_rewrite_suggestions(matches)
    gaps = match_result.get("unsupported_requirements") or match_result.get("missing_requirements") or []
    summary = build_supported_summary(job, profile, supported_skills, ranked_evidence)
    draft_text = format_draft(summary, supported_skills, ranked_evidence, suggestions, gaps, seniority_result)
    return {
        "label": LABEL,
        "summary": summary,
        "prioritized_skills": supported_skills,
        "prioritized_experience": ranked_evidence,
        "rewrite_suggestions": suggestions,
        "gaps_that_must_not_be_added": gaps,
        "seniority_suitability_note": seniority_result.get("explanation", ""),
        "text": draft_text,
    }


def rank_evidence(evidence: list[dict[str, Any]], matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scores: dict[str, int] = {}
    for match in matches:
        text = match.get("matched_resume_evidence", "")
        scores[text] = max(scores.get(text, 0), int(match.get("confidence", 0)))
    ranked = []
    for item in evidence:
        copy = dict(item)
        copy["relevance"] = scores.get(item.get("text", ""), 0)
        ranked.append(copy)
    ranked.sort(key=lambda item: (item["relevance"], item.get("weight", 0)), reverse=True)
    return [item for item in ranked if item["relevance"] >= 25][:8]


def prioritized_skills(profile: dict[str, Any], matches: list[dict[str, Any]]) -> list[str]:
    profile_skills = [part.strip() for part in re.split(r"[,;\n]+", str(profile.get("key_skills") or "")) if part.strip()]
    matched_terms = []
    for match in matches:
        if int(match.get("confidence", 0)) < 40:
            continue
        requirement = str(match.get("job_requirement") or "")
        for skill in profile_skills:
            if skill.lower() in requirement.lower() or skill.lower() in str(match.get("matched_resume_evidence", "")).lower():
                matched_terms.append(skill)
    return list(dict.fromkeys([*matched_terms, *profile_skills]))[:16]


def build_rewrite_suggestions(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suggestions = []
    used: set[str] = set()
    for match in sorted(matches, key=lambda item: int(item.get("confidence", 0)), reverse=True):
        original = str(match.get("matched_resume_evidence") or "")
        if not original or original in used or int(match.get("confidence", 0)) < 45:
            continue
        used.add(original)
        proposed = controlled_rewrite(original, str(match.get("job_requirement") or ""))
        suggestions.append(
            {
                "original_bullet": original,
                "proposed_bullet": proposed,
                "matched_job_requirement": match.get("job_requirement", ""),
                "supporting_evidence": original,
                "explanation": "Reordered and lightly standardized existing evidence only; no new tools, metrics, employers, or duties were added.",
                "confidence": match.get("confidence", 0),
                "manual_review_warning": "Review carefully before using; keep only wording you can defend in an interview.",
            }
        )
        if len(suggestions) >= 6:
            break
    return suggestions


def controlled_rewrite(original: str, requirement: str) -> str:
    clean = original.strip(" -*\t")
    lowered = clean.lower()
    for old, new in ACTION_VERBS.items():
        if lowered.startswith(old):
            clean = new + clean[len(old) :]
            break
    supported_terms = [term for term in extract_terms(requirement) if term.lower() in clean.lower()]
    if supported_terms:
        prefix = ", ".join(dict.fromkeys(supported_terms[:3]))
        if not clean.lower().startswith(prefix.lower()):
            clean = f"{prefix}: {clean}"
    return clean


def extract_terms(content: str) -> list[str]:
    terms = []
    for part in re.split(r"[,;/]|\band\b", content):
        clean = part.strip(" .:-")
        if 2 <= len(clean) <= 32 and not re.search(r"\b(years?|experience|required|preferred)\b", clean, re.I):
            terms.append(clean)
    return terms


def build_supported_summary(
    job: dict[str, Any],
    profile: dict[str, Any],
    skills: list[str],
    evidence: list[dict[str, Any]],
) -> str:
    role = str(job.get("title") or "target role")
    education = " with relevant education" if str(profile.get("education") or "").strip() else ""
    focus = ", ".join(skills[:4]) if skills else "supported software projects"
    proof = evidence[0]["text"] if evidence else str(profile.get("work_experience") or profile.get("projects") or "").strip()
    proof_clause = f" Evidence includes: {proof}" if proof else ""
    return f"Candidate for {role}{education}, with supported experience across {focus}.{proof_clause}"


def format_draft(
    summary: str,
    skills: list[str],
    evidence: list[dict[str, Any]],
    suggestions: list[dict[str, Any]],
    gaps: list[str],
    seniority_result: dict[str, Any],
) -> str:
    lines = [
        LABEL,
        "",
        "Recommended summary",
        summary,
        "",
        "Prioritized skills",
        ", ".join(skills) or "No supported skills saved yet.",
        "",
        "Reordered experience bullets",
    ]
    lines.extend([f"- {item['text']}" for item in evidence] or ["- Add saved resume or profile evidence first."])
    lines.extend(["", "Rewrite suggestions"])
    for item in suggestions:
        lines.extend(
            [
                f"Original: {item['original_bullet']}",
                f"Proposed: {item['proposed_bullet']}",
                f"Requirement: {item['matched_job_requirement']}",
                f"Why: {item['explanation']}",
                "",
            ]
        )
    lines.extend(["Gaps that must not be added", ", ".join(gaps) or "None identified from current analysis."])
    lines.extend(["", "Seniority suitability note", seniority_result.get("explanation", "")])
    return "\n".join(lines).strip()
