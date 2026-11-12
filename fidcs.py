"""/api for the FIDC pages: Início, the list (screener), a FIDC's page, gestoras, administradores, cedentes, search.

"Latest month" is the newest competência with at least half as many funds as the month before it (a month CVM is
still filling would otherwise look like the market shrank); each fund shows its own newest month up to that one.
FIC-FIDC = a fund whose carteira is at least half cotas of other FIDCs (Tabela I, itens 2h e 2i); PL sums leave
them out so the same money is not counted twice.
"""
import re
from datetime import date
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException, Query

from app.api.common import clean, connection, digits, fetch_all, fetch_one, format_cnpj
from app.api.fastjson import FastJSONRoute

router = APIRouter(route_class=FastJSONRoute)

FIC_MIN = 0.5


def latest_month(conn: psycopg.Connection) -> date | None:
    rows = conn.execute("""SELECT competencia, count(*) FROM fidc_mensal GROUP BY competencia
                           ORDER BY competencia DESC LIMIT 2""").fetchall()
    if not rows:
        return None
    if len(rows) == 2 and rows[0][1] < rows[1][1] * 0.5:
        return rows[1][0]
    return rows[0][0]


LATEST_SQL = """
WITH ult AS (
  SELECT DISTINCT ON (m.cnpj) m.* FROM fidc_mensal m
  WHERE m.competencia <= %(comp)s AND m.competencia > (%(comp)s::date - interval '6 months')
  ORDER BY m.cnpj, m.competencia DESC)
SELECT f.cnpj, f.nome, f.tipo, f.situacao, f.gestor, f.cnpj_gestor, f.administrador, f.custodiante, f.auditor,
       f.condominio AS condominio_cad, f.exclusivo, f.publico_alvo, f.data_constituicao, f.adaptacao_175,
       f.cnpj_fundo, f.pl_cadastro, f.data_pl_cadastro,
       u.competencia, u.pl, u.ativo, u.carteira, u.dc_com_risco, u.inadimplencia, u.inad_acima_90, u.pdd_sobre_dc,
       u.segmento, u.subsegmento, u.peso_segmento, u.subordinacao, u.cotistas, u.alocador_tipo, u.rentab_senior,
       u.rentab_subordinada, u.captacao, u.resgate, u.amortizacao, u.garantia_pct, u.cotas_fidc_pct,
       u.cedente1_pct, u.cedentes_informados, u.condominio,
       (coalesce(u.cotas_fidc_pct, 0) >= %(fic)s) AS fic,
       p.pl AS pl_12m
FROM fidcs f JOIN ult u ON u.cnpj = f.cnpj
LEFT JOIN fidc_mensal p ON p.cnpj = f.cnpj AND p.competencia = (u.competencia - interval '12 months')::date
"""


def _row(r: dict[str, Any]) -> dict[str, Any]:
    r["cnpj_fmt"] = format_cnpj(r["cnpj"].strip())
    r["cnpj"] = r["cnpj"].strip()
    pl, p12 = r.pop("pl_12m"), r.get("pl")
    r["pl_var_12m"] = (float(p12) / float(pl) - 1) if pl and p12 and float(pl) > 0 else None
    cap, res, amo = r.get("captacao") or 0, r.get("resgate") or 0, r.get("amortizacao") or 0
    r["captacao_liquida"] = float(cap) - float(res) - float(amo)
    r["estrutura"] = "FIC-FIDC" if r.pop("fic") else "FIDC"
    r["condominio"] = r.get("condominio") or r.pop("condominio_cad", None)
    r.pop("condominio_cad", None)
    return r


@router.get("/fidcs")
def fidcs_list():
    with connection() as conn:
        comp = latest_month(conn)
        if comp is None:
            return {"competencia": None, "rows": []}
        rows = fetch_all(conn, LATEST_SQL + " ORDER BY u.pl DESC NULLS LAST", {"comp": comp, "fic": FIC_MIN})
    return clean({"competencia": comp, "rows": [_row(r) for r in rows]})


