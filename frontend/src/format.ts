// Brazilian formatting, the single place the UI turns numbers into text.
export const MISSING = "—";

const nfCache = new Map<string, Intl.NumberFormat>();
const nf = (min: number, max = min) => {
  const k = `${min}:${max}`;
  let f = nfCache.get(k);
  if (!f) {
    f = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: min, maximumFractionDigits: max });
    nfCache.set(k, f);
  }
  return f;
};

const bad = (v: number | null | undefined): v is null | undefined => v == null || !Number.isFinite(v);

export function fmtNumber(v: number | null | undefined, decimals = 2): string {
  return bad(v) ? MISSING : nf(decimals).format(v);
}

export function fmtInt(v: number | null | undefined): string {
  return bad(v) ? MISSING : nf(0).format(Math.round(v));
}

export function fmtBRL(v: number | null | undefined, decimals = 2): string {
  if (bad(v)) return MISSING;
  const s = nf(decimals).format(Math.abs(v));
  return (v < 0 ? "-R$ " : "R$ ") + s;
}

/** Per-cota amounts: at least 2 decimals, up to 4 when the value needs them (R$ 0,1150). */
export function fmtBRLCota(v: number | null | undefined): string {
  if (bad(v)) return MISSING;
  const s = nf(2, 4).format(Math.abs(v));
  return (v < 0 ? "-R$ " : "R$ ") + s;
}

/** Compact money: R$ 505,2 mi, R$ 1,2 bi, R$ 812,3 mil. */
export function fmtBRLCompact(v: number | null | undefined): string {
  if (bad(v)) return MISSING;
  const a = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  let body: string;
  if (a >= 1e9) body = nf(1).format(a / 1e9) + " bi";
  else if (a >= 1e6) body = nf(1).format(a / 1e6) + " mi";
  else if (a >= 1e3) body = nf(1).format(a / 1e3) + " mil";
  else body = nf(2).format(a);
  return `${sign}R$ ${body}`;
}

/** Compact count: 1,2 mi, 45,3 mil, 812. */
export function fmtIntCompact(v: number | null | undefined): string {
  if (bad(v)) return MISSING;
  const a = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (a >= 1e6) return sign + nf(1).format(a / 1e6) + " mi";
  if (a >= 1e4) return sign + nf(1).format(a / 1e3) + " mil";
  return fmtInt(v);
}

/** Fraction (0.0962) to "9,62%". */
export function fmtPct(fraction: number | null | undefined, decimals = 2): string {
  return bad(fraction) ? MISSING : nf(decimals).format(fraction * 100) + "%";
}

/** Fraction with explicit sign: "+1,23%", "-0,50%", "0,00%". */
export function fmtPctSigned(fraction: number | null | undefined, decimals = 2): string {
  if (bad(fraction)) return MISSING;
  const s = fmtPct(fraction, decimals);
  return fraction > 0 && s !== fmtPct(0, decimals) ? "+" + s : s;
}

/** Multiples such as P/VP: "0,99". */
export function fmtRatio(v: number | null | undefined, decimals = 2): string {
  return fmtNumber(v, decimals);
}

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;
const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const MONTHS_LONG = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
  "outubro", "novembro", "dezembro"];

/** ISO date or timestamp to dd/mm/aaaa (or dd/mm/aaaa hh:mm). Date-only strings never shift by time zone. */
export function fmtDate(iso: string | null | undefined, withTime = false): string {
  if (!iso) return MISSING;
  const m = DATE_ONLY.exec(iso);
  if (m && !withTime) return `${m[3]}/${m[2]}/${m[1]}`;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return MISSING;
  const opts: Intl.DateTimeFormatOptions = { day: "2-digit", month: "2-digit", year: "numeric",
    timeZone: "America/Sao_Paulo", ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}) };
  return new Intl.DateTimeFormat("pt-BR", opts).format(d).replace(",", "");
}

