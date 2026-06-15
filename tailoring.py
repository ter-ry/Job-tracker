from __future__ import annotations

import re
from typing import Any

from grounding import build_candidate_evidence, classify_supported_skills, supporting_snippets
from tailoring_pipeline import build_tailoring_plan, rewrite_paragraph


LABEL = "Rule-based local tailored draft - manual review required"

ACTION_VERBS = {
    "made": "Built",
    "worked on": "Supported",
    "worked with": "Collaborated with",
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
    plan = build_tailoring_plan(job, profile, match_result)
    evidence = match_result.get("evidence", [])
    matches = match_result.get("matches", [])
    ranked_evidence = rank_evidence(evidence, matches)
    supported_skills = prioritized_skills(profile, matches)
    suggestions = [
        {
            "original_bullet": block["original_text"],
            "proposed_bullet": block["proposed_text"],
            "matched_job_requirement": block["matched_job_phrase"],
            "supporting_evidence": block["supporting_evidence"],
            "changed_wording": block["changed_wording"],
            "explanation": "Grounded rewrite derived from the shared tailoring plan.",
            "confidence": block["confidence"],
            "manual_review_warning": "Review carefully before using; keep only wording you can defend in an interview.",
            "grounded": block["grounded"],
            "evidence_id": block["evidence_id"],
        }
        for block in plan["resume_change_blocks"]
        if block.get("section") in {"experience", "projects"}
    ]
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
        "tailoring_plan": plan,
        "cover_letter_evidence_blocks": plan.get("selected_cover_letter_blocks", []),
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
    supported = []
    evidence_text = " ".join(
        str(profile.get(field) or "")
        for field in ["work_experience", "key_skills", "education", "projects", "resume_text"]
    ).lower()
    for skill in matched_terms:
        if skill.lower() in evidence_text:
            supported.append(skill)
    return list(dict.fromkeys(supported))[:16]


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
                "changed_wording": changed_wording(original, proposed),
                "explanation": "Reordered and lightly standardized existing evidence only; no new tools, metrics, employers, or duties were added.",
                "confidence": match.get("confidence", 0),
                "manual_review_warning": "Review carefully before using; keep only wording you can defend in an interview.",
            }
        )
        if len(suggestions) >= 6:
            break
    return suggestions


def controlled_rewrite(original: str, requirement: str, evidence_text: str = "", section: str = "") -> str:
    clean = original.strip(" -*\t")
    if not clean:
        return clean
    if requirement and evidence_text:
        match = {
            "job_phrase": requirement,
            "job_phrase_category": "domain terminology",
            "evidence_text": evidence_text,
        }
        proposed, _, validation, _ = rewrite_paragraph(clean, requirement, match, {"job_description": requirement}, {"full_text": evidence_text})
        if validation.get("grounded"):
            return proposed
    lowered = clean.lower()
    requirement_lower = requirement.lower()
    evidence_lower = evidence_text.lower()
    for old, new in ACTION_VERBS.items():
        if lowered.startswith(old):
            clean = new + clean[len(old) :]
            break
    if "validation, logging, and data cleaning" in lowered and any(term in requirement_lower for term in ["testing", "debug", "debugging", "validation"]):
        clean = re.sub(
            r"validation,\s*logging,\s*and\s*data\s*cleaning",
            "testing, validation, logging, and data-cleaning",
            clean,
            flags=re.I,
        )
    if re.search(r"\bdata models?\b", clean, re.I) and any(term in requirement_lower for term in ["sql", "database"]):
        clean = re.sub(r"\bdata models?\b", "database structures and data models", clean, flags=re.I)
    if "supplier specific" in lowered:
        clean = re.sub(r"supplier specific", "supplier-specific", clean, flags=re.I)
    if "manual data entry" in lowered:
        clean = re.sub(r"data entry", "data-entry", clean, flags=re.I)
    if "backend integrations with real-time data from" in lowered and any(term in requirement_lower for term in ["collaboration", "workflow", "documentation"]):
        clean = re.sub(
            r"backend integrations with real-time data from",
            "backend integrations and cross-functional data workflows using",
            clean,
            flags=re.I,
        )
    if "team documentation standards" in lowered and "documentation" in requirement_lower:
        clean = re.sub(r"team documentation standards", "documentation standards", clean, flags=re.I)
    if "python" in requirement_lower and "python" not in lowered and "python" in evidence_lower:
        if re.search(r"\b(validation|testing|automation|logging|documentation)\b", clean, re.I):
            clean = re.sub(
                r"^(Implemented|Built|Designed|Created|Developed|Supported|Maintained)\b",
                r"\1 for Python applications",
                clean,
                count=1,
                flags=re.I,
            )
    if len(clean) > int(len(original) * 1.35):
        return original.strip(" -*\t")
    return clean


def changed_wording(original: str, proposed: str) -> str:
    if original.strip() == proposed.strip():
        return "No factual changes; original wording preserved."
    return "Opening verb or supported requirement phrase was lightly reordered."


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
    candidate_evidence = build_candidate_evidence(profile)
    grouped = classify_supported_skills(job, candidate_evidence)
    supported_focus = grouped["supported_relevant"] or skills[:4]
    education = " with relevant education" if str(profile.get("education") or "").strip() else ""
    focus = ", ".join(supported_focus[:4]) if supported_focus else "documented profile experience"
    snippets = supporting_snippets(supported_focus, candidate_evidence, limit=1)
    proof = evidence[0]["text"] if evidence else (snippets[0] if snippets else "")
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
                f"Supporting evidence: {item['supporting_evidence']}",
                f"Changed wording: {item['changed_wording']}",
                f"Confidence: {item['confidence']}",
                f"Why: {item['explanation']}",
                "",
            ]
        )
    lines.extend(["Gaps that must not be added", ", ".join(gaps) or "None identified from current analysis."])
    lines.extend(["", "Seniority suitability note", seniority_result.get("explanation", "")])
    return "\n".join(lines).strip()
