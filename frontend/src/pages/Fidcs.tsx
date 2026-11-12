// FIDCs: every fund/class of the latest informe in one virtualized table. Filters, sort and search live in the URL,
// so a filtered list can be sent as a link (e.g. /fidcs?gestor=…&segmento=Financeiro).
import { useMemo, useRef } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import { fidcList, saveText, type FidcRow } from "../api";
import { Empty, ErrorBox, Loading, SituacaoTag } from "../components/ui";
import { fmtBRLCompact, fmtDate, fmtInt, fmtMonth, fmtPct, fmtPctSigned, fold } from "../format";
import { useApi, useDebounced, useDocumentTitle } from "../lib/hooks";

type Col = {
  key: keyof FidcRow | "nome"; label: string; num?: boolean; width: number; title?: string;
  render?: (r: FidcRow) => React.ReactNode; csv?: (r: FidcRow) => string | number | null;
};

const COLS: Col[] = [
  { key: "nome", label: "FIDC", width: 340 },
  { key: "gestor", label: "Gestor", width: 220 },
  { key: "administrador", label: "Administrador", width: 200 },
  { key: "segmento", label: "Segmento", width: 150, render: (r) => r.segmento ?? "—" },
  { key: "subsegmento", label: "Subsegmento", width: 160, render: (r) => r.subsegmento ?? "—" },
  { key: "pl", label: "PL", num: true, width: 104, render: (r) => fmtBRLCompact(r.pl) },
  { key: "pl_var_12m", label: "PL 12m", num: true, width: 80, title: "Variação do PL em 12 meses",
    render: (r) => <span className={r.pl_var_12m == null ? "" : r.pl_var_12m >= 0 ? "pos" : "neg"}>{fmtPctSigned(r.pl_var_12m, 0)}</span> },
  { key: "captacao_liquida", label: "Capt. líq.", num: true, width: 116, title: "Captações − resgates − amortizações no mês",
    render: (r) => fmtBRLCompact(r.captacao_liquida) },
  { key: "cotistas", label: "Cotistas", num: true, width: 78, render: (r) => fmtInt(r.cotistas) },
  { key: "alocador_tipo", label: "Alocador", width: 170, title: "Tipo de cotista com mais da metade dos cotistas" },
  { key: "subordinacao", label: "Subord.", num: true, width: 74, render: (r) => fmtPct(r.subordinacao, 1) },
  { key: "inadimplencia", label: "Inad.", num: true, width: 70, render: (r) => fmtPct(r.inadimplencia, 1) },
  { key: "pdd_sobre_dc", label: "PDD/DC", num: true, width: 72, render: (r) => fmtPct(r.pdd_sobre_dc, 1) },
  { key: "rentab_senior", label: "Rent. sênior", num: true, width: 86, title: "Rentabilidade da maior série sênior no mês", render: (r) => fmtPct(r.rentab_senior) },
  { key: "cedente1_pct", label: "Maior cedente", num: true, width: 92, title: "Peso do maior cedente informado", render: (r) => fmtPct(r.cedente1_pct, 0) },
  { key: "estrutura", label: "Estrutura", width: 78 },
  { key: "condominio", label: "Condomínio", width: 86 },
  { key: "situacao", label: "Situação", width: 110, render: (r) => <SituacaoTag s={r.situacao} /> },
  { key: "data_constituicao", label: "Constituição", width: 92, render: (r) => fmtDate(r.data_constituicao) },
  { key: "competencia", label: "Informe", width: 72, render: (r) => fmtMonth(r.competencia) },
];

const FILTERS: { key: keyof FidcRow; label: string }[] = [
  { key: "segmento", label: "Segmento" }, { key: "subsegmento", label: "Subsegmento" }, { key: "gestor", label: "Gestor" },
  { key: "administrador", label: "Administrador" }, { key: "custodiante", label: "Custodiante" },
  { key: "alocador_tipo", label: "Alocador" }, { key: "situacao", label: "Situação" }, { key: "estrutura", label: "Estrutura" },
  { key: "condominio", label: "Condomínio" },
];

function cmp(a: unknown, b: unknown): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), "pt-BR");
}

const ROW_H = 32;

