"""Static export for the online version (GitHub Pages).

Answers every API route the screens use and writes each answer as a JSON file, so the built frontend
works as a plain website without server or database:

    python -m app.export_static <out_dir>        # e.g. ../frontend/public/data

Run it after the jobs (python -m app.jobs.runner fidc_cadastro fidc_informe_mensal). It uses the same
FastAPI routes as the local app (TestClient, no lifespan: no scheduler, no worker), so the numbers are
the same as on the notebook.
"""
import json
import logging
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.common import connection
from app.core.db import run_migrations
from app.main import app

log = logging.getLogger("dash.export")


def _write(path: Path, data) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.write_text(raw, encoding="utf-8")
    return len(raw)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    out = Path(argv[0] if argv else "static_data").resolve()
    run_migrations()
    client = TestClient(app)          # not used as a context manager: the lifespan (job worker) never starts

    def get(path: str):
        r = client.get("/api" + path)
        if r.status_code != 200:
            raise RuntimeError(f"{path}: HTTP {r.status_code} {r.text[:200]}")
        return r.json()

    t0, total = time.time(), 0
    for name, path in (("fidcs", "/fidcs"), ("home", "/home"), ("gestoras", "/gestoras"),
                       ("administradores", "/administradores"), ("custodiantes", "/custodiantes"),
                       ("cedentes", "/cedentes"), ("status", "/status")):
        total += _write(out / f"{name}.json", get(path))

    status = json.loads((out / "status.json").read_text(encoding="utf-8"))
    for run in status.get("runs", []):
        total += _write(out / "runs" / f"{run['id']}.json", get(f"/jobs/runs/{run['id']}"))

    with connection() as conn:
        fund_ids = [r[0].strip() for r in conn.execute("SELECT cnpj FROM fidcs ORDER BY cnpj").fetchall()]
        ced_ids = [r[0] for r in conn.execute(
            "SELECT DISTINCT cnpj_cedente FROM fidc_cedentes ORDER BY cnpj_cedente").fetchall()]
        ced_names = dict(conn.execute(
            "SELECT e.cnpj, e.nome FROM entidades e WHERE e.cnpj IN (SELECT cnpj_cedente FROM fidc_cedentes)").fetchall())

    for i, c in enumerate(fund_ids, 1):
        total += _write(out / "fidc" / f"{c}.json", get(f"/fidcs/{c}"))
        if i % 500 == 0:
            log.info("fundos: %d de %d", i, len(fund_ids))
    for c in ced_ids:
        total += _write(out / "cedente" / f"{c}.json", get(f"/cedentes/{c}"))

    # Search index for the Ctrl+K search (done in the browser in the online version).
    with connection() as conn:
        all_funds = [(r[0].strip(), r[1], r[2]) for r in conn.execute("SELECT cnpj, nome, gestor FROM fidcs").fetchall()]
        groups = {col: conn.execute(f"""SELECT {col}, count(*) FROM fidcs WHERE {col} IS NOT NULL
                                        GROUP BY {col} ORDER BY count(*) DESC""").fetchall()
                  for col in ("gestor", "administrador")}
    total += _write(out / "search.json", {
        "fidcs": [[c, n, g] for c, n, g in all_funds],
        "cedentes": [[c, ced_names.get(c)] for c in ced_ids],
        "gestoras": [list(g) for g in groups["gestor"]],
        "administradores": [list(g) for g in groups["administrador"]],
    })
    total += _write(out / "meta.json", {"gerado_em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                        "fundos": len(fund_ids), "cedentes": len(ced_ids)})
    log.info("exportado: %d fundos, %d cedentes, %.1f MB em %.0f s", len(fund_ids), len(ced_ids),
             total / 1e6, time.time() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
