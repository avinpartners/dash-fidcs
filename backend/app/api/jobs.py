"""/api/jobs: job list with schedule state, "Atualizar agora", live progress and run logs (design section 6).

POST /jobs/run, GET /jobs/active and GET /jobs/runs/{id} wrap app.jobs.runner
(run_chain, enqueue, active). Reads use the API connection pool (these
endpoints are polled every few seconds while a job runs).
"""
import uuid
from datetime import datetime
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel

from app.api.fastjson import FastJSONRoute
from app.api.common import clean, connection, fetch_one
from app.core.config import get_settings
from app.jobs import runner
from app.jobs.catchup import JOBS, TZ, is_overdue, last_due_at, next_due_at
from app.jobs.registry import KNOWN_JOBS, is_disabled, is_implemented

router = APIRouter(route_class=FastJSONRoute)

# The sources each job loads; fnet_documents loads B3 proventos first (app/ingest/b3_proventos.py).
_JOB_SOURCES: dict[str, tuple[str, ...]] = dict(runner.JOB_SOURCES)


def jobs_list(conn: psycopg.Connection | None = None, *, skip_db: bool = False) -> list[dict[str, Any]]:
    """Every job with last success, last status, whether it is overdue, when it is next due, when
    overdue since when (due_since), and the job's sources still in error after a successful last run
    (failed_sources: the run went on without them, e.g. one SGS series or B3 proventos). Uses `conn` when given, else a pooled connection (none with skip_db);
    without a database the job list still answers (no run data)."""
    last_success: dict[str, datetime | None] = {j.name: None for j in JOBS}
    last_status: dict[str, str | None] = {j.name: None for j in JOBS}
    source_errors: dict[str, str] = {}

    def read(c: psycopg.Connection) -> None:
        for name, ts in c.execute(
            "SELECT job_name, max(finished_at) FROM job_runs WHERE status = 'success' GROUP BY job_name"
        ):
            last_success[name] = ts
        for name, status in c.execute(
            "SELECT DISTINCT ON (job_name) job_name, status FROM job_runs ORDER BY job_name, started_at DESC, id DESC"
        ):
            last_status[name] = status
        source_errors.update(c.execute("SELECT id, coalesce(label_pt, name) FROM sources WHERE last_error IS NOT NULL").fetchall())

    try:
        if conn is not None:
            read(conn)
        elif not skip_db:
            with connection() as c:
                read(c)
    except (psycopg.Error, OSError):  # the status page reports DB problems itself
        pass
    now = datetime.now(TZ)
    settings = get_settings()
    out = []
    for j in JOBS:
        disabled = is_disabled(j.name, settings)
        implemented = is_implemented(j.name)
        overdue = implemented and not disabled and is_overdue(j, last_success.get(j.name), now)
        out.append({
            "name": j.name,
            "cadence": j.cadence,
            "phase": j.phase,
            "implemented": implemented,
            "disabled": disabled,
            "last_success": last_success.get(j.name),
            "last_status": last_status.get(j.name),
            "overdue": overdue,
            "next_due": next_due_at(j, now) if implemented and not disabled else None,
            "due_since": last_due_at(j, now) if overdue else None,
            "failed_sources": [{"id": s, "name": source_errors[s]} for s in _JOB_SOURCES.get(j.name, ())
                               if s in source_errors] if last_status.get(j.name) == "success" else [],
        })
    return out


B3_OFF = ("As cargas da B3 estão desligadas (cotações e proventos). Os dados já carregados ficam. "
          "Para religar: B3_ENABLED=true no arquivo .env e reinicie o app.")

@router.get("/jobs")
def jobs():
    return jobs_list()


def worker_alive() -> bool:
    """Whether the job worker thread is running (queued jobs would otherwise wait forever)."""
    return runner.get_runner().is_alive()


WORKER_DOWN = "O executor de tarefas não está rodando; reinicie o Dash FIDCs (veja o log do servidor)"


class RunRequest(BaseModel):
    job: str | None = None


@router.post("/jobs/run")
def run_jobs(body: RunRequest | None = None):
    """Queue one job, or the whole chain when job is null ("Atualizar agora")."""
    job = body.job if body else None
    if job is not None and job not in KNOWN_JOBS:
        raise HTTPException(404, detail=f"Tarefa desconhecida: {job}")
    if job is not None and not is_implemented(job):
        raise _not_implemented(job)
    if job is not None and is_disabled(job, get_settings()):
        raise HTTPException(409, detail=B3_OFF)
    if not worker_alive():
        raise HTTPException(503, detail=WORKER_DOWN)
    if job is None:
        result = runner.run_chain("manual")
        return {**result, "already_queued": [], "message": _queued_message(result["queued"])}
    chain_id = uuid.uuid4().hex
    try:
        queued = runner.enqueue(job, "manual", chain_id=chain_id)
    except runner.JobNotImplemented:
        raise _not_implemented(job)
    return {
        "chain_id": chain_id,
        "queued": [job] if queued else [],
        "already_queued": [] if queued else [job],
        "message": _queued_message([job]) if queued else f"{job} já está na fila ou em execução",
    }


def _not_implemented(job: str) -> HTTPException:
    phase = next((j.phase for j in JOBS if j.name == job), 1)
    detail = (f"A tarefa {job} será implementada na Fase {phase}" if phase > 1
              else f"A tarefa {job} não está disponível nesta versão")
    return HTTPException(409, detail=detail)


def _queued_message(queued: list[str]) -> str:
    if not queued:
        return "Nada a fazer: as tarefas já estão na fila ou em execução"
    return "Na fila: " + ", ".join(queued)


@router.get("/jobs/active")
def jobs_active():
    """The running job (live progress and message), the queue and whether the worker is running."""
    r = runner.get_runner()
    try:            # the live progress is read through the pool (this endpoint is polled)
        with connection() as conn:
            snap = r.active(conn=conn)
    except (psycopg.Error, OSError):
        snap = r.active()
    return clean({**snap, "worker_alive": worker_alive()})


@router.get("/jobs/runs/{run_id}")
def job_run(run_id: int = Path(ge=1, le=2**63 - 1)):
    with connection() as conn:
        row = fetch_one(conn, """
            SELECT id, job_name, trigger, started_at, finished_at, status, progress, message, log, params,
                   rows_changed, chain_id
            FROM job_runs WHERE id = %s""", (run_id,))
    if row is None:
        raise HTTPException(404, detail=f"Execução {run_id} não encontrada")
    return clean(row)
