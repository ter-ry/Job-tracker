"""Small, repeatable SQLite migration runner.

The legacy application created tables opportunistically.  This module keeps
that data intact while making schema changes explicit and auditable.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable

Migration = Callable[[sqlite3.Connection], None]


def _migration_001_baseline(db: sqlite3.Connection) -> None:
    """Reserve version one for databases created by the legacy application."""


def _migration_002_candidate_documents(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS candidate_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS base_resumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            docx_path TEXT NOT NULL DEFAULT '',
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(profile_id) REFERENCES candidate_profiles(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS cover_letter_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            docx_path TEXT NOT NULL DEFAULT '',
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(profile_id) REFERENCES candidate_profiles(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS base_resumes_profile_idx ON base_resumes(profile_id);
        CREATE INDEX IF NOT EXISTS cover_letter_templates_profile_idx ON cover_letter_templates(profile_id);
        """
    )


def _migration_003_candidate_identity(db: sqlite3.Connection) -> None:
    columns = {
        "identity_mode": "TEXT NOT NULL DEFAULT 'shared'",
        "applicant_name": "TEXT NOT NULL DEFAULT ''",
        "applicant_email": "TEXT NOT NULL DEFAULT ''",
        "applicant_phone": "TEXT NOT NULL DEFAULT ''",
        "applicant_location": "TEXT NOT NULL DEFAULT ''",
    }
    existing = {row[1] for row in db.execute("PRAGMA table_info(candidate_profiles)")}
    for name, definition in columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE candidate_profiles ADD COLUMN {name} {definition}")


