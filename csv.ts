// CSV for Excel in pt-BR: ';' separator, decimal comma, dd/mm/aaaa, UTF-8 BOM, CRLF.
import type { FormatKind } from "../format";
import { fmtDate } from "../format";

export interface CsvColumn { key: string; label: string; format: FormatKind }

const BOM = "﻿";

function num(v: number, decimals: number): string {
  // No thousands separator: Excel pt-BR reads "1234,56" as a number.
  let s = v.toFixed(decimals);
  if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  if (s === "-0") s = "0";
  return s.replace(".", ",");
}

/** Cell text; numbers keep full precision (percentages as percent points). */
export function csvCell(v: unknown, format: FormatKind): string {
  if (v == null || v === "") return "";
  if (Array.isArray(v)) return v.map((x) => (typeof x === "number" ? num(x * (format === "pct" ? 100 : 1), 4) : "")).join(" ");
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "";
    switch (format) {
      case "pct": case "pct_signed": return num(v * 100, 4);
      case "int": case "int_compact": return String(Math.round(v));
      case "brl_cota": return num(v, 8);
      case "ratio": return num(v, 4);
      default: return num(v, 2);
    }
  }
  if (typeof v === "boolean") return v ? "Sim" : "Não";
  const s = String(v);
  if (format === "date" || format === "month") return /^\d{4}-\d{2}-\d{2}/.test(s) ? fmtDate(s.slice(0, 10)) : s;
  return s;
}

function quote(s: string): string {
  // Text starting like a formula is prefixed so Excel shows it as text.
  const safe = /^[=+\-@\t\r]/.test(s) ? "'" + s : s;
  return /[;"\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function headerLabel(c: CsvColumn): string {
  if (c.format === "pct" || c.format === "pct_signed") return `${c.label} (%)`;
  if (c.format === "brl" || c.format === "brl_compact" || c.format === "brl_cota") return c.label.includes("R$") ? c.label : `${c.label} (R$)`;
  return c.label;
}

/** `preamble`: lines written before the header, one cell each (data-base, sources, export time). */
export function toCSV(columns: CsvColumn[], rows: Record<string, unknown>[], preamble: string[] = []): string {
  const lines = [...preamble.map(quote), columns.map((c) => quote(headerLabel(c))).join(";")];
  for (const r of rows) {
    lines.push(columns.map((c) => {
      const cell = csvCell(r[c.key], c.format);
      return typeof r[c.key] === "number" ? cell : quote(cell);
    }).join(";"));
  }
  return BOM + lines.join("\r\n") + "\r\n";
}
