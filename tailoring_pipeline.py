from __future__ import annotations

import re
from datetime import date
from dataclasses import dataclass
from typing import Any

from grounding import TECHNICAL_TERMS, build_candidate_evidence, contains_phrase, normalize_space, split_sentences, useful_tokens
from semantic_matching import extract_resume_evidence, keyword_overlap, lexical_similarity


MULTI_WORD_PHRASE_STOPWORDS = {
    "and",
    "or",
    "the",
    "a",
    "an",
    "of",
    "for",
    "to",
    "with",
    "in",
    "on",
    "at",
    "from",
    "by",
    "using",
    "experience",
    "skills",
    "skill",
    "responsibilities",
    "required",
    "preferred",
    "role",
    "team",
    "teams",
    "ability",
    "work",
}

TECH_CATEGORY_RULES = [
    ("database/data requirements", ["database", "data model", "data modeling", "schema", "sql", "tables", "records", "postgres", "postgresql"]),
    ("testing/debugging/quality requirements", ["testing", "debug", "debugging", "validation", "quality", "reliability", "defect", "qa", "bug", "unit testing", "integration testing"]),
    ("documentation/maintainability requirements", ["documentation", "document", "maintainability", "maintainable", "release notes", "runbook", "technical documentation"]),
    ("collaboration/stakeholder requirements", ["collaborat", "cross-functional", "stakeholder", "business user", "business team", "team", "communication", "partner", "developers", "product managers", "designers"]),
    ("cloud/platform requirements", ["cloud", "aws", "azure", "linux", "deployment", "infrastructure", "platform"]),
    ("methodology/process requirements", ["agile", "scrum", "kanban", "workflow", "process", "review", "iteration", "sprint", "milestone"]),
    ("required technical skills", ["python", "javascript", "typescript", "flask", "react", "sql", "api", "automation", "git", "github", "node.js", "nodejs", "express", "rest api", "rest apis"]),
    ("preferred technical skills", ["preferred", "nice to have", "bonus", "familiarity", "exposure", "microservice", "microservices"]),
]

CURATED_PHRASES = [
    "develop and maintain software applications",
    "Python development",
    "SQL database design",
    "testing and debugging",
    "software reliability",
    "technical documentation",
    "cross-functional collaboration",
    "AWS cloud services",
    "REST APIs",
    "version control and Git branching",
    "production incident troubleshooting",
    "sprint objectives and project milestones",
    "Node.js and Express development",
    "unit and integration testing",
    "microservice architecture",
    "Agile and Scrum",
]

REWRITE_RULES = [
    {
        "category": "database/data requirements",
        "requires": {"database", "sql"},
        "patterns": [
            (r"\bdata models?\b", "database structures and data models"),
            (r"\bapplication logic\b", "application logic"),
        ],
        "insert": "database structures",
    },
    {
        "category": "testing/debugging/quality requirements",
        "requires": {"testing", "debug", "validation"},
        "patterns": [
            (r"validation,\s*logging,\s*and\s*data\s*cleaning", "testing, validation, logging, and data-cleaning"),
            (r"\bdebug issues\b", "debug issues and troubleshoot production behavior"),
        ],
        "insert": "software reliability",
    },
    {
        "category": "documentation/maintainability requirements",
        "requires": {"documentation"},
        "patterns": [
            (r"team documentation standards", "documentation standards"),
            (r"document release steps", "document release steps and technical documentation"),
        ],
        "insert": "documentation",
    },
    {
        "category": "collaboration/stakeholder requirements",
        "requires": {"collaborat", "cross-functional"},
        "patterns": [
            (r"worked with cross-functional teammates to debug issues and document release steps", "Collaborated with cross-functional teammates to debug issues, document release steps, and technical documentation"),
            (r"\bworked with\b", "Collaborated with"),
            (r"\bheld weekly tutorial sessions\b", "Collaborated with cross-functional business teams through weekly tutorial sessions"),
        ],
        "insert": "cross-functional collaboration",
    },
    {
        "category": "cloud/platform requirements",
        "requires": {"aws", "cloud", "linux"},
        "patterns": [
            (r"backend integrations with real-time data", "backend integrations and REST-based data workflows with real-time data"),
            (r"\bbackend integrations\b", "backend integrations and cloud workflows"),
        ],
        "insert": "AWS cloud services",
    },
]

ACTION_VERBS = {
    "made": "Built",
    "worked on": "Supported",
    "worked with": "Collaborated with",
    "helped": "Supported",
    "did": "Delivered",
    "created": "Created",
    "built": "Built",
}


