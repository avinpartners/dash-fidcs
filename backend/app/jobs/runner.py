"""Job queue, single worker thread, job_runs bookkeeping and the scheduler (design 4.2).

One worker runs one job at a time from a de-duplicated in-memory queue.
APScheduler ticks every 30 min (first tick 15 s after start) and enqueues
every overdue implemented job in chain order. A data job that changed rows
puts metrics_recompute at the head of the queue, so numbers appear as each
step finishes (the first load's FundosNET step alone takes an hour or more).

A run stopped by the app going down (killed, shutdown, cancel) is recorded
as 'interrupted', not 'failed': it does not delay the next catch-up and does
not mark its sources as failing.

Module API used by the app: start(), shutdown(), enqueue(job, trigger),
run_chain(trigger), active(), get_runner().
CLI (no server needed): python -m app.jobs.runner [chain | <job> ...]
"""
import logging
import threading
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

import psycopg
from psycopg.types.json import Jsonb

from app.core.config import Settings, get_settings
from app.core.http import Downloader, cleanup_partial_downloads
from app.jobs.catchup import JOBS, TZ, is_overdue, needs_session_retry
from app.jobs.registry import JOB_FUNCTIONS, JobCancelled, JobContext, JobResult, KNOWN_JOBS, is_disabled

log = logging.getLogger("dash.jobs")

# "Atualizar agora" order; the scheduler uses it too, then the remaining jobs.
CHAIN: tuple[str, ...] = ("fidc_cadastro", "fidc_informe_mensal")
DATA_JOBS = frozenset(CHAIN)
SCHEDULE_ORDER: tuple[str, ...] = CHAIN + tuple(j.name for j in JOBS if j.name not in CHAIN)
# Sources marked as failing when the job raises.
JOB_SOURCES: dict[str, tuple[str, ...]] = {
    "fidc_cadastro": ("cvm_cad_fidc",),
    "fidc_informe_mensal": ("cvm_inf_mensal_fidc",),
}
TRIGGERS = ("schedule", "catch_up", "manual")
# Jobs of later phases (catchup.JobSpec.phase) are never scheduled.
CURRENT_PHASE = 5
TICK_MINUTES = 30
FIRST_TICK_DELAY_S = 15
# A scheduled job that failed is retried by the scheduler only after this long.
FAILED_RETRY_AFTER = timedelta(hours=2)
INTERRUPTED_MESSAGE = "Interrompido: o app foi encerrado durante a execução"


class JobNotImplemented(ValueError):
    """The job exists (catchup.JOBS) but belongs to a later phase."""


@dataclass
class QueuedJob:
    job: str
    trigger: str
    chain_id: str | None = None
    params: dict | None = None
    enqueued_at: datetime = field(default_factory=lambda: datetime.now(TZ))

    def as_dict(self) -> dict[str, Any]:
        return {"job": self.job, "trigger": self.trigger, "chain_id": self.chain_id,
                "params": self.params, "enqueued_at": self.enqueued_at.isoformat()}