@router.get("/home")
def home():
    with connection() as conn:
        comp = latest_month(conn)
        if comp is None:
            return {"competencia": None}
        hist = fetch_all(conn, """
            SELECT competencia, count(*) AS fundos,
                   sum(pl) FILTER (WHERE coalesce(cotas_fidc_pct, 0) < %s) AS pl,
                   sum(cotistas) AS cotistas,
                   sum(coalesce(captacao, 0) - coalesce(resgate, 0) - coalesce(amortizacao, 0))
                     FILTER (WHERE coalesce(cotas_fidc_pct, 0) < %s) AS captacao_liquida,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY inadimplencia) AS inad_mediana,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY subordinacao) AS sub_mediana,
                   sum(inadimplente) FILTER (WHERE coalesce(cotas_fidc_pct, 0) < %s)
                     / nullif(sum(coalesce(a_vencer, 0) + coalesce(inadimplente, 0))
                              FILTER (WHERE coalesce(cotas_fidc_pct, 0) < %s), 0) AS inad_agregada
            FROM fidc_mensal WHERE competencia <= %s GROUP BY competencia ORDER BY competencia""",
            (FIC_MIN, FIC_MIN, FIC_MIN, FIC_MIN, comp))
        seg_hist = fetch_all(conn, """
            SELECT competencia, segmento, sum(pl) AS pl, count(*) AS fundos FROM fidc_mensal
            WHERE competencia <= %s AND coalesce(cotas_fidc_pct, 0) < %s AND segmento IS NOT NULL
            GROUP BY competencia, segmento ORDER BY competencia""", (comp, FIC_MIN))
        novos = fetch_all(conn, """
            SELECT f.cnpj, f.nome, f.gestor, f.data_constituicao, m.pl, m.segmento
            FROM fidcs f LEFT JOIN fidc_mensal m ON m.cnpj = f.cnpj AND m.competencia = %s
            WHERE f.data_constituicao IS NOT NULL ORDER BY f.data_constituicao DESC LIMIT 15""", (comp,))
        liquidacao = fetch_all(conn, """
            SELECT f.cnpj, f.nome, f.gestor, f.situacao, f.data_situacao, f.pl_cadastro AS pl
            FROM fidcs f WHERE f.situacao IN ('Em Liquidação', 'Cancelado')
            ORDER BY f.data_situacao DESC NULLS LAST LIMIT 15""")
    for r in novos + liquidacao:
        r["cnpj"] = r["cnpj"].strip()
    return clean({"competencia": comp, "historico": hist, "segmentos_historico": seg_hist,
                  "novos": novos, "liquidacao": liquidacao})


def _cnpj_or_404(ident: str) -> str:
    d = digits(ident)
    if len(d) != 14:
        raise HTTPException(404, detail=f"CNPJ inválido: {ident}")
    return d


