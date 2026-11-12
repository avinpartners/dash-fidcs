"""Numbered SQL migrations.

Version 1 is db/schema.sql (the Phase 0 baseline); later versions are
db/migrations/NNNN_name.sql. Each pending migration runs in its own
transaction while a PostgreSQL advisory lock keeps two processes from
migrating at once. The sha256 of every applied file is recorded; if an
applied file later changes, nothing new is applied and a warning is logged
(the app keeps serving).

Hashes are taken over the text with CRLF normalized to LF, so a Windows
checkout with different line endings does not count as a change.
"""
import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

log = logging.getLogger("dash.migrations")

DB_DIR = Path(__file__).resolve().parents[2] / "db"
SCHEMA_FILE = DB_DIR / "schema.sql"
MIGRATIONS_DIR = DB_DIR / "migrations"
LOCK_KEY = 7_331_402_175  # arbitrary, constant: pg_advisory_lock key for migrations
_NAME = re.compile(r"^(\d{4})_([A-Za-z0-9_]+)\.sql$")


class MigrationError(Exception):
    """An applied migration file changed, or the files are inconsistent."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8").replace("\r\n", "\n")

    def sha256(self) -> str:
        return hashlib.sha256(self.text().encode("utf-8")).hexdigest()


@dataclass
class MigrationReport:
    applied: list[int] = field(default_factory=list)   # versions executed by this call
    baselined: bool = False                            # version 1 recorded without running
    changed: list[int] = field(default_factory=list)   # applied versions whose file changed


def discover(schema_file: Path = SCHEMA_FILE, migrations_dir: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Version 1 = schema.sql, then every NNNN_name.sql in order."""
    found = [Migration(1, "baseline", schema_file)]
    seen = {1}
    for p in sorted(migrations_dir.glob("*.sql")) if migrations_dir.is_dir() else []:
        m = _NAME.match(p.name)
        if not m:
            log.warning("ignoring migration file with an unexpected name: %s", p.name)
            continue
        version = int(m.group(1))
        if version in seen:
            raise MigrationError(f"duplicate migration version {version}: {p.name}")
        seen.add(version)
        found.append(Migration(version, m.group(2), p))
    return sorted(found, key=lambda x: x.version)


def apply_migrations(
    url: str,
    *,
    schema_file: Path = SCHEMA_FILE,
    migrations_dir: Path = MIGRATIONS_DIR,
    strict: bool = False,
) -> MigrationReport:
    """Bring the database at `url` up to date.

    With strict=True a changed applied file raises MigrationError; otherwise
    it is logged and no pending migration runs.
    """
    migrations = discover(schema_file, migrations_dir)
    report = MigrationReport()
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                       version    INTEGER PRIMARY KEY,
                       name       TEXT NOT NULL,
                       sha256     CHAR(64) NOT NULL,
                       applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                   )"""
            )
            applied = {v: sha for v, sha in conn.execute("SELECT version, sha256 FROM schema_migrations")}
            if not applied and conn.execute("SELECT to_regclass('public.fidcs') IS NOT NULL").fetchone()[0]:
                # Phase 0 databases got schema.sql without bookkeeping.
                base = migrations[0]
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, sha256) VALUES (%s, %s, %s)",
                    (base.version, base.name, base.sha256()),
                )
                applied[base.version] = base.sha256()
                report.baselined = True
                log.info("existing schema recorded as migration 1 (baseline)")

            for m in migrations:
                if m.version in applied and applied[m.version].strip() != m.sha256():
                    report.changed.append(m.version)
            if report.changed:
                msg = (
                    f"applied migration file(s) changed since they ran: {report.changed}; "
                    "no pending migration was applied. Restore the files or add a new migration."
                )
                if strict:
                    raise MigrationError(msg)
                log.warning(msg)
                return report

            for m in migrations:
                if m.version in applied:
                    continue
                log.info("applying migration %04d_%s", m.version, m.name)
                with conn.transaction():
                    conn.execute(m.text())
                    conn.execute(
                        "INSERT INTO schema_migrations (version, name, sha256) VALUES (%s, %s, %s)",
                        (m.version, m.name, m.sha256()),
                    )
                report.applied.append(m.version)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    return report
