"""db_backup job: pg_dump -Fc into BACKUP_DIR, keep the newest BACKUP_KEEP.

The dump is written to a .tmp name and renamed when pg_dump succeeds, so a
half-written file never counts as a backup. A .tmp left by a forced stop
(Stop-Process -Force skips every cleanup) is deleted by the next backup. The password goes to pg_dump
through PGPASSWORD, never on the command line. Restore with
`pg_restore --clean --if-exists -d dash <file>` (README.md).
"""
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.core.formatting import fmt_number
from app.jobs.catchup import TZ
from app.jobs.registry import JobContext, JobResult, register

DUMP_PATTERN = re.compile(r"^dash_\d{8}_\d{4}\.dump$")
TMP_PATTERN = re.compile(r"^dash_\d{8}_\d{4}\.dump\.tmp$")
TIMEOUT_S = 3 * 60 * 60


class BackupError(RuntimeError):
    """pg_dump missing or failed; the message is pt-BR for the status page."""


def find_pg_dump(pg_bin_dir: str) -> str:
    """Path of pg_dump: PG_BIN_DIR when set (pg_dump.exe on Windows), else PATH."""
    if pg_bin_dir.strip():
        found = shutil.which("pg_dump", path=pg_bin_dir.strip())
        if found:
            return found
        raise BackupError(f"pg_dump não encontrado em PG_BIN_DIR ({pg_bin_dir}). "
                          "Confira a pasta bin do PostgreSQL no .env.")
    found = shutil.which("pg_dump")
    if found:
        return found
    raise BackupError("pg_dump não encontrado no PATH. Defina PG_BIN_DIR no .env com a pasta bin do PostgreSQL.")


def dump_command(pg_dump: str, database_url: str, target: Path) -> tuple[list[str], dict[str, str]]:
    """Command line and environment for pg_dump; the password travels only in PGPASSWORD."""
    params = {k: v for k, v in conninfo_to_dict(database_url).items() if v is not None}
    password = params.pop("password", None)
    env = dict(os.environ)
    if password:
        env["PGPASSWORD"] = str(password)
    cmd = [pg_dump, "--format=custom", "--no-password", f"--file={target}", f"--dbname={make_conninfo(**params)}"]
    return cmd, env


def prune(backup_dir: Path, keep: int) -> list[Path]:
    """Delete all but the newest `keep` dash_<yyyymmdd_hhmm>.dump files; returns the deleted paths."""
    dumps = sorted(p for p in backup_dir.iterdir() if p.is_file() and DUMP_PATTERN.match(p.name))
    old = dumps[:-keep] if keep > 0 else []
    for path in old:
        path.unlink()
    return old


def remove_stale_tmp(backup_dir: Path, max_age_s: float = TIMEOUT_S) -> list[Path]:
    """Delete dash_<stamp>.dump.tmp files older than max_age_s (no pg_dump can still be writing them)."""
    cutoff = time.time() - max_age_s
    removed = []
    for path in backup_dir.iterdir():
        try:
            if path.is_file() and TMP_PATTERN.match(path.name) and path.stat().st_mtime < cutoff:
                path.unlink()
                removed.append(path)
        except OSError:
            continue
    return removed


def run_backup(database_url: str, backup_dir: Path, pg_bin_dir: str = "", keep: int = 14,
               now: datetime | None = None) -> tuple[Path, list[Path]]:
    """Dump the database to backup_dir/dash_<yyyymmdd_hhmm>.dump; returns (file, deleted old files)."""
    pg_dump = find_pg_dump(pg_bin_dir)
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    remove_stale_tmp(backup_dir)
    stamp = (now or datetime.now(TZ)).strftime("%Y%m%d_%H%M")
    target = backup_dir / f"dash_{stamp}.dump"
    tmp = target.with_name(target.name + ".tmp")
    cmd, env = dump_command(pg_dump, database_url, tmp)
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, timeout=TIMEOUT_S, check=False,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as exc:
        tmp.unlink(missing_ok=True)
        raise BackupError(f"pg_dump não terminou em {TIMEOUT_S // 60} min") from exc
    except OSError as exc:  # e.g. blocked by App Control on Windows
        tmp.unlink(missing_ok=True)
        raise BackupError(f"não foi possível executar o pg_dump ({pg_dump}): {exc}") from exc
    if proc.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        detail = proc.stderr.decode("utf-8", "replace").strip()[-1500:]
        raise BackupError(f"pg_dump falhou (código {proc.returncode}): {detail or 'sem mensagem'}")
    os.replace(tmp, target)
    return target, prune(backup_dir, keep)


@register("db_backup")
def run(ctx: JobContext) -> JobResult:
    s = ctx.settings
    ctx.check_cancelled()
    ctx.progress(None, "Gerando backup do banco de dados")
    target, deleted = run_backup(s.database_url, Path(s.backup_dir), s.pg_bin_dir, s.backup_keep)
    size = fmt_number(target.stat().st_size / 1_000_000, 1) + " MB"
    ctx.log(f"Backup salvo em {target} ({size})")
    for path in deleted:
        ctx.log(f"Backup antigo removido: {path.name}")
    message = f"Backup {target.name} ({size})"
    if deleted:
        message += f"; {len(deleted)} antigo(s) removido(s)"
    ctx.progress(1.0, message)
    return JobResult(rows_changed=0, sources=(), message=message)
