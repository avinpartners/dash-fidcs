"""Job registry and the context a job function receives (design 4.2).

    from app.jobs.registry import JobContext, JobResult, register

    @register("cvm_informes")
    def run(ctx: JobContext) -> JobResult:
        ...
        return JobResult(rows_changed=n, sources=("cvm_inf_mensal",), data_date=last_month)
"""
import json
import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Iterable

import psycopg

from app.core.config import Settings, get_settings
from app.core.http import Downloader
from app.jobs.catchup import JOBS

log = logging.getLogger("dash.jobs")

LOG_TAIL_LINES = 200
KNOWN_JOBS = frozenset(j.name for j in JOBS)


@dataclass
class JobResult:
    rows_changed: int = 0
    sources: tuple[str, ...] = ()      # sources.id values refreshed by this run
    data_date: date | None = None      # newest reference date now in the DB for those sources
    message: str = ""                  # pt-BR summary shown on the status page


class JobCancelled(Exception):
    """Raised by ctx.check_cancelled() when the app is shutting down."""


JobFunction = Callable[["JobContext"], JobResult]
JOB_FUNCTIONS: dict[str, JobFunction] = {}


def register(name: str) -> Callable[[JobFunction], JobFunction]:
    """Decorator binding a function to a job name from catchup.JOBS."""
    if name not in KNOWN_JOBS:
        raise ValueError(f"unknown job {name!r}; add it to app/jobs/catchup.py JOBS first")

    def deco(fn: JobFunction) -> JobFunction:
        current = JOB_FUNCTIONS.get(name)
        if current is not None and current.__qualname__ != fn.__qualname__:
            raise ValueError(f"job {name!r} already registered by {current.__module__}.{current.__qualname__}")
        JOB_FUNCTIONS[name] = fn
        return fn

    return deco


def _issue_key(kind: str, cnpj: str | None, ref_month: date | None, document_id: int | None, detail) -> tuple:
    """An issue's identity as issue() deduplicates it (detail compared as canonical JSON)."""
    return (kind, cnpj.strip() if cnpj else None, ref_month, document_id,
            json.dumps(detail, ensure_ascii=False, sort_keys=True))


def is_implemented(name: str) -> bool:
    return name in JOB_FUNCTIONS


# Jobs a setting turns off: never scheduled, left out of "Atualizar agora", refused when started by hand.
B3_JOBS = frozenset({"prices_cotahist"})


def is_disabled(name: str, settings: Any) -> bool:
    return name in B3_JOBS and not settings.b3_enabled


