from __future__ import annotations

import hashlib
import json
import re
import string
from typing import Any


PDF_CORRUPTION_MESSAGE = "This PDF could not be read reliably. Please upload a DOCX or TXT version, or paste the resume text manually."

PROFILE_EVIDENCE_FIELDS = [
    ("work_experience", "structured work experience"),
    ("key_skills", "structured key skills"),
    ("education", "structured education"),
    ("projects", "structured projects"),
    ("resume_text", "uploaded resume text"),
]

TECHNICAL_TERMS = [
    "software developer",
    "software engineer",
    "software projects",
    "dashboard",
    "dashboards",
    "automation",
    "api",
    "apis",
    "cloud",
    "cloud-aware",
    "cloud development",
    "aws",
    "azure",
    "python",
    "javascript",
    "typescript",
    "flask",
    "react",
    "sql",
    "sqlite",
    "database",
    "database-backed",
    "backend",
    "frontend",
    "engineering",
    "internal tools",
    "business workflows",
    "git",
    "github",
    "version control",
    "node.js",
    "nodejs",
    "express",
    "rest api",
    "rest apis",
    "postgresql",
    "postgres",
]

# These are spelling variants, not transferable skills.  Normalizing them only
# for evidence checks permits a format-preserving terminology correction while
# keeping the original claim and its scope intact.
EQUIVALENT_TECHNOLOGY_TERMS = {
    "nodejs": "node.js",
    "java script": "javascript",
    "postgres": "postgresql",
    "restful apis": "rest apis",
}

# This vocabulary is intentionally generic.  It is used for the transparent
# Keywords Score inventory, not to manufacture résumé content or to encode a
# particular job posting.
KEYWORD_VOCABULARY = [
    "c++", "c#", ".net", "node.js", "nodejs", "javascript", "typescript", "python", "java", "php", "html", "css", "sql",
    "flask", "react", "express", "jwt", "nginx", "linux", "windows", "debian", "ubuntu", "aws", "azure", "kafka",
    "figma", "jira", "git", "github", "bitbucket", "devops", "paas", "api", "apis", "rest api", "rest apis", "restful apis",
    "database", "database design", "postgresql", "postgres", "backend", "back-end", "frontend", "front-end", "ai", "tcp", "tcp/ip",
    "ip networking", "design patterns", "development life cycle", "object oriented programming", "data solutions", "video analytics",
    "thermal cameras", "performance monitoring", "virtualization", "message queues", "gps mapping", "telematics",
]

KEYWORD_ALIASES = {
    "nodejs": "node.js",
    "java script": "javascript",
    "backend": "backend",
    "back-end": "backend",
    "frontend": "frontend",
    "front-end": "frontend",
    "postgres": "postgresql",
    "restful apis": "rest apis",
    "rest api": "rest apis",
    "apis": "api",
}

RELATED_KEYWORD_EVIDENCE = {
    "data solutions": ("data", "workflow", "reporting", "analytics", "database", "models"),
    "design patterns": ("object oriented", "oop", "software design"),
    "development life cycle": ("designed", "developed", "deployed", "launched", "production"),
    "devops": ("deployment", "deployed", "production", "ci/cd", "infrastructure", "aws", "azure"),
    "paas": ("platform", "cloud", "multi-tenant"),
}

QUALITY_METADATA_TERMS = [
    "endobj",
    "obj",
    "xref",
    "trailer",
    "startxref",
    "fontname",
    "glyph",
    "cidfont",
    "cmap",
    "xobject",
    "mediabox",
    "stream",
    "endstream",
    "renderer",
    "adobe",
]

COMMON_JOB_WORDS = {
    "and",
    "are",
    "can",
    "for",
    "from",
    "have",
    "including",
    "into",
    "must",
    "our",
    "the",
    "this",
    "that",
    "with",
    "will",
    "work",
    "you",
    "your",
    "years",
    "experience",
    "required",
    "preferred",
    "responsibilities",
    "qualifications",
    "role",
    "team",
}

RESUME_SECTION_HEADINGS = {"education", "skills", "experience", "projects"}

INCOMPATIBLE_TEMPLATE_CLAIMS = {
    "customer service",
    "retail",
    "supermarket",
    "cashier",
    "sales associate",
    "store manager",
    "food service",
    "restaurant",
    "hospitality",
    "merchandising",
    "inventory",
    "stockroom",
}