@router.get("/fidcs/{ident}")
def fidc(ident: str):
    cnpj = _cnpj_or_404(ident)
    with connection() as conn:
        f = fetch_one(conn, "SELECT * FROM fidcs WHERE cnpj = %s", (cnpj,))
        if f is None:
            raise HTTPException(404, detail=f"FIDC não encontrado: {format_cnpj(cnpj)}")
        hist = fetch_all(conn, """SELECT * FROM fidc_mensal WHERE cnpj = %s ORDER BY competencia""", (cnpj,))
        last = hist[-1]["competencia"] if hist else None
        series = fetch_all(conn, """SELECT classe_serie, tipo, qt_cotas, vl_cota, valor, cotistas, rentab_mes,
                                           desemp_esperado, desemp_real
                                    FROM fidc_series WHERE cnpj = %s AND competencia = %s
                                    ORDER BY CASE tipo WHEN 'Sênior' THEN 0 WHEN 'Mezanino' THEN 1 ELSE 2 END,
                                             valor DESC NULLS LAST""", (cnpj, last)) if last else []
        serie_hist = fetch_all(conn, """SELECT competencia, tipo, sum(valor) AS valor FROM fidc_series
                                        WHERE cnpj = %s GROUP BY competencia, tipo ORDER BY competencia""", (cnpj,))
        cedentes = fetch_all(conn, """
            SELECT c.cnpj_cedente, c.pct, e.nome,
                   (SELECT count(DISTINCT c2.cnpj) FROM fidc_cedentes c2
                    WHERE c2.cnpj_cedente = c.cnpj_cedente AND c2.competencia = c.competencia) AS fidcs
            FROM fidc_cedentes c LEFT JOIN entidades e ON e.cnpj = c.cnpj_cedente
            WHERE c.cnpj = %s AND c.competencia = %s ORDER BY c.ordem""", (cnpj, last)) if last else []
        irmaos = fetch_all(conn, """SELECT cnpj, nome FROM fidcs WHERE cnpj_fundo = %s AND cnpj <> %s ORDER BY nome""",
                           (f["cnpj_fundo"], cnpj)) if f.get("cnpj_fundo") else []
        mesma_gestora = fetch_all(conn, """
            SELECT f2.cnpj, f2.nome, m.pl, m.segmento FROM fidcs f2
            JOIN fidc_mensal m ON m.cnpj = f2.cnpj AND m.competencia = f2.ultima_competencia
            WHERE f2.gestor = %s AND f2.cnpj <> %s ORDER BY m.pl DESC NULLS LAST LIMIT 12""",
            (f["gestor"], cnpj)) if f.get("gestor") else []
    for c in cedentes:
        c["cnpj_cedente_fmt"] = format_cnpj(c["cnpj_cedente"])
    for x in irmaos + mesma_gestora:
        x["cnpj"] = x["cnpj"].strip()
    f["cnpj"] = f["cnpj"].strip()
    f["cnpj_fmt"] = format_cnpj(f["cnpj"])
    f["cnpj_fundo_fmt"] = format_cnpj((f.get("cnpj_fundo") or "").strip()) if f.get("cnpj_fundo") else None
    for h in hist:
        h.pop("cnpj", None)
    return clean({"fidc": f, "historico": hist, "series": series, "series_historico": serie_hist,
                  "cedentes": cedentes, "classes_do_fundo": irmaos, "mesma_gestora": mesma_gestora})


def _group(field: str):
    with connection() as conn:
        comp = latest_month(conn)
        if comp is None:
            return {"competencia": None, "rows": []}
        rows = fetch_all(conn, f"""
            WITH base AS ({LATEST_SQL})
            SELECT {field} AS nome, count(*) AS fundos,
                   sum(pl) FILTER (WHERE NOT fic) AS pl,
                   sum(cotistas) AS cotistas,
                   sum(coalesce(captacao, 0) - coalesce(resgate, 0) - coalesce(amortizacao, 0)) FILTER (WHERE NOT fic)
                     AS captacao_liquida,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY inadimplencia) AS inad_mediana,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY subordinacao) AS sub_mediana,
                   mode() WITHIN GROUP (ORDER BY segmento) AS segmento_principal,
                   count(*) FILTER (WHERE situacao IN ('Em Liquidação', 'Cancelado')) AS em_liquidacao
            FROM base WHERE {field} IS NOT NULL GROUP BY {field}
            ORDER BY sum(pl) FILTER (WHERE NOT fic) DESC NULLS LAST""", {"comp": comp, "fic": FIC_MIN})
    return clean({"competencia": comp, "rows": rows})


@router.get("/gestoras")
def gestoras():
    return _group("gestor")


@router.get("/administradores")
def administradores():
    return _group("administrador")


@router.get("/custodiantes")
def custodiantes():
    return _group("custodiante")