export default function Fidcs() {
  useDocumentTitle("FIDCs");
  const { data, error, reload } = useApi(() => fidcList(), []);
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const q = sp.get("q") ?? "";
  const dq = useDebounced(q, 150);
  const sort = sp.get("sort") ?? "pl";
  const desc = sp.get("dir") !== "asc";
  const plMin = Number(sp.get("plmin") ?? "") || 0;
  const set = (k: string, v: string | null) => {
    const n = new URLSearchParams(sp);
    if (v == null || v === "") n.delete(k); else n.set(k, v);
    setSp(n, { replace: true });
  };

  const rows = data?.rows ?? [];
  const options = useMemo(() => {
    const o: Record<string, [string, number][]> = {};
    FILTERS.forEach((f) => {
      const m = new Map<string, number>();
      rows.forEach((r) => { const v = r[f.key] as string | null; if (v) m.set(v, (m.get(v) ?? 0) + 1); });
      o[f.key] = [...m.entries()].sort((a, b) => b[1] - a[1]);
    });
    return o;
  }, [rows]);

  const shown = useMemo(() => {
    const f = fold(dq.trim());
    const digits = dq.replace(/\D/g, "");
    let out = rows.filter((r) => {
      for (const flt of FILTERS) {
        const v = sp.get(flt.key);
        if (v && r[flt.key] !== v) return false;
      }
      if (plMin && (r.pl ?? 0) < plMin * 1e6) return false;
      if (!f) return true;
      if (digits.length >= 4 && r.cnpj.includes(digits)) return true;
      return fold(`${r.nome} ${r.gestor ?? ""} ${r.administrador ?? ""}`).includes(f);
    });
    out = [...out].sort((a, b) => {
      const x = a[sort as keyof FidcRow], y = b[sort as keyof FidcRow];
      if (x == null || y == null) return cmp(x, y);      // empty cells last, either direction
      return desc ? -cmp(x, y) : cmp(x, y);
    });
    return out;
  }, [rows, dq, sp, sort, desc, plMin]);

  const totalPl = shown.filter((r) => r.estrutura === "FIDC").reduce((a, r) => a + (r.pl ?? 0), 0);
  const box = useRef<HTMLDivElement>(null);
  const v = useVirtualizer({ count: shown.length, getScrollElement: () => box.current, estimateSize: () => ROW_H, overscan: 12 });
  const width = COLS.reduce((a, c) => a + c.width, 0);

  const exportCsv = () => {
    const head = ["CNPJ", ...COLS.map((c) => c.label)];
    const lines = [head.join(";")];
    shown.forEach((r) => {
      const cells = [r.cnpj_fmt, ...COLS.map((c) => {
        const val = r[c.key as keyof FidcRow];
        if (typeof val === "number") return String(val).replace(".", ",");
        return (val == null ? "" : String(val)).replace(/;/g, ",");
      })];
      lines.push(cells.join(";"));
    });
    saveText(lines.join("\r\n"), `fidcs_${data?.competencia ?? ""}.csv`);
  };

  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return <Loading label="Carregando os FIDCs…" />;
  const active = FILTERS.filter((f) => sp.get(f.key)).length + (plMin ? 1 : 0);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>FIDCs</h1>
          <div className="muted">{fmtInt(shown.length)} de {fmtInt(rows.length)} fundos e classes · PL somado (sem FIC-FIDC) {fmtBRLCompact(totalPl)}
            {data.competencia && <> · informe de {fmtMonth(data.competencia, true)}</>}</div>
        </div>
        <div className="toolbar">
          <button className="btn" onClick={exportCsv}>Exportar CSV</button>
        </div>
      </div>
      <div className="filters">
        <input className="input" style={{ minWidth: 280 }} placeholder="Nome, CNPJ, gestor ou administrador" value={q}
               onChange={(e) => set("q", e.target.value)} aria-label="Buscar na lista" />
        {FILTERS.map((f) => (
          <select key={f.key} className="input" value={sp.get(f.key) ?? ""} onChange={(e) => set(f.key, e.target.value)}
                  aria-label={f.label} style={{ maxWidth: 220 }}>
            <option value="">{f.label}: todos</option>
            {options[f.key]?.map(([o, n]) => <option key={o} value={o}>{o} ({n})</option>)}
          </select>
        ))}
        <label className="small muted">PL mín. (R$ mi){" "}
          <input className="input input-num" inputMode="decimal" value={sp.get("plmin") ?? ""} onChange={(e) => set("plmin", e.target.value)} />
        </label>
        {active > 0 && <button className="btn btn-sm" onClick={() => setSp(q ? { q } : {}, { replace: true })}>Limpar filtros</button>}
      </div>
      {!shown.length ? <Empty>Nenhum FIDC com esses filtros.</Empty> : (
        <div className="card" style={{ padding: 0 }}>
          <div ref={box} className="table-box" style={{ maxHeight: "calc(100vh - 230px)" }}>
            <table className="grid compact" style={{ width, tableLayout: "fixed" }}>
              <colgroup><col style={{ width: COLS[0].width }} />{COLS.slice(1).map((c) => <col key={c.key} style={{ width: c.width }} />)}</colgroup>
              <thead><tr>{COLS.map((c) => (
                <th key={c.key} className={c.num ? "num" : undefined} title={c.title}
                    aria-sort={sort === c.key ? (desc ? "descending" : "ascending") : undefined}>
                  <button className="th-btn" onClick={() => {
                    const n = new URLSearchParams(sp);
                    if (sort === c.key) n.set("dir", desc ? "asc" : "desc"); else { n.set("sort", c.key); n.set("dir", c.num ? "desc" : "asc"); }
                    setSp(n, { replace: true });
                  }}>{c.label}{sort === c.key ? (desc ? " ↓" : " ↑") : ""}</button>
                </th>))}</tr></thead>
              <tbody>
                {(v.getVirtualItems()[0]?.start ?? 0) > 0 && <tr aria-hidden><td colSpan={COLS.length} style={{ height: v.getVirtualItems()[0].start, padding: 0, border: 0 }} /></tr>}
                {v.getVirtualItems().map((vi) => {
                  const r = shown[vi.index];
                  return (
                    <tr key={r.cnpj} className="clickable" style={{ height: ROW_H }} onClick={(e) => {
                      if ((e.target as HTMLElement).closest("a")) return;
                      navigate(`/fidcs/${r.cnpj}`);
                    }}>
                      {COLS.map((c) => (
                        <td key={c.key} className={c.num ? "num" : undefined}>
                          {c.key === "nome" ? <span className="ellipsis" title={`${r.nome} · ${r.cnpj_fmt}`}><Link to={`/fidcs/${r.cnpj}`}>{r.nome}</Link></span>
                            : c.render ? c.render(r) : <span className="ellipsis" title={String(r[c.key as keyof FidcRow] ?? "")}>{String(r[c.key as keyof FidcRow] ?? "—")}</span>}
                        </td>))}
                    </tr>
                  );
                })}
                {v.getVirtualItems().length > 0 && v.getTotalSize() - v.getVirtualItems().at(-1)!.end > 0 && <tr aria-hidden><td colSpan={COLS.length} style={{ height: v.getTotalSize() - v.getVirtualItems().at(-1)!.end, padding: 0, border: 0 }} /></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
