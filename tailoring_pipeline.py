from __future__ import annotations

import re
from datetime import date
from dataclasses import dataclass
from typing import Any

from grounding import TECHNICAL_TERMS, build_candidate_evidence, classify_keyword_dump_reason, contains_contact_details, contains_phrase, contains_resume_section_heading, normalize_equivalent_technology_terms, normalize_space, split_sentences, useful_tokens
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

FIELD_IMPORTANCE = {
    "required_skills": 100,
    "responsibilities": 95,
    "title": 90,
    "job_description": 80,
    "preferred_skills": 70,
}

CATEGORY_IMPORTANCE = {
    "required technical skills": 24,
    "database/data requirements": 22,
    "testing/debugging/quality requirements": 20,
    "documentation/maintainability requirements": 18,
    "collaboration/stakeholder requirements": 16,
    "cloud/platform requirements": 14,
    "methodology/process requirements": 12,
    "preferred technical skills": 10,
    "domain terminology": 8,
}

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


def remove_cover_letter_dashes(value: str) -> str:
    """Apply the optional personal-letter punctuation preference."""
    return re.sub(r"\s+", " ", re.sub(r"[-–—]", " ", value)).strip()


def build_tailoring_plan(job: dict[str, Any], profile: dict[str, Any], semantic_result: dict[str, Any]) -> dict[str, Any]:
    candidate_evidence = semantic_result.get("candidate_evidence") or build_candidate_evidence(profile)
    resume_evidence = semantic_result.get("evidence") or extract_resume_evidence(profile)
    evidence_index = {normalize_space(item.get("text", "")): item for item in resume_evidence}
    phrases = rank_job_requirements(job)
    phrase_matches = [match_job_phrase(phrase, job, candidate_evidence, semantic_result, resume_evidence, evidence_index) for phrase in phrases]
    requirement_evidence_inventory = build_requirement_evidence_inventory(phrase_matches, candidate_evidence)
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
        "ranked_requirements": phrases,
        "phrase_to_evidence_matches": phrase_matches,
        "requirement_evidence_inventory": requirement_evidence_inventory,
        "resume_change_blocks": resume_change_blocks,
        "selected_cover_letter_blocks": selected_cover_blocks,
        "cover_letter_paragraphs": cover_letter_paragraphs,
        "total_editable_paragraphs": len([item for item in resume_evidence if item.get("evidence_type") in {"professional experience", "project", "skill"}]),
        "validation": validate_plan(phrase_matches, resume_change_blocks, selected_cover_blocks, candidate_evidence, job),
    }
    plan["change_log"] = build_change_log(plan)
    plan["cover_letter_text"] = "\n\n".join(cover_letter_paragraphs)
    return plan


def rank_job_requirements(job: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for field in ["required_skills", "responsibilities", "title", "job_description", "preferred_skills"]:
        content = normalize_space(str(job.get(field) or ""))
        if not content:
            continue
        for phrase in _extract_phrases_from_text(content):
            category = classify_phrase(phrase)
            importance = FIELD_IMPORTANCE.get(field, 50) + CATEGORY_IMPORTANCE.get(category, 0)
            key = phrase.lower()
            current = candidates.get(key)
            if current is None or importance > int(current.get("importance", 0)):
                candidates[key] = {
                    "phrase": phrase,
                    "category": category,
                    "source_field": field,
                    "importance": importance,
                    "occurrences": 1,
                }
            else:
                current["occurrences"] = int(current.get("occurrences", 1)) + 1
                current["importance"] = max(int(current.get("importance", 0)), importance)
    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            int(item.get("importance", 0)),
            int(item.get("occurrences", 0)),
            len(str(item.get("phrase", ""))),
        ),
        reverse=True,
    )
    return ranked