/** "2026-08-01" to "ago/2026" (long: "agosto de 2026"). */
export function fmtMonth(iso: string | null | undefined, long = false): string {
  if (!iso) return MISSING;
  const m = /^(\d{4})-(\d{2})/.exec(iso);
  if (!m) return MISSING;
  const i = Number(m[2]) - 1;
  if (i < 0 || i > 11) return MISSING;
  return long ? `${MONTHS_LONG[i]} de ${m[1]}` : `${MONTHS[i]}/${m[1]}`;
}

/** "2026-09-30" to "3T2026" (quarter of the reference date). */
export function fmtQuarter(iso: string | null | undefined): string {
  if (!iso) return MISSING;
  const m = /^(\d{4})-(\d{2})/.exec(iso);
  if (!m) return MISSING;
  return `${Math.floor((Number(m[2]) - 1) / 3) + 1}T${m[1]}`;
}

/** 14 digits to 00.000.000/0000-00; anything else unchanged. */
export function fmtCNPJ(cnpj: string | null | undefined): string {
  if (!cnpj) return MISSING;
  const d = cnpj.replace(/\D/g, "");
  if (d.length !== 14) return cnpj;
  return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`;
}

export function fmtBytes(v: number | null | undefined): string {
  if (bad(v)) return MISSING;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let x = v;
  let i = 0;
  while (x >= 1024 && i < units.length - 1) { x /= 1024; i++; }
  return `${nf(i === 0 ? 0 : 1).format(x)} ${units[i]}`;
}

/** Seconds to "45 s", "3 min 05 s", "1 h 02 min". */
export function fmtDuration(seconds: number | null | undefined): string {
  if (bad(seconds) || seconds < 0) return MISSING;
  const s = Math.round(seconds);
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
  return `${Math.floor(s / 3600)} h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")} min`;
}

/** "há 5 min", "há 3 h", "há 2 dias" relative to `now`. */
export function fmtAgo(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return MISSING;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return MISSING;
  const s = Math.max(0, Math.round((now.getTime() - t) / 1000));
  if (s < 60) return "agora";
  if (s < 3600) return `há ${Math.floor(s / 60)} min`;
  if (s < 86400) return `há ${Math.floor(s / 3600)} h`;
  const d = Math.floor(s / 86400);
  return d === 1 ? "há 1 dia" : `há ${d} dias`;
}

export type FormatKind =
  | "brl" | "brl_compact" | "brl_cota" | "pct" | "pct_signed" | "ratio" | "int" | "int_compact"
  | "number" | "date" | "month" | "text";

/** Formats a value by kind; the one switch every table, card and chart tooltip uses. */
export function fmtValue(v: unknown, kind: FormatKind): string {
  if (v == null || v === "") return MISSING;
  switch (kind) {
    case "brl": return fmtBRL(v as number);
    case "brl_compact": return fmtBRLCompact(v as number);
    case "brl_cota": return fmtBRLCota(v as number);
    case "pct": return fmtPct(v as number);
    case "pct_signed": return fmtPctSigned(v as number);
    case "ratio": return fmtRatio(v as number);
    case "int": return fmtInt(v as number);
    case "int_compact": return fmtIntCompact(v as number);
    case "number": return fmtNumber(v as number);
    case "date": return fmtDate(v as string);
    case "month": return fmtMonth(v as string);
    default: return String(v);
  }
}

/** Parses a pt-BR or plain number typed by the user ("1.234,5", "0,95", "0.95"); null when empty/invalid. */
export function parseNumberInput(text: string): number | null {
  const t = text.trim().replace(/\s/g, "");
  if (!t) return null;
  let norm = t;
  if (t.includes(",")) norm = t.replace(/\./g, "").replace(",", ".");
  const n = Number(norm);
  return Number.isFinite(n) ? n : null;
}

/** Number as a short input value in pt-BR ("0,95"), no thousands separator. */
export function numberToInput(v: number | null | undefined): string {
  if (bad(v)) return "";
  return String(v).replace(".", ",");
}

/** Lowercase, accents removed: for accent-insensitive search. */
export function fold(text: string): string {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/** A co-managed FIDC lists every gestora, "A; B" (as the CVM registry has one row per gestora). */
export const gestoras = (g: string | null | undefined): string[] => (g ? g.split("; ").filter(Boolean) : []);
