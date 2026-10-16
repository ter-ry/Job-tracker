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

    def create_profile(
        self,
        name: str,
        description: str = "",
        identity_mode: str = "shared",
        applicant_name: str = "",
        applicant_email: str = "",
        applicant_phone: str = "",
        applicant_location: str = "",
    ) -> int:
        cursor = self.db.execute(
            """INSERT INTO candidate_profiles(
                name, description, is_active, identity_mode, applicant_name,
                applicant_email, applicant_phone, applicant_location
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name.strip(), description.strip(), 1 if not self.list_profiles() else 0,
                identity_mode if identity_mode in {"shared", "distinct"} else "shared",
                applicant_name.strip(), applicant_email.strip(), applicant_phone.strip(), applicant_location.strip(),
            ),
        )
        self.db.commit()
        return int(cursor.lastrowid)

    def update_profile(self, profile_id: int, **fields: str | None) -> dict[str, Any]:
        existing = self.db.execute("SELECT * FROM candidate_profiles WHERE id = ?", (profile_id,)).fetchone()
        if existing is None:
            raise ValueError("Candidate profile was not found")
        allowed = {"identity_mode", "applicant_name", "applicant_email", "applicant_phone", "applicant_location"}
        updates = {key: value for key, value in fields.items() if key in allowed and value is not None}
        if "identity_mode" in updates and updates["identity_mode"] not in {"shared", "distinct"}:
            raise ValueError("identity_mode must be shared or distinct")
        if updates.get("identity_mode") == "distinct" and not updates.get("applicant_name", existing["applicant_name"]):
            raise ValueError("Distinct identity requires applicant_name")
        if updates:
            assignments = ", ".join(f"{key} = ?" for key in updates)
            self.db.execute(
                f"UPDATE candidate_profiles SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (*updates.values(), profile_id),
            )
            self.db.commit()
        row = self.db.execute("SELECT * FROM candidate_profiles WHERE id = ?", (profile_id,)).fetchone()
        return dict(row)

    def add_resume(self, profile_id: int, name: str, content: str = "", docx_path: str = "", is_default: bool = False) -> int:
        if is_default:
            self.db.execute("UPDATE base_resumes SET is_default = 0, updated_at = CURRENT_TIMESTAMP WHERE profile_id = ?", (profile_id,))
        cursor = self.db.execute(
            "INSERT INTO base_resumes(profile_id, name, content, docx_path, is_default) VALUES (?, ?, ?, ?, ?)",
            (profile_id, name.strip(), content, docx_path, int(is_default)),
        )
        self.db.commit()
        return int(cursor.lastrowid)

    def add_cover_letter_template(self, profile_id: int, name: str, content: str = "", docx_path: str = "", is_default: bool = False) -> int:
        if is_default:
            self.db.execute("UPDATE cover_letter_templates SET is_default = 0, updated_at = CURRENT_TIMESTAMP WHERE profile_id = ?", (profile_id,))
        cursor = self.db.execute(
            "INSERT INTO cover_letter_templates(profile_id, name, content, docx_path, is_default) VALUES (?, ?, ?, ?, ?)",
            (profile_id, name.strip(), content, docx_path, int(is_default)),
        )
        self.db.commit()
        return int(cursor.lastrowid)

    def set_default(self, profile_id: int, kind: str, document_id: int) -> dict[str, Any]:
        table = {"resume": "base_resumes", "cover_letter_template": "cover_letter_templates"}.get(kind)
        if not table:
            raise ValueError("Unsupported document type")
        row = self.db.execute(f"SELECT * FROM {table} WHERE id = ? AND profile_id = ?", (document_id, profile_id)).fetchone()
        if row is None:
            raise ValueError("Document was not found for this candidate profile")
        self.db.execute(f"UPDATE {table} SET is_default = 0, updated_at = CURRENT_TIMESTAMP WHERE profile_id = ?", (profile_id,))
        self.db.execute(f"UPDATE {table} SET is_default = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (document_id,))
        self.db.commit()
        return dict(self.db.execute(f"SELECT * FROM {table} WHERE id = ?", (document_id,)).fetchone())

    def documents_for(self, profile_id: int) -> dict[str, list[dict[str, Any]]]:
        resumes = self.db.execute("SELECT * FROM base_resumes WHERE profile_id = ? ORDER BY is_default DESC, name", (profile_id,)).fetchall()
        templates = self.db.execute("SELECT * FROM cover_letter_templates WHERE profile_id = ? ORDER BY is_default DESC, name", (profile_id,)).fetchall()
        return {"resumes": [dict(row) for row in resumes], "cover_letter_templates": [dict(row) for row in templates]}
