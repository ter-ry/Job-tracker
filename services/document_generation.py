"""Orchestration boundary for document generation.

The existing generation algorithms remain unchanged; this service provides a
stable seam for later replacement and testing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class DocumentGenerationService:
    def generate(self, kind: str, builder: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            result = builder()
        except Exception as exc:  # callers persist the failure against the job
            return {"status": "failed", "error": str(exc), "kind": kind}
        if not isinstance(result, dict):
            return {"status": "failed", "error": "Generator returned an invalid result.", "kind": kind}
        return result
