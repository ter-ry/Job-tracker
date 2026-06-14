from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Protocol

from grounding import build_candidate_evidence, is_corrupted_text

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_DOWNLOAD_SIZE = "about 90 MB"

SOURCE_WEIGHTS = {
    "professional experience": 1.0,
    "internship": 0.9,
    "project": 0.7,
    "education": 0.45,
    "certification": 0.45,
    "skill list": 0.35,
}


class EmbeddingBackend(Protocol):
    model_name: str

    def encode(self, texts: list[str]) -> list[list[float]]:
        ...


class SentenceTransformerBackend:
    model_name = MODEL_NAME

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(self.model_name)

    def encode(self, texts: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(texts, normalize_embeddings=True)
        return [list(map(float, row)) for row in embeddings]


def analyze_resume_match(
    job: dict[str, Any],
    profile: dict[str, Any],
    *,
    cache_dir: Path | None = None,
    embedding_backend: EmbeddingBackend | None = None,
    use_semantic: bool = True,
) -> dict[str, Any]:
    candidate_evidence = build_candidate_evidence(profile)
    evidence = extract_resume_evidence(profile)
    requirements = extract_job_requirements(job)
    resume_hash = candidate_evidence["hash"]
    job_hash = stable_hash(json.dumps(job, sort_keys=True))
    cache_path = (cache_dir / f"{resume_hash}-{job_hash}.json") if cache_dir else None
    if cache_path and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached["cache_hit"] = True
            return cached
        except json.JSONDecodeError:
            pass

    backend_error = ""
    backend = embedding_backend
    if use_semantic and backend is None:
        try:
            backend = SentenceTransformerBackend()
        except Exception as exc:
            backend_error = str(exc)
            backend = None

    matches = compare_requirements(requirements, evidence, backend)
    required = [match for match in matches if match["category"] == "required_skill"]
    preferred = [match for match in matches if match["category"] == "preferred_skill"]
    responsibilities = [match for match in matches if match["category"] == "responsibility"]
    title_matches = [match for match in matches if match["category"] == "role_title"]
    missing = [match["job_requirement"] for match in required if match["confidence"] < 45]
    unsupported = [match["job_requirement"] for match in matches if match["confidence"] < 35]
    direct = [match for match in matches if match["match_type"] == "direct" and match["confidence"] >= 45]
    transferable = [match for match in matches if match["match_type"] == "transferable" and match["confidence"] >= 45]

    result = {
        "model": getattr(backend, "model_name", "keyword-fallback"),
        "model_available": backend is not None,
        "backend_error": backend_error,
        "cache_hit": False,
        "resume_hash": resume_hash,
        "profile_resume_hash": resume_hash,
        "job_hash": job_hash,
        "candidate_evidence": candidate_evidence,
        "evidence": evidence,
        "matches": matches,
        "direct_matches": direct,
        "transferable_matches": transferable,
        "missing_requirements": missing,
        "unsupported_requirements": unsupported,
        "scores": {
            "required_skills": average_confidence(required),
            "preferred_skills": average_confidence(preferred),
            "responsibilities": average_confidence(responsibilities),
            "transferable": average_confidence(transferable),
            "role_title": average_confidence(title_matches),
        },
    }
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def extract_resume_evidence(profile: dict[str, Any]) -> list[dict[str, Any]]:
    sections = [
        ("professional experience", "professional experience", str(profile.get("work_experience") or "")),
        ("skill list", "skill", str(profile.get("key_skills") or "")),
        ("education", "education", str(profile.get("education") or "")),
        ("project", "project", str(profile.get("projects") or "")),
        ("professional experience", "professional experience", str(profile.get("resume_text") or "")),
    ]
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source, evidence_type, content in sections:
        if source == "professional experience" and content == str(profile.get("resume_text") or "") and is_corrupted_text(content):
            continue
        for item in split_evidence_items(content, source):
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            source_section = infer_source_section(item, source)
            evidence.append(
                {
                    "text": item,
                    "source_section": source_section,
                    "evidence_type": evidence_type,
                    "confidence": source_confidence(source_section),
                    "related_skills": detectable_skills(item),
                    "weight": SOURCE_WEIGHTS.get(source_section, SOURCE_WEIGHTS.get(source, 0.5)),
                }
            )
    return evidence


def split_evidence_items(content: str, source: str) -> list[str]:
    if not content.strip():
        return []
    if source == "skill list":
        return [part.strip() for part in re.split(r"[,;\n]+", content) if len(part.strip()) >= 2]
    parts = re.split(r"\n+|(?<=[.!?])\s+|(?:^|\n)\s*[-*]\s+", content)
    return [part.strip(" -*\t") for part in parts if len(part.strip(" -*\t")) >= 8]


def infer_source_section(item: str, fallback: str) -> str:
    lowered = item.lower()
    if "intern" in lowered or "co-op" in lowered or "coop" in lowered:
        return "internship"
    if "certification" in lowered or "certified" in lowered:
        return "certification"
    return fallback


def source_confidence(source: str) -> int:
    return round(SOURCE_WEIGHTS.get(source, 0.5) * 100)


def detectable_skills(content: str) -> list[str]:
    tokens = tokenize(content)
    skills = [
        "python",
        "javascript",
        "typescript",
        "flask",
        "react",
        "sql",
        "sqlite",
        "aws",
        "azure",
        "api",
        "apis",
        "dashboard",
        "dashboards",
        "automation",
        "reporting",
        "cloud",
        "excel",
        "power bi",
    ]
    return [skill for skill in skills if skill in content.lower() or skill in tokens]


def extract_job_requirements(job: dict[str, Any]) -> list[dict[str, str]]:
    requirements: list[dict[str, str]] = []
    add_items(requirements, job.get("required_skills"), "required_skill")
    add_items(requirements, job.get("preferred_skills"), "preferred_skill")
    add_items(requirements, job.get("responsibilities"), "responsibility")
    add_items(requirements, job.get("title"), "role_title")
    if not requirements:
        add_items(requirements, job.get("job_description"), "responsibility", limit=10)
    return requirements


def add_items(output: list[dict[str, str]], value: Any, category: str, limit: int = 20) -> None:
    content = str(value or "")
    parts = re.split(r"[,;\n]+|(?<=[.!?])\s+", content)
    for part in parts:
        clean = part.strip(" -*\t")
        if len(clean) < 3 or len(clean) > 220:
            continue
        output.append({"text": clean, "category": category})
        if len(output) >= limit:
            break


def compare_requirements(
    requirements: list[dict[str, str]],
    evidence: list[dict[str, Any]],
    backend: EmbeddingBackend | None,
) -> list[dict[str, Any]]:
    if not requirements:
        return []
    if not evidence:
        return [
            empty_match(requirement["text"], requirement["category"])
            for requirement in requirements
        ]
    req_texts = [requirement["text"] for requirement in requirements]
    ev_texts = [item["text"] for item in evidence]
    semantic_scores: list[list[float]] | None = None
    if backend is not None:
        vectors = backend.encode([*req_texts, *ev_texts])
        req_vectors = vectors[: len(req_texts)]
        ev_vectors = vectors[len(req_texts) :]
        semantic_scores = [[cosine(req, ev) for ev in ev_vectors] for req in req_vectors]

    matches = []
    for req_index, requirement in enumerate(requirements):
        best: dict[str, Any] | None = None
        for ev_index, item in enumerate(evidence):
            exact = keyword_overlap(requirement["text"], item["text"])
            semantic = semantic_scores[req_index][ev_index] if semantic_scores is not None else lexical_similarity(requirement["text"], item["text"])
            weighted = ((semantic * 72) + (exact * 28)) * float(item.get("weight", 0.5))
            candidate = {
                "job_requirement": requirement["text"],
                "category": requirement["category"],
                "matched_resume_evidence": item["text"],
                "semantic_similarity": round(float(semantic), 3),
                "exact_keyword_overlap": round(float(exact), 3),
                "evidence_source": item["source_section"],
                "confidence": max(0, min(100, round(weighted))),
                "match_type": "direct" if exact >= 0.34 or semantic >= 0.78 else "transferable",
            }
            if best is None or candidate["confidence"] > best["confidence"]:
                best = candidate
        matches.append(best or empty_match(requirement["text"], requirement["category"]))
    return matches


def empty_match(requirement: str, category: str) -> dict[str, Any]:
    return {
        "job_requirement": requirement,
        "category": category,
        "matched_resume_evidence": "",
        "semantic_similarity": 0,
        "exact_keyword_overlap": 0,
        "evidence_source": "",
        "confidence": 0,
        "match_type": "missing",
    }


def keyword_overlap(left: str, right: str) -> float:
    left_tokens = useful_tokens(left)
    right_tokens = useful_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def lexical_similarity(left: str, right: str) -> float:
    left_tokens = useful_tokens(left)
    right_tokens = useful_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / math.sqrt(len(left_tokens) * len(right_tokens))


def useful_tokens(content: str) -> set[str]:
    stop = {"and", "or", "the", "with", "for", "to", "of", "in", "a", "an", "you", "will", "using", "experience"}
    return {token for token in tokenize(content) if token not in stop and len(token) > 1}


def tokenize(content: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.-]+", content.lower()))


def cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def average_confidence(matches: list[dict[str, Any]]) -> int:
    if not matches:
        return 0
    return round(sum(int(match.get("confidence", 0)) for match in matches) / len(matches))


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
