"""Runtime configuration, read from environment variables and the repo-root .env."""
import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repo root. In the Docker image (code under
# /app) this resolves to "/", where compose passes settings as env vars.
REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _env_file() -> Path | None:
    """The .env to read: DASH_ENV_FILE if set ('' disables it, used by tests), else <repo>/.env."""
    override = os.environ.get("DASH_ENV_FILE")
    if override is not None:
        return Path(override) if override else None
    return REPO_ROOT / ".env"


def _default_static_dir() -> Path:
    # Repo checkout: the built SPA. Docker image: copied to /app/static.
    dist = REPO_ROOT / "frontend" / "dist"
    docker = BACKEND_DIR / "static"
    return docker if not dist.is_dir() and docker.is_dir() else dist


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_env_file(), env_file_encoding="utf-8", extra="ignore")

    # Docker default; the native start script writes its own (127.0.0.1:5433).
    database_url: str = "postgresql://dash:dash@127.0.0.1:5434/dashfidcs"
    app_host: str = "0.0.0.0"
    app_port: int = 8081
    # Optional shared passcode. Empty means no passcode (default).
    app_passcode: str = ""
    anthropic_api_key: str = ""
    llm_monthly_budget_usd: float = 20.0
    raw_data_dir: Path = REPO_ROOT / "data" / "raw"
    static_dir: Path = _default_static_dir()
    user_agent: str = "DashFIDCs/0.1 (uso interno AVIN; contato: equipe de credito)"
    # Minimum seconds between requests to the same host.
    http_min_interval_s: float = 1.0
    # Minimum seconds between FundosNET downloads (downloadDocumento): they
    # stall for our client while the search keeps answering (phase1_checks.md F).
    fnet_download_interval_s: float = 5.0

    backup_dir: Path = REPO_ROOT / "backups"
    backup_keep: int = 14
    # Directory holding pg_dump; empty = found on PATH.
    pg_bin_dir: str = ""
    # The 30-minute APScheduler tick; tests set false. The job worker runs regardless.
    scheduler_enabled: bool = True
    # The job worker thread ("Atualizar agora" and the scheduler need it); tests set false.
    job_worker_enabled: bool = True

    # Informe mensal FIDC: months read back (one zip per month; the newest months are re-checked every day).
    fidc_history_months: int = 24
    fidc_refresh_months: int = 3
    cvm_start_year: int = 2016
    # B3 loads (COTAHIST prices and the 12-month proventos page). Off since 14/10/2026: the DCM team does not use
    # prices, DY or P/VP. Data already loaded stays; B3_ENABLED=true in .env turns the loads back on.
    b3_enabled: bool = False
    price_start_year: int = 2019
    dist_history_months: int = 36
    # Relatórios gerenciais (Phase 2): months read back per fund, and downloads per run (about 5 s each,
    # so a run stays under an hour; the backlog continues on the next run).
    relatorios_history_months: int = 12
    relatorios_max_downloads: int = 600

    # Geocoding (Phase 3): street addresses sent to Nominatim per run (1 request/s, every answer cached; 0 = city
    # level only) and an optional contact e-mail its usage policy asks for (sent as `email=`, never stored).
    nominatim_max_requests: int = 300
    nominatim_email: str = ""
    # Receita Federal CNPJ register (BrasilAPI, minhareceita.org as fallback): CNPJs asked per run, 1 request/s;
    # every answer is cached, so the first runs fill the backlog and later ones only ask for new CNPJs.
    cnpj_max_requests: int = 1500

    # Category thresholds on the share of PL (design section 5).
    category_papel_min: float = 0.6667
    category_hibrido_min: float = 0.20
    # Crédito privado list (app/ingest/credito_privado.py): smallest PL, in R$, of a class the list takes. No floor
    # since 29/10/2026 (team: as many funds as possible; the list keeps those holding a debênture).
    credito_privado_min_pl: float = 0.0

    @field_validator("raw_data_dir", "static_dir", "backup_dir", mode="before")
    @classmethod
    def _empty_path_is_default(cls, value, info):
        # 'RAW_DATA_DIR=' in .env means "use the default", not the current directory.
        if value is None or (isinstance(value, str) and not value.strip()):
            return cls.model_fields[info.field_name].default
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=_env_file())
