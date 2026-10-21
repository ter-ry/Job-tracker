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
    "java script",
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

# Tailoring Studio uses a broader, transparent requirement inventory than the
# compact Shortlist Keywords Score.  These are generic requirement phrases,
# not job-specific terms; they are extracted only when present in the current
# posting and are never used to add résumé claims.
TAILORING_REQUIREMENT_TERMS = [
    "distributed systems", "microservices", "microservice architecture", "event-driven architecture",
    "production backend experience", "backend development", "software development", "software engineering",
    "object-oriented programming", "design patterns", "data structures", "algorithms", "system design",
    "api design", "restful apis", "rest apis", "graphql", "authentication", "authorization", "permissions",
    "database migrations", "relational databases", "data modeling", "database design", "query optimization",
    "automated testing", "unit testing", "integration testing", "test-driven development", "debugging",
    "code review", "technical documentation", "production support", "incident response", "monitoring",
    "continuous integration", "continuous delivery", "ci/cd", "agile", "scrum", "cross-functional collaboration",
    "stakeholder communication", "cloud infrastructure", "containerization", "kubernetes", "docker",
    "kafka", "rabbitmq", "postgresql", "mysql", "redis", "linux", "python", "java", "javascript",
    "typescript", "c#", "c++", ".net", "flask", "django", "sql", "git", "github", "aws", "azure",
]

TAILORING_REQUIREMENT_ALIASES = {
    "back-end development": "backend development",
    "back-end": "backend",
    "front-end": "frontend",
    "rest api": "rest apis",
    "restful api": "rest apis",
    "restful apis": "rest apis",
    "relational database": "relational databases",
    "unit and integration testing": "automated testing",
    "production backend experience": "production backend experience",
}