CONTACT_PATTERNS = [
    re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    re.compile(r"\b(?:https?://)?(?:www\.)?linkedin\.com\b", re.I),
    re.compile(r"\b(?:https?://)?(?:www\.)?github\.com\b", re.I),
    re.compile(r"\b\d{3}[-.)\s]?\d{3}[-.\s]?\d{4}\b"),
]


def build_candidate_evidence(profile: dict[str, Any], extra_sections: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    sections: list[dict[str, str]] = []
    for item in extra_sections or []:
        text_value = normalize_space(str(item.get("text") or item.get("content") or ""))
        if not text_value:
            continue
        sections.append(
            {
                "field": str(item.get("source_field") or item.get("field") or "approved_evidence"),
                "label": str(item.get("source_label") or item.get("label") or "approved evidence"),
                "text": text_value,
                "id": item.get("id"),
                "source_kind": str(item.get("source_kind") or "approved_evidence"),
                "approved": True,
            }
        )
    for field, label in PROFILE_EVIDENCE_FIELDS:
        content = normalize_space(str(profile.get(field) or ""))
        if field == "resume_text" and content and is_corrupted_text(content):
            continue
        if content:
            sections.append({"field": field, "label": label, "text": content})
    full_text = normalize_space(" ".join(section["text"] for section in sections))
    skills = split_profile_skills(str(profile.get("key_skills") or ""))
    return {
        "sections": sections,
        "full_text": full_text,
        "tokens": sorted(useful_tokens(full_text)),
        "skills": skills,
        "preferred_roles": split_profile_skills(str(profile.get("preferred_roles") or "")),
        "work_authorization": normalize_space(str(profile.get("work_authorization") or "")),
        "target_seniority": normalize_space(str(profile.get("target_seniority_levels") or "")),
        "hash": stable_hash(
            json.dumps(
                {
                    "sections": sections,
                    "work_authorization": profile.get("work_authorization", ""),
                    "target_seniority": profile.get("target_seniority_levels", ""),
                    "maximum_required_years": profile.get("maximum_required_years", ""),
                },
                sort_keys=True,
            )
        ),
    }


def evidence_has_generation_source(evidence: dict[str, Any]) -> bool:
    return len(str(evidence.get("full_text") or "")) >= 80


def split_profile_skills(value: str) -> list[str]:
    parts = re.split(r"[,;\n]+", value)
    return list(dict.fromkeys(part.strip(" .:-") for part in parts if len(part.strip(" .:-")) >= 2))


def job_text(job: dict[str, Any]) -> str:
    return normalize_space(
        " ".join(
            str(job.get(field) or "")
            for field in ["title", "required_skills", "preferred_skills", "responsibilities", "job_description"]
        )
    )


def normalize_keyword(value: str) -> str:
    clean = normalize_space(value).lower().strip(" .,:;()[]{}")
    return KEYWORD_ALIASES.get(clean, clean)


def keyword_present(content: str, phrase: str) -> bool:
    """Match a keyword as a phrase, never as an unsafe substring."""
    clean = normalize_space(phrase)
    if not clean:
        return False
    pattern = rf"(?<![A-Za-z0-9]){re.escape(clean)}(?![A-Za-z0-9])"
    return re.search(pattern, content or "", re.IGNORECASE) is not None


def _keyword_requirement_type(job: dict[str, Any], term: str) -> str:
    sources = []
    for field, kind in (("required_skills", "required"), ("responsibilities", "required"), ("preferred_skills", "preferred")):
        value = str(job.get(field) or "")
        if value and keyword_present(value, term):
            sources.append(kind)
    description = str(job.get("job_description") or "")
    for match in re.finditer(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", description, re.IGNORECASE):
        context = description[max(0, match.start() - 180):match.end() + 120].lower()
        if re.search(r"\b(preferred|nice to have|bonus|asset)\b", context):
            sources.append("preferred")
        elif re.search(r"\b(required|must have|minimum|qualifications|requirements)\b", context):
            sources.append("required")
    if "required" in sources:
        return "required"
    if "preferred" in sources:
        return "preferred"
    return "unclassified"


def extract_job_keywords(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a deduplicated, vocabulary-backed job keyword inventory."""
    content = job_text(job)
    found: dict[str, dict[str, Any]] = {}
    for term in sorted(KEYWORD_VOCABULARY, key=len, reverse=True):
        if not keyword_present(content, term):
            continue
        normalized = normalize_keyword(term)
        record = found.setdefault(normalized, {
            "keyword": term,
            "normalized": normalized,
            "category": "technical",
            "requirement_type": "unclassified",
            "source_fields": [],
        })
        requirement_type = _keyword_requirement_type(job, term)
        if requirement_type == "required" or (requirement_type == "preferred" and record["requirement_type"] == "unclassified"):
            record["requirement_type"] = requirement_type
        for field in ("required_skills", "preferred_skills", "responsibilities", "job_description"):
            if keyword_present(str(job.get(field) or ""), term) and field not in record["source_fields"]:
                record["source_fields"].append(field)
    return sorted(found.values(), key=lambda item: (item["requirement_type"] == "unclassified", item["normalized"]))


def match_job_keywords_to_resume(job: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    evidence = build_candidate_evidence(profile)
    full_text = evidence.get("full_text") or ""
    records = {"matched": [], "related": [], "missing": []}
    for keyword in extract_job_keywords(job):
        normalized = keyword["normalized"]
        exact = keyword_present(full_text, keyword["keyword"])
        equivalent = not exact and any(
            keyword_present(full_text, source) and normalize_keyword(source) == normalized
            for source in [keyword["keyword"], normalized, *KEYWORD_ALIASES.keys(), *KEYWORD_ALIASES.values()]
        )
        evidence_text = next((section["text"] for section in evidence.get("sections", []) if keyword_present(section["text"], keyword["keyword"]) or keyword_present(section["text"], normalized)), "")
        record = {**keyword, "match_type": "exact" if exact else "equivalent" if equivalent else "missing", "evidence": evidence_text}
        if exact or equivalent:
            records["matched"].append(record)
            continue
        related_terms = RELATED_KEYWORD_EVIDENCE.get(normalized, ())
        related_evidence = next((section["text"] for section in evidence.get("sections", []) if any(keyword_present(section["text"], term) or term in section["text"].lower() for term in related_terms)), "")
        if related_evidence:
            record["match_type"] = "related_review"
            record["evidence"] = related_evidence
            records["related"].append(record)
        else:
            records["missing"].append(record)
    return records


def build_keywords_score_report(job: dict[str, Any], profile: dict[str, Any], final_resume_text: str | None = None) -> dict[str, Any]:
    """Return an explainable keyword score; related evidence is never counted."""
    if final_resume_text is None:
        result = match_job_keywords_to_resume(job, profile)
    else:
        result = match_job_keywords_to_resume(job, {**profile, "resume_text": final_resume_text})
    inventory = extract_job_keywords(job)
    matched = result["matched"]
    required = [item for item in inventory if item["requirement_type"] == "required"]
    preferred = [item for item in inventory if item["requirement_type"] == "preferred"]

    def subset(items: list[dict[str, Any]]) -> dict[str, Any]:
        keys = {item["normalized"] for item in items}
        hits = [item for item in matched if item["normalized"] in keys]
        return {
            "status": "assessed" if items else "not_assessed",
            "matched": len(hits),
            "total": len(items),
            "score_percent": round(len(hits) / len(items) * 100) if items else None,
        }

    total = len(inventory)
    report = {
        "score_percent": round(len(matched) / total * 100) if total else 0,
        "matched_count": len(matched),
        "total": total,
        "matched": matched,
        "related": result["related"],
        "missing": result["missing"],
        "required": subset(required),
        "preferred": subset(preferred),
        "unclassified": sum(1 for item in inventory if item["requirement_type"] == "unclassified"),
        "review_threshold_percent": 70,
        "review_before_applying": bool(total and len(matched) / total * 100 < 70),
        "heuristic_note": "Keyword coverage is a transparent review heuristic, not an ATS score or a claim that a candidate lacks a skill.",
    }
    return report


def job_keywords(job: dict[str, Any], limit: int = 30) -> list[str]:
    content = job_text(job)
    phrases: list[str] = []
    for field in ["required_skills", "preferred_skills", "responsibilities"]:
        phrases.extend(split_keyword_phrases(str(job.get(field) or "")))
    phrases.extend([term for term in TECHNICAL_TERMS if contains_phrase(content, term)])
    for token in sorted(useful_tokens(content)):
        if len(token) >= 3 and token not in COMMON_JOB_WORDS:
            phrases.append(token)
    clean = []
    for phrase in phrases:
        phrase = phrase.strip(" .:-")
        if phrase and phrase.lower() not in COMMON_JOB_WORDS and phrase.lower() not in {item.lower() for item in clean}:
            clean.append(phrase)
        if len(clean) >= limit:
            break
    return clean


def split_keyword_phrases(value: str) -> list[str]:
    output = []
    for part in re.split(r"[,;\n]+|(?<=[.!?])\s+", value):
        clean = normalize_space(part.strip(" -*:"))
        if 2 <= len(clean) <= 80:
            output.append(clean)
    return output


def classify_supported_skills(job: dict[str, Any], evidence: dict[str, Any]) -> dict[str, list[str]]:
    job_content = job_text(job)
    evidence_text = str(evidence.get("full_text") or "")
    supported_profile_skills = [
        skill for skill in evidence.get("skills", []) if contains_phrase(evidence_text, skill) or contains_token_overlap(skill, evidence_text)
    ]
    supported_relevant = [
        skill for skill in supported_profile_skills if contains_phrase(job_content, skill) or contains_token_overlap(skill, job_content)
    ]
    transferable = [skill for skill in supported_profile_skills if skill not in supported_relevant]
    unsupported = [
        keyword
        for keyword in job_keywords(job)
        if not evidence_supports_phrase(keyword, evidence)
        and not any(contains_phrase(keyword, skill) or contains_phrase(skill, keyword) for skill in supported_profile_skills)
    ]
    return {
        "supported_relevant": list(dict.fromkeys(supported_relevant))[:12],
        "transferable_supported": list(dict.fromkeys(transferable))[:12],
        "unsupported_job_keywords": list(dict.fromkeys(unsupported))[:16],
    }


def evidence_supports_phrase(phrase: str, evidence: dict[str, Any]) -> bool:
    clean = normalize_equivalent_technology_terms(normalize_space(phrase).lower())
    evidence_text = normalize_equivalent_technology_terms(str(evidence.get("full_text") or ""))
    role_text = normalize_equivalent_technology_terms(" ".join(evidence.get("preferred_roles") or []))
    if not clean or len(clean) < 2:
        return False
    if contains_phrase(evidence_text, clean) or contains_phrase(role_text, clean):
        return True
    phrase_tokens = useful_tokens(clean)
    if not phrase_tokens:
        return False
    evidence_tokens = set(evidence.get("tokens") or set()) | useful_tokens(role_text)
    return bool(phrase_tokens) and len(phrase_tokens & evidence_tokens) / len(phrase_tokens) >= 0.7


def normalize_equivalent_technology_terms(value: str) -> str:
    normalized = value.lower()
    for source, target in EQUIVALENT_TECHNOLOGY_TERMS.items():
        normalized = re.sub(rf"\b{re.escape(source)}\b", target, normalized)
    return normalized


def supporting_snippets(terms: list[str], evidence: dict[str, Any], limit: int = 4) -> list[str]:
    sections = evidence.get("sections") or []
    snippets = []
    for section in sections:
        for sentence in split_sentences(section["text"]):
            if any(evidence_supports_term_in_text(term, sentence) for term in terms) or not terms:
                snippets.append(sentence)
                break
        if len(snippets) >= limit:
            break
    return snippets


def evidence_supports_term_in_text(term: str, content: str) -> bool:
    return contains_phrase(content, term) or contains_token_overlap(term, content)


def validate_generated_content(content: str, evidence: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    conflicts = []
    lower = validation_claim_text(content).lower()
    for term in TECHNICAL_TERMS:
        if contains_phrase(lower, term) and not evidence_supports_phrase(term, evidence):
            conflicts.append(term)
    role_words = useful_tokens(str(job.get("title") or ""))
    for role_phrase in ("software developer", "software engineer"):
        if role_phrase in lower and not evidence_supports_phrase(role_phrase, evidence):
            conflicts.append(f"generated {role_phrase} wording is not supported by candidate evidence")
    empty_or_corrupted = not evidence_has_generation_source(evidence) or is_corrupted_text(str(evidence.get("full_text") or ""))
    return {
        "ok": not conflicts and not empty_or_corrupted,
        "conflicting_phrases": list(dict.fromkeys(conflicts)),
        "empty_or_corrupted_evidence": empty_or_corrupted,
        "job_title_tokens": sorted(role_words),
    }


def validate_cover_letter_output(
    content: str,
    evidence: dict[str, Any],
    job: dict[str, Any],
    max_paragraph_chars: int = 400,
) -> dict[str, Any]:
    conflicts: list[str] = []
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", content) if paragraph.strip()]
    body_paragraphs = cover_letter_body_paragraphs(paragraphs)
    body_text = "\n\n".join(body_paragraphs)
    lower = validation_claim_text(body_text).lower()

    for index, paragraph in enumerate(body_paragraphs, start=1):
        if len(paragraph) > max_paragraph_chars:
            conflicts.append(f"Paragraph {index} exceeds the configured length limit")
        issue = classify_cover_letter_paragraph_issue(paragraph, index, evidence, job)
        if issue is not None:
            if issue.startswith("Contact details detected in paragraph "):
                issue = issue.replace("Contact details detected in paragraph ", "Contact details detected in body paragraph ")
            conflicts.append(issue)

    for term in TECHNICAL_TERMS:
        if contains_phrase(lower, term) and not evidence_supports_phrase(term, evidence):
            conflicts.append(term)

    if job_domain_conflict(lower, evidence, job):
        conflicts.append("candidate/job domain conflict")

    empty_or_corrupted = not evidence_has_generation_source(evidence) or is_corrupted_text(str(evidence.get("full_text") or ""))
    return {
        "ok": not conflicts and not empty_or_corrupted,
        "conflicting_phrases": list(dict.fromkeys(conflicts)),
        "empty_or_corrupted_evidence": empty_or_corrupted,
        "paragraph_count": len(body_paragraphs),
    }


def cover_letter_body_paragraphs(paragraphs: list[str]) -> list[str]:
    normalized = [paragraph.strip() for paragraph in paragraphs if paragraph.strip()]
    if not normalized:
        return []
    greeting_index = next((index for index, paragraph in enumerate(normalized) if paragraph.lower().startswith("dear ")), None)
    signoff_index = next(
        (
            index
            for index, paragraph in enumerate(normalized)
            if paragraph.lower().startswith(("sincerely", "best regards", "regards", "kind regards", "thank you", "with appreciation"))
        ),
        None,
    )
    if greeting_index is None:
        return normalized
    body_start = min(len(normalized), greeting_index + 1)
    body_end = signoff_index if signoff_index is not None and signoff_index > body_start else len(normalized)
    return normalized[body_start:body_end]


def validation_claim_text(content: str) -> str:
    kept = []
    skip_next = False
    for line in content.splitlines():
        lowered = line.lower()
        if (
            "unsupported job keywords" in lowered
            or "keywords not supported" in lowered
            or "do not add" in lowered
            or "must not be added" in lowered
        ):
            skip_next = True
            continue
        if skip_next:
            skip_next = False
            continue
        kept.append(line)
    return "\n".join(kept)


def is_corrupted_text(value: str) -> bool:
    sample = value[:20000]
    if not sample.strip():
        return True
    printable = set(string.printable) | {"\n", "\r", "\t", "•", "–", "—", "’", "“", "”"}
    non_printable = sum(1 for char in sample if char not in printable)
    symbol_chars = sum(1 for char in sample if not (char.isalnum() or char.isspace() or char in ".,;:!?'-()/@+&%$#"))
    words = re.findall(r"[A-Za-z][A-Za-z'-]{1,}", sample)
    tokens = re.findall(r"\S+", sample)
    metadata_hits = sum(1 for term in QUALITY_METADATA_TERMS if term in sample.lower())
    long_unreadable = [
        token
        for token in tokens
        if len(token) >= 28 and not re.search(r"[aeiouAEIOU]", token) and re.search(r"[^A-Za-z0-9]", token)
    ]
    repeated_noise = bool(re.search(r"(?:\\[0-9a-fA-F]{2}|[A-Fa-f0-9]{2}){12,}", sample))
    alpha_word_ratio = len(words) / max(1, len(tokens))
    symbol_ratio = symbol_chars / max(1, len(sample))
    non_printable_ratio = non_printable / max(1, len(sample))
    return (
        non_printable_ratio > 0.02
        or symbol_ratio > 0.18
        or metadata_hits >= 3
        or alpha_word_ratio < 0.35
        or len(long_unreadable) >= 3
        or repeated_noise
    )


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def split_sentences(value: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", value)
    return [part.strip(" -*\t") for part in parts if len(part.strip(" -*\t")) >= 8]


def useful_tokens(content: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9+#.-]+", content.lower())
        if token not in COMMON_JOB_WORDS and len(token) > 1
    }


def contains_phrase(content: str, phrase: str) -> bool:
    return phrase.lower() in content.lower()


def contains_token_overlap(left: str, right: str) -> bool:
    left_tokens = useful_tokens(left)
    right_tokens = useful_tokens(right)
    if not left_tokens:
        return False
    return len(left_tokens & right_tokens) / len(left_tokens) >= 0.6


def contains_resume_section_heading(paragraph: str) -> bool:
    for line in paragraph.splitlines():
        lower = normalize_space(line).lower().rstrip(":")
        if lower and lower in RESUME_SECTION_HEADINGS:
            return True
    return False


def contains_contact_details(paragraph: str) -> bool:
    return any(pattern.search(paragraph) for pattern in CONTACT_PATTERNS)


def looks_like_keyword_dump(content: str) -> bool:
    return classify_keyword_dump_reason(content) is not None


def classify_cover_letter_paragraph_issue(paragraph: str, paragraph_index: int, evidence: dict[str, Any], job: dict[str, Any]) -> str | None:
    if contains_resume_section_heading(paragraph):
        return f"Resume section dump detected in paragraph {paragraph_index}"
    if contains_contact_details(paragraph):
        return f"Contact details detected in paragraph {paragraph_index}"
    generic_reason = classify_generic_cover_letter_language(paragraph)
    if generic_reason is not None:
        return f"Generic cover-letter language detected: {generic_reason} in paragraph {paragraph_index}"
    dump_reason = classify_keyword_dump_reason(paragraph)
    if dump_reason is not None:
        return f"{dump_reason} in paragraph {paragraph_index}"
    template_reason = classify_unrelated_template_claim(paragraph, evidence, job)
    if template_reason is not None:
        return f"Unrelated template claim detected: {template_reason} in paragraph {paragraph_index}"
    return None


def classify_generic_cover_letter_language(paragraph: str) -> str | None:
    lowered = paragraph.lower()
    generic_phrases = [
        "practical experience that aligns",
        "my background includes practical experience",
        "together, these examples",
        "my background lines up",
        "careful delivery matters",
        "staying true to my background",
        "reliability, documentation, and collaboration",
        "quality, clear communication, and steady delivery",
    ]
    for phrase in generic_phrases:
        if phrase in lowered:
            return phrase
    return None


def classify_keyword_dump_reason(content: str) -> str | None:
    paragraphs = [part.strip() for part in re.split(r"\n+", content) if part.strip()]
    for paragraph in paragraphs or [content]:
        sentence_like = bool(re.search(r"[.!?]", paragraph))
        chunks = [chunk.strip(" -*\t.,;:") for chunk in re.split(r"[,/|]+", paragraph) if chunk.strip(" -*\t.,;:")]
        short_chunks = [chunk for chunk in chunks if len(chunk.split()) <= 2]
        technical_hits = sum(1 for term in TECHNICAL_TERMS if contains_phrase(paragraph, term))
        if technical_hits >= 6 and len(short_chunks) >= 5 and not sentence_like:
            return "Raw keyword list detected"
        if len(chunks) >= 8 and len(short_chunks) >= 6 and technical_hits >= 4:
            return "Raw keyword list detected"
        if len(chunks) >= 10 and not sentence_like:
            return "Raw keyword list detected"
    return None


def classify_unrelated_template_claim(paragraph: str, evidence: dict[str, Any], job: dict[str, Any]) -> str | None:
    lowered = paragraph.lower()
    job_content = job_text(job)
    for claim in sorted(INCOMPATIBLE_TEMPLATE_CLAIMS, key=len, reverse=True):
        if claim not in lowered:
            continue
        if evidence_supports_phrase(claim, evidence) or contains_phrase(job_content, claim):
            continue
        return claim
    return None


def job_domain_conflict(content: str, evidence: dict[str, Any], job: dict[str, Any]) -> bool:
    job_text_value = job_text(job).lower()
    domain_terms = ["developer", "engineer", "python", "flask", "sql", "database", "cloud", "api", "react"]
    if not any(term in job_text_value for term in domain_terms):
        return False
    evidence_text = str(evidence.get("full_text") or "").lower()
    if not evidence_text:
        return True
    evidence_hits = sum(1 for term in domain_terms if term in evidence_text)
    return evidence_hits == 0


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
