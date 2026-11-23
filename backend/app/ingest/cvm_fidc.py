"""FIDCs from CVM open data: the monthly informe (one zip per month) and the fund/class register.

Two jobs (app/jobs/catchup.py):

- fidc_cadastro: registro_fundo_classe.zip (registro_fundo.csv, registro_classe.csv) into cadastro_cvm, plus the
  names of every CNPJ it lists (entidades, used to name cedentes). Then fidcs takes gestor, administrador,
  custodiante, auditor, situação, adaptação à RCVM 175 and the register's latest PL from it (apply_cadastro).
- fidc_informe_mensal: inf_mensal_fidc_<AAAAMM>.zip for the last FIDC_HISTORY_MONTHS months. A month already loaded
  by this loader version is not read again unless CVM published a new file for it (conditional GET: the newest
  FIDC_REFRESH_MONTHS months are always asked, older ones only when never loaded). Each month replaces its
  fidc_mensal, fidc_series and fidc_cedentes rows.

Formats (seen in the January 2026 files): ';', Latin-1, '.' decimal, dates AAAA-MM-DD, CNPJ formatted
(05.754.060/0001-13). Percent columns (rentabilidade, desempenho, peso dos cedentes, garantia) come in percent and are
stored as fractions. Series names differ between tables by an accent ('Senior' / 'Sênior') and spacing, so they are
compared folded (series_key).

NOT VERIFIED from the cloud (dados.cvm.gov.br was unreachable from the build machine): the URLs below, how far back
monthly zips exist under DADOS/ (older months may only be in HIST/ yearly zips; a 404 month is skipped and logged),
and the member names inside each zip (matched by the 'tab_<N>' part, any prefix). The first real run logs every
member it reads.

Personal data: only company CNPJs are kept as cedentes (an 11-digit CPF, or anything not a valid CNPJ, is dropped).
Nothing else in these files names a person.
"""
import csv
import io
import re
import unicodedata
import zipfile
import zlib
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

import psycopg
from psycopg.types.json import Jsonb

from app.core.db import is_loaded, mark_loaded
from app.core.http import NotFound
from app.jobs.catchup import TZ
from app.jobs.registry import JobContext, JobResult, register

SRC_MENSAL = "cvm_inf_mensal_fidc"
SRC_CAD = "cvm_cad_fidc"
MENSAL_URL = "https://dados.cvm.gov.br/dados/FIDC/DOC/INF_MENSAL/DADOS/inf_mensal_fidc_{yyyymm}.zip"
CAD_URL = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip"
LOADER_MENSAL = "fidc_informe_mensal:v1"     # bump to re-read every month
LOADER_CAD = "fidc_cadastro:v1"
ZIP_ERRORS = (zipfile.BadZipFile, zlib.error, EOFError, OSError)

LIM_MONEY = Decimal("1e18")
LIM_FRACTION = Decimal("1e4")

# Tabela II leaves: (column, segment, subsegment). Labels as in CVM's informe; G is "Cartão de crédito" and H is
# "Factoring" in the Instrução's layout (check against CVM's META dictionary if a label looks wrong).
SEGMENT_LEAVES: tuple[tuple[str, str, str], ...] = (
    ("TAB_II_A_VL_INDUST", "Industrial", "Industrial"),
    ("TAB_II_B_VL_IMOBIL", "Imobiliário", "Imobiliário"),
    ("TAB_II_C1_VL_COMERC", "Comercial", "Comercial"),
    ("TAB_II_C2_VL_VAREJO", "Comercial", "Varejo"),
    ("TAB_II_C3_VL_ARREND", "Comercial", "Arrendamento mercantil"),
    ("TAB_II_D1_VL_SERV", "Serviços", "Serviços"),
    ("TAB_II_D2_VL_SERV_PUBLICO", "Serviços", "Serviços públicos"),
    ("TAB_II_D3_VL_SERV_EDUC", "Serviços", "Educacionais"),
    ("TAB_II_D4_VL_ENTRET", "Serviços", "Entretenimento"),
    ("TAB_II_E_VL_AGRONEG", "Agronegócio", "Agronegócio"),
    ("TAB_II_F1_VL_CRED_PESSOA", "Financeiro", "Crédito pessoal"),
    ("TAB_II_F2_VL_CRED_PESSOA_CONSIG", "Financeiro", "Crédito consignado"),
    ("TAB_II_F3_VL_CRED_CORP", "Financeiro", "Crédito corporativo"),
    ("TAB_II_F4_VL_MIDMARKET", "Financeiro", "Middle market"),
    ("TAB_II_F5_VL_VEICULO", "Financeiro", "Veículos"),
    ("TAB_II_F6_VL_IMOBIL_EMPRESA", "Financeiro", "Imobiliário empresarial"),
    ("TAB_II_F7_VL_IMOBIL_RESID", "Financeiro", "Imobiliário residencial"),
    ("TAB_II_F8_VL_OUTRO", "Financeiro", "Financeiro – outros"),
    ("TAB_II_G_VL_CREDITO", "Cartão de crédito", "Cartão de crédito"),
    ("TAB_II_H1_VL_PESSOA", "Factoring", "Factoring PF"),
    ("TAB_II_H2_VL_CORP", "Factoring", "Factoring PJ"),
    ("TAB_II_I1_VL_PRECAT", "Setor público", "Precatórios"),
    ("TAB_II_I2_VL_TRIBUT", "Setor público", "Créditos tributários"),
    ("TAB_II_I3_VL_ROYALTIES", "Setor público", "Royalties"),
    ("TAB_II_I4_VL_OUTRO", "Setor público", "Setor público – outros"),
    ("TAB_II_J_VL_JUDICIAL", "Ações judiciais", "Ações judiciais"),
    ("TAB_II_K_VL_MARCA", "Marcas e PI", "Propriedade intelectual"),
)
# Segment totals filed without their leaves.
SEGMENT_TOTALS = (("TAB_II_C_VL_COMERC", "Comercial"), ("TAB_II_D_VL_SERV", "Serviços"),
                  ("TAB_II_F_VL_FINANC", "Financeiro"), ("TAB_II_H_VL_FACTOR", "Factoring"),
                  ("TAB_II_I_VL_SETOR_PUBLICO", "Setor público"))
