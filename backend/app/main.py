"""Dash FIDCs FastAPI entry point (from Dash Fundos): API under /api, built frontend served at / (SPA fallback)."""
import hashlib
import hmac
import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.jobs import all_jobs  # noqa: F401  (registers the job functions)
from app.api import fidcs, jobs, status
from app.core import db
from app.core.config import get_settings
from app.jobs import runner

log = logging.getLogger("dash")
PASSCODE_COOKIE = "dash_fidcs_passcode"


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        report = db.run_migrations()
        if report.changed:
            log.warning("database migrations held back: applied files changed %s", report.changed)
    except Exception:  # the status page reports DB problems; do not crash the UI
        log.exception("database migrations failed")
    # The worker runs even with SCHEDULER_ENABLED=false (that flag only turns off the 30-minute scheduler), so
    # "Atualizar agora" works. JOB_WORKER_ENABLED=false (tests) keeps the worker off too.
    worker = None
    settings = get_settings()
    if settings.job_worker_enabled:
        try:
            worker = runner.get_runner()
            worker.start(scheduler=settings.scheduler_enabled)
        except Exception:
            log.exception("job runner did not start")
    try:
        yield
    finally:
        if worker is not None:
            worker.shutdown()
            runner.shutdown()
        db.close_pools()


app = FastAPI(title="Dash FIDCs", lifespan=lifespan)


@app.exception_handler(psycopg.OperationalError)
async def database_unavailable(_: Request, exc: psycopg.OperationalError):
    # Includes pool timeouts (psycopg_pool.PoolTimeout); /api/status answers on its own.
    log.warning("database unavailable: %s", exc)
    return JSONResponse({"detail": "Banco de dados indisponível. Verifique se o PostgreSQL está rodando."},
                        status_code=503)


def session_token(passcode: str) -> str:
    """Cookie value for a passcode: ASCII, so it compares safely, and the passcode itself is not stored."""
    return hmac.new(passcode.encode("utf-8"), b"dash-fidcs-session", hashlib.sha256).hexdigest()


def _same(given: bytes, expected: bytes) -> bool:
    return hmac.compare_digest(given, expected)


def _authorized(request: Request, passcode: str) -> bool:
    """Cookie with the session token, or an x-passcode header with the token or the passcode itself."""
    token = session_token(passcode).encode("ascii")
    cookie = request.cookies.get(PASSCODE_COOKIE)
    if cookie is not None and _same(cookie.encode("utf-8", "replace"), token):
        return True
    header = request.headers.get("x-passcode")
    if header is None:
        return False
    raw = header.encode("latin-1", "replace")      # Starlette decodes header bytes as latin-1
    return _same(raw, token) or _same(raw, passcode.encode("utf-8"))


# Compressed answers: the app's scripts (≈1 MB) and the larger JSON lists travel 3 to 10 times smaller, which is
# what the computers on the LAN feel most (03/11/2026).
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)


@app.middleware("http")
async def passcode_guard(request: Request, call_next):
    passcode = get_settings().app_passcode
    open_paths = ("/api/health", "/api/login")
    if passcode and request.url.path.startswith("/api") and request.url.path not in open_paths:
        if not _authorized(request, passcode):
            return JSONResponse({"detail": "passcode required"}, status_code=401)
    return await call_next(request)


@app.get("/api/health")
def health():
    db_ok = True
    try:
        with db.connect(connect_timeout=5) as conn:
            conn.execute("SELECT 1")
    except Exception:
        db_ok = False
    return {"status": "ok", "db": db_ok, "passcode_enabled": bool(get_settings().app_passcode)}


class LoginIn(BaseModel):
    passcode: str = Field("", max_length=200)


@app.post("/api/login")
def login(body: LoginIn):
    passcode = get_settings().app_passcode
    if not passcode:
        return JSONResponse({"ok": True})
    if _same(body.passcode.encode("utf-8"), passcode.encode("utf-8")):
        resp = JSONResponse({"ok": True})
        resp.set_cookie(PASSCODE_COOKIE, session_token(passcode), httponly=True, samesite="lax",
                        max_age=60 * 60 * 24 * 30)
        return resp
    return JSONResponse({"ok": False}, status_code=401)


for module in (fidcs, status, jobs):
    app.include_router(module.router, prefix="/api")


# Windows takes MIME types from the registry, where .js can be text/plain (browsers then refuse the app's
# module scripts) and .woff2 may be missing. Pin the types the built frontend uses.
for _ext, _type in ((".js", "text/javascript"), (".mjs", "text/javascript"), (".css", "text/css"),
                    (".svg", "image/svg+xml"), (".json", "application/json"), (".woff2", "font/woff2"),
                    (".woff", "font/woff")):
    mimetypes.add_type(_type, _ext)


class SPAStaticFiles(StaticFiles):
    """Static files; unknown non-/api paths get index.html so deep links (/fidcs/<cnpj>) work."""

    async def get_response(self, path: str, scope):
        # Starlette hands over an OS path: "api\\nope" on Windows, "api/nope" elsewhere.
        path = path.replace("\\", "/")
        if path == "api" or path.startswith("api/"):
            raise StarletteHTTPException(status_code=404)
        try:
            resp = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            resp = None
        if resp is None or resp.status_code == 404:
            if "." in path.rsplit("/", 1)[-1]:  # a missing asset stays a 404
                raise StarletteHTTPException(status_code=404)
            resp = await super().get_response("index.html", scope)
        if path in ("", ".", "index.html") or resp.media_type == "text/html":
            resp.headers["Cache-Control"] = "no-cache"
        elif path.startswith("assets/") and resp.status_code == 200:
            # Vite names every built file after its content (index-B7yzcoZ1.js): a new build has new names, so the
            # browser keeps these for good and asks only for index.html (no-cache) again.
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


static_dir = Path(get_settings().static_dir)
if (static_dir / "index.html").is_file():
    app.mount("/", SPAStaticFiles(directory=static_dir, html=True), name="static")
else:
    log.warning("no built frontend at %s; serving the API only", static_dir)
