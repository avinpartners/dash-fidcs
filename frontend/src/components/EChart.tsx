// ECharts (tree-shaken core) wrapper: theme-aware, resizes with its box, PNG export via toolbox.
import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import {
  AxisPointerComponent, DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent, ToolboxComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";
import { token, useEffectiveTheme } from "../lib/theme";

echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent,
  ToolboxComponent, MarkLineComponent, AxisPointerComponent, CanvasRenderer]);

export interface ChartTokens {
  text: string; muted: string; grid: string; axis: string; surface: string; series: string[];
}

export function chartTokens(): ChartTokens {
  return {
    text: token("--text-2") || "#344054",
    muted: token("--muted") || "#667085",
    grid: token("--chart-grid") || "#e4e7ec",
    axis: token("--chart-axis") || "#c9ced8",
    surface: token("--surface") || "#ffffff",
    series: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => token(`--series-${i}`)).filter(Boolean),
  };
}

export function EChart({ build, height = 280, fileName, ariaLabel, deps }: {
  build: (t: ChartTokens) => EChartsCoreOption;
  height?: number;
  fileName: string;        // PNG name for "Salvar imagem"
  ariaLabel: string;
  deps: unknown[];
}) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const theme = useEffectiveTheme();

  useEffect(() => {
    if (!el.current) return;
    const c = echarts.init(el.current, undefined, { renderer: "canvas" });
    chart.current = c;
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(el.current);
    return () => { ro.disconnect(); c.dispose(); chart.current = null; };
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const option = useMemo(() => build(chartTokens()), [...deps, theme]);

  useEffect(() => {
    const t = chartTokens();
    chart.current?.setOption({
      backgroundColor: "transparent",
      textStyle: { fontFamily: "inherit", color: t.text },
      animationDuration: 300,
      toolbox: {
        right: 4, top: 0, itemSize: 13,
        iconStyle: { borderColor: t.muted },
        emphasis: { iconStyle: { borderColor: t.text, textFill: t.text } },
        feature: { saveAsImage: { title: "Salvar PNG", name: fileName, pixelRatio: 2, backgroundColor: t.surface } },
      },
      ...option,
    }, true);
  }, [option, fileName]);

  return <div ref={el} className="echart" style={{ height }} role="img" aria-label={ariaLabel} />;
}

/** Common axis styling. */
export function axisStyle(t: ChartTokens) {
  return {
    axisLine: { lineStyle: { color: t.axis } },
    axisTick: { show: false },
    axisLabel: { color: t.muted, fontSize: 11 },
    splitLine: { lineStyle: { color: t.grid, width: 1 } },
  };
}

export function tooltipStyle(t: ChartTokens) {
  return {
    trigger: "axis" as const,
    backgroundColor: t.surface,
    borderColor: t.axis,
    textStyle: { color: t.text, fontSize: 12 },
    extraCssText: "box-shadow: 0 6px 20px rgba(0,0,0,.35);",
    axisPointer: { type: "line" as const, lineStyle: { color: t.axis }, link: [{ xAxisIndex: "all" }] },
    confine: true,
  };
}

export function legendStyle(t: ChartTokens) {
  return { top: 0, left: 0, textStyle: { color: t.text, fontSize: 12 }, itemWidth: 14, itemHeight: 8, icon: "roundRect",
    inactiveColor: t.axis, inactiveBorderColor: t.axis };
}