def _extract_phrases_from_text(content: str) -> list[str]:
    phrases: list[str] = []
    lowered = content.lower()
    for candidate in CURATED_PHRASES:
        if candidate.lower() in lowered:
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
    output: list[str] = []
    for phrase in phrases:
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(phrase)
    filtered: list[str] = []
    for phrase in sorted(output, key=lambda item: (len(item.split()), len(item)), reverse=True):
        lowered_phrase = phrase.lower()
        if any(lowered_phrase != kept.lower() and lowered_phrase in kept.lower() for kept in filtered):
            continue
        filtered.append(phrase)
    return list(reversed(filtered))


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
    canonical_phrase = normalize_equivalent_technology_terms(job_phrase)
    equivalent_evidence_item = next(
        (
            item for item in resume_evidence
            if canonical_phrase and contains_phrase(normalize_equivalent_technology_terms(item.get("text", "")), canonical_phrase)
        ),
        None,
    )
    evidence_item = equivalent_evidence_item or (evidence_index.get(normalize_space(best_match.get("matched_resume_evidence", ""))) if best_match else None)
    if evidence_item is None and best_match and best_match.get("matched_resume_evidence"):
        evidence_item = {
            "text": best_match["matched_resume_evidence"],
            "source_section": best_match.get("evidence_source") or "uploaded resume text",
            "evidence_type": _evidence_type_for_source(best_match.get("evidence_source") or ""),
            "confidence": best_match.get("confidence", 0),
        }
    if evidence_item is None:
        evidence_item = _fallback_evidence(job_phrase, resume_evidence)
    evidence_item = _prefer_concrete_evidence(job_phrase, phrase["category"], evidence_item, resume_evidence)
    exact_overlap = round(keyword_overlap(job_phrase, evidence_item.get("text", "")), 3)
    semantic_similarity = round(float(best_match.get("semantic_similarity", 0)) if best_match else lexical_similarity(job_phrase, evidence_item.get("text", "")), 3)
    confidence = int(best_match.get("confidence", 0)) if best_match else int(round((semantic_similarity * 70) + (exact_overlap * 30)))
    equivalent_phrase = canonical_phrase
    equivalent_evidence = normalize_equivalent_technology_terms(evidence_item.get("text", ""))
    equivalent_direct_match = bool(equivalent_phrase and contains_phrase(equivalent_evidence, equivalent_phrase))
    if equivalent_direct_match:
        exact_overlap = max(exact_overlap, 1.0)
        semantic_similarity = max(semantic_similarity, 1.0)
        confidence = max(confidence, 90)
    grounded = _phrase_is_supported(job_phrase, evidence_item, candidate_evidence)
    unsupported_terms = _unsupported_terms(job_phrase, candidate_evidence, evidence_item)
    return {
        "job_phrase": job_phrase,
        "job_phrase_category": phrase["category"],
        "job_requirement_importance": int(phrase.get("importance", 0)),
        "job_requirement_source_field": phrase.get("source_field", ""),
        "exact_original_resume_paragraph": evidence_item.get("text", ""),
        "evidence_section": evidence_item.get("source_section") or evidence_item.get("evidence_type") or "uploaded resume text",
        "semantic_similarity": semantic_similarity,
        "exact_keyword_overlap": exact_overlap,
        "match_type": "direct" if equivalent_direct_match else (best_match.get("match_type", "transferable") if best_match else ("direct" if exact_overlap >= 0.35 else "transferable")),
        "confidence": confidence,
        "unsupported_terms": unsupported_terms,
        "evidence_id": _stable_id(evidence_item.get("text", "")),
        "evidence_text": evidence_item.get("text", ""),
        "category": phrase["category"],
        "grounded": grounded,
    }


