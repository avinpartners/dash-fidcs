"""Conferência com a CVM: compares what the dashboard shows with the raw CVM files it downloaded.

Deliberately independent from app/ingest/cvm_fidc.py (it reads the zips again with plain csv and its own rules),
so a bug in the loader shows up here as a divergence instead of being repeated.

Checked for every FIDC in the dashboard:
  cadastro (registro_fundo / registro_classe): gestora(s), administrador, custodiante, situação;
  informe mensal of the latest month: PL, ativo, carteira, cotistas; and that every fund of the informe is listed.
When the CVM itself has two rows for the same CNPJ with different values, a match with either counts as correct.

    python -m app.validacao            # prints the report (JSON)
"""
import collections
import csv
import io
import json
import logging
import re
import sys
import zipfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.api.common import connection
from app.core.config import get_settings

log = logging.getLogger("dash.validacao")

CAD_URL = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip"
MAX_EXEMPLOS = 25
TOL = Decimal("0.01")
LABELS = {
    "gestor": "Gestora(s)", "administrador": "Administrador", "custodiante": "Custodiante", "situacao": "Situação",
    "pl": "PL", "ativo": "Ativo", "carteira": "Carteira", "cotistas": "Cotistas",
    "sem_cadastro": "FIDC sem cadastro na CVM", "faltando": "No informe da CVM, mas fora do dash",
}


def _digits(s: str | None) -> str:
    d = re.sub(r"\D", "", s or "")
    return d.zfill(14) if d else ""


def _dec(s: str | None) -> Decimal | None:
    try:
        return Decimal(s) if s not in (None, "") else None
    except InvalidOperation:
        return None


def _read(zf: zipfile.ZipFile, pattern: str) -> list[dict[str, str]]:
    name = next((n for n in zf.namelist() if re.search(pattern, n, re.IGNORECASE)), None)
    if name is None:
        raise ValueError(f"arquivo {pattern} não encontrado no zip")
    return list(csv.DictReader(io.StringIO(zf.read(name).decode("latin1")), delimiter=";"))


def _raw_path(sha: str) -> Path:
    return Path(get_settings().raw_data_dir) / sha[:2] / sha


def _latest_raw(conn, url_like: str) -> tuple[Path, str, datetime] | None:
    r = conn.execute("SELECT sha256, url, fetched_at FROM raw_files WHERE url LIKE %s ORDER BY fetched_at DESC LIMIT 1",
                     (url_like,)).fetchone()
    if not r:
        return None
    p = _raw_path(r[0].strip())
    return (p, r[1], r[2]) if p.exists() else None


def run() -> dict[str, Any]:
    out: dict[str, Any] = {"gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ok": False,
                           "competencia": None, "arquivos": {}, "conferidos": {}, "divergencias": {},
                           "exemplos": {}, "informativo": {}, "rotulos": LABELS, "erro": None}
    try:
        _run(out)
        out["ok"] = not any(out["divergencias"].values())
    except Exception as exc:  # the report says what went wrong; it never breaks the publication
        log.exception("validação falhou")
        out["erro"] = f"{type(exc).__name__}: {exc}"
    return out


