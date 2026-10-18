"""Small, repeatable SQLite migration runner.

The legacy application created tables opportunistically.  This module keeps
that data intact while making schema changes explicit and auditable.
"""

from __future__ import annotations

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


MIGRATIONS: tuple[tuple[int, str, Migration], ...] = (
    (1, "legacy baseline", _migration_001_baseline),
    (2, "candidate document profiles", _migration_002_candidate_documents),
    (3, "candidate identity fields", _migration_003_candidate_identity),
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