def _migration_004_tailoring_studio(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS tailoring_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            candidate_profile_id INTEGER NOT NULL,
            resume_id INTEGER NOT NULL,
            source_path TEXT NOT NULL DEFAULT '',
            draft_path TEXT NOT NULL DEFAULT '',
            changes_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'draft',
            layout_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(job_id, candidate_profile_id, resume_id),
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS tailoring_drafts_job_idx ON tailoring_drafts(job_id);
        CREATE TABLE IF NOT EXISTS keyword_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_profile_id INTEGER NOT NULL,
            normalized_keyword TEXT NOT NULL,
            keyword TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'unknown',
            project_employer TEXT NOT NULL DEFAULT '',
            supporting_bullet TEXT NOT NULL DEFAULT '',
            source_fingerprint TEXT NOT NULL DEFAULT '',
            approved_replacement TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(candidate_profile_id, normalized_keyword),
            FOREIGN KEY(candidate_profile_id) REFERENCES candidate_profiles(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS keyword_memory_profile_idx ON keyword_memory(candidate_profile_id);
        """
    )


def _migration_005_tailoring_package_handoff(db: sqlite3.Connection) -> None:
    columns = {
        "approved_at": "TEXT NOT NULL DEFAULT ''",
        "approved_tailoring_draft_id": "INTEGER NOT NULL DEFAULT 0",
        "approved_tailored_resume_path": "TEXT NOT NULL DEFAULT ''",
    }
    existing = {row[1] for row in db.execute("PRAGMA table_info(tailoring_drafts)")}
    for name, definition in columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE tailoring_drafts ADD COLUMN {name} {definition}")
    queue_exists = db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'application_preparation_queue'").fetchone()
    if not queue_exists:
        return
    try:
        queue_columns = {row[1] for row in db.execute("PRAGMA table_info(application_preparation_queue)")}
        for name, definition in {
            "approved_tailoring_draft_id": "INTEGER NOT NULL DEFAULT 0",
            "approved_tailored_resume_path": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if name not in queue_columns:
                db.execute(f"ALTER TABLE application_preparation_queue ADD COLUMN {name} {definition}")
    except sqlite3.OperationalError:
        # The standalone profile-store migration tests do not create the
        # application queue. The application initializer creates it before
        # running this migration on a real database.
        return


def _migration_006_keyword_memory_source(db: sqlite3.Connection) -> None:
    existing = {row[1] for row in db.execute("PRAGMA table_info(keyword_memory)")}
    if "resume_id" not in existing:
        db.execute("ALTER TABLE keyword_memory ADD COLUMN resume_id INTEGER NOT NULL DEFAULT 0")


def _migration_007_keyword_memory_paragraph(db: sqlite3.Connection) -> None:
    existing = {row[1] for row in db.execute("PRAGMA table_info(keyword_memory)")}
    if "source_paragraph_index" not in existing:
        db.execute("ALTER TABLE keyword_memory ADD COLUMN source_paragraph_index INTEGER NOT NULL DEFAULT -1")


def _migration_008_tailoring_requirement_overrides(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS tailoring_requirement_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            normalized_requirement TEXT NOT NULL,
            override TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(job_id, normalized_requirement),
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS tailoring_requirement_overrides_job_idx ON tailoring_requirement_overrides(job_id);
        """
    )


def _migration_009_skill_confirmation_metadata(db: sqlite3.Connection) -> None:
    """Add metadata that distinguishes profile skill confirmations from bullet memory."""
    columns = {
        "confirmation_source": "TEXT NOT NULL DEFAULT ''",
        "confirmed_at": "TEXT NOT NULL DEFAULT ''",
        "notes": "TEXT NOT NULL DEFAULT ''",
    }
    existing = {row[1] for row in db.execute("PRAGMA table_info(keyword_memory)")}
    for name, definition in columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE keyword_memory ADD COLUMN {name} {definition}")


def _migration_010_tailoring_revision_history(db: sqlite3.Connection) -> None:
    existing = {row[1] for row in db.execute("PRAGMA table_info(tailoring_drafts)")}
    if "revision_history_json" not in existing:
        db.execute("ALTER TABLE tailoring_drafts ADD COLUMN revision_history_json TEXT NOT NULL DEFAULT '{}'")


def _migration_011_versioned_tailoring_drafts(db: sqlite3.Connection) -> None:
    """Allow immutable approved drafts and independent later revisions."""
    columns = {row[1] for row in db.execute("PRAGMA table_info(tailoring_drafts)")}
    if "revision_number" in columns and "parent_draft_id" in columns and "superseded_by_draft_id" in columns:
        return
    db.executescript(
        """
        CREATE TABLE tailoring_drafts_versioned (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            candidate_profile_id INTEGER NOT NULL,
            resume_id INTEGER NOT NULL,
            source_path TEXT NOT NULL DEFAULT '',
            draft_path TEXT NOT NULL DEFAULT '',
            changes_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'draft',
            layout_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            approved_at TEXT NOT NULL DEFAULT '',
            approved_tailoring_draft_id INTEGER NOT NULL DEFAULT 0,
            approved_tailored_resume_path TEXT NOT NULL DEFAULT '',
            revision_history_json TEXT NOT NULL DEFAULT '{}',
            parent_draft_id INTEGER NOT NULL DEFAULT 0,
            revision_number INTEGER NOT NULL DEFAULT 1,
            superseded_by_draft_id INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
        );
        INSERT INTO tailoring_drafts_versioned(
            id, job_id, candidate_profile_id, resume_id, source_path, draft_path,
            changes_json, status, layout_json, created_at, updated_at, approved_at,
            approved_tailoring_draft_id, approved_tailored_resume_path,
            revision_history_json, revision_number
        )
        SELECT id, job_id, candidate_profile_id, resume_id, source_path, draft_path,
            changes_json, status, layout_json, created_at, updated_at, approved_at,
            approved_tailoring_draft_id, approved_tailored_resume_path,
            revision_history_json, 1
        FROM tailoring_drafts;
        DROP TABLE tailoring_drafts;
        ALTER TABLE tailoring_drafts_versioned RENAME TO tailoring_drafts;
        CREATE INDEX IF NOT EXISTS tailoring_drafts_job_idx ON tailoring_drafts(job_id);
        CREATE INDEX IF NOT EXISTS tailoring_drafts_scope_idx ON tailoring_drafts(job_id, candidate_profile_id, resume_id, revision_number);
        """
    )


def _migration_012_discovery_status_semantics(db: sqlite3.Connection) -> None:
    """Separate automatic discovery from explicit user saves without losing history."""
    columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
    if "discovery_first_seen_at" not in columns or "status" not in columns:
        return
    db.execute(
        """UPDATE jobs
           SET status = 'Discovered', updated_at = CURRENT_TIMESTAMP
         WHERE discovery_first_seen_at <> ''
           AND status = 'Saved'
           AND discovery_state NOT IN ('saved', 'applied')"""
    )


def _migration_013_workplace_evidence(db: sqlite3.Connection) -> None:
    """Store explicit workplace and provider-conflict evidence for re-enrichment."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'").fetchone():
        # Profile-only migration tests and newly created stores create the jobs
        # table later during application initialization.
        return
    columns = {
        "workplace_address": "TEXT NOT NULL DEFAULT ''",
        "workplace_postal_code": "TEXT NOT NULL DEFAULT ''",
        "workplace_evidence": "TEXT NOT NULL DEFAULT ''",
        "workplace_evidence_source": "TEXT NOT NULL DEFAULT ''",
        "workplace_precision": "TEXT NOT NULL DEFAULT ''",
        "workplace_confidence": "INTEGER NOT NULL DEFAULT 0",
        "remote_classification_conflict": "TEXT NOT NULL DEFAULT ''",
        "provider_raw_json": "TEXT NOT NULL DEFAULT '{}'",
    }
    existing = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
    for name, definition in columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")


def _migration_014_structured_posting_evidence(db: sqlite3.Connection) -> None:
    """Preserve multi-site workplaces and explicit posting evidence."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'").fetchone():
        return
    columns = {
        "workplace_alternatives_json": "TEXT NOT NULL DEFAULT '[]'",
        "credentials_json": "TEXT NOT NULL DEFAULT '[]'",
        "benefits_json": "TEXT NOT NULL DEFAULT '[]'",
        "arrangement_evidence": "TEXT NOT NULL DEFAULT ''",
    }
    existing = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
    for name, definition in columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
    existing = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
    legacy_fields = {
        "workplace_address", "workplace_postal_code", "workplace_evidence",
        "workplace_evidence_source", "workplace_precision", "workplace_confidence",
    }
    if legacy_fields <= existing:
        rows = db.execute(
            """SELECT id, workplace_address, workplace_postal_code, workplace_evidence,
                      workplace_evidence_source, workplace_precision, workplace_confidence,
                      workplace_alternatives_json
                 FROM jobs"""
        ).fetchall()
        for row in rows:
            if str(row[7] or "").strip() not in {"", "[]"} or not str(row[1] or "").strip():
                continue
            alternative = {
                "address": str(row[1] or "").strip(),
                "postal_code": str(row[2] or "").strip(),
                "precision": str(row[5] or "street address").strip(),
                "confidence": int(row[6] or 0),
                "evidence": str(row[3] or row[1] or "").strip(),
                "evidence_source": str(row[4] or "legacy single workplace").strip(),
                "assignment_status": "confirmed",
            }
            db.execute(
                "UPDATE jobs SET workplace_alternatives_json = ? WHERE id = ?",
                [json.dumps([alternative], ensure_ascii=False), int(row[0])],
            )

