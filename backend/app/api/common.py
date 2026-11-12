"""Helpers shared by the /api routers: DB access, JSON conversion, fund lookup, provenance."""
import math
import re
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Iterator
from zoneinfo import ZoneInfo

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row

from app.core.db import get_pool
from app.core.provenance import prov, source_label

# Sources added after app.core.provenance.SOURCE_LABELS was written (same text as sources.label_pt);
# used only when that map does not know the id yet.
EXTRA_SOURCE_LABELS: dict[str, str] = {
    "b3_proventos": "B3 – Proventos (fundos listados)",
}

TZ_BR = ZoneInfo("America/Sao_Paulo")
TICKER_RE = re.compile(r"^[A-Za-z0-9]{4,12}$")
CNPJ_CHARS_RE = re.compile(r"^[\d./\-\s]+$")


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    """Pooled connection for a request (committed on exit)."""
    with get_pool().connection() as conn:
        yield conn


def fetch_all(conn: psycopg.Connection, sql: str, params: Any = None) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_one(conn: psycopg.Connection, sql: str, params: Any = None) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def num(value: Any) -> float | int | None:
    """Decimal/number -> JSON number; NaN and infinities -> None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    f = float(value)
    return f if math.isfinite(f) else None


def clean(value: Any) -> Any:
    """Recursively convert DB values to JSON-ready ones (Decimal -> float, dates -> ISO)."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (Decimal, float)):
        return num(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


STALE_EDIT = ("Outra pessoa alterou isto {quando}{quem}. Recarregue a página antes de salvar; "
              "suas mudanças não foram gravadas.")


def assert_unchanged(conn: psycopg.Connection, table: str, row_id: Any, expected: datetime | None,
                     *, stamp: str = "coalesce(updated_at, created_at)", by: str | None = None,
                     what: str = "Registro") -> None:
    """Optimistic lock for team edits: refuse (409) a save made from a form loaded before someone else's save.

    `expected` is the row's updated_at (or created_at) as the client loaded it; None skips the check (older
    clients). The row is locked until the request's transaction ends, so two saves cannot interleave.
    `table`, `stamp` and `by` are code constants, never request text.
    """
    who = f", {by}" if by else ""
    row = conn.execute(f"SELECT {stamp}{who} FROM {table} WHERE id = %s FOR UPDATE", (row_id,)).fetchone()
    if row is None:
        raise HTTPException(404, detail=f"{what} não encontrado")
    if expected is None or row[0] is None or row[0] == expected:
        return
    when = row[0].astimezone(TZ_BR)
    name = row[1] if by and len(row) > 1 and row[1] else None
    raise HTTPException(409, detail=STALE_EDIT.format(quando=f"às {when:%H:%M} de {when:%d/%m}",
                                                      quem=f" ({name})" if name else ""))


def digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def format_cnpj(cnpj: str | None) -> str | None:
    d = digits(cnpj or "")
    if len(d) != 14:
        return cnpj
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def fund_url(ticker: str | None, cnpj: str) -> str:
    """SPA route of the fund page."""
    return f"/fundos/{ticker or cnpj.strip()}"


def resolve_fund(conn: psycopg.Connection, ident: str) -> dict[str, Any]:
    """funds row for a ticker (any case; a former ticker too) or a CNPJ (digits or formatted); 404 otherwise."""
    text = (ident or "").strip()
    row = None
    if CNPJ_CHARS_RE.match(text) and len(digits(text)) == 14:
        row = fetch_one(conn, "SELECT * FROM funds WHERE cnpj = %s", (digits(text),))
    elif TICKER_RE.match(text):
        row = fetch_one(conn, "SELECT * FROM funds WHERE upper(ticker) = %s", (text.upper(),))
        if row is None:                  # a ticker the fund traded under before (CVBI11 -> PCIP11)
            row = fetch_one(conn, """SELECT f.* FROM fund_listings l JOIN funds f ON f.cnpj = l.cnpj
                                     WHERE upper(l.ticker) = %s ORDER BY l.last_trade DESC LIMIT 1""",
                            (text.upper(),))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Fundo não encontrado: {text or '(vazio)'}")
    return row


def make_prov(raw: Any, source: str, ref: Any = None, ref_kind: str = "date",
              url: str | None = None, note: str | None = None) -> dict[str, Any]:
    """Provenance dict: the stored one (fund_metrics.provenance[col]) when present, else the defaults.

    The label always comes from app.core.provenance (label_for) so it matches the sources table.
    """
    if isinstance(raw, dict) and raw.get("source"):
        out = prov(
            str(raw["source"]),
            raw.get("ref") if raw.get("ref") is not None else ref,
            ref_kind=str(raw.get("ref_kind") or ref_kind),
            url=raw.get("url") or url,
            note=raw.get("note") if "note" in raw else note,
        )
    else:
        out = prov(source, ref, ref_kind=ref_kind, url=url, note=note)
    out["label"] = label_for(out["source"])
    return out


def label_for(source_id: str) -> str:
    """pt-BR label of a source id (app.core.provenance, then EXTRA_SOURCE_LABELS)."""
    label = source_label(source_id)
    return EXTRA_SOURCE_LABELS.get(source_id, label) if label == source_id else label


# pt-BR names of data-quality issue kinds (same texts as frontend/src/lib/meta.ts ISSUE_LABELS); the fund
# page's gaps list shows these, never the raw kind code.
ISSUE_LABELS: dict[str, str] = {
    "possible_split": "Possível desdobramento/grupamento",
    "ticker_conflict": "Conflito de ticker",
    "ticker_change": "Mudança de ticker",
    "cotahist_annual_missing": "Arquivo anual COTAHIST ausente",
    "cotahist_bad_file": "Arquivo COTAHIST ilegível",
    "cotahist_invalid": "Arquivo COTAHIST inconsistente",
    "cotahist_quote_factor": "Fator de cotação diferente de 1",
    "fnet_listing_failed": "Falha na listagem do FundosNET",
    "fnet_negative_value": "Valor negativo em aviso",
    "fnet_notice_failed": "Aviso de rendimentos ilegível",
    "fnet_notice_inactive": "Aviso de rendimentos inativo",
    "fnet_unknown_element": "Elemento desconhecido no aviso",
    "macro_bad_rows": "Linhas inválidas em série macro",
    "macro_series_failed": "Falha em série macro",
    "missing_file": "Arquivo ausente",
    "tesouro_bad_lines": "Linhas inválidas no Tesouro Direto",
    "tesouro_failed": "Falha no Tesouro Direto",
    "unexpected_format": "Formato inesperado",
    "missing_value": "Valor ausente",
    "value_out_of_range": "Valor fora do intervalo esperado",
    "isin_conflict": "Conflito de ISIN",
    "pl_non_positive": "PL zero ou negativo",
    "b3_label_unknown": "Tipo de provento da B3 não reconhecido",
    "b3_proventos_conflict": "Proventos conflitantes na B3",
    "b3_proventos_failed": "Falha nos proventos da B3",
    "b3_proventos_absent": "Fundo sem proventos na B3",
    "relatorio_review": "Relatório gerencial para revisão",
    "relatorio_failed": "Relatório gerencial não lido",
    "cri_taxa_unparsed": "Taxas de CRI não interpretadas",
    "cra_taxa_unparsed": "Taxas de CRA não interpretadas",
    "distribution_mismatch": "Provento diferente entre FundosNET e B3",
    "fnet_downloads_unavailable": "Downloads do FundosNET indisponíveis",
    "metrics_failed": "Falha no cálculo das métricas",
    "metric_out_of_range": "Métrica fora do intervalo esperado",
    "dy_outlier": "DY mensal atípico",
    "personal_data_member": "Arquivo com dados pessoais no download (não lido)",
    "personal_data_dropped": "Colunas com dados pessoais não gravadas",
    "geocoding_ambiguous_city": "Cidade ambígua no texto de um ativo",
    "geocoding_deal_city": "Cidade do deal não encontrada",
    "geocoding_nominatim_failed": "Falha no OpenStreetMap (Nominatim)",
    "cnpj_registry_failed": "Falha na consulta ao cadastro de CNPJ (Receita Federal)",
}


def issue_label(kind: str) -> str:
    """pt-BR name of an issue kind; an unknown kind gets a generic name rather than its code."""
    return ISSUE_LABELS.get(kind, "Problema não classificado")


def source_ref(source_id: str) -> dict[str, str]:
    return {"source": source_id, "label": label_for(source_id)}


def metrics_function(name: str) -> Callable | None:
    """A function of app.metrics.fund (written by the metrics module), or None if it does not exist."""
    try:
        from app.metrics import fund as metrics_fund
    except Exception:  # noqa: BLE001 - a broken metrics module must not break the API
        return None
    fn = getattr(metrics_fund, name, None)
    return fn if callable(fn) else None
