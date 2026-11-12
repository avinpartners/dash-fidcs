// Cedentes: the company CNPJs FIDCs report as their largest cedentes, and which FIDCs each one feeds.
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, saveText } from "../api";
import { Card, Empty, ErrorBox, Loading } from "../components/ui";
import { fmtBRLCompact, fmtInt, fmtMonth, fmtPct, fold } from "../format";
import { useApi, useDocumentTitle } from "../lib/hooks";

export function CedentesList() {
  useDocumentTitle("Cedentes");
  const { data, error, reload } = useApi((s) => api.cedentes(s), []);
  const [q, setQ] = useState("");
  const rows = useMemo(() => {
    const f = fold(q.trim()), dg = q.replace(/\D/g, "");
    return (data?.rows ?? []).filter((r) => !q.trim() || (dg.length >= 4 && r.cnpj_cedente.includes(dg)) || fold(r.nome ?? "").includes(f)
      || (r.gestoras ?? []).some((g) => fold(g).includes(f)));
  }, [data, q]);
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return <Loading />;
  const exportCsv = () => saveText(["CNPJ;Nome;FIDCs;Peso medio;Peso max;PL dos FIDCs;Segmento;Gestoras",
    ...rows.map((r) => [r.cnpj_cedente_fmt, r.nome ?? "", r.fidcs, String(r.peso_medio ?? "").replace(".", ","),
      String(r.peso_max ?? "").replace(".", ","), String(r.pl_fidcs ?? "").replace(".", ","), r.segmento ?? "",
      (r.gestoras ?? []).join(" | ")].join(";"))].join("\r\n"), `cedentes_${data.competencia ?? ""}.csv`);
  return (
    <>
      <div className="page-head">
        <div><h1>Cedentes</h1>
          <div className="muted">{fmtInt(rows.length)} CNPJs informados como maiores cedentes · informe de {fmtMonth(data.competencia, true)}.
            Só parte dos fundos preenche este campo; CPFs não são guardados.</div></div>
        <div className="toolbar"><button className="btn" onClick={exportCsv}>Exportar CSV</button></div>
      </div>
      <div className="filters">
        <input className="input" style={{ minWidth: 320 }} placeholder="CNPJ, nome do cedente ou gestora" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="card" style={{ padding: 0 }}>
        <div className="table-box" style={{ maxHeight: "calc(100vh - 220px)" }}>
          <table className="grid compact">
            <thead><tr><th>CNPJ</th><th>Nome (cadastro CVM)</th><th className="num">FIDCs</th><th className="num">Peso médio</th>
              <th className="num">Peso máx.</th><th className="num">PL dos FIDCs</th><th>Segmento</th><th>Gestoras</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.cnpj_cedente}>
                <td className="mono"><Link to={`/cedentes/${r.cnpj_cedente}`}>{r.cnpj_cedente_fmt}</Link></td>
                <td className="small">{r.nome ?? <span className="muted">—</span>}</td><td className="num">{fmtInt(r.fidcs)}</td>
                <td className="num">{fmtPct(r.peso_medio, 1)}</td><td className="num">{fmtPct(r.peso_max, 1)}</td>
                <td className="num">{fmtBRLCompact(r.pl_fidcs)}</td><td className="small">{r.segmento ?? "—"}</td>
                <td className="small"><span className="ellipsis" style={{ maxWidth: 360 }} title={(r.gestoras ?? []).join(", ")}>{(r.gestoras ?? []).join(", ") || "—"}</span></td>
              </tr>))}</tbody>
          </table>
        </div>
      </div>
    </>
  );
}

export function CedentePage() {
  const { cnpj = "" } = useParams();
  const { data, error, reload } = useApi((s) => api.cedente(cnpj, s), [cnpj]);
  useDocumentTitle(data?.nome ?? `Cedente ${data?.cnpj_fmt ?? ""}`);
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return <Loading />;
  const last = data.rows[0]?.competencia;
  const atual = data.rows.filter((r) => r.competencia === last);
  const hist = data.rows.filter((r) => r.competencia !== last);
  return (
    <>
      <div className="page-head"><div>
        <div className="small muted"><Link to="/cedentes">Cedentes</Link> ›</div>
        <h1>{data.nome ?? "Cedente"}</h1><div className="mono muted">{data.cnpj_fmt}</div>
      </div></div>
      <Card title={`FIDCs que informaram este cedente${last ? ` em ${fmtMonth(last, true)}` : ""}`}>
        {!atual.length ? <Empty>Nenhum FIDC informou este CNPJ.</Empty> : (
          <table className="grid compact"><thead><tr><th>FIDC</th><th>Gestor</th><th>Segmento</th><th className="num">Peso do cedente</th><th className="num">PL do FIDC</th></tr></thead>
            <tbody>{atual.map((r) => (
              <tr key={r.cnpj}><td><Link to={`/fidcs/${r.cnpj}`}>{r.nome}</Link></td><td className="small">{r.gestor ?? "—"}</td>
                <td className="small">{r.segmento ?? "—"}</td><td className="num">{fmtPct(r.pct, 1)}</td><td className="num">{fmtBRLCompact(r.pl)}</td></tr>))}</tbody></table>
        )}
      </Card>
      {hist.length > 0 && (
        <Card title="Meses anteriores">
          <div className="table-box"><table className="grid compact"><thead><tr><th>Competência</th><th>FIDC</th><th className="num">Peso</th><th className="num">PL</th></tr></thead>
            <tbody>{hist.map((r) => (
              <tr key={`${r.competencia}-${r.cnpj}`}><td>{fmtMonth(r.competencia)}</td><td><Link to={`/fidcs/${r.cnpj}`}>{r.nome}</Link></td>
                <td className="num">{fmtPct(r.pct, 1)}</td><td className="num">{fmtBRLCompact(r.pl)}</td></tr>))}</tbody></table></div>
        </Card>
      )}
    </>
  );
}
