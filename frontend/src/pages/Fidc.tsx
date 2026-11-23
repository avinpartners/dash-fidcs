// A FIDC's page: identification from the CVM register, the latest informe and its history month by month.
import { Link, useParams } from "react-router-dom";
import { api, type Mensal } from "../api";
import { EChart } from "../components/EChart";
import { Card, Empty, ErrorBox, KV, Kpi, Loading, SituacaoTag } from "../components/ui";
import { barsH, barsV, monthChart } from "../charts/fidc";
import { fmtBRL, fmtBRLCompact, fmtBRLCota, fmtDate, fmtInt, fmtMonth, fmtNumber, fmtPct, fmtPctSigned, gestoras } from "../format";
import { useApi, useDocumentTitle } from "../lib/hooks";

const AGING_LABEL: Record<string, string> = {
  "30": "até 30 d", "60": "31–60", "90": "61–90", "120": "91–120", "150": "121–150", "180": "151–180", "360": "181–360",
  "720": "361–720", "1080": "721–1080", MAIOR_1080: "> 1080",
};
const LIQ_LABEL: Record<string, string> = { "0": "imediata", "30": "até 30 d", "60": "até 60 d", "90": "até 90 d", "180": "até 180 d", "360": "até 360 d", MAIOR_360: "> 360 d" };
const SCR = ["AA", "A", "B", "C", "D", "E", "F", "G", "H"];

const yes = (v: unknown) => (v === true ? "Sim" : v === false ? "Não" : "—");
const txt = (v: unknown) => (v == null || v === "" ? "—" : String(v));

function bucket(d: Record<string, number> | null, labels: Record<string, string>) {
  const keys = Object.keys(labels);
  return { labels: keys.map((k) => labels[k]), values: keys.map((k) => d?.[k] ?? 0) };
}