class JobRunner:
    def __init__(
        self,
        settings: Settings | None = None,
        conn_factory: Callable[[], psycopg.Connection] | None = None,
        downloader_factory: Callable[[Settings], Downloader] | None = None,
    ):
        self.settings = settings or get_settings()
        self._conn_factory = conn_factory or (
            lambda: psycopg.connect(self.settings.database_url, connect_timeout=10)
        )
        self._downloader_factory = downloader_factory
        self._queue: deque[QueuedJob] = deque()
        self._cond = threading.Condition()
        self._current: dict[str, Any] | None = None
        self._stop = threading.Event()          # also the jobs' cancel flag
        self._thread: threading.Thread | None = None
        self._scheduler = None
        self._ticks = 0

    # -- queue ----------------------------------------------------------------

    def enqueue(self, job: str, trigger: str = "manual", *, chain_id: str | None = None,
                params: dict | None = None, front: bool = False) -> bool:
        """Queue `job`; False when it is already queued or running (de-duplicated).

        front=True puts it at the head of the queue; an already queued entry is
        moved there (and True is returned).
        """
        if job not in KNOWN_JOBS:
            raise ValueError(f"unknown job {job!r}")
        if job not in JOB_FUNCTIONS:
            raise JobNotImplemented(f"job {job!r} is not implemented in this phase")
        if trigger not in TRIGGERS:
            raise ValueError(f"unknown trigger {trigger!r}")
        with self._cond:
            if self._current and self._current["job"] == job:
                return False
            queued = next((q for q in self._queue if q.job == job), None)
            if queued is not None:
                if not front:
                    return False
                self._queue.remove(queued)
                self._queue.appendleft(queued)
                return True
            item = QueuedJob(job, trigger, chain_id, params)
            if front:
                self._queue.appendleft(item)
            else:
                self._queue.append(item)
            self._cond.notify()
        return True

    def run_chain(self, trigger: str = "manual", *, chain_id: str | None = None) -> dict[str, Any]:
        """Queue the implemented jobs of CHAIN in order under one chain_id."""
        chain_id = chain_id or uuid.uuid4().hex
        queued = [j for j in CHAIN if j in JOB_FUNCTIONS and not is_disabled(j, self.settings)
                  and self.enqueue(j, trigger, chain_id=chain_id)]
        return {"chain_id": chain_id, "queued": queued}

    def active(self, conn: psycopg.Connection | None = None) -> dict[str, Any]:
        """Snapshot for the API: the running job (with live progress) and the queue.

        The live progress is read through `conn` when given (the API passes a pooled
        connection), else through a new connection of the runner's own.
        """
        with self._cond:
            current = dict(self._current) if self._current else None
            queued = [q.as_dict() for q in self._queue]
        if current and current.get("run_id"):
            query = "SELECT progress, message FROM job_runs WHERE id = %s"
            try:
                if conn is not None:
                    row = conn.execute(query, (current["run_id"],)).fetchone()
                else:
                    with self._conn_factory() as own:
                        row = own.execute(query, (current["run_id"],)).fetchone()
                if row:
                    current["progress"] = float(row[0]) if row[0] is not None else None
                    current["message"] = row[1]
            except psycopg.Error:
                pass
        return {"current": current, "queued": queued}

    # -- execution -------------------------------------------------------------

    def run_next(self) -> bool:
        """Run the next queued job in the calling thread; False when the queue is empty."""
        with self._cond:
            if not self._queue:
                return False
            item = self._queue.popleft()
            self._current = {**item.as_dict(), "run_id": None,
                             "started_at": datetime.now(TZ).isoformat(), "progress": None, "message": None}
        try:
            self._execute(item)
        finally:
            with self._cond:
                self._current = None
        return True

    def run_until_idle(self, max_jobs: int = 100) -> int:
        """Drain the queue synchronously (tests and the CLI); returns jobs run."""
        n = 0
        while n < max_jobs and self.run_next():
            n += 1
        return n

    def _execute(self, item: QueuedJob) -> None:
        fn = JOB_FUNCTIONS[item.job]
        try:
            with self._conn_factory() as conn:
                run_id = conn.execute(
                    """INSERT INTO job_runs (job_name, trigger, status, params, chain_id, message)
                       VALUES (%s, %s, 'running', %s, %s, 'Iniciando') RETURNING id""",
                    (item.job, item.trigger, Jsonb(item.params) if item.params is not None else None, item.chain_id),
                ).fetchone()[0]
        except psycopg.Error:
            log.exception("cannot start %s: database unavailable", item.job)
            return
        with self._cond:
            if self._current is not None:
                self._current["run_id"] = run_id

        downloader = self._downloader_factory(self.settings) if self._downloader_factory else None
        ctx = JobContext(run_id, self.settings, downloader=downloader, conn_factory=self._conn_factory,
                         cancel_event=self._stop, job_name=item.job)
        log.info("job %s started (run %s, trigger %s)", item.job, run_id, item.trigger)
        try:
            result = fn(ctx)
            if result is None:
                result = JobResult()
            if not isinstance(result, JobResult):
                raise TypeError(f"job {item.job} returned {type(result).__name__}, expected JobResult")
        except BaseException as exc:  # noqa: BLE001 - a job must never kill the worker
            self._record_failure(ctx, item, exc)
            if not isinstance(exc, Exception):
                raise
        else:
            self._record_success(ctx, item, result)
        finally:
            ctx.close()

    def _record_success(self, ctx: JobContext, item: QueuedJob, result: JobResult) -> None:
        with self._conn_factory() as conn:
            conn.execute(
                """UPDATE job_runs SET status = 'success', finished_at = now(), progress = 1,
                       rows_changed = %s, message = %s WHERE id = %s""",
                (result.rows_changed, result.message or "Concluído", ctx.run_id),
            )
            for source in result.sources:
                conn.execute(
                    """UPDATE sources SET last_success_at = now(),
                           last_data_date = GREATEST(last_data_date, %s::date),
                           last_error = NULL, last_error_at = NULL
                       WHERE id = %s""",
                    (result.data_date, source),
                )
        log.info("job %s succeeded (run %s, %s rows changed)", item.job, ctx.run_id, result.rows_changed)
        if item.job in DATA_JOBS and result.rows_changed > 0 and "metrics_recompute" in JOB_FUNCTIONS:
            # Next in line, ahead of the remaining data jobs: the screener shows
            # this step's numbers without waiting for FundosNET and macro.
            self.enqueue("metrics_recompute", item.trigger, chain_id=item.chain_id, front=True)

    def _record_failure(self, ctx: JobContext, item: QueuedJob, exc: BaseException) -> None:
        interrupted = isinstance(exc, JobCancelled) or not isinstance(exc, Exception)
        if interrupted:
            status, message = "interrupted", "Cancelado: o app foi encerrado durante a execução"
            log.warning("job %s interrupted (run %s): %s", item.job, ctx.run_id, exc)
        else:
            status, message = "failed", f"Falhou: {type(exc).__name__}: {exc}"[:1000]
            log.error("job %s failed (run %s): %s", item.job, ctx.run_id, exc)
        ctx.log("".join(traceback.format_exception(exc)).rstrip())
        try:
            with self._conn_factory() as conn:
                conn.execute(
                    "UPDATE job_runs SET status = %s, finished_at = now(), message = %s WHERE id = %s",
                    (status, message, ctx.run_id),
                )
                # An interrupted run says nothing about the source.
                for source in () if interrupted else JOB_SOURCES.get(item.job, ()):
                    conn.execute(
                        "UPDATE sources SET last_error = %s, last_error_at = now() WHERE id = %s",
                        (message, source),
                    )
        except psycopg.Error:
            log.exception("could not record the failure of run %s", ctx.run_id)

    # -- scheduling ------------------------------------------------------------

    def schedule_tick(self, trigger: str = "schedule", now: datetime | None = None) -> list[str]:
        """Enqueue every overdue implemented job, in SCHEDULE_ORDER; returns the jobs queued."""
        now = now or datetime.now(TZ)
        last_ok: dict[str, datetime] = {}
        last_fail: dict[str, datetime] = {}
        try:
            with self._conn_factory() as conn:
                # 'interrupted' runs are left out on purpose: they must not trigger the back-off.
                for name, status, ts in conn.execute(
                    """SELECT job_name, status, max(coalesce(finished_at, started_at)) FROM job_runs
                       WHERE status IN ('success', 'failed') GROUP BY job_name, status"""
                ):
                    (last_ok if status == "success" else last_fail)[name] = ts
                source_dates = dict(conn.execute("SELECT id, last_data_date FROM sources").fetchall())
        except psycopg.Error:
            log.exception("scheduler tick skipped: database unavailable")
            return []
        specs = {j.name: j for j in JOBS}
        chain_id = uuid.uuid4().hex
        queued = []
        for name in SCHEDULE_ORDER:
            spec = specs[name]
            if spec.phase > CURRENT_PHASE or name not in JOB_FUNCTIONS or is_disabled(name, self.settings):
                continue
            due = is_overdue(spec, last_ok.get(name), now)
            if not due and spec.session_retry:
                dates = [source_dates.get(s) for s in JOB_SOURCES.get(name, ())]
                data_date = None if not dates or None in dates else min(dates)
                due = needs_session_retry(spec, data_date, last_ok.get(name), now)
            if not due:
                continue
            failed = last_fail.get(name)
            if failed and (name not in last_ok or failed > last_ok[name]) and now - failed < FAILED_RETRY_AFTER:
                continue
            if self.enqueue(name, trigger, chain_id=chain_id):
                queued.append(name)
        if queued:
            log.info("scheduler (%s) queued: %s", trigger, ", ".join(queued))
        return queued

    def _tick(self) -> None:
        self._ticks += 1
        self.schedule_tick("catch_up" if self._ticks == 1 else "schedule")

    def recover_stale_runs(self) -> int:
        """Runs left 'running' by a previous process (killed, laptop shut down) become 'interrupted'.

        Not 'failed': the startup catch-up must run them again right away.
        """
        try:
            with self._conn_factory() as conn:
                cur = conn.execute(
                    """UPDATE job_runs SET status = 'interrupted', finished_at = now(), message = %s
                       WHERE status = 'running'""",
                    (INTERRUPTED_MESSAGE,),
                )
                return cur.rowcount
        except psycopg.Error:
            log.exception("could not check for interrupted runs")
            return 0

    # -- lifecycle ---------------------------------------------------------------

    def is_alive(self) -> bool:
        """Whether the worker thread is running (otherwise queued jobs wait forever)."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, *, scheduler: bool = True) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.recover_stale_runs()
        try:
            # Nothing downloads yet: .part files left by a forced stop are garbage.
            cleanup_partial_downloads(self.settings.raw_data_dir)
        except OSError:
            log.exception("could not clean partial downloads")
        self._thread = threading.Thread(target=self._worker, name="dash-jobs", daemon=True)
        self._thread.start()
        if scheduler:
            from apscheduler.schedulers.background import BackgroundScheduler

            self._scheduler = BackgroundScheduler(
                timezone=TZ, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 600}
            )
            self._scheduler.add_job(
                self._tick, "interval", minutes=TICK_MINUTES, id="dash-tick",
                next_run_time=datetime.now(TZ) + timedelta(seconds=FIRST_TICK_DELAY_S),
            )
            self._scheduler.start()

    def shutdown(self, timeout: float = 10.0) -> None:
        """Stop the scheduler, ask the running job to cancel, wait up to `timeout` s."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                log.warning("job worker still busy after %.0f s; leaving it (daemon thread)", timeout)
            self._thread = None

    def _worker(self) -> None:
        while not self._stop.is_set():
            with self._cond:
                while not self._queue and not self._stop.is_set():
                    self._cond.wait(timeout=5)
                if self._stop.is_set():
                    return
            try:
                self.run_next()
            except Exception:  # noqa: BLE001
                log.exception("job worker error")


