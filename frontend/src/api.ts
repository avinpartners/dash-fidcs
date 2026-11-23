// API client of Dash FIDCs. Local app: every call goes to /api on the same server (FastAPI).
// Online version (VITE_STATIC=1, GitHub Pages): the same answers come from JSON files under data/, written each
// day by backend/app/export_static.py; search runs in the browser and the update buttons are hidden.
export const STATIC = import.meta.env.VITE_STATIC === "1";
const DATA = `${import.meta.env.BASE_URL}data`;

/** Maps an API path to its exported JSON file (online version). */
function staticPath(path: string): string {
  const m = path.match(/^\/(fidcs|cedentes)\/([^/?]+)$/);
  if (m) return `${DATA}/${m[1] === "fidcs" ? "fidc" : "cedente"}/${decodeURIComponent(m[2]).replace(/\D/g, "")}.json`;
  const r = path.match(/^\/jobs\/runs\/(\d+)$/);
  if (r) return `${DATA}/runs/${r[1]}.json`;
  return `${DATA}${path}.json`;
}

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function request<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  if (STATIC && (init.method ?? "GET") !== "GET") throw new ApiError("Indisponível na versão online", 405);
  const res = STATIC ? await fetch(staticPath(path), { signal })
    : await fetch(`/api${path}`, { credentials: "same-origin", ...init, signal });
  if (STATIC && res.status === 404) throw new ApiError("Não encontrado", 404);
  if (res.status === 401) {
    window.dispatchEvent(new CustomEvent("dash:passcode"));
    throw new ApiError("Senha necessária", 401);
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { const j = await res.json(); if (j?.detail) detail = String(j.detail); } catch { /* not JSON */ }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

const get = <T,>(path: string, signal?: AbortSignal) => request<T>(path, {}, signal);
const post = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export type Dict<T = number> = Record<string, T>;

export interface FidcRow {
  cnpj: string; cnpj_fmt: string; nome: string; tipo: string | null; situacao: string | null;
  gestor: string | null; cnpj_gestor: string | null; administrador: string | null; custodiante: string | null;
  auditor: string | null; exclusivo: boolean | null; publico_alvo: string | null; data_constituicao: string | null;
  adaptacao_175: string | null; cnpj_fundo: string | null; pl_cadastro: number | null; data_pl_cadastro: string | null;
  competencia: string; pl: number | null; ativo: number | null; carteira: number | null; dc_com_risco: number | null;
  inadimplencia: number | null; inad_acima_90: number | null; pdd_sobre_dc: number | null;
  segmento: string | null; subsegmento: string | null; peso_segmento: number | null; subordinacao: number | null;
  cotistas: number | null; alocador_tipo: string | null; rentab_senior: number | null; rentab_subordinada: number | null;
  captacao: number | null; resgate: number | null; amortizacao: number | null; captacao_liquida: number;
  garantia_pct: number | null; cotas_fidc_pct: number | null; cedente1_pct: number | null;
  cedentes_informados: number | null; condominio: string | null; estrutura: "FIDC" | "FIC-FIDC";
  pl_var_12m: number | null;
}

export interface ListResponse<R> { competencia: string | null; rows: R[] }

export interface HomeMonth {
  competencia: string; fundos: number; pl: number | null; cotistas: number | null; captacao_liquida: number | null;
  inad_mediana: number | null; sub_mediana: number | null; inad_agregada: number | null;
}
export interface HomeResponse {
  competencia: string | null; historico: HomeMonth[];
  segmentos_historico: { competencia: string; segmento: string; pl: number | null; fundos: number }[];
  novos: { cnpj: string; nome: string; gestor: string | null; data_constituicao: string; pl: number | null; segmento: string | null }[];
  liquidacao: { cnpj: string; nome: string; gestor: string | null; situacao: string; data_situacao: string | null; pl: number | null }[];
}

export interface Mensal {
  competencia: string; pl: number | null; pl_medio: number | null; ativo: number | null; disponibilidades: number | null;
  carteira: number | null; dc_com_risco: number | null; dc_sem_risco: number | null; a_vencer: number | null;
  inadimplente: number | null; inad_acima_90: number | null; antecipado: number | null; inadimplencia: number | null;
  pdd_sobre_dc: number | null; segmentos: Dict | null; segmento: string | null; subsegmento: string | null;
  peso_segmento: number | null; subordinacao: number | null; valor_cotas: number | null; valor_senior: number | null;
  valor_subordinada: number | null; cotistas: number | null; cotistas_tipo: Dict | null; alocador_tipo: string | null;
  rentab_senior: number | null; rentab_subordinada: number | null; captacao: number | null; resgate: number | null;
  amortizacao: number | null; garantia_pct: number | null; liquidez: Dict | null; prazo_vencimento: Dict | null;
  rating_scr: Dict | null; cotas_fidc_pct: number | null; cedente1_pct: number | null; cedentes_informados: number | null;
  condominio: string | null;
}
export interface Serie {
  classe_serie: string; tipo: string; qt_cotas: number | null; vl_cota: number | null; valor: number | null;
  cotistas: number | null; rentab_mes: number | null; desemp_esperado: number | null; desemp_real: number | null;
}
export interface FidcDetail {
  fidc: Record<string, unknown> & { cnpj: string; cnpj_fmt: string; nome: string; gestor: string | null;
    administrador: string | null; situacao: string | null; cnpj_fundo_fmt: string | null; nome_fundo: string | null };
  historico: Mensal[]; series: Serie[];
  series_historico: { competencia: string; tipo: string; valor: number | null }[];
  cedentes: { cnpj_cedente: string; cnpj_cedente_fmt: string; pct: number | null; nome: string | null; fidcs: number }[];
  classes_do_fundo: { cnpj: string; nome: string }[];
  mesma_gestora: { cnpj: string; nome: string; pl: number | null; segmento: string | null }[];
}
export interface GroupRow {
  nome: string; fundos: number; pl: number | null; cotistas: number | null; captacao_liquida: number | null;
  inad_mediana: number | null; sub_mediana: number | null; segmento_principal: string | null; em_liquidacao: number;
}
export interface CedenteRow {
  cnpj_cedente: string; cnpj_cedente_fmt: string; nome: string | null; fidcs: number; peso_medio: number | null;
  peso_max: number | null; pl_fidcs: number | null; gestoras: string[] | null; segmento: string | null;
}
export interface CedenteDetail {
  cnpj: string; cnpj_fmt: string; nome: string | null;
  rows: { competencia: string; cnpj: string; nome: string; gestor: string | null; pct: number | null; pl: number | null; segmento: string | null }[];
}
export interface SearchHit { kind: "fidc" | "cedente" | "gestora" | "administrador"; id: string; label: string; sub: string | null }

export interface JobInfo {
  name: string; cadence: string; implemented: boolean; disabled: boolean; last_success: string | null;
  last_status: string | null; overdue: boolean; next_due: string | null; due_since: string | null;
  failed_sources: { id: string; name: string }[];
}
export interface JobRun {
  id: number; job_name: string; trigger: string; started_at: string; finished_at: string | null; status: string;
  progress: number | null; message: string | null; rows_changed: number | null; duration_s: number | null; log?: string | null;
}
export interface StatusResponse {
  jobs: JobInfo[];
  sources: { id: string; label: string; base_url: string | null; last_success_at: string | null; last_data_date: string | null;
    last_error: string | null; last_error_at: string | null; notes: string | null }[];
  runs: JobRun[];
  issues: { by_kind: Dict; open: { id: number; kind: string; cnpj: string | null; name: string | null; ref_month: string | null; detail: unknown; created_at: string }[] };
  db: { ok: boolean; error?: string; server_version?: string; size_bytes?: number; schema_version?: number; tables?: Dict };
}
export interface ValidacaoItem { cnpj: string; nome: string; dash: string | number | null; cvm: string | number | null }
export interface Validacao {
  gerado_em: string; ok: boolean; competencia: string | null; erro: string | null;
  arquivos: { cadastro?: { url: string; baixado_em: string }; informe?: { url: string; baixado_em: string } };
  conferidos: Dict; divergencias: Dict; exemplos: Record<string, ValidacaoItem[]>;
  informativo: { administrador_mudou?: number; texto?: string }; rotulos: Record<string, string>;
}
export interface ActiveJobs {
  current: { job: string; trigger: string; started_at: string; progress: number | null; message: string | null; run_id: number | null } | null;
  queued: { job: string }[]; worker_alive: boolean;
}

// The list is ~4 000 rows: fetched once per visit and shared by the pages that need it.
let listCache: { at: number; p: Promise<ListResponse<FidcRow>> } | null = null;
export function fidcList(): Promise<ListResponse<FidcRow>> {
  if (!listCache || Date.now() - listCache.at > 5 * 60_000) {
    const p = get<ListResponse<FidcRow>>("/fidcs");
    listCache = { at: Date.now(), p };
    p.catch(() => { listCache = null; });
  }
  return listCache.p;
}

export const api = {
  fidcs: () => fidcList(),
  fidc: (cnpj: string, s?: AbortSignal) => get<FidcDetail>(`/fidcs/${encodeURIComponent(cnpj)}`, s),
  home: (s?: AbortSignal) => get<HomeResponse>("/home", s),
  group: (kind: "gestoras" | "administradores" | "custodiantes", s?: AbortSignal) => get<ListResponse<GroupRow>>(`/${kind}`, s),
  cedentes: (s?: AbortSignal) => get<ListResponse<CedenteRow>>("/cedentes", s),
  cedente: (cnpj: string, s?: AbortSignal) => get<CedenteDetail>(`/cedentes/${encodeURIComponent(cnpj)}`, s),
  search: (q: string, s?: AbortSignal) => STATIC ? staticSearch(q) : get<{ hits: SearchHit[] }>(`/search?q=${encodeURIComponent(q)}`, s),
  status: (s?: AbortSignal) => get<StatusResponse>("/status", s),
  validacao: (s?: AbortSignal) => get<Validacao>("/validacao", s),
  jobsActive: (s?: AbortSignal) => STATIC ? Promise.resolve<ActiveJobs>({ current: null, queued: [], worker_alive: true })
    : get<ActiveJobs>("/jobs/active", s),
  jobRun: (id: number, s?: AbortSignal) => get<JobRun>(`/jobs/runs/${id}`, s),
  runJobs: (job: string | null) => post<{ message: string }>("/jobs/run", { job }),
  login: (passcode: string) => post<{ ok: boolean }>("/login", { passcode }),
};

// ---- Search in the browser (online version): same order as /api/search (CNPJ, then names, gestoras, administradores).
interface SearchIndex { fidcs: [string, string, string | null][]; cedentes: [string, string | null][];
  gestoras: [string, number][]; administradores: [string, number][] }
let searchIndex: Promise<SearchIndex> | null = null;
const foldTxt = (t: string) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const fmtCnpj = (c: string) => c.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5");

async function staticSearch(q: string): Promise<{ hits: SearchHit[] }> {
  const text = q.trim();
  if (text.length < 2) return { hits: [] };
  if (!searchIndex) {
    searchIndex = fetch(`${DATA}/search.json`).then((r) => { if (!r.ok) throw new ApiError(`HTTP ${r.status}`, r.status); return r.json(); });
    searchIndex.catch(() => { searchIndex = null; });
  }
  const ix = await searchIndex;
  const d = text.replace(/\D/g, "");
  const f = foldTxt(text);
  const hits: SearchHit[] = [];
  if (d.length >= 6) {
    ix.fidcs.filter((x) => x[0].startsWith(d)).slice(0, 8).forEach(([id, label, sub]) => hits.push({ kind: "fidc", id, label, sub }));
    ix.cedentes.filter((x) => x[0].startsWith(d)).slice(0, 5)
      .forEach(([id, nome]) => hits.push({ kind: "cedente", id, label: nome ?? fmtCnpj(id), sub: "Cedente" }));
  }
  const words = f.split(/\s+/).filter(Boolean);
  const match = (s: string | null) => { const t = foldTxt(s ?? ""); return words.every((w) => t.includes(w)); };
  ix.fidcs.filter((x) => match(x[1]))
    .sort((a, b) => Number(foldTxt(b[1]).includes(f)) - Number(foldTxt(a[1]).includes(f)) || a[1].length - b[1].length)
    .slice(0, 12).forEach(([id, label, sub]) => hits.push({ kind: "fidc", id, label, sub }));
  ix.gestoras.filter((x) => match(x[0])).slice(0, 5)
    .forEach(([nome, n]) => hits.push({ kind: "gestora", id: nome, label: nome, sub: `${n} FIDCs` }));
  ix.administradores.filter((x) => match(x[0])).slice(0, 5)
    .forEach(([nome, n]) => hits.push({ kind: "administrador", id: nome, label: nome, sub: `${n} FIDCs` }));
  const seen = new Set<string>();
  return { hits: hits.filter((h) => { const k = `${h.kind}|${h.id}`; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 25) };
}

export const JOB_LABELS: Record<string, string> = {
  fidc_cadastro: "Cadastro CVM (fundos e classes)",
  fidc_informe_mensal: "Informe mensal FIDC",
  db_backup: "Backup do banco",
};

/** Save text as a file (CSV exports). */
export function saveText(text: string, name: string, type = "text/csv;charset=utf-8") {
  const blob = new Blob(["﻿" + text], { type });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
