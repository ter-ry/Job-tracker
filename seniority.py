from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


SENIORITY_LEVELS = [
    "internship",
    "entry_level",
    "junior",
    "intermediate",
    "senior",
    "lead",
    "manager",
    "director",
]

DETECTED_LEVELS = [*SENIORITY_LEVELS, "unknown"]
LEVEL_RANK = {level: index for index, level in enumerate(SENIORITY_LEVELS)}

MANAGEMENT_TERMS = [
    "manage a team",
    "manage staff",
    "people management",
    "direct reports",
    "performance reviews",
    "hiring",
    "headcount",
    "budget responsibility",
    "own the budget",
]

LEADERSHIP_TERMS = [
    "lead technical direction",
    "technical lead",
    "mentor",
    "architecture",
    "architectural",
    "own roadmap",
    "ownership",
    "cross-functional leadership",
]


@dataclass(frozen=True)
class ExperienceRange:
    minimum: float | None
    maximum: float | None
    requirement_type: str
    text: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "minimum": self.minimum,
            "maximum": self.maximum,
            "requirement_type": self.requirement_type,
            "text": self.text,
        }


def parse_target_levels(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[,;\n]+", str(value or ""))
    levels = []
    aliases = {
        "intern": "internship",
        "new grad": "entry_level",
        "new_grad": "entry_level",
        "entry": "entry_level",
        "entry level": "entry_level",
        "mid": "intermediate",
        "mid level": "intermediate",
        "managerial": "manager",
    }
    for item in raw:
        clean = re.sub(r"[\s-]+", "_", str(item).strip().lower())
        clean = aliases.get(clean.replace("_", " "), aliases.get(clean, clean))
        if clean in SENIORITY_LEVELS and clean not in levels:
            levels.append(clean)
    return levels


def analyze_job_seniority(job: dict[str, Any]) -> dict[str, Any]:
    title = str(job.get("title") or "")
    description = " ".join(
        str(job.get(field) or "")
        for field in ["required_skills", "preferred_skills", "responsibilities", "job_description", "notes"]
    )
    title_level, title_hits = detect_level(title)
    description_level, description_hits = detect_level(description)
    required_ranges, preferred_ranges, ambiguous_ranges = extract_experience_ranges(description)
    required_field = str(job.get("required_skills") or "").lower()
    preferred_field = str(job.get("preferred_skills") or "").lower()
    if ambiguous_ranges:
        still_ambiguous: list[ExperienceRange] = []
        for item in ambiguous_ranges:
            phrase = item.text.lower().replace(" ", "")
            if phrase and phrase in required_field.replace(" ", ""):
                required_ranges.append(ExperienceRange(item.minimum, item.maximum, "required", item.text))
            elif phrase and phrase in preferred_field.replace(" ", ""):
                preferred_ranges.append(ExperienceRange(item.minimum, item.maximum, "preferred", item.text))
            else:
                still_ambiguous.append(item)
        ambiguous_ranges = still_ambiguous
    required_range = strongest_range(required_ranges)
    preferred_range = strongest_range(preferred_ranges)
    management_flag = contains_any(description, MANAGEMENT_TERMS) or contains_any(title, ["manager", "director"])
    leadership_flag = contains_any(description, LEADERSHIP_TERMS)
    budget_or_hiring = contains_any(description, ["budget", "hiring", "hire engineers", "recruit", "headcount"])

    evidence_levels = [level for level in [title_level, description_level] if level != "unknown"]
    if required_range and (required_range.minimum or 0) >= 10:
        evidence_levels.append("director" if management_flag or budget_or_hiring else "lead")
    elif required_range and (required_range.minimum or 0) >= 7:
        evidence_levels.append("lead" if leadership_flag else "senior")
    elif required_range and (required_range.minimum or 0) >= 5:
        evidence_levels.append("senior")
    elif required_range and (required_range.minimum or 0) >= 3:
        evidence_levels.append("intermediate")
    elif required_range and (required_range.maximum or required_range.minimum or 0) <= 2:
        evidence_levels.append("junior")
    if management_flag:
        evidence_levels.append("manager" if "director" not in title.lower() else "director")

    detected = combine_levels(evidence_levels)
    disagreement = (
        title_level != "unknown"
        and description_level != "unknown"
        and abs(LEVEL_RANK.get(title_level, 0) - LEVEL_RANK.get(description_level, 0)) >= 2
    )
    confidence = 35
    if detected != "unknown":
        confidence += 25
    if required_range or preferred_range:
        confidence += 20
    if title_level != "unknown":
        confidence += 10
    if description_level != "unknown":
        confidence += 10
    if disagreement:
        confidence -= 20

    return {
        "detected_level": detected,
        "title_level": title_level,
        "description_level": description_level,
        "title_evidence": title_hits,
        "description_evidence": description_hits,
        "required_experience": required_range.as_dict() if required_range else None,
        "preferred_experience": preferred_range.as_dict() if preferred_range else None,
        "ambiguous_experience": [item.as_dict() for item in ambiguous_ranges],
        "management_role": management_flag,
        "leadership_expectations": leadership_flag,
        "budget_or_hiring_responsibility": budget_or_hiring,
        "confidence": max(0, min(100, confidence)),
        "title_description_disagreement": disagreement,
        "warning": "Title and description seniority signals disagree." if disagreement else "",
    }


def detect_level(content: str) -> tuple[str, list[str]]:
    lowered = content.lower()
    checks = [
        ("director", ["director", "head of engineering", "vp engineering"]),
        ("manager", ["engineering manager", "development manager", "manager, software", "people manager"]),
        ("lead", ["lead ", "tech lead", "technical lead", "principal", "staff engineer"]),
        ("senior", ["senior", "sr.", "sr "]),
        ("intermediate", ["intermediate", "mid-level", "mid level", "level 2"]),
        ("junior", ["junior", "jr.", "jr ", "early career"]),
        ("entry_level", ["entry level", "entry-level", "new grad", "graduate developer", "no experience required"]),
        ("internship", ["intern", "internship", "co-op", "coop"]),
    ]
    hits: list[str] = []
    for level, terms in checks:
        found = [term.strip() for term in terms if term in lowered]
        if found:
            hits.extend(found)
            return level, list(dict.fromkeys(hits))
    return "unknown", []


def extract_experience_ranges(content: str) -> tuple[list[ExperienceRange], list[ExperienceRange], list[ExperienceRange]]:
    lowered = content.lower()
    required: list[ExperienceRange] = []
    preferred: list[ExperienceRange] = []
    ambiguous: list[ExperienceRange] = []
    if re.search(r"\b(no|zero)\s+(?:professional\s+)?experience\s+required\b", lowered):
        required.append(ExperienceRange(0, 0, "required", "no experience required"))

    range_pattern = re.compile(
        r"(?P<a>\d{1,2})(?:\s*(?:\+|plus)|\s*(?:-|to|–)\s*(?P<b>\d{1,2})(?:\s*(?:\+|plus))?)?\s*(?:years?|yrs?)"
        r"(?:\s+of)?\s+(?:professional\s+)?(?:work\s+)?(?:experience|development|engineering|programming)?",
        re.I,
    )
    for match in range_pattern.finditer(content):
        if is_false_experience_match(content, match.start(), match.end()):
            continue
        snippet = content[max(0, match.start() - 80) : min(len(content), match.end() + 80)]
        kind = classify_experience_context(snippet)
        a = float(match.group("a"))
        b = float(match.group("b")) if match.group("b") else (None if "+" in match.group(0) or "plus" in match.group(0).lower() else a)
        item = ExperienceRange(a, b, kind, match.group(0).strip())
        if kind == "required":
            required.append(item)
        elif kind == "preferred":
            preferred.append(item)
        else:
            ambiguous.append(item)
    return required, preferred, ambiguous


def is_false_experience_match(content: str, start: int, end: int) -> bool:
    snippet = content[max(0, start - 30) : min(len(content), end + 30)].lower()
    if re.search(r"\$\s*\d", snippet) or any(term in snippet for term in ["salary", "per year", "annually", "version", "python 3", "team of", "people on"]):
        return True
    number = int(re.search(r"\d{1,4}", content[start:end]).group(0))
    if 1900 <= number <= 2100:
        return True
    return False


def classify_experience_context(snippet: str) -> str:
    lowered = snippet.lower()
    if any(term in lowered for term in ["required", "must have", "minimum", "at least", "need", "requires"]):
        return "required"
    if any(term in lowered for term in ["preferred", "nice to have", "bonus", "asset", "ideally"]):
        return "preferred"
    return "ambiguous"


def strongest_range(ranges: list[ExperienceRange]) -> ExperienceRange | None:
    if not ranges:
        return None
    return max(ranges, key=lambda item: (item.minimum or 0, item.maximum or item.minimum or 0))


def combine_levels(levels: list[str]) -> str:
    clean = [level for level in levels if level in LEVEL_RANK]
    if not clean:
        return "unknown"
    return max(clean, key=lambda level: LEVEL_RANK[level])


def contains_any(content: str, terms: list[str]) -> bool:
    lowered = content.lower()
    return any(term in lowered for term in terms)


def score_seniority_fit(profile: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    targets = parse_target_levels(profile.get("target_seniority_levels")) or ["entry_level", "junior", "intermediate"]
    max_required = parse_optional_float(profile.get("maximum_required_years"))
    stretch_allowed = parse_bool(profile.get("willing_to_apply_to_stretch_roles"))
    management_allowed = parse_bool(profile.get("management_roles_allowed"))
    detected = analysis.get("detected_level") or "unknown"
    required = analysis.get("required_experience") or {}
    required_min = required.get("minimum")
    required_max = required.get("maximum")
    demonstrated_years = explicit_professional_years(profile)
    management = bool(analysis.get("management_role"))
    explanation: list[str] = []
    stretch = False

    if detected == "unknown":
        score = 72
        explanation.append("Seniority is uncertain, so this uses a neutral score.")
    else:
        target_ranks = [LEVEL_RANK[level] for level in targets if level in LEVEL_RANK]
        detected_rank = LEVEL_RANK.get(detected, min(target_ranks or [2]))
        nearest_gap = min(abs(detected_rank - rank) for rank in target_ranks) if target_ranks else 0
        if detected in targets:
            score = 94
            explanation.append(f"Detected level {detected} matches selected target seniority.")
        elif detected_rank > max(target_ranks or [detected_rank]):
            stretch = nearest_gap <= 1
            score = 76 if stretch and stretch_allowed else 42
            explanation.append(f"Detected level {detected} is above selected targets: {', '.join(targets)}.")
        else:
            score = 82
            explanation.append(f"Detected level {detected} is below or adjacent to selected targets.")

    if required_min is not None:
        if max_required is not None and required_min > max_required:
            over_by = required_min - max_required
            stretch = over_by <= 1.5
            score -= 18 if stretch and stretch_allowed else 38
            explanation.append(f"Required experience starts at {required_min:g} years, above the saved maximum of {max_required:g}.")
        elif demonstrated_years is not None and demonstrated_years < required_min:
            gap = required_min - demonstrated_years
            stretch = True
            score -= 30 if gap >= 2 else 20
            explanation.append(f"The résumé explicitly demonstrates {demonstrated_years:g} years of professional experience, below the required {required_min:g} years.")
        elif demonstrated_years is None and max_required is None and required_min > 0:
            stretch = True
            score -= 30 if required_min >= 5 else 24
            explanation.append(f"The résumé does not explicitly demonstrate the required {required_min:g} years of professional experience.")
        elif required_max is not None and required_max <= 2:
            score += 6
            explanation.append("Required experience is in the 0-2 year range.")
    if required_min is not None and required_min >= 10:
        score -= 28
        explanation.append("10+ years of experience is a strong mismatch for early-career targets.")
    if management and not management_allowed:
        score -= 35
        explanation.append("People-management duties are present but management roles are disabled.")
    elif management:
        explanation.append("People-management duties are present.")
    if analysis.get("title_description_disagreement"):
        score -= 5
        explanation.append("Title and description seniority signals disagree; using combined evidence.")

    return {
        "score": max(0, min(100, round(score))),
        "explanation": " ".join(explanation),
        "stretch_role": bool(stretch),
        "management_role": management,
        "confidence": analysis.get("confidence", 0),
    }


def parse_optional_float(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def explicit_professional_years(profile: dict[str, Any]) -> float | None:
    """Read only explicit professional-experience claims, never project durations."""
    source = " ".join(str(profile.get(field) or "") for field in ("work_experience", "resume_text"))
    number_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    pattern = re.compile(r"\b(?P<number>\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)(?:\s*\+)?\s+years?\s+(?:of\s+)?(?:professional|production|software|engineering|programming|application)\s+experience\b", re.I)
    matches: list[float] = []
    for match in pattern.finditer(source):
        raw = match.group("number").lower()
        matches.append(float(number_words.get(raw, raw)))
    return max(matches) if matches else None


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "allowed"}