export default function Fidc() {
  const { cnpj = "" } = useParams();
  const { data, error, reload } = useApi((s) => api.fidc(cnpj, s), [cnpj]);
  useDocumentTitle(data?.fidc.nome ?? "FIDC");
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return <Loading />;
  const f = data.fidc;
  const h = data.historico;
  const last: Mensal | undefined = h[h.length - 1];
  const p12 = h.length > 12 ? h[h.length - 13] : undefined;
  const months = h.map((m) => m.competencia);
  const capLiq = last ? (last.captacao ?? 0) - (last.resgate ?? 0) - (last.amortizacao ?? 0) : null;
  const fic = (last?.cotas_fidc_pct ?? 0) >= 0.5;

  return (
    <>
      <div className="page-head">
        <div>
          <div className="small muted"><Link to="/fidcs">FIDCs</Link> ›</div>
          <h1 style={{ marginBottom: 4 }}>{f.nome}</h1>
          <div className="toolbar small">
            <span className="mono">{f.cnpj_fmt}</span>
            <SituacaoTag s={f.situacao} />
            {fic && <span className="tag" title="Carteira com mais da metade em cotas de outros FIDCs">FIC-FIDC</span>}
            {last?.segmento && <span className="tag">{last.segmento}{last.subsegmento && last.subsegmento !== last.segmento ? ` · ${last.subsegmento}` : ""}</span>}
            {f.gestor && <span>{gestoras(f.gestor).length > 1 ? "Gestoras (cogestão)" : "Gestor"}:{" "}
              {gestoras(f.gestor).map((g, i) => <span key={g}>{i > 0 && " · "}<Link to={`/fidcs?gestor=${encodeURIComponent(g)}`}>{g}</Link></span>)}</span>}
            {f.administrador && <span className="muted">· Administrador: <Link to={`/fidcs?administrador=${encodeURIComponent(String(f.administrador))}`}>{String(f.administrador)}</Link></span>}
          </div>
        </div>
        <div className="muted small">{last ? <>Último informe: {fmtMonth(last.competencia, true)}</> : "Sem informe mensal carregado"}</div>
      </div>

      {!last ? <Empty>Este CNPJ ainda não tem informe mensal carregado.</Empty> : (
        <>
          <div className="kpis">
            <Kpi label="Patrimônio líquido" value={fmtBRLCompact(last.pl)}
                 sub={p12?.pl ? <span className={(last.pl ?? 0) >= p12.pl ? "pos" : "neg"}>{fmtPctSigned((last.pl ?? 0) / p12.pl - 1, 1)} <span className="muted">em 12 meses</span></span> : <span className="muted">PL médio {fmtBRLCompact(last.pl_medio)}</span>} />
            <Kpi label="Captação líquida no mês" value={fmtBRLCompact(capLiq)} sub={<span className="muted">capt. {fmtBRLCompact(last.captacao)} · resg. {fmtBRLCompact(last.resgate)} · amort. {fmtBRLCompact(last.amortizacao)}</span>} />
            <Kpi label="Cotistas" value={fmtInt(last.cotistas)} sub={<span className="muted">{last.alocador_tipo ?? "—"}</span>} />
            <Kpi label="Subordinação" value={fmtPct(last.subordinacao, 1)} sub={<span className="muted">subordinada + mezanino</span>} />
            <Kpi label="Inadimplência" value={fmtPct(last.inadimplencia, 2)} sub={<span className="muted">&gt; 90 dias {fmtBRLCompact(last.inad_acima_90)} · PDD/DC {fmtPct(last.pdd_sobre_dc, 1)}</span>} />
            <Kpi label="Rentabilidade no mês" value={fmtPct(last.rentab_senior)} sub={<span className="muted">sênior · subordinada {fmtPct(last.rentab_subordinada)}</span>} />
          </div>

          <div className="two-col" style={{ marginTop: 12 }}>
            <Card title="Patrimônio líquido e cotistas">
              <EChart height={260} fileName="pl" ariaLabel="PL e cotistas por mês" deps={[h]}
                      build={(t) => monthChart(t, months, [
                        { name: "PL", data: h.map((m) => m.pl), kind: "bar" },
                        { name: "Cotistas", data: h.map((m) => m.cotistas), axis: 1 },
                      ], "brl", "int")} />
            </Card>
            <Card title="Estrutura de cotas" subtitle="Valor das cotas por tipo (quantidade × valor da cota)">
              <EChart height={260} fileName="cotas" ariaLabel="Valor das cotas por tipo" deps={[data.series_historico]}
                      build={(t) => monthChart(t, months, ["Sênior", "Mezanino", "Subordinada"].map((tp) => ({
                        name: tp, kind: "bar", stack: "c",
                        data: months.map((m) => data.series_historico.find((s) => s.competencia === m && s.tipo === tp)?.valor ?? null),
                      })), "brl")} />
            </Card>
          </div>
          <div className="two-col">
            <Card title="Inadimplência, PDD e subordinação">
              <EChart height={240} fileName="risco" ariaLabel="Inadimplência, PDD e subordinação" deps={[h]}
                      build={(t) => monthChart(t, months, [
                        { name: "Inadimplência", data: h.map((m) => m.inadimplencia) },
                        { name: "PDD / DC", data: h.map((m) => m.pdd_sobre_dc) },
                        { name: "Subordinação", data: h.map((m) => m.subordinacao) },
                      ], "pct")} />
            </Card>
            <Card title="Rentabilidade mensal">
              <EChart height={240} fileName="rentabilidade" ariaLabel="Rentabilidade sênior e subordinada" deps={[h]}
                      build={(t) => monthChart(t, months, [
                        { name: "Sênior", data: h.map((m) => m.rentab_senior) },
                        { name: "Subordinada", data: h.map((m) => m.rentab_subordinada) },
                      ], "pct")} />
            </Card>
          </div>
          <div className="two-col">
            <Card title="Captações, resgates e amortizações">
              <EChart height={240} fileName="fluxos" ariaLabel="Fluxos mensais" deps={[h]}
                      build={(t) => monthChart(t, months, [
                        { name: "Captações", data: h.map((m) => m.captacao), kind: "bar" },
                        { name: "Resgates", data: h.map((m) => (m.resgate == null ? null : -m.resgate)), kind: "bar", stack: "s" },
                        { name: "Amortizações", data: h.map((m) => (m.amortizacao == null ? null : -m.amortizacao)), kind: "bar", stack: "s" },
                      ], "brl")} />
            </Card>
            <Card title="Carteira por segmento" subtitle={`Direitos creditórios por segmento em ${fmtMonth(last.competencia)}`}>
              {last.segmentos && Object.keys(last.segmentos).length ? (
                <EChart height={240} fileName="segmentos" ariaLabel="Carteira por segmento" deps={[last]}
                        build={(t) => barsH(t, Object.entries(last.segmentos ?? {}), "brl")} />
              ) : <Empty>O fundo não informou direitos creditórios por segmento (comum em FIC-FIDC).</Empty>}
            </Card>
          </div>
          <div className="two-col">
            <Card title="Prazo de vencimento dos direitos creditórios" subtitle="A vencer, por faixa de dias">
              <EChart height={220} fileName="prazo" ariaLabel="Prazo de vencimento" deps={[last]}
                      build={(t) => { const b = bucket(last.prazo_vencimento, AGING_LABEL); return barsV(t, b.labels, b.values, "brl"); }} />
            </Card>
            <Card title="Liquidez da carteira" subtitle="Ativos que viram caixa em até…">
              <EChart height={220} fileName="liquidez" ariaLabel="Liquidez" deps={[last]}
                      build={(t) => { const b = bucket(last.liquidez, LIQ_LABEL); return barsV(t, b.labels, b.values, "brl"); }} />
            </Card>
          </div>
          <div className="two-col">
            <Card title="Rating dos devedores (SCR)" subtitle="Classificação de risco por devedor, Resolução CMN 2.682">
              {last.rating_scr ? (
                <EChart height={220} fileName="scr" ariaLabel="Rating SCR" deps={[last]}
                        build={(t) => barsV(t, SCR, SCR.map((k) => last.rating_scr?.[k] ?? 0), "brl")} />
              ) : <Empty>Não informado.</Empty>}
            </Card>
            <Card title="Cotistas por tipo" subtitle="Sênior e subordinadas somadas">
              {last.cotistas_tipo ? (
                <EChart height={220} fileName="cotistas" ariaLabel="Cotistas por tipo" deps={[last]}
                        build={(t) => barsH(t, Object.entries(last.cotistas_tipo ?? {}), "int")} />
              ) : <Empty>Não informado.</Empty>}
            </Card>
          </div>

          <Card title="Séries e classes de cotas" subtitle={`Informe de ${fmtMonth(last.competencia, true)}`}>
            <div className="table-box">
              <table className="grid compact">
                <thead><tr><th>Série / subclasse</th><th>Tipo</th><th className="num">Cotas</th><th className="num">Valor da cota</th>
                  <th className="num">Valor</th><th className="num">Cotistas</th><th className="num">Rent. mês</th>
                  <th className="num">Desemp. esperado</th><th className="num">Desemp. real</th></tr></thead>
                <tbody>{data.series.map((s) => (
                  <tr key={s.classe_serie}><td>{s.classe_serie}</td><td>{s.tipo}</td><td className="num">{fmtNumber(s.qt_cotas, 0)}</td>
                    <td className="num">{fmtBRLCota(s.vl_cota)}</td><td className="num">{fmtBRLCompact(s.valor)}</td>
                    <td className="num">{fmtInt(s.cotistas)}</td><td className="num">{fmtPct(s.rentab_mes)}</td>
                    <td className="num">{fmtPct(s.desemp_esperado)}</td><td className="num">{fmtPct(s.desemp_real)}</td></tr>))}</tbody>
              </table>
            </div>
          </Card>

          <div className="two-col">
            <Card title="Maiores cedentes" subtitle="CNPJs informados pelo fundo (CPFs não são guardados)">
              {!data.cedentes.length ? <Empty>O fundo não informou cedentes com CNPJ neste mês.</Empty> : (
                <div className="table-box">
                  <table className="grid compact">
                    <thead><tr><th>CNPJ</th><th>Nome (cadastro CVM)</th><th className="num">Peso</th><th className="num">FIDCs com este cedente</th></tr></thead>
                    <tbody>{data.cedentes.map((c) => (
                      <tr key={c.cnpj_cedente}><td className="mono"><Link to={`/cedentes/${c.cnpj_cedente}`}>{c.cnpj_cedente_fmt}</Link></td>
                        <td className="small">{c.nome ?? "—"}</td><td className="num">{fmtPct(c.pct, 1)}</td><td className="num">{fmtInt(c.fidcs)}</td></tr>))}</tbody>
                  </table>
                </div>
              )}
            </Card>
            <Card title="Identificação">
              <dl className="kvs">
                <KV label="CNPJ">{f.cnpj_fmt}</KV>
                <KV label="Tipo">{txt(f.tipo)}</KV>
                {f.nome_fundo && f.nome_fundo !== f.nome && <KV label="Fundo">{f.nome_fundo} ({txt(f.cnpj_fundo_fmt)})</KV>}
                <KV label="Situação">{txt(f.situacao)}{f.data_situacao ? ` desde ${fmtDate(String(f.data_situacao))}` : ""}</KV>
                <KV label="Constituição">{fmtDate(f.data_constituicao as string | null)}</KV>
                <KV label="Adaptação à RCVM 175">{fmtDate(f.adaptacao_175 as string | null)}</KV>
                <KV label={gestoras(f.gestor).length > 1 ? "Gestoras (cogestão)" : "Gestor"}>{f.gestor ? gestoras(f.gestor).join(" · ") : txt(f.gestor)}</KV>
                <KV label="Administrador">{txt(f.administrador)}</KV>
                <KV label="Custodiante">{txt(f.custodiante)}</KV>
                <KV label="Auditor">{txt(f.auditor)}</KV>
                <KV label="Condomínio">{txt(last.condominio ?? f.condominio)}</KV>
                <KV label="Exclusivo">{yes(f.exclusivo)}</KV>
                <KV label="Público-alvo">{txt(f.publico_alvo)}</KV>
                <KV label="PL no cadastro">{fmtBRL(f.pl_cadastro as number | null, 0)}{f.data_pl_cadastro ? ` em ${fmtDate(String(f.data_pl_cadastro))}` : ""}</KV>
                <KV label="Ativo total">{fmtBRLCompact(last.ativo)}</KV>
                <KV label="DC com / sem risco">{fmtBRLCompact(last.dc_com_risco)} / {fmtBRLCompact(last.dc_sem_risco)}</KV>
                <KV label="Garantias">{fmtPct(last.garantia_pct, 1)} dos direitos creditórios</KV>
              </dl>
            </Card>
          </div>
        </>
      )}

      {(data.classes_do_fundo.length > 0 || data.mesma_gestora.length > 0) && (
        <div className="two-col">
          {data.classes_do_fundo.length > 0 && (
            <Card title="Outras classes do mesmo fundo">
              <ul>{data.classes_do_fundo.map((c) => <li key={c.cnpj}><Link to={`/fidcs/${c.cnpj}`}>{c.nome}</Link></li>)}</ul>
            </Card>
          )}
          {data.mesma_gestora.length > 0 && (
            <Card title="Outros FIDCs da gestora" actions={f.gestor && gestoras(f.gestor).length === 1 ? <Link className="btn btn-sm" to={`/fidcs?gestor=${encodeURIComponent(f.gestor)}`}>Todos</Link> : undefined}>
              <table className="grid compact"><tbody>{data.mesma_gestora.map((c) => (
                <tr key={c.cnpj}><td className="wrap"><Link to={`/fidcs/${c.cnpj}`}>{c.nome}</Link></td><td className="small">{c.segmento ?? "—"}</td>
                  <td className="num">{fmtBRLCompact(c.pl)}</td></tr>))}</tbody></table>
            </Card>
          )}
        </div>
      )}
    </>
  );
}
