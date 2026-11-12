// Chart option builders for the FIDC pages (ECharts, theme tokens from EChart.chartTokens).
import type { EChartsCoreOption } from "echarts/core";
import { axisStyle, legendStyle, tooltipStyle, type ChartTokens } from "../components/EChart";
import { fmtBRLCompact, fmtInt, fmtMonth, fmtPct, fmtValue, type FormatKind } from "../format";
import { axisTooltip, monthHeader } from "./common";

const fmtAxis: Record<string, (v: number) => string> = {
  brl: (v) => fmtBRLCompact(v).replace("R$ ", ""),
  pct: (v) => fmtPct(v, 0),
  int: (v) => fmtInt(v),
};

export interface SeriesSpec { name: string; data: (number | null)[]; kind?: "bar" | "line"; stack?: string; axis?: 0 | 1 }

/** Months on x; one or two y axes (left: unitL, right: unitR). */
export function monthChart(t: ChartTokens, months: string[], series: SeriesSpec[], unitL: "brl" | "pct" | "int",
                           unitR?: "brl" | "pct" | "int"): EChartsCoreOption {
  const kinds: Record<string, FormatKind> = {};
  series.forEach((s) => { kinds[s.name] = ((s.axis === 1 ? unitR : unitL) === "brl" ? "brl_compact" : (s.axis === 1 ? unitR : unitL) === "pct" ? "pct" : "int") as FormatKind; });
  const yAxis = [unitL, unitR].filter(Boolean).map((u, i) => ({
    type: "value", minInterval: u === "int" ? 1 : undefined, ...axisStyle(t), splitLine: i === 0 ? axisStyle(t).splitLine : { show: false },
    axisLabel: { ...axisStyle(t).axisLabel, formatter: fmtAxis[u as string] },
  }));
  return {
    grid: { left: 8, right: 8, top: 36, bottom: 4, containLabel: true },
    legend: { ...legendStyle(t), show: series.length > 1 },
    tooltip: { ...tooltipStyle(t), formatter: axisTooltip(kinds, monthHeader) },
    xAxis: { type: "category", data: months, ...axisStyle(t), axisLabel: { ...axisStyle(t).axisLabel, formatter: (v: string) => fmtMonth(v) } },
    yAxis,
    series: series.map((s, i) => ({
      name: s.name, type: s.kind ?? "line", data: s.data, stack: s.stack, yAxisIndex: s.axis ?? 0,
      itemStyle: { color: t.series[i % t.series.length] }, lineStyle: { width: 2 }, symbol: "circle", symbolSize: 5,
      showSymbol: months.length < 30, barMaxWidth: 28, connectNulls: false,
    })),
  };
}

/** Horizontal bars of a {label: value} map, biggest first. */
export function barsH(t: ChartTokens, items: [string, number][], kind: "brl" | "pct" | "int"): EChartsCoreOption {
  const rows = [...items].sort((a, b) => a[1] - b[1]);
  const f = (v: number) => kind === "brl" ? fmtBRLCompact(v) : kind === "pct" ? fmtPct(v, 1) : fmtInt(v);
  return {
    grid: { left: 8, right: 64, top: 8, bottom: 4, containLabel: true },
    tooltip: { ...tooltipStyle(t), trigger: "item", formatter: (p: { name: string; value: number }) => `${p.name}: <b>${f(p.value)}</b>` },
    xAxis: { type: "value", ...axisStyle(t), axisLabel: { ...axisStyle(t).axisLabel, formatter: fmtAxis[kind] } },
    yAxis: { type: "category", data: rows.map((r) => r[0]), ...axisStyle(t), axisLabel: { ...axisStyle(t).axisLabel, width: 170, overflow: "truncate" } },
    series: [{ type: "bar", data: rows.map((r) => r[1]), itemStyle: { color: t.series[0], borderRadius: [0, 3, 3, 0] }, barMaxWidth: 18,
      label: { show: true, position: "right", color: t.muted, fontSize: 11, formatter: (p: { value: number }) => f(p.value) } }],
  };
}

/** Vertical bars over fixed buckets (prazo, liquidez, rating). */
export function barsV(t: ChartTokens, labels: string[], values: number[], kind: "brl" | "pct" | "int"): EChartsCoreOption {
  return {
    grid: { left: 8, right: 8, top: 16, bottom: 4, containLabel: true },
    tooltip: { ...tooltipStyle(t), trigger: "item", formatter: (p: { name: string; value: number }) => `${p.name}: <b>${fmtValue(p.value, kind === "brl" ? "brl_compact" : kind === "pct" ? "pct" : "int")}</b>` },
    xAxis: { type: "category", data: labels, ...axisStyle(t) },
    yAxis: { type: "value", ...axisStyle(t), axisLabel: { ...axisStyle(t).axisLabel, formatter: fmtAxis[kind] } },
    series: [{ type: "bar", data: values, itemStyle: { color: t.series[0], borderRadius: [3, 3, 0, 0] }, barMaxWidth: 32 }],
  };
}
