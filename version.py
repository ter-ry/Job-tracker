"""Application version metadata shared by the UI, launcher, and release build."""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys


def _bundled_version() -> str:
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(getattr(sys, "_MEIPASS", "")) / "VERSION.txt")
    candidates.append(Path(__file__).resolve().parent / "release_packaging" / "windows" / "VERSION.txt")
    for candidate in candidates:
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            continue
        if value:
            return value
    return "0.0.0-dev"


APP_VERSION = os.environ.get("JOB_TRACKER_VERSION") or _bundled_version()
APP_NAME = "Job Tracker"
GITHUB_REPOSITORY = "ter-ry/Job-tracker"


_SEMVER_RE = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)(?:-([0-9A-Za-z.-]+))?$")


def normalize_semver(value: str) -> str:
    """Return a comparable release version without a leading tag prefix."""
    candidate = str(value or "").strip()
    if candidate.lower().startswith("v"):
        candidate = candidate[1:]
    match = _SEMVER_RE.fullmatch(candidate)
    if not match:
        return ""
    major, minor, patch, prerelease = match.groups()
    return f"{int(major)}.{int(minor)}.{int(patch)}" + (f"-{prerelease}" if prerelease else "")


def semver_key(value: str) -> tuple[int, int, int, int, tuple[tuple[int, object], ...]] | None:
    normalized = normalize_semver(value)
    match = _SEMVER_RE.fullmatch(normalized)
    if not match:
        return None
    major, minor, patch, prerelease = match.groups()
    identifiers: list[tuple[int, object]] = []
    if prerelease:
        for identifier in prerelease.split("."):
            identifiers.append((0, int(identifier)) if identifier.isdigit() else (1, identifier))
    return int(major), int(minor), int(patch), 0 if prerelease else 1, tuple(identifiers)