def _run(out: dict[str, Any]) -> None:
    with connection() as conn:
        comp = conn.execute("SELECT max(competencia) FROM fidc_mensal").fetchone()[0]
        if comp is None:
            raise ValueError("banco sem informe mensal")
        out["competencia"] = comp.isoformat()
        cad = _latest_raw(conn, CAD_URL)
        inf = _latest_raw(conn, f"%inf_mensal_fidc_{comp:%Y%m}.zip")
        rows = conn.execute("""
            SELECT f.cnpj, f.nome, f.gestor, f.administrador, f.custodiante, f.situacao,
                   m.pl, m.ativo, m.carteira, m.cotistas
            FROM fidcs f LEFT JOIN fidc_mensal m ON m.cnpj = f.cnpj AND m.competencia = %s""", (comp,)).fetchall()
    if cad is None or inf is None:
        raise ValueError("arquivos da CVM não encontrados no cache (rode as atualizações primeiro)")
    out["arquivos"] = {"cadastro": {"url": cad[1], "baixado_em": cad[2].isoformat(timespec="seconds")},
                       "informe": {"url": inf[1], "baixado_em": inf[2].isoformat(timespec="seconds")}}

    with zipfile.ZipFile(cad[0]) as zf:
        fundos = _read(zf, r"(^|/)registro_fundo\.csv$")
        classes = _read(zf, r"(^|/)registro_classe\.csv$")
    with zipfile.ZipFile(inf[0]) as zf:
        t1 = _read(zf, r"tab_I_\d{6}\.csv$")
        t4 = _read(zf, r"tab_IV_\d{6}\.csv$")
        tx1 = _read(zf, r"tab_X_1_\d{6}\.csv$")

    # cadastro, read the way a person would: every row of a fund ID is one of its gestoras
    gest = collections.defaultdict(list)
    fund_by_id: dict[str, dict[str, str]] = {}
    fund_by_cnpj = collections.defaultdict(list)
    for f in fundos:
        fund_by_id.setdefault(f["ID_Registro_Fundo"], f)
        fund_by_cnpj[_digits(f["CNPJ_Fundo"])].append(f)
        g = (f.get("Gestor") or "").strip()
        if g and g not in gest[f["ID_Registro_Fundo"]]:
            gest[f["ID_Registro_Fundo"]].append(g)
    cls_by_cnpj = collections.defaultdict(list)
    for c in classes:
        cls_by_cnpj[_digits(c["CNPJ_Classe"])].append(c)

    # informe: every value the CVM gives for a CNPJ (it sometimes has two rows)
    def values(table: list[dict[str, str]], col: str) -> dict[str, set[Decimal]]:
        v: dict[str, set[Decimal]] = collections.defaultdict(set)
        for r in table:
            x = _dec(r.get(col))
            if x is not None:
                v[_digits(r["CNPJ_FUNDO_CLASSE"])].add(x)
        return v
    pl_v, at_v, ca_v = values(t4, "TAB_IV_A_VL_PL"), values(t1, "TAB_I_VL_ATIVO"), values(t1, "TAB_I2_VL_CARTEIRA")
    cot: dict[str, int] = collections.Counter()
    for r in tx1:
        n = _dec(r.get("TAB_X_NR_COTST"))
        if n and n > 0:
            cot[_digits(r["CNPJ_FUNDO_CLASSE"])] += int(n)
    adm_inf = {_digits(r["CNPJ_FUNDO_CLASSE"]): _digits(r.get("CNPJ_ADMIN")) for r in t1}

    conferidos: collections.Counter = collections.Counter()
    prob: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    adm_mudou = 0

    def bad(campo: str, cnpj: str, nome: str, dash: Any, cvm: Any) -> None:
        prob[campo].append({"cnpj": cnpj, "nome": nome, "dash": dash, "cvm": cvm})

    for cnpj, nome, gestor, admin, cust, sit, pl, ativo, carteira, cotistas in rows:
        cnpj = cnpj.strip()
        cs = cls_by_cnpj.get(cnpj)
        if cs:
            c = max(cs, key=lambda c: (c["Situacao"] == "Em Funcionamento Normal", c["Data_Registro"]))
            f = fund_by_id.get(c["ID_Registro_Fundo"], {})
            exp_g, exp_cust = gest.get(c["ID_Registro_Fundo"], []), (c.get("Custodiante") or "").strip()
            exp_sit = (c.get("Situacao") or "").strip()
        elif fund_by_cnpj.get(cnpj):
            f = max(fund_by_cnpj[cnpj], key=lambda f: (f["Situacao"] != "Cancelado", f["Data_Registro"]))
            exp_g, exp_cust, exp_sit = gest.get(f["ID_Registro_Fundo"], []), None, (f.get("Situacao") or "").strip()
        else:
            conferidos["sem_cadastro"] += 1
            bad("sem_cadastro", cnpj, nome, "no dash", "sem registro")
            continue
        conferidos["sem_cadastro"] += 1
        got_g = [g for g in (gestor or "").split("; ") if g]
        conferidos["gestor"] += 1
        if set(got_g) != set(exp_g):
            bad("gestor", cnpj, nome, " · ".join(got_g) or None, " · ".join(exp_g) or None)
        exp_admin = (f.get("Administrador") or "").strip()
        conferidos["administrador"] += 1
        if (admin or "") != exp_admin:
            bad("administrador", cnpj, nome, admin, exp_admin or None)
        if exp_cust is not None:
            conferidos["custodiante"] += 1
            if (cust or "") != exp_cust:
                bad("custodiante", cnpj, nome, cust, exp_cust or None)
        conferidos["situacao"] += 1
        if (sit or "") != exp_sit:
            bad("situacao", cnpj, nome, sit, exp_sit or None)

        if cnpj in pl_v or cnpj in at_v:
            for campo, got, exp in (("pl", pl, pl_v.get(cnpj, set())), ("ativo", ativo, at_v.get(cnpj, set())),
                                    ("carteira", carteira, ca_v.get(cnpj, set()))):
                conferidos[campo] += 1
                if not exp and got is None:
                    continue
                if got is None or not any(abs(Decimal(got) - e) <= TOL for e in exp):
                    bad(campo, cnpj, nome, None if got is None else float(got),
                        " ou ".join(f"{float(e):.2f}" for e in sorted(exp)) or None)
            conferidos["cotistas"] += 1
            if (cotistas or None) != (cot.get(cnpj) or None):
                bad("cotistas", cnpj, nome, cotistas, cot.get(cnpj))
            # compared by CNPJ: the informe spells names differently (accents, abbreviations)
            if adm_inf.get(cnpj) and _digits(f.get("CNPJ_Administrador")) and adm_inf[cnpj] != _digits(f.get("CNPJ_Administrador")):
                adm_mudou += 1

    no_dash = {r[0].strip() for r in rows}
    no_informe = set(pl_v) | set(at_v)
    conferidos["faltando"] = len(no_informe)
    nomes_inf = {_digits(r["CNPJ_FUNDO_CLASSE"]): (r.get("DENOM_SOCIAL") or "").strip() for r in t1}
    for c in sorted(no_informe - no_dash):
        bad("faltando", c, nomes_inf.get(c, ""), None, "no informe")

    out["conferidos"] = dict(conferidos)
    out["divergencias"] = {k: len(prob.get(k, [])) for k in conferidos}
    out["exemplos"] = {k: v[:MAX_EXEMPLOS] for k, v in prob.items()}
    out["informativo"] = {
        "administrador_mudou": adm_mudou,
        "texto": "Fundos cujo administrador no informe do mês difere do cadastro atual (troca de administrador "
                 "depois do mês do informe). O dash mostra o do cadastro atual.",
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(json.dumps(run(), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
