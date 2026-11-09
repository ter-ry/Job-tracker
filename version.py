"""Application version metadata shared by the UI, launcher, and release build."""

from __future__ import annotations

import os
from pathlib import Path
import sys


def _bundled_version() -> str:
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(getattr(sys, "_MEIPASS", "")) / "VERSION.txt")
    candidates.append(Path(__file__).resolve().parent / "packaging" / "windows" / "VERSION.txt")
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