class JobContext:
    """Everything a job needs: settings, a downloader, DB access and status reporting.

    progress/log/issue write through short autocommit connections so the
    status page sees them while the job's own transaction is still open.
    Issues raised in this run are remembered, so resolve_cleared can close the
    ones a full re-check no longer raises.
    """

    def __init__(
        self,
        run_id: int,
        settings: Settings | None = None,
        downloader: Downloader | None = None,
        conn_factory: Callable[[], psycopg.Connection] | None = None,
        cancel_event: threading.Event | None = None,
        job_name: str = "",
    ):
        self.run_id = run_id
        self.job_name = job_name
        self.settings = settings or get_settings()
        self._conn_factory = conn_factory or (
            lambda: psycopg.connect(self.settings.database_url, connect_timeout=10)
        )
        self._downloader = downloader
        self._cancel = cancel_event or threading.Event()
        self._log_lines: deque[str] = deque(maxlen=LOG_TAIL_LINES)
        self._lock = threading.Lock()
        self._raised: set[tuple] = set()

    @property
    def downloader(self) -> Downloader:
        if self._downloader is None:
            self._downloader = Downloader(self.settings, conn_factory=self._conn_factory)
        return self._downloader

    @downloader.setter
    def downloader(self, value: Downloader) -> None:
        self._downloader = value

    def connect(self) -> psycopg.Connection:
        """A new connection; `with ctx.connect() as conn:` commits on success."""
        return self._conn_factory()

    def _write(self, sql: str, params: tuple) -> None:
        try:
            with self._conn_factory() as conn:
                conn.execute(sql, params)
        except psycopg.Error:
            log.exception("could not update job_runs %s", self.run_id)

    def progress(self, fraction: float | None, message: str) -> None:
        """Progress 0..1 (None = unknown) and a short pt-BR message for the status page."""
        if fraction is not None:
            fraction = min(max(float(fraction), 0.0), 1.0)
        self._write("UPDATE job_runs SET progress = %s, message = %s WHERE id = %s", (fraction, message, self.run_id))

    def log(self, message: str) -> None:
        """Append a line to job_runs.log (the last 200 lines are kept)."""
        log.info("[%s #%s] %s", self.job_name, self.run_id, message)
        with self._lock:
            for line in str(message).splitlines() or [""]:
                self._log_lines.append(line)
            text = "\n".join(self._log_lines)
        self._write("UPDATE job_runs SET log = %s WHERE id = %s", (text, self.run_id))

    def log_text(self) -> str:
        with self._lock:
            return "\n".join(self._log_lines)

    def issue(self, kind: str, detail: dict, *, severity: str = "warning", cnpj: str | None = None,
              ref_month: date | None = None, document_id: int | None = None) -> None:
        """Record a data_quality_issues row; an identical open issue is not duplicated."""
        payload = json.dumps(detail, ensure_ascii=False, default=str, sort_keys=True)
        with self._lock:
            self._raised.add(_issue_key(kind, cnpj, ref_month, document_id, json.loads(payload)))
        self._write(
            """INSERT INTO data_quality_issues (kind, severity, cnpj, ref_month, document_id, detail)
               SELECT %s, %s, %s, %s, %s, %s::jsonb
               WHERE NOT EXISTS (
                   SELECT 1 FROM data_quality_issues
                   WHERE status = 'open' AND kind = %s
                     AND cnpj IS NOT DISTINCT FROM %s::char(14) AND ref_month IS NOT DISTINCT FROM %s::date
                     AND document_id IS NOT DISTINCT FROM %s::bigint AND detail = %s::jsonb)""",
            (kind, severity, cnpj, ref_month, document_id, payload,
             kind, cnpj, ref_month, document_id, payload),
        )

    def resolve_cleared(self, kinds: Iterable[str], cnpjs: Iterable[str] | None = None) -> int:
        """Resolve the open issues of `kinds` (of the funds in `cnpjs`, when given) this run did not raise.

        Call it only after the run checked again everything those issues are about, so an issue not
        raised again means its cause has cleared: a source that answers again, a split no longer
        detected. Returns how many were resolved.
        """
        kinds = list(kinds)
        scope = None if cnpjs is None else list(cnpjs)
        if not kinds or scope == []:
            return 0
        with self._lock:
            raised = set(self._raised)
        try:
            with self._conn_factory() as conn:
                rows = conn.execute(
                    """SELECT id, kind, cnpj, ref_month, document_id, detail FROM data_quality_issues
                       WHERE status = 'open' AND kind = ANY(%s) AND (%s::text[] IS NULL OR cnpj = ANY(%s))""",
                    (kinds, scope, scope)).fetchall()
                stale = [r[0] for r in rows if _issue_key(*r[1:]) not in raised]
                if stale:
                    conn.execute("UPDATE data_quality_issues SET status = 'resolved', resolved_at = now() "
                                 "WHERE id = ANY(%s)", (stale,))
        except psycopg.Error:
            log.exception("could not resolve issues %s", kinds)
            return 0
        return len(stale)

    def source_error(self, source_id: str, message: str) -> None:
        """Mark one source as failing while the job itself goes on (e.g. Tesouro inside macro_series)."""
        self._write(
            "UPDATE sources SET last_error = %s, last_error_at = now() WHERE id = %s",
            (message[:2000], source_id),
        )

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled("cancelado: o app está sendo encerrado")

    def close(self) -> None:
        if self._downloader is not None:
            self._downloader.close()
