"""Database access: plain connections, a shared pool, migrations."""
import logging
import threading

import psycopg
from psycopg_pool import ConnectionPool

from app.core.config import get_settings
from app.core.migrations import MigrationReport, apply_migrations

log = logging.getLogger("dash.db")

_pools: dict[str, ConnectionPool] = {}
_pools_lock = threading.Lock()


def connect(url: str | None = None, **kwargs) -> psycopg.Connection:
    """A new connection (caller closes it; `with connect() as conn:` commits on success)."""
    kwargs.setdefault("connect_timeout", 10)
    return psycopg.connect(url or get_settings().database_url, **kwargs)


def get_pool(url: str | None = None) -> ConnectionPool:
    """Process-wide pool for API requests: `with get_pool().connection() as conn: ...`."""
    url = url or get_settings().database_url
    with _pools_lock:
        pool = _pools.get(url)
        if pool is None:
            pool = ConnectionPool(
                # A page asks for several things at once (Início: 5 requests): keep 4 connections open so
                # they do not wait for new ones (slow on Windows).
                url, min_size=4, max_size=8, timeout=15, open=True,
                kwargs={"connect_timeout": 10}, name="dash",
            )
            _pools[url] = pool
        return pool


def close_pools() -> None:
    with _pools_lock:
        for pool in _pools.values():
            pool.close()
        _pools.clear()


def run_migrations(url: str | None = None, *, strict: bool = False) -> MigrationReport:
    return apply_migrations(url or get_settings().database_url, strict=strict)


def ensure_schema() -> None:
    """Kept for Phase 0 callers; same as run_migrations()."""
    run_migrations()


def is_loaded(conn: psycopg.Connection, raw_file_id: int, loader: str) -> bool:
    """True if `loader` already parsed this raw file (raw_file_loads)."""
    row = conn.execute(
        "SELECT 1 FROM raw_file_loads WHERE raw_file_id = %s AND loader = %s", (raw_file_id, loader)
    ).fetchone()
    return row is not None


def mark_loaded(conn: psycopg.Connection, raw_file_id: int, loader: str, rows: int | None = None) -> None:
    conn.execute(
        """INSERT INTO raw_file_loads (raw_file_id, loader, rows) VALUES (%s, %s, %s)
           ON CONFLICT (raw_file_id, loader) DO UPDATE SET loaded_at = now(), rows = EXCLUDED.rows""",
        (raw_file_id, loader, rows),
    )