# -- module-level API --------------------------------------------------------------

_runner: JobRunner | None = None
_runner_lock = threading.Lock()


def get_runner() -> JobRunner:
    global _runner
    with _runner_lock:
        if _runner is None:
            _runner = JobRunner()
        return _runner


def start(settings: Settings | None = None) -> JobRunner:
    """Start the worker and the scheduler (the app starts its runner itself, see main.lifespan)."""
    global _runner
    with _runner_lock:
        if _runner is None or settings is not None:
            _runner = JobRunner(settings)
        runner = _runner
    runner.start()
    return runner


def shutdown() -> None:
    global _runner
    with _runner_lock:
        runner, _runner = _runner, None
    if runner is not None:
        runner.shutdown()


def enqueue(job: str, trigger: str = "manual", **kwargs) -> bool:
    return get_runner().enqueue(job, trigger, **kwargs)


def run_chain(trigger: str = "manual") -> dict[str, Any]:
    return get_runner().run_chain(trigger)


def active() -> dict[str, Any]:
    return get_runner().active()


def main(argv: list[str]) -> int:
    """Run jobs synchronously: `python -m app.jobs.runner chain` or `... cvm_informes`."""
    import app.jobs.all_jobs  # noqa: F401  (registers the job functions)
    from app.core.db import run_migrations

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_migrations()
    runner = JobRunner()
    names = argv or ["chain"]
    for name in names:
        if name == "chain":
            runner.run_chain("manual")
            continue
        try:
            runner.enqueue(name, "manual")
        except ValueError as exc:
            print(exc)
            return 2
    runner.run_until_idle()
    with runner._conn_factory() as conn:
        rows = conn.execute(
            "SELECT job_name, status, rows_changed, message FROM job_runs ORDER BY id DESC LIMIT %s", (20,)
        ).fetchall()
    for row in reversed(rows):
        print(*row, sep=" | ")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
