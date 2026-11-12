// Shared chart pieces: tooltip formatter in pt-BR, month helpers, mark specs.
import { fmtDate, fmtMonth, fmtQuarter, fmtValue, type FormatKind } from "../format";

export interface TipParam {
  seriesName: string; marker: string; value: unknown; axisValue?: unknown; axisValueLabel?: string; name?: string;
}

/** Axis tooltip: header + "● Série: valor" lines, each formatted by its series kind. */
export function axisTooltip(kinds: Record<string, FormatKind>, header: (p: TipParam) => string) {
  return (raw: unknown) => {
    const ps = (Array.isArray(raw) ? raw : [raw]) as TipParam[];
    if (!ps.length) return "";
    const seen = new Set<string>();
    const lines = ps.filter((p) => {
      if (seen.has(p.seriesName)) return false;
      seen.add(p.seriesName);
      return true;
    }).map((p) => {
      const v = Array.isArray(p.value) ? p.value[1] : p.value;
      return `${p.marker}${p.seriesName}: <b>${fmtValue(v as number | null, kinds[p.seriesName] ?? "number")}</b>`;
    });
    return `<div style="font-weight:600;margin-bottom:2px">${header(ps[0])}</div>${lines.join("<br/>")}`;
  };
}

export const monthHeader = (p: TipParam) => fmtMonth(String(p.axisValue ?? p.name ?? ""), true);
export const quarterHeader = (p: TipParam) => fmtQuarter(String(p.axisValue ?? p.name ?? ""));
export const dateHeader = (p: TipParam) => {
  const v = Array.isArray(p.value) ? p.value[0] : p.axisValue;
  return typeof v === "number" ? fmtDate(new Date(v).toISOString().slice(0, 10)) : fmtDate(String(v));
};

/** Time-axis tick label: "ago/26". */
export function timeTick(v: number): string {
  const d = new Date(v);
  return fmtMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`).replace(/\/(\d{2})(\d{2})$/, "/$2");
}

/** Category-axis month label: "ago/26". */
export const monthTick = (v: string) => fmtMonth(v).replace(/\/(\d{2})(\d{2})$/, "/$2");

/** Last day of the month of an ISO date (VP/cota of an informe refers to the month end). */
export function monthEnd(iso: string): string {
  const y = Number(iso.slice(0, 4));
  const m = Number(iso.slice(5, 7));
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return `${iso.slice(0, 7)}-${String(last).padStart(2, "0")}`;
}

export function barStyle(color: string) {
  return { color, borderRadius: [4, 4, 0, 0] };
}

export function lineSeries(name: string, color: string, data: unknown[], extra: Record<string, unknown> = {}) {
  return {
    // Filled dots in the series colour (ECharts' default hollow marker is white inside, glaring on dark cards).
    name, type: "line", data, showSymbol: false, symbol: "circle", symbolSize: 8, connectNulls: false,
    lineStyle: { width: 2, color }, itemStyle: { color }, emphasis: { focus: "none" }, ...extra,
  };
}

/** Two stacked panels sharing the x axis (instead of a second y axis). */
export function twoGrids(topLegend = true) {
  return [
    { left: 8, right: 12, top: topLegend ? 44 : 24, height: topLegend ? "44%" : "48%", containLabel: true },
    { left: 8, right: 12, bottom: 4, height: "24%", containLabel: true },
  ];
}

export const pctAxis = (v: number) => fmtValue(v, "pct").replace(",00", "");
export const brlAxis = (v: number) => fmtValue(v, "brl");
export const compactAxis = (v: number) => fmtValue(v, "brl_compact").replace("R$ ", "");
