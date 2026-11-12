"""Polite downloader with a content-addressed raw file cache (design 4.1).

Every stored file lives at RAW_DATA_DIR/<sha[:2]>/<sha> and has a raw_files
row (sha256 unique). Requests to one host are spaced by HTTP_MIN_INTERVAL_S;
5xx (incl. Cloudflare 520-524), 429, timeouts and connection errors are
retried with backoff 2, 4, 8, 16 s; 404/410 raise NotFound at once. A JSON
request answered 200 with an empty body is retried the same way.

Files that can carry personal data (FNET notices, the CVM informe anual zip)
are fetched into memory with fetch_bytes, cleaned by their loader and only
then written with store_bytes (raw_files.sanitizer names the cleaner).
"""
import hashlib
import logging
import os
import ssl
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
import psycopg

from app.core.config import Settings, get_settings

log = logging.getLogger("dash.http")

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 520, 521, 522, 523, 524})
NOT_FOUND_STATUSES = frozenset({404, 410})
MAX_RETRY_AFTER_S = 120.0
_CHUNK = 1 << 16


class NotFound(Exception):
    """HTTP 404/410: the resource does not exist (not retried). `body` holds the start of the response text."""

    def __init__(self, url: str, status: int, body: str = ""):
        super().__init__(f"HTTP {status} for {url}")
        self.url = url
        self.status = status
        self.body = body


class TransientResponse(Exception):
    """Raised by a response handler for a 2xx answer that should be retried like a 5xx
    (e.g. BCB SGS sometimes answers 200 with an empty body, phase1_checks.md D)."""


class FetchError(Exception):
    """Retries exhausted, or a non-retryable HTTP error."""

    def __init__(self, message: str, url: str, status: int | None = None):
        super().__init__(message)
        self.url = url
        self.status = status


@dataclass(frozen=True)
class RawFile:
    id: int | None              # raw_files.id (None when store=False)
    path: Path                  # cached file
    sha256: str
    bytes: int
    url: str
    not_modified: bool          # True: server answered 304, this is the earlier copy
    status: int
    content_type: str | None = None


@dataclass(frozen=True)
class FetchedBytes:
    """A response held in memory by Downloader.fetch_bytes (nothing written to the cache)."""
    content: bytes
    url: str
    status: int                 # 2xx, or 304 (content is then the cached copy of `previous`)
    etag: str | None
    last_modified: str | None
    content_type: str | None
    previous: RawFile | None = None

    @property
    def not_modified(self) -> bool:
        return self.status == 304


