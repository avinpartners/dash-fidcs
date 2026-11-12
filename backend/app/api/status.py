"""/api/status: Status dos dados (design section 6).

Jobs, source freshness, the last 50 runs, open data quality issues, LLM spend
against the monthly cap, the review queue and database facts. If the
database is down the page still gets an answer with db.ok = false.
"""
import logging
from datetime import datetime
from typing import Any

import psycopg
from fastapi import APIRouter

from app.api.fastjson import FastJSONRoute
from app.api.common import clean, connection, fetch_all, label_for
from app.api.jobs import jobs_list
from app.core.config import get_settings
from app.jobs.catchup import TZ

log = logging.getLogger("dash.api")
router = APIRouter(route_class=FastJSONRoute)

RUNS_N = 50
ISSUES_N = 100
# Row counts the Status page shows. Large tables use the planner estimate (pg_class.reltuples, kept
# fresh by autovacuum/ANALYZE) instead of a full count(*); they are listed in tables_estimated.
COUNTED_TABLES = ("fidcs", "fidc_mensal", "fidc_series", "fidc_cedentes", "cadastro_cvm")
ESTIMATED_TABLES = frozenset({"fidc_series"})


def _table_counts(conn: psycopg.Connection) -> tuple[dict[str, int], list[str]]:
    estimates = dict(conn.execute(
        """SELECT c.relname, c.reltuples::bigint FROM pg_class c
           WHERE c.relname = ANY(%s) AND c.relnamespace = 'public'::regnamespace""",
        (sorted(ESTIMATED_TABLES),)).fetchall())
    tables: dict[str, int] = {}
    estimated: list[str] = []
    for t in COUNTED_TABLES:
        est = estimates.get(t)
        if t in ESTIMATED_TABLES and est is not None and est > 0:    # -1 = never analyzed (PG 14+)
            tables[t] = int(est)
            estimated.append(t)
        else:
            tables[t] = conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
    return tables, estimated


def _db_facts(conn: psycopg.Connection) -> dict[str, Any]:
    size = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
    version = conn.execute("SHOW server_version").fetchone()[0]
    migrations = fetch_all(conn, "SELECT version, name, applied_at FROM schema_migrations ORDER BY version")
    tables, estimated = _table_counts(conn)
    return {
        "ok": True,
        "server_version": version,
        "size_bytes": size,
        "schema_version": migrations[-1]["version"] if migrations else None,
        "migrations": clean(migrations),
        "tables": tables,
        "tables_estimated": estimated,
    }


@router.get("/status")
def status():
    settings = get_settings()
    out: dict[str, Any] = {
        "jobs": [], "sources": [], "runs": [],
        "issues": {"by_kind": {}, "open": []},
        "llm": {"spent_usd": None, "budget_usd": settings.llm_monthly_budget_usd,
                "key_configured": bool(settings.anthropic_api_key.strip())},
        "review_queue": 0,
        "db": {"ok": False},
    }
    try:
        with connection() as conn:
            sources = fetch_all(conn, """
                SELECT id, name, label_pt, base_url, schedule, last_success_at, last_data_date, last_error,
                       last_error_at, notes
                FROM sources ORDER BY id""")
            for s in sources:
                s["label"] = s.pop("label_pt") or label_for(s["id"])
            out["sources"] = clean(sources)
            runs = fetch_all(conn, """
                SELECT id, job_name, trigger, started_at, finished_at, status, progress, message, rows_changed,
                       chain_id, EXTRACT(EPOCH FROM (COALESCE(finished_at, now()) - started_at)) AS duration_s
                FROM job_runs ORDER BY started_at DESC, id DESC LIMIT %s""", (RUNS_N,))
            out["runs"] = clean(runs)
            by_kind = conn.execute("""
                SELECT kind, count(*) FROM data_quality_issues WHERE status = 'open'
                GROUP BY kind ORDER BY count(*) DESC, kind""").fetchall()
            open_issues = fetch_all(conn, """
                SELECT i.id, i.kind, i.severity, i.cnpj, NULL AS ticker, f.nome AS name, i.ref_month, i.document_id,
                       i.detail, i.created_at
                FROM data_quality_issues i LEFT JOIN fidcs f ON f.cnpj = i.cnpj
                WHERE i.status = 'open' ORDER BY i.created_at DESC, i.id DESC LIMIT %s""", (ISSUES_N,))
            out["issues"] = {"by_kind": {k: n for k, n in by_kind}, "open": clean(open_issues)}
            out["llm"]["spent_usd"] = 0
            out["db"] = _db_facts(conn)
            out["jobs"] = clean(jobs_list(conn))
    except (psycopg.Error, OSError) as exc:  # pool timeouts are psycopg errors too
        log.warning("status: database unavailable: %s", exc)
        out["db"] = {"ok": False, "error": f"Banco de dados indisponível: {type(exc).__name__}"}
    if not out["jobs"]:          # database down: the job list without run data, no second connection attempt
        out["jobs"] = clean(jobs_list(skip_db=True))
    return out
