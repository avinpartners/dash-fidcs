// Gestoras, administradores and custodiantes: each one's FIDCs summed at the latest month (PL leaves FIC-FIDC out).
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, saveText, type GroupRow } from "../api";
import { ErrorBox, Loading, ShareBar } from "../components/ui";
import { fmtBRLCompact, fmtInt, fmtMonth, fmtPct, fold } from "../format";
import { useApi, useDocumentTitle } from "../lib/hooks";

type Kind = "gestoras" | "administradores" | "custodiantes";
const TITLE: Record<Kind, string> = { gestoras: "Gestoras", administradores: "Administradores", custodiantes: "Custodiantes" };
const PARAM: Record<Kind, string> = { gestoras: "gestor", administradores: "administrador", custodiantes: "custodiante" };

const COLS: { key: keyof GroupRow; label: string; num?: boolean }[] = [
  { key: "nome", label: "Nome" }, { key: "fundos", label: "FIDCs", num: true }, { key: "pl", label: "PL", num: true },
  { key: "captacao_liquida", label: "Capt. líq. no mês", num: true }, { key: "cotistas", label: "Cotistas", num: true },
  { key: "sub_mediana", label: "Subord. mediana", num: true }, { key: "inad_mediana", label: "Inad. mediana", num: true },
  { key: "segmento_principal", label: "Segmento mais comum" }, { key: "em_liquidacao", label: "Em liquidação / cancel.", num: true },
];

export default function Groups({ kind }: { kind: Kind }) {
  useDocumentTitle(TITLE[kind]);
  const { data, error, reload } = useApi((s) => api.group(kind, s), [kind]);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<keyof GroupRow>("pl");
  const [desc, setDesc] = useState(true);
  const rows = useMemo(() => {
    const f = fold(q.trim());
    const out = (data?.rows ?? []).filter((r) => !f || fold(r.nome).includes(f));
    return out.sort((a, b) => {
      const x = a[sort], y = b[sort];
      if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1;
      const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "pt-BR");
      return desc ? -c : c;
    });
  }, [data, q, sort, desc]);
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return <Loading />;
  const total = (data.rows ?? []).reduce((a, r) => a + (r.pl ?? 0), 0);
  const maxPl = Math.max(...rows.map((r) => r.pl ?? 0), 1);
  const exportCsv = () => saveText([COLS.map((c) => c.label).join(";"), ...rows.map((r) => COLS.map((c) => {
    const v = r[c.key]; return typeof v === "number" ? String(v).replace(".", ",") : String(v ?? "").replace(/;/g, ",");
  }).join(";"))].join("\r\n"), `${kind}_${data.competencia ?? ""}.csv`);
  return (
    <>
      <div className="page-head">
        <div><h1>{TITLE[kind]}</h1>
          <div className="muted">{fmtInt(rows.length)} nomes · PL somado {fmtBRLCompact(total)} (sem FIC-FIDC) · informe de {fmtMonth(data.competencia, true)}</div></div>
        <div className="toolbar"><button className="btn" onClick={exportCsv}>Exportar CSV</button></div>
      </div>
      <div className="filters">
        <input className="input" style={{ minWidth: 280 }} placeholder="Buscar nome" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="card" style={{ padding: 0 }}>
        <div className="table-box" style={{ maxHeight: "calc(100vh - 220px)" }}>
          <table className="grid compact">
            <thead><tr>{COLS.map((c) => (
              <th key={c.key} className={c.num ? "num" : undefined}>
                <button className="th-btn" onClick={() => { if (sort === c.key) setDesc(!desc); else { setSort(c.key); setDesc(!!c.num); } }}>
                  {c.label}{sort === c.key ? (desc ? " ↓" : " ↑") : ""}</button></th>))}
              <th style={{ width: 140 }}>Participação</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.nome}>
                <td><Link to={`/fidcs?${PARAM[kind]}=${encodeURIComponent(r.nome)}`}>{r.nome}</Link></td>
                <td className="num">{fmtInt(r.fundos)}</td><td className="num">{fmtBRLCompact(r.pl)}</td>
                <td className={`num ${r.captacao_liquida == null ? "" : r.captacao_liquida >= 0 ? "pos" : "neg"}`}>{fmtBRLCompact(r.captacao_liquida)}</td>
                <td className="num">{fmtInt(r.cotistas)}</td><td className="num">{fmtPct(r.sub_mediana, 1)}</td>
                <td className="num">{fmtPct(r.inad_mediana, 1)}</td><td className="small">{r.segmento_principal ?? "—"}</td>
                <td className="num">{r.em_liquidacao ? fmtInt(r.em_liquidacao) : "—"}</td>
                <td title={fmtPct(total ? (r.pl ?? 0) / total : null, 1)}><ShareBar v={r.pl ?? 0} max={maxPl} /></td>
              </tr>))}</tbody>
          </table>
        </div>
      </div>
    </>
  );
}