SEM_SEGMENTO = "Sem direitos creditórios por segmento"

INVESTOR_TYPES: tuple[tuple[str, str], ...] = (
    ("PF", "Pessoa física"), ("PJ_NAO_FINANC", "Empresa não financeira"), ("BANCO", "Banco"),
    ("CORRETORA_DISTRIB", "Corretora ou distribuidora"), ("PJ_FINANC", "Outra PJ financeira"),
    ("INVNR", "Investidor não residente"), ("EAPC", "Previdência aberta (EAPC)"),
    ("EFPC", "Fundo de pensão (EFPC)"), ("RPPS", "Regime próprio (RPPS)"), ("SEGUR", "Seguradora"),
    ("CAPITALIZ", "Capitalização"), ("COTA_FIDC", "FIDC / FIC-FIDC"), ("FII", "FII"),
    ("OUTRO_FI", "Outros fundos de investimento"), ("CLUBE", "Clube de investimento"), ("OUTRO", "Outros"),
)
AGING = ("30", "60", "90", "120", "150", "180", "360", "720", "1080", "MAIOR_1080")
LIQUIDEZ = ("0", "30", "60", "90", "180", "360", "MAIOR_360")
SCR = ("AA", "A", "B", "C", "D", "E", "F", "G", "H")
TABLES = ("I", "II", "IV", "V", "VI", "X", "X_1", "X_1_1", "X_2", "X_3", "X_4", "X_5", "X_6", "X_7")


# -- value parsing --------------------------------------------------------------------------------------------------

def dec(value: str | None, limit: Decimal = LIM_MONEY) -> Decimal | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        d = Decimal(text)
    except InvalidOperation:
        return None
    if not d.is_finite() or abs(d) >= limit:
        return None
    return d


def pct(value: str | None) -> Decimal | None:
    """A percent column as a fraction (51.19 -> 0.5119)."""
    d = dec(value, LIM_FRACTION * 100)
    return None if d is None else d / 100


def digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _cnpj_valid(cnpj: str) -> bool:
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    def check(body: str, weights: list[int]) -> str:
        s = sum(int(d) * w for d, w in zip(body, weights)) % 11
        return "0" if s < 2 else str(11 - s)
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    return check(cnpj[:12], w1) == cnpj[12] and check(cnpj[:13], [6] + w1) == cnpj[13]


def company_cnpj(value: str | None) -> str | None:
    d = digits(value)
    if len(d) < 14 and len(d) > 11:
        d = d.zfill(14)
    return d if len(d) == 14 and _cnpj_valid(d) else None


def fund_cnpj(value: str | None) -> str | None:
    d = digits(value)
    return d.zfill(14) if 8 <= len(d) <= 14 else None


def iso_date(value: str | None) -> date | None:
    text = (value or "").strip()[:10]
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        try:
            return datetime.strptime(text, "%d/%m/%Y").date()
        except ValueError:
            return None


def month_start(d: date) -> date:
    return d.replace(day=1)


def yes_no(value: str | None) -> bool | None:
    v = (value or "").strip().upper()
    return True if v in ("S", "SIM") else False if v in ("N", "NAO", "NÃO") else None


def fold(text: str | None) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", t.replace("|", " ")).strip()


def series_key(text: str | None) -> str:
    return fold(text)


def series_kind(text: str | None) -> str:
    t = fold(text)
    if "MEZANINO" in t:
        return "Mezanino"
    if "SUBORDINAD" in t:
        return "Subordinada"
    return "Sênior"


def text(value: str | None) -> str | None:
    t = (value or "").strip()
    return t or None


# -- CSV / zip reading --------------------------------------------------------------------------------------------

def read_csv_bytes(data: bytes) -> list[dict[str, str]]:
    try:
        decoded = data.decode("utf-8") if data[:3] == b"\xef\xbb\xbf" else data.decode("latin-1")
    except UnicodeDecodeError:
        decoded = data.decode("cp1252", "replace")
    decoded = decoded.lstrip("﻿")
    reader = csv.reader(io.StringIO(decoded), delimiter=";", quoting=csv.QUOTE_NONE)
    try:
        header = [h.strip() for h in next(reader)]
    except StopIteration:
        return []
    rows = []
    for fields in reader:
        if not fields or (len(fields) == 1 and not fields[0].strip()):
            continue
        if len(fields) < len(header):
            fields = fields + [""] * (len(header) - len(fields))
        rows.append(dict(zip(header, fields)))
    return rows


def find_member(names: Iterable[str], table: str) -> str | None:
    """The CSV of 'tab_<table>' (tab_I does not match tab_II nor tab_I_...)."""
    pat = re.compile(rf"(?:^|[/_])tab_{re.escape(table)}_\d{{6}}\.csv$", re.IGNORECASE)
    hits = [n for n in names if pat.search(n)]
    return sorted(hits, key=len)[0] if hits else None