def build_tailoring_plan(job: dict[str, Any], profile: dict[str, Any], semantic_result: dict[str, Any]) -> dict[str, Any]:
    candidate_evidence = semantic_result.get("candidate_evidence") or build_candidate_evidence(profile)
    resume_evidence = semantic_result.get("evidence") or extract_resume_evidence(profile)
    evidence_index = {normalize_space(item.get("text", "")): item for item in resume_evidence}
    phrases = extract_job_phrases(job)
    phrase_matches = [match_job_phrase(phrase, job, candidate_evidence, semantic_result, resume_evidence, evidence_index) for phrase in phrases]
    resume_change_blocks = build_resume_change_blocks(phrase_matches, profile, job, candidate_evidence, evidence_index)
    skills_block = build_skills_block(profile, phrase_matches, candidate_evidence)
    if skills_block is not None:
        resume_change_blocks.insert(0, skills_block)
    selected_cover_blocks = select_cover_letter_blocks(resume_change_blocks)
    cover_letter_paragraphs = build_cover_letter_paragraphs(job, profile, selected_cover_blocks, candidate_evidence)
    plan = {
        "candidate_evidence_hash": candidate_evidence["hash"],
        "job_hash": semantic_result.get("job_hash", ""),
        "extracted_job_phrases": phrases,
        "phrase_to_evidence_matches": phrase_matches,
        "resume_change_blocks": resume_change_blocks,
        "selected_cover_letter_blocks": selected_cover_blocks,
        "cover_letter_paragraphs": cover_letter_paragraphs,
        "total_editable_paragraphs": len([item for item in resume_evidence if item.get("evidence_type") in {"professional experience", "project", "skill"}]),
        "validation": validate_plan(phrase_matches, resume_change_blocks, selected_cover_blocks, candidate_evidence, job),
    }
    plan["change_log"] = build_change_log(plan)
    plan["cover_letter_text"] = "\n\n".join(cover_letter_paragraphs)
    return plan


def extract_job_phrases(job: dict[str, Any]) -> list[dict[str, Any]]:
    content = normalize_space(
        " ".join(
            str(job.get(field) or "")
            for field in ["required_skills", "preferred_skills", "responsibilities", "job_description", "title"]
        )
    )
    if not content:
        return []
    phrases: list[str] = []
    for candidate in CURATED_PHRASES:
        if candidate.lower() in content.lower():
            phrases.append(candidate)
    for term in TECHNICAL_TERMS:
        if contains_phrase(content, term):
            phrases.append(term)
    for chunk in re.split(r"[,;/\n]+|(?<=[.!?])\s+", content):
        clean = normalize_space(chunk.strip(" -*:"))
        if not _looks_like_phrase(clean):
            continue
        phrases.append(clean)
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for phrase in phrases:
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append({"phrase": phrase, "category": classify_phrase(phrase)})
    return output


def classify_phrase(phrase: str) -> str:
    lowered = phrase.lower()
    for category, tokens in TECH_CATEGORY_RULES:
        if any(token in lowered for token in tokens):
            return category
    return "domain terminology"


