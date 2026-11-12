// Início: the FIDC market at the latest month (CVM informe mensal), its history, who leads it and what changed.
import { Link } from "react-router-dom";
import { api, fidcList, type FidcRow, type HomeMonth } from "../api";
import { EChart } from "../components/EChart";
import { Card, Empty, ErrorBox, Kpi, Loading } from "../components/ui";
import { barsH, monthChart } from "../charts/fidc";
import { fmtBRLCompact, fmtDate, fmtInt, fmtIntCompact, fmtMonth, fmtPct, fmtPctSigned } from "../format";
import { useApi, useDocumentTitle } from "../lib/hooks";

function delta(cur: number | null | undefined, prev: number | null | undefined) {
  if (cur == null || prev == null || !prev) return null;
  return cur / prev - 1;
}

function DeltaSub({ v, label = "vs. mês anterior" }: { v: number | null; label?: string }) {
  if (v == null) return <span className="muted">—</span>;
  return <span className={v >= 0 ? "pos" : "neg"}>{fmtPctSigned(v, 1)} <span className="muted">{label}</span></span>;
}

function sumBy(rows: FidcRow[], key: (r: FidcRow) => string | null, val: (r: FidcRow) => number): [string, number][] {
  const m = new Map<string, number>();
  rows.forEach((r) => { const k = key(r); if (k) m.set(k, (m.get(k) ?? 0) + val(r)); });
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}