TAILORING_COMPETENCIES = [
    ("production backend experience", "experience", ("production-grade backend", "production backend", "backend systems", "backend services", "backend applications")),
    ("backend programming languages", "technical", ("python", "go", "c++", "rust", "java", "kotlin", "scala", "typescript", "c#")),
    ("distributed and event-driven systems", "architecture", ("distributed systems", "distributed applications", "event-driven", "asynchronous architecture", "event streams")),
    ("api and service design", "architecture", ("api design", "rest apis", "restful apis", "apis", "service boundaries", "service interfaces", "domain models")),
    ("database architecture and migrations", "data", ("relational data stores", "non-relational data stores", "data modeling", "database architecture", "schema evolution", "migrations", "data access patterns")),
    ("transactional correctness", "architecture", ("transactional systems", "idempotency", "consistency", "reconciliation", "auditability")),
    ("llm and ai orchestration", "ai", ("llms", "llm", "ai-powered", "ai systems", "retrieval", "tool integrations", "workflow orchestration")),
    ("cloud platforms", "cloud", ("aws", "gcp", "azure", "cloud platforms", "cloud-based")),
    ("infrastructure as code and ci/cd", "operations", ("infrastructure-as-code", "infrastructure as code", "ci/cd", "continuous integration", "continuous delivery", "deployment automation")),
    ("observability and production operations", "operations", ("observability", "logging", "tracing", "metrics", "alerting", "incident response", "production support", "production operations")),
    ("security, identity, and permissions", "security", ("authentication", "authorization", "permissions", "identity", "access control", "audit logging", "data protection")),
    ("testing and code quality", "quality", ("testing", "debugging", "code quality", "code review", "testable", "reliability")),
    ("data structures, algorithms, and system design", "fundamentals", ("data structures", "algorithms", "system design", "software engineering fundamentals")),
    ("messaging and queue platforms", "integration", ("kafka", "rabbitmq", "kinesis", "sqs", "sns", "pub/sub", "message queues", "queues", "streaming")),
    ("regulated domain experience", "domain", ("fintech", "mortgage", "lending", "payments", "insurance", "banking", "regulated domains")),
    ("cross-functional communication", "collaboration", ("cross-functional", "stakeholders", "stakeholder", "communication", "business stakeholders")),
]

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
                "text": preserve_evidence_boundaries(text_value),
                "id": item.get("id"),
                "source_kind": str(item.get("source_kind") or "approved_evidence"),
                "approved": True,
            }
        )
    resume_sections = profile.get("_resume_sections")
    if isinstance(resume_sections, list) and resume_sections:
        for item in resume_sections:
            if not isinstance(item, dict):
                continue
            value = preserve_evidence_boundaries(str(item.get("text") or item.get("content") or ""))
            if value:
                sections.append(
                    {
                        "field": "selected_resume",
                        "label": str(item.get("label") or "Résumé"),
                        "text": value,
                    }
                )
    else:
        for field, label in PROFILE_EVIDENCE_FIELDS:
            content = str(profile.get(field) or "")
            if field == "resume_text" and content and is_corrupted_text(content):
                continue
            if content:
                sections.append({"field": field, "label": label, "text": preserve_evidence_boundaries(content)})
    full_text = normalize_space(" ".join(section["text"] for section in sections))
    skills = split_profile_skills(str(profile.get("key_skills") or ""))
    return {
        "sections": sections,
        "units": evidence_units(sections),
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


def preserve_evidence_boundaries(value: str) -> str:
    """Normalize spacing without erasing résumé paragraph or line boundaries."""
    return "\n".join(normalize_space(line) for line in str(value or "").splitlines() if normalize_space(line))


def evidence_units(sections: list[dict[str, Any]]) -> list[dict[str, str]]:
    units: list[dict[str, str]] = []
    for section in sections:
        for line in str(section.get("text") or "").splitlines():
            clean_line = normalize_space(line)
            if not clean_line:
                continue
            sentences = split_sentences(clean_line)
            for sentence in sentences or [clean_line]:
                units.append({"section": str(section.get("label") or "Résumé"), "text": sentence})
    return units


def evidence_snippet(value: str, phrase: str, minimum: int = 80, maximum: int = 160) -> str:
    clean = normalize_space(value)
    if len(clean) <= maximum:
        return clean
    match = re.search(re.escape(phrase), clean, re.IGNORECASE)
    if not match:
        return clean[: maximum - 1].rstrip() + "…"
    start = max(0, match.start() - maximum // 3)
    end = min(len(clean), start + maximum)
    if end - start < minimum:
        start = max(0, end - minimum)
    snippet = clean[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(clean):
        snippet += "…"
    return snippet if len(snippet) <= maximum else snippet[: maximum - 1].rstrip() + "…"


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
    clean = normalize_space(value).lower().strip(" ,:;()[]{}")
    return KEYWORD_ALIASES.get(clean, clean)


def normalize_tailoring_requirement(value: str) -> str:
    clean = normalize_space(value).lower().strip(" ,:;()[]{}.*")
    clean = re.sub(r"\b(?:required|preferred|qualifications?|responsibilities|nice to have)\b\s*:?", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return TAILORING_REQUIREMENT_ALIASES.get(clean, KEYWORD_ALIASES.get(clean, clean))


def _tailoring_requirement_type(job: dict[str, Any], phrase: str) -> str:
    normalized = normalize_tailoring_requirement(phrase)
    for field, kind in (("required_skills", "required"), ("preferred_skills", "preferred")):
        content = str(job.get(field) or "")
        if keyword_present(content, phrase) or keyword_present(content, normalized):
            return kind
    description = str(job.get("job_description") or "")
    active = "unclassified"
    for line in description.splitlines():
        heading = normalize_space(line).lower().strip(" :")
        if re.match(r"^(required|required qualifications|requirements|minimum qualifications)$", heading):
            active = "required"
            continue
        if re.match(r"^(preferred|preferred qualifications|nice to have|bonus|assets?)$", heading):
            active = "preferred"
            continue
        if (keyword_present(line, phrase) or keyword_present(line, normalized)) and active != "unclassified":
            return active
    return "unclassified"


def extract_tailoring_requirements(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract a broad, deduplicated Studio inventory from the current post.

    The extractor intentionally keeps requirements separate from résumé
    evidence.  It recognizes posted phrases and requirement sections only;
    it does not infer that a candidate has any of them.
    """
    description = str(job.get("job_description") or "")
    content = " ".join(str(job.get(field) or "") for field in ("title", "required_skills", "preferred_skills", "responsibilities", "job_description"))
    lines = [normalize_space(line).strip(" -*•") for line in description.splitlines() if normalize_space(line)]
    section = "unclassified"
    sections: list[tuple[str, str, str]] = []
    for line in lines:
        heading = line.lower().strip(" :")
        if re.match(r"^(responsibilities|responsibility|overview|about the role|the role)$", heading):
            section = "responsibility"
        elif re.match(r"^(qualifications?|required qualifications?|requirements?)$", heading):
            section = "required"
        elif re.match(r"^(preferred experience|preferred qualifications?|nice to have|bonus|assets?)$", heading):
            section = "preferred"
        elif not re.search(r"^(full job description|li-remote)$", heading):
            sections.append((section, line, heading))

    def occurrences(terms: tuple[str, ...]) -> list[tuple[str, str, str]]:
        hits = []
        for kind, line, _ in sections:
            matched_terms = [term for term in terms if keyword_present(line, term)]
            if matched_terms:
                hits.append((kind, line, matched_terms[0]))
        return hits

    records: list[dict[str, Any]] = []
    for canonical, category, terms in TAILORING_COMPETENCIES:
        hits = occurrences(terms)
        field_hits = []
        for field, kind in (("required_skills", "required"), ("preferred_skills", "preferred")):
            value = str(job.get(field) or "")
            if any(keyword_present(value, term) for term in terms):
                field_hits.append(kind)
        if not hits and not field_hits:
            if not any(keyword_present(content, term) for term in terms):
                continue
        kinds = field_hits + [hit[0] for hit in hits]
        requirement_type = "required" if "required" in kinds else "preferred" if "preferred" in kinds else "responsibility" if "responsibility" in kinds else "unclassified"
        source_lines = list(dict.fromkeys(hit[1] for hit in hits))
        matched_terms = list(dict.fromkeys(
            term for term in terms
            if any(keyword_present(line, term) for _, line, _ in hits)
        ))
        records.append({
            "keyword": canonical,
            "normalized": normalize_tailoring_requirement(canonical),
            "category": category,
            "requirement_type": requirement_type,
            "source_fields": ["job_description"] if hits else ["required_skills" if "required" in field_hits else "preferred_skills"],
            "source_evidence": source_lines[:4],
            "alternative_terms": matched_terms,
        })

    years = re.search(r"\b\d+\s*(?:to|-|–)\s*\d+\+?\s+years?\s+of\s+experience\b[^.\n]*", content, re.I)
    if years:
        hits = occurrences((years.group(0),))
        records.append({"keyword": normalize_space(years.group(0)), "normalized": normalize_tailoring_requirement(years.group(0)), "category": "experience", "requirement_type": "required" if any(hit[0] == "required" for hit in hits) else "unclassified", "source_fields": ["job_description"], "source_evidence": [hit[1] for hit in hits][:3], "alternative_terms": []})
    return sorted(records, key=lambda item: (item["requirement_type"] == "unclassified", item["requirement_type"] == "responsibility", item["normalized"]))


def match_tailoring_requirements(job: dict[str, Any], resume_text: str) -> dict[str, list[dict[str, Any]]]:
    """Match Studio requirements with exact, equivalent, partial or missing evidence."""
    evidence = build_candidate_evidence({"resume_text": resume_text})
    full_text = evidence["full_text"]
    units = evidence["units"]
    result = {"matched": [], "related": [], "missing": []}
    alias_pairs = [(source, target) for source, target in {**KEYWORD_ALIASES, **TAILORING_REQUIREMENT_ALIASES}.items()]
    for requirement in extract_tailoring_requirements(job):
        normalized = requirement["normalized"]
        alternatives = tuple(requirement.get("alternative_terms") or ())
        exact_source = next((term for term in alternatives if keyword_present(full_text, term)), None)
        exact = bool(exact_source)
        equivalent_source = next((source for source, target in alias_pairs if target == normalized and keyword_present(full_text, source)), None)
        if not equivalent_source and not exact and normalized != requirement["keyword"] and keyword_present(full_text, normalized):
            equivalent_source = normalized
        source_phrase = equivalent_source or requirement["keyword"]
        if exact_source:
            source_phrase = exact_source
        unit = next((item for item in units if keyword_present(item["text"], source_phrase) or keyword_present(item["text"], normalized)), None)
        if normalized == "api and service design" and exact and keyword_present(full_text, "rest apis"):
            exact = False
            equivalent_source = "REST APIs"
            source_phrase = "REST APIs"
        record = {**requirement, "match_type": "exact" if exact else "equivalent" if equivalent_source else "missing", "found_as": source_phrase if exact or equivalent_source else "", "source_section": unit.get("section", "Résumé") if unit else "Résumé", "evidence": evidence_snippet(unit["text"], source_phrase) if unit and (exact or equivalent_source) else ""}
        if exact or equivalent_source:
            result["matched"].append(record)
            continue
        words = [word for word in re.findall(r"[a-z0-9+#.]+", " ".join(alternatives or (normalized,))) if len(word) > 2 and word not in COMMON_JOB_WORDS]
        partial_unit = next((item for item in units if sum(keyword_present(item["text"], word) for word in words) >= max(1, len(words) // 2)), None)
        if partial_unit:
            record["match_type"] = "partial"
            record["source_section"] = partial_unit.get("section", "Résumé")
            record["evidence"] = evidence_snippet(partial_unit["text"], words[0] if words else normalized)
            result["related"].append(record)
        else:
            result["missing"].append(record)
    return result


def build_tailoring_coverage_report(job: dict[str, Any], resume_text: str) -> dict[str, Any]:
    source_text = " ".join(str(job.get(field) or "").strip() for field in ("job_description", "required_skills", "preferred_skills", "responsibilities"))
    if not normalize_space(source_text):
        return {
            "available": False,
            "unavailable_reason": "The complete job description is not stored for this posting. Edit or refresh the job with the original description before reviewing tailoring requirements.",
            "score_percent": None,
            "matched_count": 0,
            "total": 0,
            "matched": [],
            "related": [],
            "missing": [],
            "required": {"status": "not_assessed", "matched": 0, "total": 0, "score_percent": None},
            "preferred": {"status": "not_assessed", "matched": 0, "total": 0, "score_percent": None},
            "unclassified": 0,
            "unclassified_keywords": [],
            "review_before_applying": False,
            "heuristic_note": "Coverage is unavailable until the complete job description is stored. This is not a zero-percent qualification result.",
        }
    result = match_tailoring_requirements(job, resume_text)
    inventory = extract_tailoring_requirements(job)
    matched = result["matched"]
    required = [item for item in inventory if item["requirement_type"] == "required"]
    preferred = [item for item in inventory if item["requirement_type"] == "preferred"]
    def subset(items: list[dict[str, Any]]) -> dict[str, Any]:
        keys = {item["normalized"] for item in items}
        hits = [item for item in matched if item["normalized"] in keys]
        return {"status": "assessed" if items else "not_assessed", "matched": len(hits), "total": len(items), "score_percent": round(len(hits) / len(items) * 100) if items else None}
    total = len(inventory)
    return {"available": True, "score_percent": round(len(matched) / total * 100) if total else 0, "matched_count": len(matched), "total": total, "matched": matched, "related": result["related"], "missing": result["missing"], "required": subset(required), "preferred": subset(preferred), "unclassified": sum(1 for item in inventory if item["requirement_type"] == "unclassified"), "unclassified_keywords": [item for item in inventory if item["requirement_type"] == "unclassified"], "review_threshold_percent": 70, "review_before_applying": bool(total and len(matched) / total * 100 < 70), "heuristic_note": "Tailoring coverage is a transparent keyword and requirement review heuristic, not a qualification score. Partial evidence is shown separately and is not counted as matched."}


def apply_tailoring_requirement_overrides(report: dict[str, Any], overrides: dict[str, str]) -> dict[str, Any]:
    """Exclude only job-scoped user-marked non-requirements from adjusted coverage."""
    if not report.get("available"):
        return report
    excluded = {normalize_tailoring_requirement(key) for key, value in overrides.items() if value == "not_a_requirement"}
    all_items = report.get("matched", []) + report.get("related", []) + report.get("missing", [])
    for item in all_items:
        item["user_override"] = overrides.get(item.get("normalized"), "")
        item["excluded_from_adjusted_coverage"] = item.get("normalized") in excluded
    eligible = [item for item in all_items if item.get("normalized") not in excluded]
    matched = [item for item in report.get("matched", []) if item.get("normalized") not in excluded]
    report["excluded_count"] = len(excluded)
    report["adjusted_total"] = len(eligible)
    report["adjusted_matched_count"] = len(matched)
    report["adjusted_score_percent"] = round(len(matched) / len(eligible) * 100) if eligible else None
    report["score_percent"] = report["adjusted_score_percent"]
    report["matched_count"] = len(matched)
    report["original_total"] = len(all_items)
    report["original_matched_count"] = len(report.get("matched", []))
    return report


def keyword_present(content: str, phrase: str) -> bool:
    """Match a keyword as a phrase, never as an unsafe substring."""
    clean = normalize_space(phrase)
    if not clean:
        return False
    pattern = rf"(?<![A-Za-z0-9]){re.escape(clean)}(?![A-Za-z0-9])"
    return re.search(pattern, content or "", re.IGNORECASE) is not None


def _keyword_requirement_type(job: dict[str, Any], term: str) -> str:
    sources = []
    for field, kind in (("required_skills", "required"), ("preferred_skills", "preferred")):
        value = str(job.get(field) or "")
        if value and keyword_present(value, term):
            sources.append(kind)
    description = str(job.get("job_description") or "")
    section = "unclassified"
    for line in description.splitlines():
        clean = normalize_space(line).lower()
        if re.search(r"\b(preferred|nice to have|bonus|assets?)\b\s*:?$", clean):
            section = "preferred"
        elif re.search(r"\b(required|requirements|minimum qualifications|qualifications)\b\s*:?$", clean):
            section = "required"
        if not keyword_present(line, term):
            continue
        if re.search(r"\b(preferred|nice to have|bonus|asset)\b\s*:", clean):
            sources.append("preferred")
        elif re.search(r"\b(required|requirements|must have|minimum qualifications|qualifications)\b\s*:", clean):
            sources.append("required")
        elif section in {"required", "preferred"}:
            sources.append(section)
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
    records = list(found.values())
    redundant = set()
    for shorter in records:
        for longer in records:
            if shorter is longer or shorter["normalized"] == longer["normalized"]:
                continue
            if len(longer["keyword"]) > len(shorter["keyword"]) and keyword_present(longer["keyword"], shorter["keyword"]):
                redundant.add(shorter["normalized"])
                break
    records = [item for item in records if item["normalized"] not in redundant]
    return sorted(records, key=lambda item: (item["requirement_type"] == "unclassified", item["normalized"]))


def match_job_keywords_to_resume(job: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    evidence = build_candidate_evidence(profile)
    full_text = evidence.get("full_text") or ""
    units = evidence.get("units") or []
    records = {"matched": [], "related": [], "missing": []}
    for keyword in extract_job_keywords(job):
        normalized = keyword["normalized"]
        exact = keyword_present(full_text, keyword["keyword"])
        equivalent = not exact and any(
            keyword_present(full_text, source) and normalize_keyword(source) == normalized
            for source in [keyword["keyword"], normalized, *KEYWORD_ALIASES.keys(), *KEYWORD_ALIASES.values()]
        )
        source_phrase = keyword["keyword"]
        if equivalent and not exact:
            source_phrase = next(
                (candidate for candidate in [keyword["keyword"], normalized, *KEYWORD_ALIASES.keys(), *KEYWORD_ALIASES.values()] if keyword_present(full_text, candidate) and normalize_keyword(candidate) == normalized),
                keyword["keyword"],
            )
        evidence_unit = next((unit for unit in units if keyword_present(unit["text"], source_phrase) or keyword_present(unit["text"], normalized)), None)
        record = {
            **keyword,
            "match_type": "exact" if exact else "equivalent" if equivalent else "missing",
            "found_as": source_phrase if exact or equivalent else "",
            "source_section": evidence_unit.get("section", "Résumé") if evidence_unit else "Résumé",
            "evidence": evidence_snippet(evidence_unit["text"], source_phrase) if evidence_unit and (exact or equivalent) else "",
        }
        if exact or equivalent:
            records["matched"].append(record)
            continue
        related_terms = RELATED_KEYWORD_EVIDENCE.get(normalized, ())
        related_unit = next((unit for unit in units if any(keyword_present(unit["text"], term) or term in unit["text"].lower() for term in related_terms)), None)
        if related_unit:
            record["match_type"] = "related_review"
            record["source_section"] = related_unit.get("section", "Résumé")
            record["evidence"] = evidence_snippet(related_unit["text"], next((term for term in related_terms if keyword_present(related_unit["text"], term)), related_terms[0] if related_terms else ""))
            records["related"].append(record)
        else:
            records["missing"].append(record)
    return records


def build_keywords_score_report(job: dict[str, Any], profile: dict[str, Any], final_resume_text: str | None = None) -> dict[str, Any]:
    """Return an explainable keyword score; related evidence is never counted."""
    selected_resume = final_resume_text if final_resume_text is not None else str(profile.get("resume_text") or "")
    selected_profile = {"resume_text": selected_resume} if selected_resume else profile
    if profile.get("_resume_sections") and final_resume_text is None:
        selected_profile["_resume_sections"] = profile["_resume_sections"]
    result = match_job_keywords_to_resume(job, selected_profile)
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
        "unclassified_keywords": [item for item in inventory if item["requirement_type"] == "unclassified"],
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