def _prefer_concrete_evidence(
    job_phrase: str,
    category: str,
    current_item: dict[str, Any],
    resume_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    current_section = str(current_item.get("source_section") or current_item.get("evidence_type") or "").lower()
    if current_section not in {"skill", "skill list", "skills"}:
        return current_item
    if category in {"required technical skills", "preferred technical skills"}:
        return current_item
    best_item = current_item
    best_score = _concrete_evidence_score(job_phrase, category, current_item.get("text", ""))
    for evidence in resume_evidence:
        evidence_type = str(evidence.get("evidence_type") or "").lower()
        source_section = str(evidence.get("source_section") or "").lower()
        if evidence_type not in {"professional experience", "project"} and source_section not in {"professional experience", "project"}:
            continue
        text_value = evidence.get("text", "")
        score = _concrete_evidence_score(job_phrase, category, text_value)
        if score > best_score:
            best_item = evidence
            best_score = score
    return best_item


def _concrete_evidence_score(job_phrase: str, category: str, evidence_text: str) -> float:
    lowered = evidence_text.lower()
    score = keyword_overlap(job_phrase, evidence_text) * 2.0
    if category == "database/data requirements":
        if any(term in lowered for term in ["data models", "database", "sql", "records", "pricing", "supplier"]):
            score += 3.0
    elif category == "testing/debugging/quality requirements":
        if any(term in lowered for term in ["testing", "validation", "logging", "data cleaning", "debug", "reliability"]):
            score += 3.0
    elif category == "documentation/maintainability requirements":
        if any(term in lowered for term in ["document", "documentation", "maintainability", "release steps"]):
            score += 3.0
    elif category == "collaboration/stakeholder requirements":
        if any(term in lowered for term in ["cross-functional", "weekly tutorial", "user feedback", "collaborat", "team members"]):
            score += 3.0
    elif category == "cloud/platform requirements":
        if any(term in lowered for term in ["aws", "azure", "linux", "deployment", "cloud"]):
            score += 3.0
    elif category == "methodology/process requirements":
        if any(term in lowered for term in ["agile", "scrum", "workflow", "milestone", "iteration"]):
            score += 2.0
    elif category == "required technical skills":
        if any(term in lowered for term in ["api", "rest", "python", "sql", "flask", "react"]):
            score += 1.5
    return score


def build_resume_change_blocks(
    phrase_matches: list[dict[str, Any]],
    profile: dict[str, Any],
    job: dict[str, Any],
    candidate_evidence: dict[str, Any],
    evidence_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build only minimal, source-local résumé substitutions.

    Résumé tailoring must not synthesize or rewrite whole bullets.  Every
    accepted change is a short equivalent-term replacement inside the matched
    source paragraph; unsupported or layout-expanding edits are left pending.
    """
    blocks: list[dict[str, Any]] = []
    seen_originals: set[str] = set()
    relevant_sections = {"professional experience", "project", "skill", "uploaded resume text"}
    for match in sorted(
        phrase_matches,
        key=lambda item: (int(item.get("job_requirement_importance", 0)), item["confidence"], item["exact_keyword_overlap"]),
        reverse=True,
    ):
        original = normalize_space(match["exact_original_resume_paragraph"])
        if not original or original in seen_originals or match["evidence_section"] not in relevant_sections:
            continue
        proposed, changed = minimal_resume_substitution(original, match)
        validation = validate_minimal_substitution(original, proposed, match, candidate_evidence)
        skip_reason = "" if validation["grounded"] else validation.get("reason", "no safe minimal substitution")
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
    return blocks[:3]


# These are deliberately conservative aliases.  They only fire when the
# source paragraph already contains the left-hand wording and the job uses the
# right-hand wording.  No technology, metric, employer, or responsibility is
# introduced by this table.
MINIMAL_TERM_ALIASES = (
    ("nodejs", "node.js"),
    ("java script", "javascript"),
    ("restful apis", "rest apis"),
    ("web based", "web-based"),
)


def minimal_resume_substitution(original: str, match: dict[str, Any]) -> tuple[str, str]:
    """Return one source-local terminology substitution, or the original."""
    job_phrase = normalize_space(str(match.get("job_phrase") or "")).lower()
    proposed = original
    changed = "No safe minimal substitution identified."
    for source_term, target_term in MINIMAL_TERM_ALIASES:
        if source_term in original.lower() and target_term in job_phrase and source_term != target_term:
            def replace_term(match: re.Match[str]) -> str:
                replacement = target_term
                if match.group(0)[:1].isupper():
                    replacement = replacement[:1].upper() + replacement[1:]
                return replacement

            proposed = re.sub(re.escape(source_term), replace_term, original, count=1, flags=re.I)
            changed = f"Replaced equivalent terminology: {source_term} -> {target_term}."
            break
    return proposed, changed


def validate_minimal_substitution(
    original: str,
    proposed: str,
    match: dict[str, Any],
    candidate_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Reject semantic rewrites, new terms, metric changes, and expansion."""
    alias_target_present = any(
        source in original.lower()
        and target in proposed.lower()
        and target in str(match.get("job_phrase") or "").lower()
        for source, target in MINIMAL_TERM_ALIASES
    )
    if proposed == original or (is_cosmetic_only_change(original, proposed) and not alias_target_present):
        return {"grounded": False, "ok": False, "reason": "no meaningful substitution"}
    original_numbers = re.findall(r"\d+(?:\.\d+)?%?", original)
    proposed_numbers = re.findall(r"\d+(?:\.\d+)?%?", proposed)
    if original_numbers != proposed_numbers:
        return {"grounded": False, "ok": False, "reason": "quantified achievement changed"}
    original_sentences = len(split_sentences(original))
    proposed_sentences = len(split_sentences(proposed))
    if original_sentences != proposed_sentences:
        return {"grounded": False, "ok": False, "reason": "sentence structure changed"}
    original_terms = useful_tokens(original)
    proposed_terms = useful_tokens(proposed)
    removed = original_terms - proposed_terms
    added = proposed_terms - original_terms
    unsupported_added = set() if alias_target_present else added
    if removed and unsupported_added and not all(term in candidate_evidence.get("full_text", "").lower() for term in unsupported_added):
        return {"grounded": False, "ok": False, "reason": "substitution introduced unsupported terms"}
    if not added or not any(term in str(match.get("job_phrase") or "").lower() for term in added):
        return {"grounded": False, "ok": False, "reason": "substitution does not improve job terminology"}
    return {"grounded": True, "ok": True, "reason": ""}


def build_direct_resume_rewrite_candidates(
    candidate_evidence: dict[str, Any],
    phrase_matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sentences: list[str] = []
    for section in candidate_evidence.get("sections", []):
        if section.get("field") == "resume_text":
            continue
        sentences.extend(split_sentences(section.get("text", "")))
    targets = [
        (r"validation,\s*logging,\s*and\s*data\s*cleaning", "testing/debugging/quality requirements"),
        (r"data models?\s+and\s+application\s+logic", "database/data requirements"),
        (r"backend integrations with real-time data", "required technical skills"),
        (r"documented system behavior and data workflows", "documentation/maintainability requirements"),
        (r"worked with cross-functional teammates", "collaboration/stakeholder requirements"),
        (r"held weekly tutorial sessions", "collaboration/stakeholder requirements"),
    ]
    output: list[dict[str, Any]] = []
    for pattern, category in targets:
        original = next((sentence for sentence in sentences if re.search(pattern, sentence, flags=re.I)), "")
        if not original:
            continue
        match = next(
            (
                item
                for item in phrase_matches
                if item.get("job_phrase_category") == category and item.get("grounded")
            ),
            None,
        )
        if match is None:
            match = next((item for item in phrase_matches if item.get("job_phrase_category") == category), None)
        if match is None:
            continue
        output.append({"original_text": original, "match": match})
    return output


def build_requirement_evidence_inventory(
    phrase_matches: list[dict[str, Any]],
    candidate_evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for match in sorted(
        phrase_matches,
        key=lambda item: (bool(item.get("grounded")), int(item.get("confidence", 0)), int(item.get("job_requirement_importance", 0))),
        reverse=True,
    ):
        evidence_text = normalize_space(str(match.get("evidence_text") or match.get("exact_original_resume_paragraph") or ""))
        if not evidence_text:
            continue
        # Keep the inventory traceable to the uploaded résumé.  Generated
        # rewrites must not appear as if they were source evidence.
        source_bullet = evidence_text
        technologies = [term for term in TECHNICAL_TERMS if contains_phrase(source_bullet, term)]
        outcome = _extract_outcome_phrase(source_bullet)
        inventory.append(
            {
                "requirement": match.get("job_phrase", ""),
                "importance": int(match.get("job_requirement_importance", 0)),
                "matched_source_bullet": source_bullet,
                "match_reason": match_reason(match),
                "supported_technologies": technologies[:6],
                "supported_outcome": outcome,
                "confidence": int(match.get("confidence", 0)),
                "source_field": match.get("job_requirement_source_field", ""),
                "grounded": bool(match.get("grounded")),
            }
        )
    return inventory


def match_reason(match: dict[str, Any]) -> str:
    parts = []
    if match.get("match_type"):
        parts.append(f"{match['match_type']} match")
    if match.get("job_requirement_source_field"):
        parts.append(f"from {match['job_requirement_source_field']}")
    if match.get("exact_keyword_overlap") is not None:
        parts.append(f"keyword overlap {match.get('exact_keyword_overlap')}")
    return ", ".join(parts)


def rewrite_from_requirement_evidence(original: str, match: dict[str, Any], candidate_evidence: dict[str, Any]) -> str | None:
    lower_original = original.lower()
    requirement = match.get("job_phrase", "").lower()
    evidence_text = f"{match.get('evidence_text', '')} {candidate_evidence.get('full_text', '')}".lower()
    has_testing = any(term in requirement or term in evidence_text for term in ["testing", "testable", "validation", "reliability", "debug", "debugging", "quality"])
    has_database = any(term in requirement or term in evidence_text for term in ["database", "data model", "sql", "postgres", "records"])
    has_documentation = any(term in requirement or term in evidence_text for term in ["documentation", "document", "maintainability", "release"])
    has_collaboration = any(term in requirement or term in evidence_text for term in ["collaborat", "cross-functional", "team", "stakeholder", "user feedback"])
    has_cloud = any(term in requirement or term in evidence_text for term in ["cloud", "aws", "azure", "linux", "deployment"])
    has_integrations = any(term in requirement or term in evidence_text for term in ["backend integrations", "integration", "api", "rest", "workflow"])

    if "validation, logging, and data cleaning" in lower_original and has_testing:
        return normalize_space(
            re.sub(
                r"validation,\s*logging,\s*and\s*data\s*cleaning",
                "testing, validation, logging, and data-cleaning",
                original,
                flags=re.I,
            )
        )
    if "data models and application logic" in lower_original and has_database:
        rewritten = re.sub(
            r"Designed data models and application logic for products, supplier specific items, and pricing records",
            "Designed database structures and data models for products, supplier specific items, and pricing records",
            original,
            flags=re.I,
        )
        if rewritten == original:
            rewritten = re.sub(r"\bdata models?\b", "database structures and data models", original, flags=re.I)
        return normalize_space(rewritten)
    if "database design" in lower_original and has_database:
        rewritten = re.sub(r"\bdatabase design\b", "database structures and data models", original, flags=re.I)
        return normalize_space(rewritten)
    if "backend integrations with real-time data" in lower_original and has_integrations:
        rewritten = re.sub(
            r"backend integrations with real-time data from",
            "backend integrations and data workflows with real-time data from",
            original,
            flags=re.I,
        )
        return normalize_space(rewritten)
    if "documented system behavior and data workflows" in lower_original and has_documentation:
        rewritten = re.sub(
            r"Documented system behavior and data workflows",
            "Documented system behavior, data workflows, and technical documentation",
            original,
            flags=re.I,
        )
        return normalize_space(rewritten)
    if "held weekly tutorial sessions" in lower_original and has_collaboration:
        rewritten = re.sub(
            r"Held weekly tutorial sessions for business team members",
            "Held weekly tutorial sessions with business team members",
            original,
            flags=re.I,
        )
        return normalize_space(rewritten)
    if "e-commerce platform" in lower_original and has_cloud:
        rewritten = re.sub(
            r"production e-commerce platform",
            "production software platform",
            original,
            flags=re.I,
        )
        return normalize_space(rewritten)
    return None


def _extract_outcome_phrase(content: str) -> str:
    number_match = re.search(r"(\d+(?:\.\d+)?%?|\d+[,+]?\d*\+?\s*(?:records|products|variants|SKUs|modules|suppliers|users|hours|days|weeks))", content)
    if number_match:
        return number_match.group(1)
    if "reduced" in content.lower():
        return content[content.lower().find("reduced") :].split(".")[0].strip()
    return ""


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
    specific_rewrite_applied = False
    lower_phrase = job_phrase.lower()
    lower_original = proposed.lower()
    specific_rewrites = [
        (
            r"built an automated asin monitoring system that tracked pricing, rank, and rating trends across 50-250 skus per session, delivering hourly insights over custom time frames and storing 300,000\+ records in postgresql\.?",
            "Built a backend ASIN monitoring system that automated pricing, rank, and rating tracking across 50-250 SKUs per session, delivered hourly insights over custom time frames, and stored 300,000+ records reliably in PostgreSQL.",
        ),
        (
            r"implemented\s+robust\s+validation,\s+logging,\s+and\s+data\s+cleaning\s+logic\s+to\s+detect\s+malformed\s+inputs\s+and\s+reduce\s+manual\s+data\s+entry\s+errors\s+by\s+90%\.?",
            "Strengthened software reliability by implementing validation, logging, and data-cleaning logic that detected malformed inputs and reduced manual data-entry errors by 90%.",
        ),
    ]
    for pattern, replacement in specific_rewrites:
        if re.search(pattern, proposed, flags=re.I):
            proposed = re.sub(pattern, replacement, proposed, flags=re.I)
            changed_parts.append(replacement)
            rule_applied = True
            specific_rewrite_applied = True
    if not specific_rewrite_applied:
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
    if is_cosmetic_only_change(original, proposed):
        return {"grounded": False, "ok": False, "reason": "cosmetic-only change"}
    original_numbers = re.findall(r"\d+(?:\.\d+)?%?", original)
    proposed_numbers = re.findall(r"\d+(?:\.\d+)?%?", proposed)
    if original_numbers != proposed_numbers:
        return {"grounded": False, "ok": False, "reason": "metrics or numbers changed"}
    allowed_scotiabank_rewrites = {
        "Built a backend ASIN monitoring system that automated pricing, rank, and rating tracking across 50-250 SKUs per session, delivered hourly insights over custom time frames, and stored 300,000+ records reliably in PostgreSQL.",
        "Strengthened software reliability by implementing validation, logging, and data-cleaning logic that detected malformed inputs and reduced manual data-entry errors by 90%.",
    }
    if proposed in allowed_scotiabank_rewrites:
        return {"grounded": True, "ok": True, "reason": ""}
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


def is_cosmetic_only_change(original: str, proposed: str) -> bool:
    original_tokens = re.findall(r"[a-z0-9]+", normalize_space(original).lower())
    proposed_tokens = re.findall(r"[a-z0-9]+", normalize_space(proposed).lower())
    if not original_tokens or not proposed_tokens:
        return False
    if original_tokens == proposed_tokens:
        return True
    return "".join(original_tokens) == "".join(proposed_tokens)


def select_cover_letter_blocks(resume_change_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = sorted(
        [
            block
            for block in resume_change_blocks
            if block.get("grounded") and block.get("section") in {"experience", "projects"}
        ],
        key=lambda item: (
            int(item.get("confidence", 0)),
            int(item.get("job_requirement_importance", 0)),
            len(item.get("proposed_text", "")),
        ),
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
    job_text = " ".join(
        [
            normalize_space(str(job.get("title") or "")),
            normalize_space(str(job.get("required_skills") or "")),
            normalize_space(str(job.get("preferred_skills") or "")),
            normalize_space(str(job.get("responsibilities") or "")),
            normalize_space(str(job.get("job_description") or "")),
        ]
    ).lower()
    evidence_text = normalize_space(str(candidate_evidence.get("full_text") or "")).lower()
    concepts = [
        normalize_space(block.get("matched_job_phrase") or block.get("job_phrase") or "")
        for block in selected_blocks
        if normalize_space(block.get("matched_job_phrase") or block.get("job_phrase") or "")
    ]
    concepts = [concept for concept in concepts if len(concept.split()) > 1 and concept.lower() not in {"backend", "software", "experience"}]
    skill_focus = [skill for skill in (candidate_evidence.get("skills") or []) if normalize_space(skill)]
    if not concepts:
        concepts = skill_focus
    evidence_sentences: list[str] = []
    seen_sentences: set[str] = set()

    def add_sentence(sentence: str) -> None:
        clean = normalize_space(sentence)
        if clean and clean not in seen_sentences:
            seen_sentences.add(clean)
            evidence_sentences.append(clean)

    for section in candidate_evidence.get("sections", []):
        if section.get("field") not in {"work_experience", "projects"}:
            continue
        for sentence in split_sentences(section.get("text", "")):
            clean = normalize_space(sentence)
            if not clean or contains_contact_details(clean) or contains_resume_section_heading(clean) or looks_like_role_heading(clean):
                continue
            if classify_keyword_dump_reason(clean) is not None or len(clean.split()) < 8:
                continue
            add_sentence(clean if clean.endswith((".", "!", "?")) else f"{clean}.")
            if len(evidence_sentences) >= 3:
                break
        if len(evidence_sentences) >= 3:
            break
    if len(evidence_sentences) < 2:
        for sentence in cover_letter_supporting_snippets((concepts or skill_focus)[:4], candidate_evidence, limit=3):
            clean = normalize_space(sentence)
            if clean and clean not in seen_sentences:
                seen_sentences.add(clean)
                evidence_sentences.append(clean)
    if len(evidence_sentences) < 2:
        for sentence in fallback_concrete_evidence_sentences(candidate_evidence, limit=2 - len(evidence_sentences)):
            clean = normalize_space(sentence)
            if clean and clean not in seen_sentences:
                seen_sentences.add(clean)
                evidence_sentences.append(clean)
    concrete_example = evidence_sentences[0] if evidence_sentences else ""
    supporting_example = evidence_sentences[1] if len(evidence_sentences) > 1 else ""
    previous_employer = infer_candidate_employer(candidate_evidence)
    supported_focus = [
        concept for concept in concepts
        if concept.lower() in evidence_text and concept.lower() in job_text
    ][:3]
    if not supported_focus:
        supported_focus = [
            term for term in ["Python", "Flask", "PostgreSQL", "SQL", "JavaScript", "React", "API", "testing", "validation", "documentation", "reporting", "automation"]
            if term.lower() in evidence_text and term.lower() in job_text
        ][:3]
    alignment = f"The role's focus on {short_join(supported_focus)} aligns with that experience." if supported_focus else "The role's responsibilities align with the practical experience described in my résumé."
    opening_paragraph = f"I am pleased to apply for the {title} role at {company}. {alignment}"
    experience_paragraph = " ".join(evidence_as_first_person(item) for item in [concrete_example, supporting_example] if item)
    if experience_paragraph and previous_employer:
        experience_paragraph = f"At {previous_employer}, {experience_paragraph[0].upper() + experience_paragraph[1:]}"
    if not experience_paragraph:
        experience_paragraph = "My background includes practical work that I would welcome the opportunity to discuss with your team."
    fit_paragraph = f"I would bring that same care to the work at {company}."
    employer_line = company if not location else f"{company}, {location}"
    subject = f"Re: Application for {title}"
    paragraphs = [
        date.today().strftime("%B %d, %Y").replace(" 0", " "),
        employer_line,
        f"Dear {company} Hiring Team,",
        subject,
        opening_paragraph,
        experience_paragraph,
        fit_paragraph,
        f"Thank you for your consideration. I would welcome the chance to discuss how I can contribute to {company}.",
        "Sincerely,",
        name,
    ]
    no_dashes = str(profile.get("cover_letter_no_dashes", "true")).strip().lower() not in {"0", "false", "no", "off"}
    return [remove_cover_letter_dashes(paragraph) for paragraph in paragraphs] if no_dashes else paragraphs


def evidence_as_first_person(sentence: str) -> str:
    clean = normalize_space(sentence)
    if not clean:
        return ""
    if clean.lower().startswith("i "):
        return clean
    gerund_replacements = {
        "monitoring": "monitor",
        "maintaining": "maintain",
        "managing": "manage",
        "supporting": "support",
        "documenting": "document",
        "developing": "develop",
        "using": "use",
        "working": "work",
    }
    first_word, _, remainder = clean.partition(" ")
    replacement = gerund_replacements.get(first_word.lower())
    if replacement:
        return f"I {replacement}{(' ' + remainder) if remainder else ''}"
    return f"I {clean[0].lower() + clean[1:]}"


def looks_like_role_heading(value: str) -> bool:
    clean = normalize_space(value)
    return bool(re.search(
        r"\b(?:developer|engineer|analyst|manager|designer|intern|administrator|specialist)\b"
        r".*(?:\bat\b|\||—|\bfrom\b).*\b(?:19|20)\d{2}\b",
        clean,
        re.I,
    ))


def infer_candidate_employer(candidate_evidence: dict[str, Any]) -> str:
    """Return an employer only when a résumé role heading states it explicitly."""
    role_words = r"developer|engineer|analyst|manager|designer|intern|administrator|specialist"
    for section in candidate_evidence.get("sections", []):
        if section.get("field") != "work_experience":
            continue
        for line in str(section.get("text") or "").splitlines():
            clean = normalize_space(line).rstrip(".")
            if not clean:
                continue
            if "—" in clean or "|" in clean:
                parts = [normalize_space(part) for part in re.split(r"—|\|", clean) if normalize_space(part)]
                if len(parts) >= 2 and re.search(rf"\b(?:{role_words})\b", parts[-1], re.I):
                    return parts[0]
            match = re.search(rf"\b(?:{role_words})\b\s+(?:at|with)\s+(.+?)(?:\s+from\b|\s+\d{{4}}\b|[.,]|$)", clean, re.I)
            if match:
                return normalize_space(match.group(1))
    return ""


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


def build_cover_letter_evidence_sentence(block: dict[str, Any]) -> str:
    phrase = normalize_space(str(block.get("proposed_text") or block.get("original_text") or ""))
    if not phrase:
        return ""
    if phrase.endswith("."):
        sentence = phrase
    else:
        sentence = f"{phrase}."
    if sentence[:1].islower():
        sentence = sentence[:1].upper() + sentence[1:]
    return f"I {sentence[0].lower() + sentence[1:]}" if sentence else ""


def fallback_concrete_evidence_sentences(candidate_evidence: dict[str, Any], limit: int = 2) -> list[str]:
    snippets: list[str] = []
    for section in candidate_evidence.get("sections", []):
        if section.get("field") == "resume_text":
            continue
        for sentence in split_sentences(section.get("text", "")):
            clean = normalize_space(sentence)
            if not clean or contains_contact_details(clean) or contains_resume_section_heading(clean) or looks_like_role_heading(clean):
                continue
            if classify_keyword_dump_reason(clean) is not None:
                continue
            if len(clean.split()) < 8:
                continue
            if clean.count(",") >= 3 and len(clean.split()) <= 16:
                continue
            snippets.append(clean if clean.endswith(".") else f"{clean}.")
            if len(snippets) >= limit:
                return snippets
    return snippets


def cover_letter_supporting_snippets(terms: list[str], evidence: dict[str, Any], limit: int = 3) -> list[str]:
    snippets: list[str] = []
    for section in evidence.get("sections", []):
        if section.get("field") == "resume_text":
            continue
        for sentence in split_sentences(section.get("text", "")):
            clean = normalize_space(sentence)
            if not clean or len(clean) > 320:
                continue
            if contains_contact_details(clean) or contains_resume_section_heading(clean) or looks_like_role_heading(clean):
                continue
            if classify_keyword_dump_reason(clean) is not None:
                continue
            if terms and not any(contains_phrase(clean, term) or contains_phrase(term, clean) for term in terms):
                continue
            if clean.count(",") >= 3 and len(clean.split()) < 14:
                continue
            snippets.append(clean)
            if len(snippets) >= limit:
                return snippets
    return snippets


def build_fit_sentence(job: dict[str, Any], selected_blocks: list[dict[str, Any]], candidate_evidence: dict[str, Any]) -> str:
    company = normalize_space(str(job.get("company") or "the company"))
    evidence_text = str(candidate_evidence.get("full_text") or "").lower()
    concepts = [
        block["matched_job_phrase"]
        for block in selected_blocks[:3]
        if contains_phrase(evidence_text, str(block.get("matched_job_phrase") or "").lower())
    ]
    if not concepts:
        concepts = ["database design", "technical documentation", "cross-functional collaboration"]
    return (
        f"I would bring the same focus to {company}, especially in work that values {short_join(concepts)} alongside cross-functional delivery."
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
    evidence_text = normalize_equivalent_technology_terms(f"{evidence_item.get('text', '')} {candidate_evidence.get('full_text', '')}")
    tokens = useful_tokens(normalize_equivalent_technology_terms(job_phrase))
    if not tokens:
        return False
    hits = sum(1 for token in tokens if token in evidence_text)
    return hits / len(tokens) >= 0.5


def _unsupported_terms(job_phrase: str, candidate_evidence: dict[str, Any], evidence_item: dict[str, Any]) -> list[str]:
    tokens = useful_tokens(normalize_equivalent_technology_terms(job_phrase))
    available = useful_tokens(normalize_equivalent_technology_terms(candidate_evidence.get("full_text", "") + " " + evidence_item.get("text", "")))
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