export function Home() {
  useDocumentTitle("Início");
  const h = useApi((s) => api.home(s), []);
  const list = useApi(() => fidcList(), []);
  if (h.error) return <ErrorBox error={h.error} onRetry={h.reload} />;
  if (!h.data) return <Loading />;
  const d = h.data;
  if (!d.competencia) {
    return (
      <div className="page-narrow">
        <h1>Dash FIDCs</h1>
        <Empty>Ainda não há dados. A primeira carga começa sozinha alguns segundos depois de abrir o app; acompanhe em{" "}
          <Link to="/status">Status dos dados</Link>.</Empty>
      </div>
    );
  }
  const hist = d.historico;
  const last: HomeMonth = hist[hist.length - 1];
  const prev: HomeMonth | undefined = hist[hist.length - 2];
  const months = hist.map((m) => m.competencia);
  const rows = list.data?.rows ?? [];
  const semFic = rows.filter((r) => r.estrutura === "FIDC");
  const segNames = [...new Set(d.segmentos_historico.map((s) => s.segmento))];
  const segTotals = segNames.map((n) => [n, d.segmentos_historico.filter((s) => s.segmento === n && s.competencia === d.competencia)
    .reduce((a, s) => a + (s.pl ?? 0), 0)] as [string, number]).sort((a, b) => b[1] - a[1]);
  const topSegs = segTotals.slice(0, 6).map((s) => s[0]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Mercado de FIDCs</h1>
          <div className="muted">Informe mensal da CVM · competência {fmtMonth(d.competencia, true)} · {fmtInt(last.fundos)} fundos e classes</div>
        </div>
        <div className="toolbar">
          <Link className="btn" to="/fidcs">Ver todos os FIDCs</Link>
          <button className="btn" onClick={() => window.dispatchEvent(new CustomEvent("dash:search", { detail: "" }))}>Buscar…</button>
        </div>
      </div>

      <div className="kpis">
        <Kpi label="FIDCs que entregaram o informe" value={fmtInt(last.fundos)} sub={<DeltaSub v={delta(last.fundos, prev?.fundos)} />} />
        <Kpi label="Patrimônio líquido (sem FIC-FIDC)" value={fmtBRLCompact(last.pl)} sub={<DeltaSub v={delta(last.pl, prev?.pl)} />} />
        <Kpi label="Captação líquida no mês" value={fmtBRLCompact(last.captacao_liquida)} sub={<span className="muted">captações − resgates − amortizações</span>} />
        <Kpi label="Cotistas" value={fmtIntCompact(last.cotistas)} sub={<DeltaSub v={delta(last.cotistas, prev?.cotistas)} />} />
        <Kpi label="Inadimplência do mercado" value={fmtPct(last.inad_agregada)} sub={<span className="muted">mediana por fundo {fmtPct(last.inad_mediana)}</span>} />
        <Kpi label="Subordinação mediana" value={fmtPct(last.sub_mediana)} sub={<span className="muted">subordinada + mezanino</span>} />
      </div>

      <div className="two-col" style={{ marginTop: 12 }}>
        <Card title="Patrimônio e número de fundos" subtitle="PL somado sem FIC-FIDC (barras) e fundos que entregaram o informe (linha)">
          <EChart height={280} fileName="pl-fundos" ariaLabel="PL e número de fundos por mês" deps={[hist]}
                  build={(t) => monthChart(t, months, [
                    { name: "PL", data: hist.map((m) => m.pl), kind: "bar" },
                    { name: "Fundos", data: hist.map((m) => m.fundos), axis: 1 },
                  ], "brl", "int")} />
        </Card>
        <Card title="PL por segmento" subtitle="Maior segmento da carteira de cada fundo, como declarado à CVM (sem FIC-FIDC)">
          <EChart height={280} fileName="pl-segmento" ariaLabel="PL por segmento ao longo dos meses" deps={[d.segmentos_historico]}
                  build={(t) => monthChart(t, months, topSegs.map((sg) => ({
                    name: sg, kind: "bar", stack: "s",
                    data: months.map((m) => d.segmentos_historico.find((s) => s.competencia === m && s.segmento === sg)?.pl ?? null),
                  })), "brl")} />
        </Card>
      </div>

      <div className="two-col">
        <Card title="Captação líquida por mês">
          <EChart height={240} fileName="captacao" ariaLabel="Captação líquida por mês" deps={[hist]}
                  build={(t) => monthChart(t, months, [{ name: "Captação líquida", data: hist.map((m) => m.captacao_liquida), kind: "bar" }], "brl")} />
        </Card>
        <Card title="Inadimplência e subordinação">
          <EChart height={240} fileName="risco" ariaLabel="Inadimplência e subordinação por mês" deps={[hist]}
                  build={(t) => monthChart(t, months, [
                    { name: "Inadimplência do mercado", data: hist.map((m) => m.inad_agregada) },
                    { name: "Inadimplência mediana", data: hist.map((m) => m.inad_mediana) },
                    { name: "Subordinação mediana", data: hist.map((m) => m.sub_mediana) },
                  ], "pct")} />
        </Card>
      </div>

      {list.error ? <ErrorBox error={list.error} onRetry={list.reload} /> : !list.data ? <Loading label="Carregando os fundos…" /> : (
        <div className="two-col">
          <Card title="Maiores gestoras por PL" actions={<Link className="btn btn-sm" to="/gestoras">Todas</Link>}>
            <EChart height={320} fileName="gestoras" ariaLabel="Maiores gestoras" deps={[rows]}
                    build={(t) => barsH(t, sumBy(semFic, (r) => r.gestor, (r) => r.pl ?? 0).slice(0, 12), "brl")} />
          </Card>
          <Card title="Quem investe nos FIDCs" subtitle="Fundos por tipo de cotista predominante (mais da metade dos cotistas)">
            <EChart height={320} fileName="alocadores" ariaLabel="Fundos por tipo de alocador" deps={[rows]}
                    build={(t) => barsH(t, sumBy(rows, (r) => r.alocador_tipo, () => 1).slice(0, 12), "int")} />
          </Card>
        </div>
      )}

      <div className="two-col">
        <Card title="Constituídos mais recentemente" subtitle="Data de constituição no cadastro da CVM">
          <div className="table-box">
            <table className="grid compact" style={{ tableLayout: "fixed" }}>
              <colgroup><col style={{ width: "44%" }} /><col style={{ width: "28%" }} /><col style={{ width: "14%" }} /><col style={{ width: "14%" }} /></colgroup>
              <thead><tr><th>FIDC</th><th>Gestor</th><th>Constituição</th><th className="num">PL</th></tr></thead>
              <tbody>{d.novos.map((n) => (
                <tr key={n.cnpj}><td className="wrap"><Link to={`/fidcs/${n.cnpj}`}>{n.nome}</Link></td><td className="small wrap">{n.gestor ?? "—"}</td>
                  <td>{fmtDate(n.data_constituicao)}</td><td className="num">{fmtBRLCompact(n.pl)}</td></tr>))}</tbody>
            </table>
          </div>
        </Card>
        <Card title="Entraram em liquidação ou foram cancelados" subtitle="Situação no cadastro atual da CVM, os mais recentes primeiro">
          <div className="table-box">
            <table className="grid compact" style={{ tableLayout: "fixed" }}>
              <colgroup><col style={{ width: "46%" }} /><col style={{ width: "18%" }} /><col style={{ width: "16%" }} /><col style={{ width: "20%" }} /></colgroup>
              <thead><tr><th>FIDC</th><th>Situação</th><th>Desde</th><th className="num">PL no cadastro</th></tr></thead>
              <tbody>{d.liquidacao.map((n) => (
                <tr key={n.cnpj}><td className="wrap"><Link to={`/fidcs/${n.cnpj}`}>{n.nome}</Link></td><td className="small">{n.situacao}</td>
                  <td>{fmtDate(n.data_situacao)}</td><td className="num">{fmtBRLCompact(n.pl)}</td></tr>))}</tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  );
}