def by_cnpj(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        c = fund_cnpj(r.get("CNPJ_FUNDO_CLASSE") or r.get("CNPJ_FUNDO"))
        if c and c not in out:
            out[c] = r
    return out


def group_cnpj(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        c = fund_cnpj(r.get("CNPJ_FUNDO_CLASSE") or r.get("CNPJ_FUNDO"))
        if c:
            out[c].append(r)
    return out


# -- building one month -------------------------------------------------------------------------------------------

def _f(x: Decimal | None) -> float:
    return float(x) if x is not None else 0.0


def segments(row: dict[str, str] | None) -> tuple[dict[str, float], str | None, str | None, Decimal | None]:
    if row is None:
        return {}, None, None, None
    leaves: dict[str, float] = {}
    tops: dict[str, float] = defaultdict(float)
    for col, top, leaf in SEGMENT_LEAVES:
        v = _f(dec(row.get(col)))
        if v > 0:
            leaves[leaf] = leaves.get(leaf, 0.0) + v
            tops[top] += v
    for col, top in SEGMENT_TOTALS:
        v = _f(dec(row.get(col)))
        if v > tops.get(top, 0.0):
            extra = v - tops.get(top, 0.0)
            tops[top] = v
            if extra > 0.005:
                leaves[f"{top} – não detalhado"] = leaves.get(f"{top} – não detalhado", 0.0) + extra
    total = sum(tops.values())
    if total <= 0:
        return {}, SEM_SEGMENTO, None, None
    top = max(tops, key=lambda k: tops[k])
    top_leaves = {k: v for k, v in leaves.items()
                  if any(l == k and t == top for _, t, l in SEGMENT_LEAVES) or k == f"{top} – não detalhado"}
    sub = max(top_leaves, key=lambda k: top_leaves[k]) if top_leaves else top
    return {k: round(v, 2) for k, v in leaves.items()}, top, sub, Decimal(str(tops[top] / total))


def aging(row: dict[str, str] | None, tab: str) -> dict[str, Decimal | None]:
    if row is None:
        return {}
    out = {
        "a_vencer": dec(row.get(f"TAB_{tab}_A_VL_DIRCRED_PRAZO")),
        "inad": dec(row.get(f"TAB_{tab}_B_VL_DIRCRED_INAD")),
        "antecipado": dec(row.get(f"TAB_{tab}_C_VL_DIRCRED_ANTECIPADO")),
    }
    over90 = Decimal(0)
    for i, a in enumerate(AGING, start=1):
        if i >= 4:
            over90 += dec(row.get(f"TAB_{tab}_B{i}_VL_INAD_{a}")) or 0
    out["inad_90"] = over90
    for i, a in enumerate(AGING, start=1):
        out[f"prazo_{a}"] = dec(row.get(f"TAB_{tab}_A{i}_VL_PRAZO_VENC_{a}"))
    return out


def investors(row: dict[str, str] | None) -> tuple[dict[str, int], str | None]:
    if row is None:
        return {}, None
    cnt: dict[str, int] = {}
    for code, label in INVESTOR_TYPES:
        n = 0
        for part in ("SENIOR", "SUBORD"):
            v = dec(row.get(f"TAB_X_NR_COTST_{part}_{code}"))
            if v is not None and v > 0:
                n += int(v)
        if n:
            cnt[label] = n
    total = sum(cnt.values())
    if not total:
        return {}, None
    top, n = max(cnt.items(), key=lambda kv: kv[1])
    return cnt, (top if n / total >= 0.5 else "Misto")


def build_month(tables: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    """Every fund of one month's zip: fidcs rows, fidc_mensal rows, series, cedentes; plus counts of dropped values."""
    t1 = by_cnpj(tables.get("I", []))
    t2 = by_cnpj(tables.get("II", []))
    t4 = by_cnpj(tables.get("IV", []))
    t5 = by_cnpj(tables.get("V", []))
    t6 = by_cnpj(tables.get("VI", []))
    tx = by_cnpj(tables.get("X", []))
    tx11 = by_cnpj(tables.get("X_1_1", []))
    tx5 = by_cnpj(tables.get("X_5", []))
    tx7 = by_cnpj(tables.get("X_7", []))
    tx1 = group_cnpj(tables.get("X_1", []))
    tx2 = group_cnpj(tables.get("X_2", []))
    tx3 = group_cnpj(tables.get("X_3", []))
    tx4 = group_cnpj(tables.get("X_4", []))
    tx6 = group_cnpj(tables.get("X_6", []))
    dropped: dict[str, int] = defaultdict(int)
    funds, mensal, series, cedentes = [], [], [], []

    for cnpj, r in t1.items():
        comp_date = iso_date(r.get("DT_COMPTC"))
        if comp_date is None:
            dropped["sem_data"] += 1
            continue
        comp = month_start(comp_date)
        funds.append({
            "cnpj": cnpj, "nome": text(r.get("DENOM_SOCIAL")) or cnpj, "tipo": text(r.get("TP_FUNDO_CLASSE")),
            "administrador": text(r.get("ADMIN")), "cnpj_administrador": company_cnpj(r.get("CNPJ_ADMIN")),
            "condominio": (text(r.get("CONDOM")) or "").capitalize() or None,
            "exclusivo": yes_no(r.get("FUNDO_EXCLUSIVO")), "classe_unica": yes_no(r.get("CLASSE_UNICA")),
            "competencia": comp,
        })
        # series: value, cotistas, rentabilidade, desempenho
        ser: dict[str, dict[str, Any]] = {}
        for s in tx2.get(cnpj, []):
            k = series_key(s.get("TAB_X_CLASSE_SERIE"))
            if not k:
                continue
            qt, vl = dec(s.get("TAB_X_QT_COTA"), Decimal("1e20")), dec(s.get("TAB_X_VL_COTA"), Decimal("1e20"))
            val = qt * vl if qt is not None and vl is not None else None
            ser[k] = {"classe_serie": text(s.get("TAB_X_CLASSE_SERIE")), "tipo": series_kind(k), "qt_cotas": qt,
                      "vl_cota": vl, "valor": val if val is not None and abs(val) < LIM_MONEY else None}
        def slot(raw: str | None) -> dict[str, Any] | None:
            k = series_key(raw)
            if not k:
                return None
            if k not in ser:
                ser[k] = {"classe_serie": text(raw), "tipo": series_kind(k), "qt_cotas": None, "vl_cota": None,
                          "valor": None}
            return ser[k]
        cot_total = 0
        for s in tx1.get(cnpj, []):
            n = dec(s.get("TAB_X_NR_COTST"))
            sl = slot(s.get("TAB_X_CLASSE_SERIE"))
            if sl is not None and n is not None:
                sl["cotistas"] = int(n)
            if n is not None and n > 0:
                cot_total += int(n)
        for s in tx3.get(cnpj, []):
            sl = slot(s.get("TAB_X_CLASSE_SERIE"))
            v = pct(s.get("TAB_X_VL_RENTAB_MES"))
            if sl is not None:
                if v is not None and abs(v) > 1:
                    dropped["rentabilidade_fora_da_faixa"] += 1
                    v = None
                sl["rentab_mes"] = v
        for s in tx6.get(cnpj, []):
            sl = slot(s.get("TAB_X_CLASSE_SERIE"))
            if sl is not None:
                e, rr = pct(s.get("TAB_X_PR_DESEMP_ESPERADO")), pct(s.get("TAB_X_PR_DESEMP_REAL"))
                sl["desemp_esperado"] = e if e is not None and abs(e) <= 10 else None
                sl["desemp_real"] = rr if rr is not None and abs(rr) <= 10 else None
        seen_names: set[str] = set()
        for sl in ser.values():
            name = (sl["classe_serie"] or "")[:200]
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            series.append({"cnpj": cnpj, "competencia": comp, **{k: sl.get(k) for k in (
                "tipo", "qt_cotas", "vl_cota", "valor", "cotistas", "rentab_mes", "desemp_esperado", "desemp_real")},
                "classe_serie": name})
        total_val = sum((sl["valor"] for sl in ser.values() if sl["valor"] is not None), Decimal(0))
        sub_val = sum((sl["valor"] for sl in ser.values() if sl["valor"] is not None and sl["tipo"] != "Sênior"),
                      Decimal(0))
        sen_val = total_val - sub_val
        subord = sub_val / total_val if total_val > 0 else None
        if subord is not None and not (0 <= subord <= 1):
            dropped["subordinacao_fora_da_faixa"] += 1
            subord = None
        def biggest(kind_filter) -> Decimal | None:
            cands = [sl for sl in ser.values() if kind_filter(sl["tipo"]) and sl.get("rentab_mes") is not None]
            if not cands:
                return None
            return max(cands, key=lambda s: s["valor"] or 0)["rentab_mes"]
        rsen = biggest(lambda t: t == "Sênior")
        rsub = biggest(lambda t: t != "Sênior")

        # cedentes (DC com e sem aquisição substancial de riscos)
        ced: list[tuple[str, Decimal]] = []
        for block in ("2A", "2B"):
            for i in range(1, 10):
                cc = r.get(f"TAB_I{block}12_CPF_CNPJ_CEDENTE_{i}")
                if not (cc or "").strip():
                    continue
                c14 = company_cnpj(cc)
                p = pct(r.get(f"TAB_I{block}12_PR_CEDENTE_{i}"))
                if c14 is None:
                    dropped["cedente_cpf_ou_invalido"] += 1
                    continue
                if p is None or not (0 <= p <= 1):
                    dropped["peso_cedente_fora_da_faixa"] += 1
                    p = None
                ced.append((c14, p))
        merged: dict[str, Decimal | None] = {}
        for c14, p in ced:
            if c14 not in merged or (p is not None and (merged[c14] or 0) < p):
                merged[c14] = p
        ordered = sorted(merged.items(), key=lambda kv: -(kv[1] or 0))
        for i, (c14, p) in enumerate(ordered, start=1):
            cedentes.append({"cnpj": cnpj, "competencia": comp, "ordem": i, "cnpj_cedente": c14, "pct": p})

        ag5, ag6 = aging(t5.get(cnpj), "V"), aging(t6.get(cnpj), "VI")
        def add(key: str) -> Decimal | None:
            vals = [a.get(key) for a in (ag5, ag6) if a.get(key) is not None]
            return sum(vals, Decimal(0)) if vals else None
        a_vencer, inad, inad90 = add("a_vencer"), add("inad"), add("inad_90")
        inadimplencia = None
        if a_vencer is not None and inad is not None and (a_vencer + inad) > 0:
            inadimplencia = inad / (a_vencer + inad)
        prazo = {a: float(v) for a in AGING if (v := add(f"prazo_{a}")) is not None}
        dc_risco = dec(r.get("TAB_I2A_VL_DIRCRED_RISCO"))
        pdd = (dec(r.get("TAB_I2A11_VL_REDUCAO_RECUP")) or 0) + (dec(r.get("TAB_I2B11_VL_REDUCAO_RECUP")) or 0)
        dc_total = (dc_risco or 0) + (dec(r.get("TAB_I2B_VL_DIRCRED_SEM_RISCO")) or 0)
        segs, seg, subseg, peso = segments(t2.get(cnpj))
        cot_tipo, aloc = investors(tx11.get(cnpj))
        x4 = defaultdict(lambda: Decimal(0))
        for s in tx4.get(cnpj, []):
            v = dec(s.get("TAB_X_VL_TOTAL"))
            if v is not None:
                x4[fold(s.get("TAB_X_TP_OPER"))] += v
        liq = {}
        if (lr := tx5.get(cnpj)) is not None:
            liq = {k: float(v) for k in LIQUIDEZ if (v := dec(lr.get(f"TAB_X_VL_LIQUIDEZ_{k}"))) is not None}
        scr = {}
        if (sr := tx.get(cnpj)) is not None:
            scr = {k: float(v) for k in SCR if (v := dec(sr.get(f"TAB_X_SCR_RISCO_DEVEDOR_{k}"))) is not None and v}
        gar = pct(tx7[cnpj].get("TAB_X_PR_GARANTIA_DIRCRED")) if cnpj in tx7 else None
        if gar is not None and not (0 <= gar <= 1):
            dropped["garantia_fora_da_faixa"] += 1
            gar = None
        t4r = t4.get(cnpj, {})
        cart = dec(r.get("TAB_I2_VL_CARTEIRA"))
        cotas_fidc = (dec(r.get("TAB_I2H_VL_COTA_FIDC")) or 0) + (dec(r.get("TAB_I2I_VL_COTA_FIDC_NP")) or 0)
        cotas_pct = cotas_fidc / cart if cart and cart > 0 and 0 <= cotas_fidc / cart <= 2 else None
        mensal.append({
            "cnpj": cnpj, "competencia": comp,
            "pl": dec(t4r.get("TAB_IV_A_VL_PL")), "pl_medio": dec(t4r.get("TAB_IV_B_VL_PL_MEDIO")),
            "ativo": dec(r.get("TAB_I_VL_ATIVO")), "disponibilidades": dec(r.get("TAB_I1_VL_DISP")),
            "carteira": dec(r.get("TAB_I2_VL_CARTEIRA")), "dc_com_risco": dc_risco,
            "dc_sem_risco": dec(r.get("TAB_I2B_VL_DIRCRED_SEM_RISCO")),
            "a_vencer": a_vencer, "inadimplente": inad, "inad_acima_90": inad90, "antecipado": add("antecipado"),
            "inadimplencia": inadimplencia,
            "pdd_sobre_dc": (pdd / dc_total) if dc_total and dc_total > 0 and 0 <= pdd / dc_total <= 10 else None,
            "segmentos": segs or None, "segmento": seg, "subsegmento": subseg, "peso_segmento": peso,
            "subordinacao": subord, "valor_cotas": total_val or None, "valor_senior": sen_val if total_val else None,
            "valor_subordinada": sub_val if total_val else None,
            "cotistas": cot_total or None, "cotistas_tipo": cot_tipo or None, "alocador_tipo": aloc,
            "rentab_senior": rsen, "rentab_subordinada": rsub,
            "captacao": x4.get("CAPTACOES NO MES"), "resgate": x4.get("RESGATES NO MES"),
            "amortizacao": x4.get("AMORTIZACOES"),
            "garantia_pct": gar, "liquidez": liq or None, "prazo_vencimento": prazo or None,
            "rating_scr": scr or None, "cotas_fidc_pct": cotas_pct,
            "cedente1_pct": ordered[0][1] if ordered else None, "cedentes_informados": len(ordered) or None,
            "condominio": (text(r.get("CONDOM")) or "").capitalize() or None,
        })
    return {"funds": funds, "mensal": mensal, "series": series, "cedentes": cedentes, "dropped": dict(dropped)}


MENSAL_COLS = ("cnpj", "competencia", "raw_file_id", "pl", "pl_medio", "ativo", "disponibilidades", "carteira",
               "dc_com_risco", "dc_sem_risco", "a_vencer", "inadimplente", "inad_acima_90", "antecipado",
               "inadimplencia", "pdd_sobre_dc", "segmentos", "segmento", "subsegmento", "peso_segmento",
               "subordinacao", "valor_cotas", "valor_senior", "valor_subordinada", "cotistas", "cotistas_tipo",
               "alocador_tipo", "rentab_senior", "rentab_subordinada", "captacao", "resgate", "amortizacao",
               "garantia_pct", "liquidez", "prazo_vencimento", "rating_scr", "cotas_fidc_pct", "cedente1_pct", "cedentes_informados",
               "condominio")
JSON_COLS = {"segmentos", "cotistas_tipo", "liquidez", "prazo_vencimento", "rating_scr"}
SERIES_COLS = ("cnpj", "competencia", "classe_serie", "tipo", "qt_cotas", "vl_cota", "valor", "cotistas",
               "rentab_mes", "desemp_esperado", "desemp_real")


def store_month(conn: psycopg.Connection, built: dict[str, Any], raw_file_id: int | None) -> int:
    """Write one month (replacing what that month had). Returns fidc_mensal rows written."""
    months = sorted({m["competencia"] for m in built["mensal"]})
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO fidcs (cnpj, nome, tipo, administrador, cnpj_administrador, condominio, exclusivo,
                                  classe_unica, ultima_competencia)
               VALUES (%(cnpj)s, %(nome)s, %(tipo)s, %(administrador)s, %(cnpj_administrador)s, %(condominio)s,
                       %(exclusivo)s, %(classe_unica)s, %(competencia)s)
               ON CONFLICT (cnpj) DO UPDATE SET
                 nome = CASE WHEN EXCLUDED.ultima_competencia >= coalesce(fidcs.ultima_competencia, '1900-01-01')
                             THEN EXCLUDED.nome ELSE fidcs.nome END,
                 tipo = coalesce(EXCLUDED.tipo, fidcs.tipo),
                 administrador = coalesce(fidcs.administrador, EXCLUDED.administrador),
                 cnpj_administrador = coalesce(fidcs.cnpj_administrador, EXCLUDED.cnpj_administrador),
                 condominio = coalesce(EXCLUDED.condominio, fidcs.condominio),
                 exclusivo = coalesce(EXCLUDED.exclusivo, fidcs.exclusivo),
                 classe_unica = coalesce(EXCLUDED.classe_unica, fidcs.classe_unica),
                 ultima_competencia = GREATEST(fidcs.ultima_competencia, EXCLUDED.ultima_competencia),
                 updated_at = now()""",
            built["funds"])
        for m in months:
            cur.execute("DELETE FROM fidc_cedentes WHERE competencia = %s", (m,))
            cur.execute("DELETE FROM fidc_series WHERE competencia = %s", (m,))
            cur.execute("DELETE FROM fidc_mensal WHERE competencia = %s", (m,))
        rows = []
        for m in built["mensal"]:
            row = {**m, "raw_file_id": raw_file_id}
            rows.append(tuple(Jsonb(row[c]) if c in JSON_COLS and row[c] is not None else row[c] for c in MENSAL_COLS))
        cur.executemany(f"INSERT INTO fidc_mensal ({', '.join(MENSAL_COLS)}) VALUES "
                        f"({', '.join(['%s'] * len(MENSAL_COLS))}) ON CONFLICT DO NOTHING", rows)
        cur.executemany(f"INSERT INTO fidc_series ({', '.join(SERIES_COLS)}) VALUES "
                        f"({', '.join(['%s'] * len(SERIES_COLS))}) ON CONFLICT DO NOTHING",
                        [tuple(s.get(c) for c in SERIES_COLS) for s in built["series"]])
        cur.executemany("""INSERT INTO fidc_cedentes (cnpj, competencia, ordem, cnpj_cedente, pct)
                           VALUES (%(cnpj)s, %(competencia)s, %(ordem)s, %(cnpj_cedente)s, %(pct)s)
                           ON CONFLICT DO NOTHING""", built["cedentes"])
    return len(rows)


def read_zip(path_or_bytes, log=None) -> dict[str, list[dict[str, str]]]:
    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, (bytes, bytearray)) else path_or_bytes
    out: dict[str, list[dict[str, str]]] = {}
    with zipfile.ZipFile(src) as zf:
        names = zf.namelist()
        for t in TABLES:
            member = find_member(names, t)
            if member is None:
                continue
            out[t] = read_csv_bytes(zf.read(member))
            if log:
                log(f"  {member}: {len(out[t])} linhas")
    return out


def months_back(today: date, n: int) -> list[date]:
    """M-1 back to M-n (the current month has no informe yet), newest first."""
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(date(y, m, 1))
    return out


def apply_cadastro(conn: psycopg.Connection) -> int:
    """fidcs takes the register's fields (the register wins over the informe for administrador)."""
    cur = conn.execute("""
        UPDATE fidcs f SET
          cnpj_fundo = c.cnpj_fundo, nome_fundo = c.nome_fundo, situacao = c.situacao,
          data_situacao = c.data_situacao, data_constituicao = c.data_constituicao, data_registro = c.data_registro,
          adaptacao_175 = c.adaptacao_175,
          administrador = coalesce(c.administrador, f.administrador),
          cnpj_administrador = coalesce(c.cnpj_administrador, f.cnpj_administrador),
          gestor = c.gestor, cnpj_gestor = c.cnpj_gestor, custodiante = c.custodiante, auditor = c.auditor,
          condominio = coalesce(c.condominio, f.condominio), exclusivo = coalesce(c.exclusivo, f.exclusivo),
          publico_alvo = c.publico_alvo, pl_cadastro = c.pl, data_pl_cadastro = c.data_pl, updated_at = now()
        FROM cadastro_cvm c WHERE c.cnpj = f.cnpj""")
    return cur.rowcount


@register("fidc_informe_mensal")
def run_informe_mensal(ctx: JobContext) -> JobResult:
    s = ctx.settings
    today = datetime.now(TZ).date()
    months = months_back(today, max(1, int(s.fidc_history_months)))
    refresh = set(months[: max(1, int(s.fidc_refresh_months))])
    with ctx.connect() as conn:
        loaded = {r[0] for r in conn.execute("SELECT DISTINCT competencia FROM fidc_mensal")}
    rows_changed, newest, read_months, missing = 0, None, [], []
    for i, m in enumerate(months):
        ctx.check_cancelled()
        ctx.progress(i / len(months), f"Informe mensal FIDC {m:%m/%Y}")
        if m in loaded and m not in refresh:
            newest = max(newest or m, m)
            continue
        url = MENSAL_URL.format(yyyymm=f"{m:%Y%m}")
        try:
            raw = ctx.downloader.fetch(url, source_id=SRC_MENSAL, timeout=300)
        except NotFound:
            missing.append(f"{m:%m/%Y}")
            ctx.log(f"{m:%m/%Y}: arquivo ainda não publicado ou fora de DADOS/ (404) – {url}")
            continue
        with ctx.connect() as conn:
            if raw.id and is_loaded(conn, raw.id, LOADER_MENSAL) and m in loaded:
                newest = max(newest or m, m)
                continue
        ctx.log(f"{m:%m/%Y}: lendo {url}{' (sem mudanças desde a última leitura)' if raw.not_modified else ''}")
        try:
            tables = read_zip(raw.path, ctx.log)
        except ZIP_ERRORS as exc:
            ctx.issue("unexpected_format", {"url": url, "erro": str(exc)}, ref_month=m)
            ctx.log(f"{m:%m/%Y}: zip ilegível ({exc})")
            continue
        if "I" not in tables:
            ctx.issue("unexpected_format", {"url": url, "erro": "zip sem a tabela I"}, ref_month=m)
            continue
        built = build_month(tables)
        with ctx.connect() as conn:
            n = store_month(conn, built, raw.id)
            if raw.id:
                mark_loaded(conn, raw.id, LOADER_MENSAL, n)
            apply_cadastro(conn)
        rows_changed += n
        read_months.append(f"{m:%m/%Y}")
        newest = max(newest or m, m)
        if built["dropped"]:
            ctx.log(f"{m:%m/%Y}: valores descartados por estarem fora da faixa possível: {built['dropped']}")
        ctx.log(f"{m:%m/%Y}: {n} fundos")
    msg = (f"Meses lidos: {', '.join(read_months)}" if read_months else "Nenhum mês novo") + \
          (f" · sem arquivo: {', '.join(missing)}" if missing else "")
    return JobResult(rows_changed=rows_changed, sources=(SRC_MENSAL,), data_date=newest, message=msg)


# -- cadastro -----------------------------------------------------------------------------------------------------

def _g(row: dict[str, str], *names: str) -> str | None:
    for n in names:
        if n in row and (v := text(row[n])):
            return v
    return None


GESTOR_SEP = "; "


def build_cadastro(fundos: list[dict[str, str]], classes: list[dict[str, str]]
                   ) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """cadastro_cvm rows (classes first; a fund's own CNPJ when no class has it) and (cnpj, nome) names."""
    fund_by_id: dict[str, dict[str, str]] = {}
    # A fund managed by more than one gestora (cogestão) has one registro_fundo row per gestora, same ID and CNPJ.
    gestores_by_id: dict[str, list[tuple[str, str | None]]] = {}
    names: dict[str, str] = {}
    for f in fundos:
        fid = _g(f, "ID_Registro_Fundo")
        if fid:
            fund_by_id.setdefault(fid, f)
            nome_g = text(f.get("Gestor"))
            if nome_g:
                kind = (_g(f, "Tipo_Pessoa_Gestor") or "").upper()
                doc = company_cnpj(f.get("CPF_CNPJ_Gestor")) if kind != "PF" else None
                lst = gestores_by_id.setdefault(fid, [])
                if all(n != nome_g for n, _ in lst):
                    lst.append((nome_g, doc))
        for c, n in ((f.get("CNPJ_Fundo"), f.get("Denominacao_Social")), (f.get("CNPJ_Administrador"), f.get("Administrador"))):
            if (c14 := company_cnpj(c)) and text(n):
                names.setdefault(c14, text(n))
        if (_g(f, "Tipo_Pessoa_Gestor") or "PJ").upper() == "PJ" and (c14 := company_cnpj(f.get("CPF_CNPJ_Gestor"))) \
                and text(f.get("Gestor")):
            names.setdefault(c14, text(f.get("Gestor")))

    def gestor(f: dict[str, str]) -> tuple[str | None, str | None]:
        """All the fund's gestoras joined by GESTOR_SEP (names never contain ';': the CVM files are ';'-separated),
        and the CNPJ of the first one listed."""
        lst = gestores_by_id.get(_g(f, "ID_Registro_Fundo") or "", [])
        if not lst:
            return None, None
        return GESTOR_SEP.join(n for n, _ in lst), lst[0][1]

    out: dict[str, dict[str, Any]] = {}
    rank = {"Em Funcionamento Normal": 0}
    for c in classes:
        cnpj = fund_cnpj(c.get("CNPJ_Classe"))
        if not cnpj:
            continue
        f = fund_by_id.get(_g(c, "ID_Registro_Fundo") or "", {})
        g, gc = gestor(f) if f else (None, None)
        row = {
            "cnpj": cnpj, "origem": "classe", "tipo": _g(c, "Tipo_Classe"), "nome": _g(c, "Denominacao_Social"),
            "cnpj_fundo": fund_cnpj(f.get("CNPJ_Fundo")) if f else None, "nome_fundo": _g(f, "Denominacao_Social") if f else None,
            "situacao": _g(c, "Situacao"), "data_situacao": iso_date(c.get("Data_Inicio_Situacao")),
            "data_constituicao": iso_date(c.get("Data_Constituicao")), "data_registro": iso_date(c.get("Data_Registro")),
            "adaptacao_175": iso_date(f.get("Data_Adaptacao_RCVM175")) if f else None,
            "administrador": _g(f, "Administrador") if f else None,
            "cnpj_administrador": company_cnpj(f.get("CNPJ_Administrador")) if f else None,
            "gestor": g, "cnpj_gestor": gc, "custodiante": _g(c, "Custodiante"), "auditor": _g(c, "Auditor"),
            "condominio": _g(c, "Forma_Condominio"), "exclusivo": yes_no(c.get("Exclusivo")),
            "publico_alvo": _g(c, "Publico_Alvo"), "pl": dec(c.get("Patrimonio_Liquido")),
            "data_pl": iso_date(c.get("Data_Patrimonio_Liquido")),
        }
        if (c14 := company_cnpj(c.get("CNPJ_Classe"))) and row["nome"]:
            names.setdefault(c14, row["nome"])
        prev = out.get(cnpj)
        if prev is None or rank.get(row["situacao"] or "", 1) < rank.get(prev["situacao"] or "", 1) or \
                (rank.get(row["situacao"] or "", 1) == rank.get(prev["situacao"] or "", 1)
                 and (row["data_registro"] or date.min) > (prev["data_registro"] or date.min)):
            out[cnpj] = row
    # Funds with no class row: a CNPJ can have several registrations (re-registered after a cancellation);
    # keep the one not cancelled, else the newest, as for classes.
    latest: dict[str, dict[str, str]] = {}
    for f in fundos:
        cnpj = fund_cnpj(f.get("CNPJ_Fundo"))
        if not cnpj or cnpj in out:
            continue
        key = ((_g(f, "Situacao") or "") != "Cancelado", iso_date(f.get("Data_Registro")) or date.min)
        prev = latest.get(cnpj)
        if prev is None or key > ((_g(prev, "Situacao") or "") != "Cancelado",
                                  iso_date(prev.get("Data_Registro")) or date.min):
            latest[cnpj] = f
    for cnpj, f in latest.items():
        g, gc = gestor(f)
        out[cnpj] = {
            "cnpj": cnpj, "origem": "fundo", "tipo": _g(f, "Tipo_Fundo"), "nome": _g(f, "Denominacao_Social"),
            "cnpj_fundo": cnpj, "nome_fundo": _g(f, "Denominacao_Social"), "situacao": _g(f, "Situacao"),
            "data_situacao": iso_date(f.get("Data_Inicio_Situacao")),
            "data_constituicao": iso_date(f.get("Data_Constituicao")), "data_registro": iso_date(f.get("Data_Registro")),
            "adaptacao_175": iso_date(f.get("Data_Adaptacao_RCVM175")), "administrador": _g(f, "Administrador"),
            "cnpj_administrador": company_cnpj(f.get("CNPJ_Administrador")), "gestor": g, "cnpj_gestor": gc,
            "custodiante": None, "auditor": None, "condominio": None, "exclusivo": None, "publico_alvo": None,
            "pl": dec(f.get("Patrimonio_Liquido")), "data_pl": iso_date(f.get("Data_Patrimonio_Liquido")),
        }
    return list(out.values()), list(names.items())


CAD_COLS = ("cnpj", "origem", "tipo", "nome", "cnpj_fundo", "nome_fundo", "situacao", "data_situacao",
            "data_constituicao", "data_registro", "adaptacao_175", "administrador", "cnpj_administrador", "gestor",
            "cnpj_gestor", "custodiante", "auditor", "condominio", "exclusivo", "publico_alvo", "pl", "data_pl")


def store_cadastro(conn: psycopg.Connection, rows: list[dict[str, Any]], names: list[tuple[str, str]]) -> int:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM cadastro_cvm")
        cur.executemany(f"INSERT INTO cadastro_cvm ({', '.join(CAD_COLS)}) VALUES ({', '.join(['%s'] * len(CAD_COLS))})",
                        [tuple(r[c] for c in CAD_COLS) for r in rows])
        cur.executemany("""INSERT INTO entidades (cnpj, nome) VALUES (%s, %s)
                           ON CONFLICT (cnpj) DO UPDATE SET nome = EXCLUDED.nome""", names)
    return len(rows)


def read_cadastro_zip(src) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    with zipfile.ZipFile(src) as zf:
        names = zf.namelist()
        def member(stem: str) -> str | None:
            hits = [n for n in names if re.search(rf"(?:^|/){stem}\.csv$", n, re.IGNORECASE)]
            return hits[0] if hits else None
        mf, mc = member("registro_fundo"), member("registro_classe")
        if not mf or not mc:
            raise ValueError(f"registro_fundo/registro_classe não encontrados no zip: {names}")
        return read_csv_bytes(zf.read(mf)), read_csv_bytes(zf.read(mc))


@register("fidc_cadastro")
def run_cadastro(ctx: JobContext) -> JobResult:
    ctx.progress(0.05, "Baixando o cadastro de fundos e classes da CVM")
    raw = ctx.downloader.fetch(CAD_URL, source_id=SRC_CAD, timeout=600)
    with ctx.connect() as conn:
        if raw.id and is_loaded(conn, raw.id, LOADER_CAD):
            n = apply_cadastro(conn)
            return JobResult(rows_changed=0, sources=(SRC_CAD,), data_date=datetime.now(TZ).date(),
                             message=f"Cadastro sem mudanças; {n} FIDCs conferidos")
    ctx.progress(0.3, "Lendo o cadastro")
    fundos, classes = read_cadastro_zip(raw.path)
    ctx.log(f"registro_fundo: {len(fundos)} linhas; registro_classe: {len(classes)} linhas")
    rows, names = build_cadastro(fundos, classes)
    ctx.progress(0.7, "Gravando o cadastro")
    with ctx.connect() as conn:
        n = store_cadastro(conn, rows, names)
        if raw.id:
            mark_loaded(conn, raw.id, LOADER_CAD, n)
        upd = apply_cadastro(conn)
    return JobResult(rows_changed=n, sources=(SRC_CAD,), data_date=datetime.now(TZ).date(),
                     message=f"{n} classes/fundos no cadastro; {upd} FIDCs atualizados")


def load_local(conn: psycopg.Connection, zip_or_dir: str) -> int:
    """Developer helper: load one month from a local zip or a folder of the month's CSVs (no download)."""
    from pathlib import Path
    p = Path(zip_or_dir)
    if p.is_dir():
        tables = {}
        names = [str(x) for x in p.iterdir()]
        for t in TABLES:
            m = find_member(names, t)
            if m:
                tables[t] = read_csv_bytes(Path(m).read_bytes())
    else:
        tables = read_zip(str(p))
    built = build_month(tables)
    n = store_month(conn, built, None)
    apply_cadastro(conn)
    return n
