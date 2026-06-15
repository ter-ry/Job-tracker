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
]

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

CONTACT_PATTERNS = [
    re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    re.compile(r"\b(?:https?://)?(?:www\.)?linkedin\.com\b", re.I),
    re.compile(r"\b(?:https?://)?(?:www\.)?github\.com\b", re.I),
    re.compile(r"\b\d{3}[-.)\s]?\d{3}[-.\s]?\d{4}\b"),
]


def build_candidate_evidence(profile: dict[str, Any]) -> dict[str, Any]:
    sections: list[dict[str, str]] = []
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
    clean = normalize_space(phrase).lower()
    evidence_text = str(evidence.get("full_text") or "")
    role_text = " ".join(evidence.get("preferred_roles") or [])
    if not clean or len(clean) < 2:
        return False
    if contains_phrase(evidence_text, clean) or contains_phrase(role_text, clean):
        return True
    phrase_tokens = useful_tokens(clean)
    if not phrase_tokens:
        return False
    evidence_tokens = set(evidence.get("tokens") or set()) | useful_tokens(role_text)
    return bool(phrase_tokens) and len(phrase_tokens & evidence_tokens) / len(phrase_tokens) >= 0.7


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
    candidate_roles = useful_tokens(" ".join(evidence.get("preferred_roles") or []))
    if any(term in lower for term in ["software developer", "software engineer"]) and not ({"software", "developer", "engineer"} & candidate_roles):
        conflicts.append("generated software role wording not supported by preferred roles")
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
    lower = validation_claim_text(content).lower()
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", content) if paragraph.strip()]

    for paragraph in paragraphs:
        if len(paragraph) > max_paragraph_chars:
            conflicts.append("cover letter paragraph exceeds the configured length limit")
        if contains_resume_section_heading(paragraph):
            conflicts.append("cover letter body contains resume section headings")
        if contains_contact_details(paragraph):
            conflicts.append("cover letter body contains contact details")

    for term in TECHNICAL_TERMS:
        if contains_phrase(lower, term) and not evidence_supports_phrase(term, evidence):
            conflicts.append(term)

    if looks_like_keyword_dump(lower):
        conflicts.append("cover letter appears to be keyword dumping")

    if job_domain_conflict(lower, evidence, job):
        conflicts.append("candidate/job domain conflict")

    empty_or_corrupted = not evidence_has_generation_source(evidence) or is_corrupted_text(str(evidence.get("full_text") or ""))
    return {
        "ok": not conflicts and not empty_or_corrupted,
        "conflicting_phrases": list(dict.fromkeys(conflicts)),
        "empty_or_corrupted_evidence": empty_or_corrupted,
        "paragraph_count": len(paragraphs),
    }


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
    if sum(1 for term in TECHNICAL_TERMS if contains_phrase(content, term)) >= 12:
        return True
    return any(chunk.count(",") >= 10 for chunk in re.split(r"\n+", content))


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
