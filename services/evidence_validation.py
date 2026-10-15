"""Evidence validation boundary; generation algorithms are intentionally out of scope."""

from __future__ import annotations

from typing import Any

from grounding import validate_cover_letter_output, validate_generated_content


def validate_resume(content: str, evidence: dict[str, Any], job: dict[str, Any] | None = None) -> dict[str, Any]:
    return validate_generated_content(content, evidence, job or {})


def validate_cover_letter(content: str, evidence: dict[str, Any], job: dict[str, Any] | None = None) -> dict[str, Any]:
    return validate_cover_letter_output(content, evidence, job or {})