def match_job_phrase(
    phrase: dict[str, Any],
    job: dict[str, Any],
    candidate_evidence: dict[str, Any],
    semantic_result: dict[str, Any],
    resume_evidence: list[dict[str, Any]],
    evidence_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    job_phrase = phrase["phrase"]
    best_match = _best_semantic_match(job_phrase, phrase["category"], semantic_result.get("matches", []), resume_evidence, evidence_index)
    evidence_item = evidence_index.get(normalize_space(best_match.get("matched_resume_evidence", ""))) if best_match else None
    if evidence_item is None and best_match and best_match.get("matched_resume_evidence"):
        evidence_item = {
            "text": best_match["matched_resume_evidence"],
            "source_section": best_match.get("evidence_source") or "uploaded resume text",
            "evidence_type": _evidence_type_for_source(best_match.get("evidence_source") or ""),
            "confidence": best_match.get("confidence", 0),
        }
    if evidence_item is None:
        evidence_item = _fallback_evidence(job_phrase, resume_evidence)
    exact_overlap = round(keyword_overlap(job_phrase, evidence_item.get("text", "")), 3)
    semantic_similarity = round(float(best_match.get("semantic_similarity", 0)) if best_match else lexical_similarity(job_phrase, evidence_item.get("text", "")), 3)
    confidence = int(best_match.get("confidence", 0)) if best_match else int(round((semantic_similarity * 70) + (exact_overlap * 30)))
    grounded = _phrase_is_supported(job_phrase, evidence_item, candidate_evidence)
    unsupported_terms = _unsupported_terms(job_phrase, candidate_evidence, evidence_item)
    return {
        "job_phrase": job_phrase,
        "job_phrase_category": phrase["category"],
        "exact_original_resume_paragraph": evidence_item.get("text", ""),
        "evidence_section": evidence_item.get("source_section") or evidence_item.get("evidence_type") or "uploaded resume text",
        "semantic_similarity": semantic_similarity,
        "exact_keyword_overlap": exact_overlap,
        "match_type": best_match.get("match_type", "transferable") if best_match else ("direct" if exact_overlap >= 0.35 else "transferable"),
        "confidence": confidence,
        "unsupported_terms": unsupported_terms,
        "evidence_id": _stable_id(evidence_item.get("text", "")),
        "evidence_text": evidence_item.get("text", ""),
        "category": phrase["category"],
        "grounded": grounded,
    }


def build_resume_change_blocks(
    phrase_matches: list[dict[str, Any]],
    profile: dict[str, Any],
    job: dict[str, Any],
    candidate_evidence: dict[str, Any],
    evidence_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    seen_originals: set[str] = set()
    relevant_sections = {"professional experience", "project", "skill", "uploaded resume text"}
    for match in sorted(phrase_matches, key=lambda item: (item["confidence"], item["exact_keyword_overlap"]), reverse=True):
        original = normalize_space(match["exact_original_resume_paragraph"])
        if not original or original in seen_originals or match["evidence_section"] not in relevant_sections:
            continue
        proposed, changed, validation, skip_reason = rewrite_paragraph(original, match["job_phrase"], match, job, candidate_evidence)
        block = {
            "change_id": _stable_id(f"{original}|{match['job_phrase']}"),
            "section": _section_for_evidence(match["evidence_section"]),
            "original_text": original,
            "proposed_text": proposed,
            "matched_job_phrase": match["job_phrase"],
            "supporting_evidence": match["evidence_text"],
            "changed_wording": changed,
            "confidence": match["confidence"],
            "grounded": validation["grounded"],
            "validation_result": validation,
            "skip_reason": skip_reason,
            "evidence_id": match["evidence_id"],
            "evidence_section": match["evidence_section"],
            "match_type": match["match_type"],
            "unsupported_terms": match["unsupported_terms"],
        }
        if validation["grounded"] and proposed.strip() and proposed != original:
            blocks.append(block)
            seen_originals.add(original)
    return blocks[:5]


def build_skills_block(profile: dict[str, Any], phrase_matches: list[dict[str, Any]], candidate_evidence: dict[str, Any]) -> dict[str, Any] | None:
    skills_text = normalize_space(str(profile.get("key_skills") or ""))
    if not skills_text:
        return None
    skills = [skill.strip() for skill in re.split(r"[,;\n]+", skills_text) if skill.strip()]
    supported = []
    evidence_text = candidate_evidence.get("full_text", "").lower()
    for skill in skills:
        if skill.lower() in evidence_text:
            supported.append(skill)
    if not supported:
        return None
    ordered = reorder_skills(supported, phrase_matches)
    proposed_text = ", ".join(ordered)
    if normalize_space(proposed_text) == normalize_space(skills_text):
        return None
    return {
        "change_id": _stable_id(f"skills|{skills_text}"),
        "section": "skills",
        "original_text": skills_text,
        "proposed_text": proposed_text,
        "matched_job_phrase": "Skills reordered for job relevance",
        "supporting_evidence": ", ".join(ordered[:6]),
        "changed_wording": "Skill order prioritized supported job-relevant terms.",
        "confidence": 72,
        "grounded": True,
        "validation_result": {"grounded": True, "ok": True, "reason": ""},
        "skip_reason": "",
        "evidence_id": _stable_id(skills_text),
        "evidence_section": "skill list",
        "match_type": "direct",
        "unsupported_terms": [],
    }


def reorder_skills(skills: list[str], phrase_matches: list[dict[str, Any]]) -> list[str]:
    priorities: list[str] = []
    lower_skills = {skill.lower(): skill for skill in skills}
    ordered_matches = sorted(phrase_matches, key=lambda item: item["confidence"], reverse=True)
    for match in ordered_matches:
        phrase = match["job_phrase"].lower()
        for skill in skills:
            lower = skill.lower()
            if lower in priorities:
                continue
            if lower in phrase or phrase in lower or _skill_supported_by_match(skill, match):
                priorities.append(lower)
    remaining = [skill.lower() for skill in skills if skill.lower() not in priorities]
    return [lower_skills[key] for key in [*priorities, *remaining]]


def _skill_supported_by_match(skill: str, match: dict[str, Any]) -> bool:
    evidence = f"{match.get('evidence_text', '')} {match.get('job_phrase', '')}".lower()
    return skill.lower() in evidence or any(token in evidence for token in re.split(r"\s+", skill.lower()) if len(token) > 2)


def rewrite_paragraph(
    original: str,
    job_phrase: str,
    match: dict[str, Any],
    job: dict[str, Any],
    candidate_evidence: dict[str, Any],
) -> tuple[str, str, dict[str, Any], str]:
    proposed = original
    changed_parts: list[str] = []
    rule_applied = False
    lower_phrase = job_phrase.lower()
    lower_original = proposed.lower()
    for rule in REWRITE_RULES:
        if rule["category"] != match["job_phrase_category"]:
            continue
        if not any(token in (match["evidence_text"] + " " + lower_phrase).lower() for token in rule["requires"]):
            continue
        for pattern, replacement in rule["patterns"]:
            if re.search(pattern, proposed, flags=re.I):
                proposed = re.sub(pattern, replacement, proposed, flags=re.I)
                changed_parts.append(replacement)
                rule_applied = True
        if rule_applied and rule.get("insert") and rule["insert"].lower() not in proposed.lower():
            if proposed.endswith("."):
                proposed = proposed[:-1] + f" with {rule['insert']}."
            else:
                proposed = f"{proposed} with {rule['insert']}"
    if not rule_applied:
        if match["job_phrase_category"] == "collaboration/stakeholder requirements" and "worked with" in lower_original:
            proposed = re.sub(r"\bworked with\b", "Collaborated with", proposed, flags=re.I)
            if "cross-functional" not in proposed.lower():
                proposed = proposed.replace("Collaborated with", "Collaborated with cross-functional", 1)
            changed_parts.append("collaborated with cross-functional teams")
            rule_applied = True
        elif match["job_phrase_category"] == "documentation/maintainability requirements" and "document" in lower_original:
            proposed = re.sub(r"\bdocument release steps\b", "document release steps and technical documentation", proposed, flags=re.I)
            if "technical documentation" not in proposed.lower():
                proposed = proposed.replace("document", "document technical documentation", 1)
            changed_parts.append("technical documentation")
            rule_applied = True
    proposed = normalize_space(proposed)
    if proposed and proposed[-1] not in ".!?":
        proposed += "."
    validation = validate_rewrite(original, proposed, job_phrase, candidate_evidence)
    skip_reason = "" if validation["grounded"] else validation.get("reason", "rewrite was not sufficiently grounded")
    changed = "; ".join(dict.fromkeys(changed_parts)) or "Supported job phrase was lightly reordered."
    return proposed, changed, validation, skip_reason


def validate_rewrite(original: str, proposed: str, job_phrase: str, candidate_evidence: dict[str, Any]) -> dict[str, Any]:
    original_numbers = re.findall(r"\d+(?:\.\d+)?%?", original)
    proposed_numbers = re.findall(r"\d+(?:\.\d+)?%?", proposed)
    if original_numbers != proposed_numbers:
        return {"grounded": False, "ok": False, "reason": "metrics or numbers changed"}
    if len(proposed) > max(1, int(len(original) * 1.25)):
        return {"grounded": False, "ok": False, "reason": "rewrite exceeded target length"}
    if proposed == original:
        return {"grounded": False, "ok": False, "reason": "cosmetic-only change"}
    added_terms = [term for term in useful_tokens(proposed) if term not in useful_tokens(original)]
    if not any(term in candidate_evidence.get("full_text", "").lower() or term in job_phrase.lower() for term in added_terms):
        original_lead = original.lower().split(" ", 1)[0] if original else ""
        proposed_lead = proposed.lower().split(" ", 1)[0] if proposed else ""
        if not (
            original_lead in ACTION_VERBS
            and proposed_lead == ACTION_VERBS[original_lead].lower()
            and any(token in candidate_evidence.get("full_text", "").lower() or token in job_phrase.lower() for token in useful_tokens(original))
        ):
            return {"grounded": False, "ok": False, "reason": "no supported job phrase added"}
    return {"grounded": True, "ok": True, "reason": ""}


def select_cover_letter_blocks(resume_change_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = sorted(
        [block for block in resume_change_blocks if block.get("grounded") and block.get("section") in {"experience", "projects"}],
        key=lambda item: (int(item.get("confidence", 0)), len(item.get("proposed_text", ""))),
        reverse=True,
    )
    return scored[:3]


def build_cover_letter_paragraphs(
    job: dict[str, Any],
    profile: dict[str, Any],
    selected_blocks: list[dict[str, Any]],
    candidate_evidence: dict[str, Any],
) -> list[str]:
    company = normalize_space(str(job.get("company") or "your team"))
    title = normalize_space(str(job.get("title") or "the role"))
    location = normalize_space(str(job.get("location") or ""))
    name = normalize_space(str(profile.get("name") or ""))
    concepts = [
        normalize_space(block.get("matched_job_phrase") or block.get("job_phrase") or "")
        for block in selected_blocks
        if normalize_space(block.get("matched_job_phrase") or block.get("job_phrase") or "")
    ]
    focus = short_join(concepts[:3]) if concepts else "the most relevant experience from my background"
    evidence_sentences = [build_evidence_sentence(block) for block in selected_blocks[:2]]
    if not evidence_sentences:
        evidence_sentences = ["My background includes practical experience that aligns with the role requirements."]
    fit_sentence = build_fit_sentence(job, selected_blocks, candidate_evidence)
    employer_line = company if not location else f"{company} - {location}"
    subject = f"Re: Application for {title}"
    return [
        date.today().strftime("%B %d, %Y").replace(" 0", " "),
        employer_line,
        f"Dear {company} Hiring Team,",
        subject,
        f"I'm excited to apply for the {title} role at {company}. The posting stood out because it aligns with {focus} and the practical execution I have already used in real projects.",
        " ".join(evidence_sentences)
        + f" These examples come from existing work experience and projects, which lets me speak directly to the role with truthful, relevant detail.",
        fit_sentence + f" I would bring that same focus to {company} through clear communication and dependable follow-through.",
        f"Thank you for your consideration. I would welcome the chance to discuss how I can contribute to {company} as a {title.lower()}.",
        "Sincerely,",
        name,
    ]


def build_opening_fit_sentence(selected_blocks: list[dict[str, Any]], candidate_evidence: dict[str, Any]) -> str:
    concepts = [block["matched_job_phrase"] for block in selected_blocks[:2]]
    if not concepts:
        concepts = ["relevant experience"]
    return f"My background aligns through {short_join(concepts)} and other practical experience from my work history."


def build_evidence_sentence(block: dict[str, Any]) -> str:
    phrase = block.get("proposed_text") or block.get("original_text") or ""
    phrase = normalize_space(phrase)
    if len(phrase) > 400:
        phrase = phrase[:397].rstrip() + "..."
    return f"In recent experience, I {phrase[0].lower() + phrase[1:]}" if phrase else ""


def build_fit_sentence(job: dict[str, Any], selected_blocks: list[dict[str, Any]], candidate_evidence: dict[str, Any]) -> str:
    company = normalize_space(str(job.get("company") or "the company"))
    concepts = [block["matched_job_phrase"] for block in selected_blocks[:3]]
    if not concepts:
        concepts = ["documentation", "collaboration", "quality"]
    return (
        f"I would bring the same focus to {company}, especially in work that values {short_join(concepts)}, "
        f"clear communication, and dependable follow-through."
    )


def short_join(items: list[str]) -> str:
    clean = [normalize_space(item) for item in items if normalize_space(item)]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return " and ".join(clean)
    return ", ".join(clean[:-1]) + f", and {clean[-1]}"


def validate_plan(
    phrase_matches: list[dict[str, Any]],
    resume_change_blocks: list[dict[str, Any]],
    cover_letter_blocks: list[dict[str, Any]],
    candidate_evidence: dict[str, Any],
    job: dict[str, Any],
) -> dict[str, Any]:
    resume_ok = bool(resume_change_blocks)
    cover_ok = bool(cover_letter_blocks)
    unsupported = [match["job_phrase"] for match in phrase_matches if match["unsupported_terms"] and not match["grounded"]]
    return {
        "ok": resume_ok and cover_ok and not unsupported,
        "resume_ok": resume_ok,
        "cover_letter_ok": cover_ok,
        "conflicting_phrases": unsupported,
        "unsupported_terms": unsupported,
        "empty_or_corrupted_evidence": not bool(candidate_evidence.get("full_text")),
        "job_title_tokens": sorted(useful_tokens(str(job.get("title") or ""))),
    }


def build_change_log(plan: dict[str, Any]) -> dict[str, Any]:
    applied = [
        {
            "section": item["section"],
            "original_text": item["original_text"],
            "new_text": item["proposed_text"],
            "matched_job_phrase": item["matched_job_phrase"],
            "supporting_evidence": item["supporting_evidence"],
            "confidence": item["confidence"],
        }
        for item in plan["resume_change_blocks"]
        if item.get("grounded")
    ]
    skipped = [
        {
            "section": item["section"],
            "original_text": item["original_text"],
            "new_text": item["proposed_text"],
            "matched_job_phrase": item["matched_job_phrase"],
            "skip_reason": item.get("skip_reason") or item.get("validation_result", {}).get("reason", ""),
        }
        for item in plan["resume_change_blocks"]
        if not item.get("grounded")
    ]
    return {
        "total_editable_paragraphs": plan.get("total_editable_paragraphs", 0),
        "extracted_job_phrases": plan.get("extracted_job_phrases", []),
        "phrase_to_evidence_matches": plan.get("phrase_to_evidence_matches", []),
        "proposed_changes": plan.get("resume_change_blocks", []),
        "applied_changes": applied,
        "skipped_changes": skipped,
    }


def _best_semantic_match(
    job_phrase: str,
    category: str,
    semantic_matches: list[dict[str, Any]],
    resume_evidence: list[dict[str, Any]],
    evidence_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    lowered = job_phrase.lower()
    best: dict[str, Any] | None = None
    for match in semantic_matches:
        requirement = str(match.get("job_requirement") or "").lower()
        if not requirement:
            continue
        if lowered == requirement or lowered in requirement or requirement in lowered or match.get("category") == category:
            if best is None or int(match.get("confidence", 0)) > int(best.get("confidence", 0)):
                best = match
    if best is not None:
        return best
    best_score = -1.0
    best_match: dict[str, Any] = {}
    for evidence in resume_evidence:
        text_value = evidence.get("text", "")
        exact = keyword_overlap(job_phrase, text_value)
        semantic = lexical_similarity(job_phrase, text_value)
        score = semantic * 0.7 + exact * 0.3
        if score > best_score:
            best_score = score
            best_match = {
                "job_requirement": job_phrase,
                "matched_resume_evidence": text_value,
                "semantic_similarity": semantic,
                "exact_keyword_overlap": exact,
                "evidence_source": evidence.get("source_section") or evidence.get("evidence_type") or "",
                "confidence": round(score * 100),
                "match_type": "direct" if exact >= 0.35 else "transferable",
            }
    return best_match


def _fallback_evidence(job_phrase: str, resume_evidence: list[dict[str, Any]]) -> dict[str, Any]:
    if resume_evidence:
        return resume_evidence[0]
    return {"text": job_phrase, "source_section": "uploaded resume text", "evidence_type": "uploaded resume text"}


def _phrase_is_supported(job_phrase: str, evidence_item: dict[str, Any], candidate_evidence: dict[str, Any]) -> bool:
    evidence_text = f"{evidence_item.get('text', '')} {candidate_evidence.get('full_text', '')}".lower()
    tokens = useful_tokens(job_phrase)
    if not tokens:
        return False
    hits = sum(1 for token in tokens if token in evidence_text)
    return hits / len(tokens) >= 0.5


def _unsupported_terms(job_phrase: str, candidate_evidence: dict[str, Any], evidence_item: dict[str, Any]) -> list[str]:
    tokens = useful_tokens(job_phrase)
    available = useful_tokens(candidate_evidence.get("full_text", "") + " " + evidence_item.get("text", ""))
    return sorted(token for token in tokens if token not in available)


def _looks_like_phrase(value: str) -> bool:
    if not value:
        return False
    words = value.split()
    if len(words) < 2 or len(words) > 10:
        return False
    lowered = value.lower()
    return not any(stop == lowered for stop in MULTI_WORD_PHRASE_STOPWORDS)


def _stable_id(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _section_for_evidence(value: str) -> str:
    lowered = value.lower()
    if "skill" in lowered:
        return "skills"
    if "project" in lowered:
        return "projects"
    if "experience" in lowered or "intern" in lowered:
        return "experience"
    return "experience"


def _evidence_type_for_source(value: str) -> str:
    lowered = value.lower()
    if "skill" in lowered:
        return "skill"
    if "project" in lowered:
        return "project"
    return "professional experience"
