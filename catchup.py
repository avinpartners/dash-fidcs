"""Scheduling rules and startup catch-up (Dash FIDCs; framework from Dash Fundos).

The host laptop is often off, so cron-style triggers alone would miss runs.
On startup (and every 30 minutes) we ask, for each job, "is a run overdue?"
based on its last successful run, and run it if so.

Due times sit after the sources publish: the COTAHIST daily file was out by
20:34 (BRT) and the Tesouro CSV carried Last-Modified 07:24 (BRT) in the
laptop trial (PHASE1_DESIGN section 10). prices_cotahist also retries while
the latest expected session is missing (needs_session_retry): a run that met
a 404 counts as a success and would otherwise wait for the next day.
cvm_informes runs daily: informes arrive around the 14th of the following
month and CVM re-publishes the zips; unchanged zips cost a conditional GET.
cri_registry (securitizadora CRI informe) follows it daily for the same
reason: the yearly zip is updated continuously (cvm_securit.md surprise 5);
cra_registry (the CRA informe) right after it, then debenture_registry (ANBIMA's
SND list, regenerated on every request).
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")


@dataclass(frozen=True)
class JobSpec:
    name: str
    cadence: str           # 'daily' | 'weekly' | 'monthly'
    # daily: earliest local time a run counts for the day
    # weekly: that time on `weekday` (0 = Monday)
    # monthly: day of month from which the month's run is due
    due_time: time = time(7, 0)
    due_day: int = 1
    weekday: int = 0
    phase: int = 1         # project phase that implements the job (2/3: not yet, never run)
    # daily job with one file per weekday session: re-run while the latest
    # expected session is missing from its sources' last_data_date
    session_retry: bool = False


JOBS: list[JobSpec] = [
    # CVM cadastro (registro_fundo_classe.zip) first: names, gestor and administrador of every class.
    JobSpec("fidc_cadastro", "daily", time(8, 0)),
    # Informe mensal FIDC: one zip per month, out around the 15th of the following month and re-published while
    # funds send corrections; unchanged zips cost a conditional GET.
    JobSpec("fidc_informe_mensal", "daily", time(8, 15)),
    JobSpec("db_backup", "daily", time(0, 0)),
]


def last_due_at(job: JobSpec, now: datetime) -> datetime:
    """Most recent moment at which a run of `job` became due (<= now)."""
    now = now.astimezone(TZ)
    if job.cadence == "daily":
        candidate = datetime.combine(now.date(), job.due_time, TZ)
        return candidate if candidate <= now else candidate - timedelta(days=1)
    if job.cadence == "weekly":
        candidate = datetime.combine(now.date() - timedelta(days=(now.weekday() - job.weekday) % 7), job.due_time, TZ)
        return candidate if candidate <= now else candidate - timedelta(days=7)
    if job.cadence == "monthly":
        candidate = datetime.combine(date(now.year, now.month, job.due_day), time(0, 0), TZ)
        if candidate <= now:
            return candidate
        prev_month = (now.replace(day=1) - timedelta(days=1))
        return datetime.combine(date(prev_month.year, prev_month.month, job.due_day), time(0, 0), TZ)
    raise ValueError(f"unknown cadence {job.cadence!r}")


def next_due_at(job: JobSpec, now: datetime) -> datetime:
    """First moment after `now` at which a new run of `job` becomes due."""
    last = last_due_at(job, now)
    if job.cadence == "daily":
        return datetime.combine(last.date() + timedelta(days=1), job.due_time, TZ)
    if job.cadence == "weekly":
        return datetime.combine(last.date() + timedelta(days=7), job.due_time, TZ)
    year, month = (last.year + 1, 1) if last.month == 12 else (last.year, last.month + 1)
    return datetime.combine(date(year, month, job.due_day), time(0, 0), TZ)


def is_overdue(job: JobSpec, last_success: datetime | None, now: datetime) -> bool:
    if last_success is None:
        return True
    return last_success < last_due_at(job, now)


# A session retry waits at least this long after the previous successful run.
SESSION_RETRY_INTERVAL = timedelta(hours=1)


def latest_expected_session(job: JobSpec, now: datetime) -> date:
    """Latest weekday whose file should be out by `now`: today once due_time passed, else the day before."""
    now = now.astimezone(TZ)
    day = now.date() if now.time() >= job.due_time else now.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def needs_session_retry(job: JobSpec, last_data_date: date | None, last_success: datetime | None,
                        now: datetime) -> bool:
    """True when the latest expected session is still missing and another try is allowed.

    Tries at most every SESSION_RETRY_INTERVAL until the end of the session
    day, then once more (the next morning's catch-up); after that it stops,
    so a weekday holiday (404 all day) costs a handful of requests.
    """
    if not job.session_retry or last_success is None:
        return False
    session = latest_expected_session(job, now)
    if last_data_date is not None and last_data_date >= session:
        return False
    if now - last_success < SESSION_RETRY_INTERVAL:
        return False
    window_end = datetime.combine(session + timedelta(days=1), time(0, 0), TZ)
    return now < window_end or last_success < window_end


def overdue_jobs(last_success: dict[str, datetime | None], now: datetime) -> list[JobSpec]:
    return [j for j in JOBS if is_overdue(j, last_success.get(j.name), now)]