MIGRATIONS: tuple[tuple[int, str, Migration], ...] = (
    (1, "legacy baseline", _migration_001_baseline),
    (2, "candidate document profiles", _migration_002_candidate_documents),
    (3, "candidate identity fields", _migration_003_candidate_identity),
    (4, "interactive tailoring studio", _migration_004_tailoring_studio),
    (5, "tailoring package handoff", _migration_005_tailoring_package_handoff),
    (6, "keyword memory source résumé", _migration_006_keyword_memory_source),
    (7, "keyword memory paragraph identity", _migration_007_keyword_memory_paragraph),
    (8, "tailoring requirement overrides", _migration_008_tailoring_requirement_overrides),
    (9, "skill confirmation metadata", _migration_009_skill_confirmation_metadata),
    (10, "tailoring revision history", _migration_010_tailoring_revision_history),
    (11, "versioned tailoring drafts", _migration_011_versioned_tailoring_drafts),
    (12, "discovery status semantics", _migration_012_discovery_status_semantics),
    (13, "workplace evidence", _migration_013_workplace_evidence),
    (14, "structured posting evidence", _migration_014_structured_posting_evidence),
)


def run_migrations(db: sqlite3.Connection) -> int:
    """Apply pending migrations transactionally and return the current version."""

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    recorded = {row[0] for row in db.execute("SELECT version FROM schema_migrations")}
    legacy_version = int(db.execute("PRAGMA user_version").fetchone()[0] or 0)
    for version, name, migration in MIGRATIONS:
        if version in recorded:
            continue
        # Version one describes the already-deployed schema.  Never replay it
        # against a user's existing database.
        if version == 1 and legacy_version >= 1:
            migration(db)
        else:
            migration(db)
        db.execute("INSERT INTO schema_migrations(version, name) VALUES (?, ?)", (version, name))
        db.execute(f"PRAGMA user_version = {version}")
    db.commit()
    return int(db.execute("PRAGMA user_version").fetchone()[0])
