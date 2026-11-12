// Small shared pieces (from Dash Fundos): states, cards, key-value pairs, segmented control, status tags.
import type { ReactNode } from "react";

export function Loading({ label = "Carregando…" }: { label?: string }) {
  return <div className="state state-loading" role="status"><span className="spinner" aria-hidden /> {label}</div>;
}

export function ErrorBox({ error, onRetry }: { error: Error | string; onRetry?: () => void }) {
  const msg = typeof error === "string" ? error : error.message;
  return (
    <div className="state state-error" role="alert">
      <strong>Não foi possível carregar.</strong> {msg}
      {onRetry && <button className="btn btn-sm" onClick={onRetry}>Tentar de novo</button>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="state state-empty">{children}</div>;
}

export function Card({ title, actions, children, className, id, subtitle }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; id?: string; subtitle?: ReactNode;
}) {
  return (
    <section className={`card${className ? " " + className : ""}`} id={id}>
      {(title || actions) && (
        <header className="card-head">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <div className="card-sub">{subtitle}</div>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function StatusTag({ status }: { status: string | null | undefined }) {
  switch (status) {
    case "success": return <span className="tag ok">✓ Sucesso</span>;
    case "failed": return <span className="tag err">✕ Falhou</span>;
    case "running": return <span className="tag run">● Em execução</span>;
    case "interrupted": return <span className="tag" title="O app foi fechado durante a execução; não conta como falha">⏸ Interrompido</span>;
    case null: case undefined: return <span className="muted">—</span>;
    default: return <span className="tag">{status}</span>;
  }
}

export function KV({ label, children }: { label: ReactNode; children: ReactNode }) {
  return <div className="kv"><dt>{label}</dt><dd>{children}</dd></div>;
}

export function Kpi({ label, value, sub }: { label: ReactNode; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub != null && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: { key: T; label: string }[]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.key} role="radio" aria-checked={value === o.key} className={value === o.key ? "on" : ""}
                onClick={() => onChange(o.key)}>{o.label}</button>
      ))}
    </div>
  );
}

/** Situação na CVM as a coloured tag. */
export function SituacaoTag({ s }: { s: string | null | undefined }) {
  if (!s) return <span className="muted">—</span>;
  const cls = s === "Em Funcionamento Normal" ? "ok" : s === "Em Liquidação" ? "warn" : s === "Cancelado" ? "err" : "";
  const label = s === "Em Funcionamento Normal" ? "Ativo" : s;
  return <span className={`tag ${cls}`} title={s}>{label}</span>;
}

/** Inline bar for a share 0..1 (tables). */
export function ShareBar({ v, max = 1 }: { v: number | null | undefined; max?: number }) {
  if (v == null || !Number.isFinite(v)) return null;
  return <span className="hbar" style={{ width: `${Math.max(1, Math.min(100, (v / max) * 100))}%` }} />;
}