@router.get("/cedentes")
def cedentes():
    with connection() as conn:
        comp = latest_month(conn)
        if comp is None:
            return {"competencia": None, "rows": []}
        rows = fetch_all(conn, """
            WITH ult AS (SELECT DISTINCT ON (cnpj) cnpj, competencia FROM fidc_mensal
                         WHERE competencia <= %(comp)s AND competencia > (%(comp)s::date - interval '6 months')
                         ORDER BY cnpj, competencia DESC)
            SELECT c.cnpj_cedente, e.nome, count(DISTINCT c.cnpj) AS fidcs, avg(c.pct) AS peso_medio,
                   max(c.pct) AS peso_max, sum(m.pl) AS pl_fidcs,
                   array_agg(DISTINCT f.gestor) FILTER (WHERE f.gestor IS NOT NULL) AS gestoras,
                   mode() WITHIN GROUP (ORDER BY m.segmento) AS segmento
            FROM ult u JOIN fidc_cedentes c ON c.cnpj = u.cnpj AND c.competencia = u.competencia
            JOIN fidc_mensal m ON m.cnpj = u.cnpj AND m.competencia = u.competencia
            JOIN fidcs f ON f.cnpj = u.cnpj
            LEFT JOIN entidades e ON e.cnpj = c.cnpj_cedente
            GROUP BY c.cnpj_cedente, e.nome ORDER BY count(DISTINCT c.cnpj) DESC, sum(m.pl) DESC NULLS LAST
            LIMIT 2000""", {"comp": comp})
    for r in rows:
        r["cnpj_cedente_fmt"] = format_cnpj(r["cnpj_cedente"])
    return clean({"competencia": comp, "rows": rows})


@router.get("/cedentes/{ident}")
def cedente(ident: str):
    c = _cnpj_or_404(ident)
    with connection() as conn:
        nome = conn.execute("SELECT nome FROM entidades WHERE cnpj = %s", (c,)).fetchone()
        rows = fetch_all(conn, """
            SELECT c.competencia, c.cnpj, f.nome, f.gestor, c.pct, m.pl, m.segmento
            FROM fidc_cedentes c JOIN fidcs f ON f.cnpj = c.cnpj
            LEFT JOIN fidc_mensal m ON m.cnpj = c.cnpj AND m.competencia = c.competencia
            WHERE c.cnpj_cedente = %s ORDER BY c.competencia DESC, c.pct DESC NULLS LAST""", (c,))
    for r in rows:
        r["cnpj"] = r["cnpj"].strip()
    return clean({"cnpj": c, "cnpj_fmt": format_cnpj(c), "nome": nome[0] if nome else None, "rows": rows})


@router.get("/search")
def search(q: str = Query("", max_length=120)):
    text = q.strip()
    if len(text) < 2:
        return {"hits": []}
    d = digits(text)
    with connection() as conn:
        hits: list[dict[str, Any]] = []
        if len(d) >= 6:
            for r in fetch_all(conn, "SELECT cnpj, nome, gestor FROM fidcs WHERE cnpj LIKE %s LIMIT 8", (d + "%",)):
                hits.append({"kind": "fidc", "id": r["cnpj"].strip(), "label": r["nome"], "sub": r["gestor"]})
            for r in fetch_all(conn, """SELECT DISTINCT c.cnpj_cedente, e.nome FROM fidc_cedentes c
                                        LEFT JOIN entidades e ON e.cnpj = c.cnpj_cedente
                                        WHERE c.cnpj_cedente LIKE %s LIMIT 5""", (d + "%",)):
                hits.append({"kind": "cedente", "id": r["cnpj_cedente"], "label": r["nome"] or format_cnpj(r["cnpj_cedente"]),
                             "sub": "Cedente"})
        like = "%" + re.sub(r"[%_]", "", text) + "%"
        for r in fetch_all(conn, """SELECT cnpj, nome, gestor FROM fidcs
                                    WHERE nome ILIKE %s OR nome %% %s
                                    ORDER BY (nome ILIKE %s) DESC, similarity(nome, %s) DESC LIMIT 12""",
                           (like, text, like, text)):
            hits.append({"kind": "fidc", "id": r["cnpj"].strip(), "label": r["nome"], "sub": r["gestor"]})
        for kind, col in (("gestora", "gestor"), ("administrador", "administrador")):
            for r in fetch_all(conn, f"""SELECT {col} AS nome, count(*) AS n FROM fidcs WHERE {col} ILIKE %s
                                         GROUP BY {col} ORDER BY count(*) DESC LIMIT 5""", (like,)):
                hits.append({"kind": kind, "id": r["nome"], "label": r["nome"], "sub": f"{r['n']} FIDCs"})
    seen, out = set(), []
    for h in hits:
        k = (h["kind"], h["id"])
        if k not in seen:
            seen.add(k)
            out.append(h)
    return {"hits": out[:25]}
