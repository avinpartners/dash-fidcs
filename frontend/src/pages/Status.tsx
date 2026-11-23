// Status dos dados: each job (when it last ran, when it runs next), "Atualizar agora" with live progress, sources,
// the last runs with their logs, and the database.
import { Fragment, useCallback, useEffect, useState } from "react";
import { api, JOB_LABELS, STATIC, type ActiveJobs, type JobRun } from "../api";
import { Card, ErrorBox, Loading, StatusTag } from "../components/ui";
import { fmtAgo, fmtBytes, fmtDate, fmtDuration, fmtInt, fmtMonth } from "../format";
import { useApi, useDocumentTitle, useInterval } from "../lib/hooks";

const TRIGGERS: Record<string, string> = { manual: "Manual", schedule: "Agendada", catch_up: "Recuperação" };
const label = (n: string) => JOB_LABELS[n] ?? n;

const fmtVal = (v: string | number | null) => (v == null || v === "" ? "—" : typeof v === "number" ? v.toLocaleString("pt-BR") : v);

/** Conferência com a CVM: the dashboard compared field by field with the CVM files of the last update. */
function Conferencia() {
  const { data, error, reload } = useApi((s) => api.validacao(s), []);
  const [aberto, setAberto] = useState<string | null>(null);
  const title = "Conferência com a CVM";
  const subtitle = "Cada FIDC do dash comparado com os arquivos da CVM da última atualização (cadastro e informe mensal)";
  if (error) return <Card title={title}><ErrorBox error={error} onRetry={reload} /></Card>;
  if (!data) return <Card title={title} subtitle={subtitle}><Loading label="Conferindo com os arquivos da CVM (leva uns segundos)…" /></Card>;
  if (data.erro) return <Card title={title} subtitle={subtitle}><div className="state state-error">A conferência não rodou: {data.erro}</div></Card>;
  const campos = Object.keys(data.conferidos);
  const total = Object.values(data.divergencias).reduce((a, n) => a + n, 0);
  return (
    <Card title={title} subtitle={subtitle}>
      <div className={total ? "state state-error" : "notice"} style={{ marginBottom: 10 }}>
        {total ? <>⚠ {fmtInt(total)} divergência{total > 1 ? "s" : ""} encontrada{total > 1 ? "s" : ""}. Clique no campo para ver os fundos.</>
          : <>✓ Tudo confere com a CVM: nenhuma divergência.</>}
        <span className="muted small"> Informe de {fmtMonth(data.competencia, true)} · conferido {fmtDate(data.gerado_em, true)}</span>
      </div>
      <table className="grid compact">
        <thead><tr><th>Campo</th><th className="num">Fundos conferidos</th><th className="num">Divergências</th></tr></thead>
        <tbody>{campos.map((k) => (
          <Fragment key={k}>
            <tr className={data.divergencias[k] ? "clickable" : undefined} onClick={() => data.divergencias[k] && setAberto(aberto === k ? null : k)}>
              <td>{data.rotulos[k] ?? k}</td><td className="num">{fmtInt(data.conferidos[k])}</td>
              <td className="num">{data.divergencias[k] ? <span className="neg">{fmtInt(data.divergencias[k])}</span> : <span className="pos">0</span>}</td></tr>
            {aberto === k && <tr><td colSpan={3}>
              <table className="grid compact"><thead><tr><th>FIDC</th><th>No dash</th><th>Na CVM</th></tr></thead>
                <tbody>{(data.exemplos[k] ?? []).map((e) => (
                  <tr key={e.cnpj}><td className="wrap small">{e.nome} <span className="muted">{e.cnpj}</span></td>
                    <td className="wrap small">{fmtVal(e.dash)}</td><td className="wrap small">{fmtVal(e.cvm)}</td></tr>))}</tbody></table>
              {data.divergencias[k] > (data.exemplos[k]?.length ?? 0) && <div className="muted small">Mostrando {data.exemplos[k]?.length} de {fmtInt(data.divergencias[k])}.</div>}
            </td></tr>}
          </Fragment>))}</tbody>
      </table>
      {!!data.informativo?.administrador_mudou && <div className="muted small" style={{ marginTop: 8 }}>
        Informativo: {fmtInt(data.informativo.administrador_mudou)} fundos com administrador no informe diferente do cadastro atual. {data.informativo.texto}</div>}
    </Card>
  );
}

function RunLog({ id }: { id: number }) {
  const { data, error } = useApi((s) => api.jobRun(id, s), [id]);
  if (error) return <div className="error small">{error.message}</div>;
  if (!data) return <Loading />;
  return <pre className="log">{data.log || "(sem log)"}</pre>;
}