class RateLimiter:
    """At most one request per host every `min_interval` seconds (thread-safe)."""

    def __init__(self, min_interval: float, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> float:
        """Block until `host` may be called; returns the seconds waited."""
        with self._lock:
            now = self._clock()
            slot = max(now, self._next.get(host, now))
            self._next[host] = slot + self.min_interval
        delay = slot - now
        if delay > 0:
            self._sleep(delay)
        return delay


_shared_limiters: dict[float, RateLimiter] = {}
_shared_lock = threading.Lock()


def _shared_limiter(min_interval: float) -> RateLimiter:
    with _shared_lock:
        if min_interval not in _shared_limiters:
            _shared_limiters[min_interval] = RateLimiter(min_interval)
        return _shared_limiters[min_interval]


def cache_path(raw_dir: Path, sha256: str) -> Path:
    return Path(raw_dir) / sha256[:2] / sha256


def cleanup_partial_downloads(raw_dir: Path, max_age_s: float = 3600.0) -> int:
    """Delete raw_dir/tmp/*.part files older than max_age_s; returns how many were removed.

    A forced stop (Stop-Process -Force, shutdown) skips the except/unlink in
    _stream_to_cache, so a killed download leaves its .part file behind. Call
    this when no download can be in flight (worker start).
    """
    tmp_dir = Path(raw_dir) / "tmp"
    if not tmp_dir.is_dir():
        return 0
    cutoff = time.time() - max_age_s
    removed = 0
    for part in tmp_dir.glob("*.part"):
        try:
            if part.is_file() and part.stat().st_mtime < cutoff:
                part.unlink()
                removed += 1
        except OSError as exc:
            log.warning("could not remove partial download %s: %s", part, exc)
    if removed:
        log.info("removed %d partial download(s) left in %s", removed, tmp_dir)
    return removed


def _default_client(settings: Settings) -> httpx.Client:
    # The default SSL context uses the OS trust store on Windows, so a
    # corporate TLS proxy keeps working. Never disable verification.
    return httpx.Client(
        verify=ssl.create_default_context(),
        trust_env=True,
        follow_redirects=True,
        headers={"User-Agent": settings.user_agent},
    )


class Downloader:
    def __init__(
        self,
        settings: Settings | None = None,
        conn_factory: Callable[[], psycopg.Connection] | None = None,
        client: httpx.Client | None = None,
        *,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ):
        """`sleep`/`clock` are for tests: when given, backoff and rate limiting use them."""
        self.settings = settings or get_settings()
        self._conn_factory = conn_factory or (lambda: psycopg.connect(self.settings.database_url, connect_timeout=10))
        self._own_client = client is None
        self.client = client or _default_client(self.settings)
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._extra_limiters: dict[float, RateLimiter] = {}
        if sleep or clock:
            self.limiter = RateLimiter(self.settings.http_min_interval_s, self._sleep, clock or time.monotonic)
        else:
            self.limiter = _shared_limiter(self.settings.http_min_interval_s)
        self.raw_dir = Path(self.settings.raw_data_dir)

    def close(self) -> None:
        if self._own_client:
            self.client.close()

    def __enter__(self) -> "Downloader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- public API ---------------------------------------------------------

    def fetch(self, url: str, *, source_id: str, params: dict | None = None, headers: dict | None = None,
              timeout: float = 90.0, retries: int = 4, conditional: bool = True, store: bool = True) -> RawFile:
        """Download `url` into the cache; with store=True also upsert raw_files.

        conditional=True sends If-None-Match / If-Modified-Since from the
        latest raw_files row for the same URL; a 304 returns that row with
        not_modified=True.
        """
        req_headers = dict(headers or {})
        previous = self._latest_row(url) if (conditional and store) else None
        if previous:
            if previous["http_etag"]:
                req_headers["If-None-Match"] = previous["http_etag"]
            if previous["http_last_modified"]:
                req_headers["If-Modified-Since"] = previous["http_last_modified"]

        def handle(resp: httpx.Response) -> RawFile:
            if resp.status_code == 304:
                if not previous:
                    raise FetchError(f"HTTP 304 without a cached copy for {url}", url, 304)
                return RawFile(previous["id"], cache_path(self.raw_dir, previous["sha256"]), previous["sha256"],
                               previous["bytes"], url, True, 304, previous["content_type"])
            sha, size, path = self._stream_to_cache(resp)
            ctype = resp.headers.get("content-type")
            raw_id = None
            if store:
                raw_id = self._upsert_raw(source_id, url, sha, size, resp.headers.get("etag"),
                                          resp.headers.get("last-modified"), ctype)
            return RawFile(raw_id, path, sha, size, url, False, resp.status_code, ctype)

        return self._request(url, params=params, headers=req_headers, timeout=timeout, retries=retries,
                             stream=True, handle=handle)

    def fetch_bytes(self, url: str, *, source_id: str, params: dict | None = None, headers: dict | None = None,
                    timeout: float = 90.0, retries: int = 4, conditional: bool = True,
                    min_interval: float | None = None) -> FetchedBytes:
        """GET `url` into memory; nothing is written (no cache file, no raw_files row).

        Same rate limit, retries and conditional headers as fetch(). On a 304
        the content is the cached file of the latest raw_files row for the URL
        (already cleaned when it was stored with store_bytes). `source_id` is
        used for logging only. `min_interval` spaces these requests (per host)
        on top of the general per-host limit, e.g. FundosNET downloads.
        """
        req_headers = dict(headers or {})
        previous = self._latest_row(url) if conditional else None
        if previous:
            if previous["http_etag"]:
                req_headers["If-None-Match"] = previous["http_etag"]
            if previous["http_last_modified"]:
                req_headers["If-Modified-Since"] = previous["http_last_modified"]

        def handle(resp: httpx.Response) -> FetchedBytes:
            if resp.status_code == 304:
                if not previous:
                    raise FetchError(f"HTTP 304 without a cached copy for {url} ({source_id})", url, 304)
                path = cache_path(self.raw_dir, previous["sha256"])
                cached = RawFile(previous["id"], path, previous["sha256"], previous["bytes"], url, True, 304,
                                 previous["content_type"])
                return FetchedBytes(path.read_bytes(), url, 304, previous["http_etag"],
                                    previous["http_last_modified"], previous["content_type"], cached)
            return FetchedBytes(resp.read(), url, resp.status_code, resp.headers.get("etag"),
                                resp.headers.get("last-modified"), resp.headers.get("content-type"))

        return self._request(url, params=params, headers=req_headers, timeout=timeout, retries=retries,
                             stream=True, handle=handle, min_interval=min_interval)

    def store_bytes(self, data: bytes, *, source_id: str, url: str, content_type: str | None = None,
                    etag: str | None = None, last_modified: str | None = None, sanitizer: str | None = None,
                    status: int = 200) -> RawFile:
        """Write `data` to the cache (atomically) and upsert its raw_files row.

        Used for content cleaned in memory: `sanitizer` records what removed the
        personal data; etag/last_modified are the original response's, so the
        next conditional GET still gets a 304.
        """
        sha = hashlib.sha256(data).hexdigest()
        final = cache_path(self.raw_dir, sha)
        if not (final.is_file() and final.stat().st_size == len(data)):
            tmp_dir = self.raw_dir / "tmp"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=tmp_dir, suffix=".part")
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                final.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp, final)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
        raw_id = self._upsert_raw(source_id, url, sha, len(data), etag, last_modified, content_type, sanitizer)
        return RawFile(raw_id, final, sha, len(data), url, status == 304, status, content_type)

    def fetch_json(self, url: str, *, source_id: str, params: dict | None = None, headers: dict | None = None,
                   timeout: float = 90.0, retries: int = 4) -> Any:
        """GET and parse JSON; nothing is stored. `source_id` is used for logging only.

        The body is parsed whatever the Content-Type (B3 serves JSON as
        text/plain). A 2xx with an empty body, or with a body that is not JSON
        (BCB SGS 12 on 07/10/2026), is retried like a 5xx; the final error
        quotes the start of the body.
        """
        req_headers = {"Accept": "application/json", **(headers or {})}

        def handle(resp: httpx.Response) -> Any:
            resp.read()
            if not resp.content.strip():
                raise TransientResponse(f"HTTP {resp.status_code} com corpo vazio")
            try:
                return resp.json()
            except ValueError as exc:
                start = resp.content[:160].decode("utf-8", "replace")
                raise TransientResponse(f"HTTP {resp.status_code} com JSON inválido ({exc}); início: {start!r}") from exc

        return self._request(url, params=params, headers=req_headers, timeout=timeout, retries=retries,
                             stream=True, handle=handle)

    # -- internals ----------------------------------------------------------

    def _extra_limiter(self, interval: float) -> RateLimiter:
        limiter = self._extra_limiters.get(interval)
        if limiter is None:
            limiter = self._extra_limiters[interval] = RateLimiter(interval, self._sleep, self._clock)
        return limiter

    def _request(self, url, *, params, headers, timeout, retries, stream, handle, min_interval=None):
        host = urlsplit(url).hostname or ""
        attempts = retries + 1
        last_problem = ""
        last_status = None
        for attempt in range(attempts):
            self.limiter.wait(host)
            if min_interval:   # after the host limit, so the gap to the previous such request is >= min_interval
                self._extra_limiter(min_interval).wait(host)
            retry_after = None
            try:
                with self.client.stream("GET", url, params=params, headers=headers, timeout=timeout) as resp:
                    status = resp.status_code
                    if status in NOT_FOUND_STATUSES:
                        try:
                            body = resp.read()[:2000].decode("utf-8", "replace")
                        except httpx.HTTPError:
                            body = ""
                        raise NotFound(str(resp.url), status, body)
                    if status in RETRY_STATUSES:
                        last_problem, last_status = f"HTTP {status}", status
                        retry_after = _retry_after(resp.headers.get("retry-after"))
                    elif status == 304 or 200 <= status < 300:
                        try:
                            return handle(resp)
                        except TransientResponse as exc:
                            last_problem, last_status = str(exc), status
                    else:
                        raise FetchError(f"HTTP {status} for {url}", url, status)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_problem, last_status = f"{type(exc).__name__}: {exc}", None
            if attempt + 1 < attempts:
                delay = max(float(2 ** (attempt + 1)), retry_after or 0.0)
                log.info("%s on %s (attempt %d/%d); retrying in %.0f s", last_problem, url, attempt + 1, attempts, delay)
                self._sleep(delay)
        raise FetchError(f"{last_problem} after {attempts} attempts: {url}", url, last_status)

    def _stream_to_cache(self, resp: httpx.Response) -> tuple[str, int, Path]:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = self.raw_dir / "tmp"
        tmp_dir.mkdir(exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        fd, tmp_name = tempfile.mkstemp(dir=tmp_dir, suffix=".part")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fh:
                for chunk in resp.iter_bytes(_CHUNK):
                    digest.update(chunk)
                    size += len(chunk)
                    fh.write(chunk)
            sha = digest.hexdigest()
            final = cache_path(self.raw_dir, sha)
            final.parent.mkdir(parents=True, exist_ok=True)
            if final.exists() and final.stat().st_size == size:
                tmp.unlink()
            else:
                os.replace(tmp, final)
            return sha, size, final
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _latest_row(self, url: str) -> dict | None:
        with self._conn_factory() as conn:
            row = conn.execute(
                """SELECT id, sha256, bytes, http_etag, http_last_modified, content_type
                   FROM raw_files WHERE url = %s ORDER BY fetched_at DESC, id DESC LIMIT 1""",
                (url,),
            ).fetchone()
        if not row:
            return None
        rec = dict(zip(("id", "sha256", "bytes", "http_etag", "http_last_modified", "content_type"), row))
        rec["sha256"] = rec["sha256"].strip()
        if not cache_path(self.raw_dir, rec["sha256"]).is_file():
            return None  # cache moved or cleaned: download again
        return rec

    def _upsert_raw(self, source_id, url, sha, size, etag, last_modified, ctype, sanitizer=None) -> int:
        with self._conn_factory() as conn:
            return conn.execute(
                """INSERT INTO raw_files (source_id, url, sha256, bytes, http_etag, http_last_modified, content_type,
                                          sanitizer)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (sha256) DO UPDATE SET
                       url = EXCLUDED.url, fetched_at = now(), http_etag = EXCLUDED.http_etag,
                       http_last_modified = EXCLUDED.http_last_modified, content_type = EXCLUDED.content_type,
                       sanitizer = COALESCE(EXCLUDED.sanitizer, raw_files.sanitizer)
                   RETURNING id""",
                (source_id, url, sha, size, etag, last_modified, ctype, sanitizer),
            ).fetchone()[0]


# Columns that point at raw_files (nulled before a raw file is deleted).
RAW_FILE_REFERENCES: tuple[tuple[str, str], ...] = (("fidc_mensal", "raw_file_id"),)


def delete_raw_file(conn: psycopg.Connection, raw_dir: Path, raw_id: int, sha256: str) -> None:
    """Remove one cached file and its raw_files row (raw_file_loads cascade; references nulled).

    The file is unlinked right away; if the transaction then rolls back, the
    row points at a missing file, which the Downloader treats as "download again".
    """
    for table, column in RAW_FILE_REFERENCES:
        conn.execute(f"UPDATE {table} SET {column} = NULL WHERE {column} = %s", (raw_id,))
    conn.execute("DELETE FROM raw_files WHERE id = %s", (raw_id,))
    try:
        cache_path(raw_dir, sha256.strip()).unlink(missing_ok=True)
    except OSError as exc:
        log.warning("could not delete cached file %s: %s", sha256, exc)


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return min(float(value), MAX_RETRY_AFTER_S)
    except ValueError:
        return None
