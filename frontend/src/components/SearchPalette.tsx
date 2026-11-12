// Ctrl+K: FIDCs (nome ou CNPJ), gestoras, administradores, cedentes (CNPJ) and the app's pages.
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type SearchHit } from "../api";
import { fold } from "../format";
import { useDebounced } from "../lib/hooks";

const PAGES = [
  { path: "/", label: "Início" }, { path: "/fidcs", label: "FIDCs" }, { path: "/gestoras", label: "Gestoras" },
  { path: "/administradores", label: "Administradores" }, { path: "/custodiantes", label: "Custodiantes" },
  { path: "/cedentes", label: "Cedentes" }, { path: "/status", label: "Status dos dados" },
  { path: "/metodologia", label: "Metodologia" },
];
const KIND: Record<SearchHit["kind"], string> = { fidc: "FIDC", cedente: "Cedente", gestora: "Gestora", administrador: "Administrador" };

function url(h: SearchHit): string {
  switch (h.kind) {
    case "fidc": return `/fidcs/${h.id}`;
    case "cedente": return `/cedentes/${h.id}`;
    case "gestora": return `/fidcs?gestor=${encodeURIComponent(h.id)}`;
    default: return `/fidcs?administrador=${encodeURIComponent(h.id)}`;
  }
}

type Item = { kind: "hit"; hit: SearchHit } | { kind: "page"; label: string; path: string };

export function SearchPalette({ open, onClose, initial = "" }: { open: boolean; onClose: () => void; initial?: string }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [sel, setSel] = useState(0);
  const dq = useDebounced(q, 180);
  const input = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (open) { setQ(initial); setHits([]); setSel(0); setTimeout(() => input.current?.focus(), 0); }
  }, [open, initial]);

  useEffect(() => {
    if (!open || dq.trim().length < 2) { setHits([]); setLoading(false); return; }
    const ctrl = new AbortController();
    setLoading(true);
    api.search(dq.trim(), ctrl.signal)
      .then((r) => { setHits(r.hits); setLoading(false); setSel(0); })
      .catch((e: Error) => { if (e.name !== "AbortError") setLoading(false); });
    return () => ctrl.abort();
  }, [dq, open]);

  const items: Item[] = useMemo(() => {
    const f = fold(q.trim());
    const pages = PAGES.filter((p) => !f || fold(p.label).includes(f)).map((p) => ({ kind: "page" as const, ...p }));
    return [...hits.map((hit) => ({ kind: "hit" as const, hit })), ...pages];
  }, [hits, q]);

  if (!open) return null;
  const go = (it: Item) => { onClose(); navigate(it.kind === "hit" ? url(it.hit) : it.path); };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); if (items[sel]) go(items[sel]); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  };
  return (
    <div className="palette-backdrop" onMouseDown={onClose}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Busca" onMouseDown={(e) => e.stopPropagation()}>
        <input ref={input} className="palette-input" placeholder="Nome ou CNPJ do FIDC, gestora, administrador ou CNPJ de cedente…"
               value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} role="combobox" aria-expanded="true"
               aria-controls="palette-list" />
        <ul className="palette-list" id="palette-list" role="listbox">
          {items.map((it, i) => (
            <li key={it.kind === "hit" ? `${it.hit.kind}:${it.hit.id}` : it.path} role="option" aria-selected={i === sel}
                className={i === sel ? "sel" : ""} onMouseEnter={() => setSel(i)}
                onMouseDown={(e) => { e.preventDefault(); go(it); }}>
              {it.kind === "hit" ? (
                <><span className="pal-kind">{KIND[it.hit.kind]}</span><span className="pal-name">{it.hit.label}</span>
                  <span className="pal-meta">{it.hit.sub ?? ""}</span></>
              ) : <><span className="pal-kind">Página</span><span className="pal-name">{it.label}</span></>}
            </li>
          ))}
        </ul>
        <div className="palette-foot muted">
          {loading ? "Buscando…" : q.trim() && !hits.length ? "Nada encontrado." : "↑↓ para navegar · Enter para abrir · Esc para fechar"}
        </div>
      </div>
    </div>
  );
}