export default function Status() {
  useDocumentTitle("Status dos dados");
  const st = useApi((s) => api.status(s), []);
  const [active, setActive] = useState<ActiveJobs | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const poll = useCallback(() => {
    api.jobsActive().then((a) => {
      setActive((prev) => { if (prev?.current && !a.current) st.reload(); return a; });
    }).catch(() => setActive(null));
  }, [st]);
  useEffect(() => { if (!STATIC) poll(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  useInterval(poll, STATIC ? null : active?.current || active?.queued.length ? 3000 : 20000);
  const run = async (job: string | null) => {
    try { const r = await api.runJobs(job); setMsg(r.message); poll(); } catch (e) { setMsg((e as Error).message); }
  };
  if (st.error) return <ErrorBox error={st.error} onRetry={st.reload} />;
  if (!st.data) return <Loading />;
  const d = st.data;
  const cur = active?.current;
  return (
    <>
      <div className="page-head">
        <div><h1>Status dos dados</h1><div className="muted">{STATIC
          ? "Versão online: os dados da CVM são baixados e o site é republicado sozinho todo dia útil de manhã."
          : "As atualizações rodam sozinhas todo dia; o botão roda tudo agora."}</div></div>
        {!STATIC && <div className="toolbar"><button className="btn btn-primary" onClick={() => run(null)}>Atualizar agora</button></div>}
      </div>
      {msg && <div className="notice">{msg}</div>}
      {(cur || (active?.queued.length ?? 0) > 0) && (
        <Card title="Em andamento">
          {cur && <div><span className="spinner" aria-hidden /> <strong>{label(cur.job)}</strong>{" "}
            {cur.progress != null ? `${Math.round(cur.progress * 100)}% · ` : ""}{cur.message ?? "Iniciando…"} · começou {fmtAgo(cur.started_at)}
            <div className={`progress${cur.progress == null ? " indeterminate" : ""}`}><span style={cur.progress == null ? undefined : { width: `${Math.round(cur.progress * 100)}%` }} /></div></div>}
          {(active?.queued.length ?? 0) > 0 && <div className="muted small">Na fila: {active!.queued.map((q) => label(q.job)).join(", ")}</div>}
        </Card>
      )}
      {active?.worker_alive === false && <div className="state state-error">As tarefas automáticas não estão rodando. Feche com Parar.cmd e abra de novo com Iniciar.cmd.</div>}
      <Conferencia />
      <Card title="Tarefas">
        <table className="grid compact">
          <thead><tr><th>Tarefa</th><th>Frequência</th><th>Último sucesso</th><th>Última execução</th>{!STATIC && <><th>Próxima</th><th /></>}</tr></thead>
          <tbody>{d.jobs.filter((j) => !STATIC || j.name !== "db_backup").map((j) => (
            <tr key={j.name}><td>{label(j.name)}{j.overdue && !STATIC && <span className="tag warn" style={{ marginLeft: 6 }}>atrasada</span>}</td>
              <td>{j.cadence === "daily" ? "Diária" : j.cadence === "weekly" ? "Semanal" : "Mensal"}</td>
              <td>{j.last_success ? `${fmtDate(j.last_success, true)} (${fmtAgo(j.last_success)})` : "—"}</td>
              <td><StatusTag status={j.last_status} /></td>{!STATIC && <><td>{j.next_due ? fmtDate(j.next_due, true) : "—"}</td>
              <td><button className="btn btn-sm" onClick={() => run(j.name)}>Rodar</button></td></>}</tr>))}</tbody>
        </table>
      </Card>
      <Card title="Fontes">
        <table className="grid compact">
          <thead><tr><th>Fonte</th><th>Dado mais recente</th><th>Último sucesso</th><th>Erro</th></tr></thead>
          <tbody>{d.sources.map((s) => (
            <tr key={s.id}><td>{s.base_url ? <a href={s.base_url} target="_blank" rel="noreferrer">{s.label}</a> : s.label}
              {s.notes && <div className="small muted">{s.notes}</div>}</td>
              <td>{s.id === "cvm_inf_mensal_fidc" ? fmtMonth(s.last_data_date, true) : fmtDate(s.last_data_date)}</td>
              <td>{s.last_success_at ? fmtAgo(s.last_success_at) : "—"}</td>
              <td className="wrap small">{s.last_error ? <span className="error">{s.last_error}</span> : "—"}</td></tr>))}</tbody>
        </table>
      </Card>
      <Card title="Últimas execuções" subtitle="Clique numa linha para ver o log">
        <div className="table-box">
          <table className="grid compact">
            <thead><tr><th>Tarefa</th><th>Origem</th><th>Início</th><th>Duração</th><th>Status</th><th className="num">Linhas</th><th>Mensagem</th></tr></thead>
            <tbody>{d.runs.map((r: JobRun) => (
              <Fragment key={r.id}>
                <tr className="clickable" onClick={() => setOpen(open === r.id ? null : r.id)}>
                  <td>{label(r.job_name)}</td><td>{TRIGGERS[r.trigger] ?? r.trigger}</td><td>{fmtDate(r.started_at, true)}</td>
                  <td>{fmtDuration(r.duration_s)}</td><td><StatusTag status={r.status} /></td><td className="num">{fmtInt(r.rows_changed)}</td>
                  <td className="wrap small">{r.message}</td></tr>
                {open === r.id && <tr><td colSpan={7}><RunLog id={r.id} /></td></tr>}
              </Fragment>))}</tbody>
          </table>
        </div>
      </Card>
      <Card title="Banco de dados">
        {d.db.ok ? <div className="small">PostgreSQL {d.db.server_version} · {fmtBytes(d.db.size_bytes)} · versão do esquema {d.db.schema_version} ·{" "}
          {Object.entries(d.db.tables ?? {}).map(([k, v]) => `${k}: ${fmtInt(v)}`).join(" · ")}</div>
          : <div className="error">{d.db.error ?? "Banco de dados indisponível"}</div>}
      </Card>
    </>
  );
}
