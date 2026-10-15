"""Persistence boundary for reusable candidate profiles and documents."""

from __future__ import annotations

import sqlite3
from typing import Any


class CandidateProfileStore:
    """Store multiple resumes and cover-letter templates per candidate profile."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def list_profiles(self) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM candidate_profiles ORDER BY is_active DESC, name").fetchall()
        return [dict(row) for row in rows]

    def create_profile(self, name: str, description: str = "") -> int:
        cursor = self.db.execute(
            "INSERT INTO candidate_profiles(name, description, is_active) VALUES (?, ?, ?)",
            (name.strip(), description.strip(), 1 if not self.list_profiles() else 0),
        )
        self.db.commit()
        return int(cursor.lastrowid)

    def add_resume(self, profile_id: int, name: str, content: str = "", docx_path: str = "", is_default: bool = False) -> int:
        cursor = self.db.execute(
            "INSERT INTO base_resumes(profile_id, name, content, docx_path, is_default) VALUES (?, ?, ?, ?, ?)",
            (profile_id, name.strip(), content, docx_path, int(is_default)),
        )
        self.db.commit()
        return int(cursor.lastrowid)

    def add_cover_letter_template(self, profile_id: int, name: str, content: str = "", docx_path: str = "", is_default: bool = False) -> int:
        cursor = self.db.execute(
            "INSERT INTO cover_letter_templates(profile_id, name, content, docx_path, is_default) VALUES (?, ?, ?, ?, ?)",
            (profile_id, name.strip(), content, docx_path, int(is_default)),
        )
        self.db.commit()
        return int(cursor.lastrowid)

    def documents_for(self, profile_id: int) -> dict[str, list[dict[str, Any]]]:
        resumes = self.db.execute("SELECT * FROM base_resumes WHERE profile_id = ? ORDER BY is_default DESC, name", (profile_id,)).fetchall()
        templates = self.db.execute("SELECT * FROM cover_letter_templates WHERE profile_id = ? ORDER BY is_default DESC, name", (profile_id,)).fetchall()
        return {"resumes": [dict(row) for row in resumes], "cover_letter_templates": [dict(row) for row in templates]}
