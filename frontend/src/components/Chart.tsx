import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";

/** Reads the design tokens off :root so charts and chrome can never drift.
 *  Re-reads on theme change, because the dark palette is a selected set of
 *  steps rather than an automatic inversion of the light one. */
export function useTokens() {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const root = document.documentElement;
    const obs = new MutationObserver(() => setTick((t) => t + 1));
    obs.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setTick((t) => t + 1);
    mq.addEventListener("change", onChange);
    return () => { obs.disconnect(); mq.removeEventListener("change", onChange); };
  }, []);

  return useMemo(() => {
    const cs = getComputedStyle(document.documentElement);
    const v = (name: string) => cs.getPropertyValue(name).trim();
    return {
      tick,
      surface: v("--surface-1"),
      text: v("--text-primary"),
      textSecondary: v("--text-secondary"),
      muted: v("--text-muted"),
      grid: v("--grid"),
      axis: v("--axis"),
      border: v("--border"),
      // Categorical, fixed order. Never cycled past slot 8.
      series: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--series-${i}`)),
      diverging: [
        v("--div-neg-3"), v("--div-neg-2"), v("--div-neg-1"),
        v("--div-mid"),
        v("--div-pos-1"), v("--div-pos-2"), v("--div-pos-3"),
      ],
      sequential: [v("--seq-100"), v("--seq-250"), v("--seq-400"), v("--seq-550"), v("--seq-700")],
      good: v("--status-good"),
      warning: v("--status-warning"),
      critical: v("--status-critical"),
      deltaUp: v("--delta-up"),
      deltaDown: v("--delta-down"),
    };
  }, [tick]);
}

export type Tokens = ReturnType<typeof useTokens>;

/** Chrome shared by every chart: hairline recessive grid and axes, no dashes,
 *  tooltips on by default, thin marks. */
export function baseOption(t: Tokens): echarts.EChartsOption {
  return {
    backgroundColor: "transparent",
    animationDuration: 300,
    textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", fontSize: 12 },
    grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
    tooltip: {
      backgroundColor: t.surface,
      borderColor: t.border,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: t.text, fontSize: 12 },
      extraCssText: "box-shadow:0 4px 16px rgba(0,0,0,.12);border-radius:8px;",
    },
    legend: {
      type: "scroll",
      icon: "roundRect",
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 16,
      textStyle: { color: t.textSecondary, fontSize: 12 },
      inactiveColor: t.muted,
    },
  };
}

export const axisCommon = (t: Tokens) => ({
  axisLine: { show: true, lineStyle: { color: t.axis, width: 1 } },
  axisTick: { show: false },
  axisLabel: { color: t.muted, fontSize: 11 },
  splitLine: { show: true, lineStyle: { color: t.grid, width: 1, type: "solid" as const } },
});

interface Props {
  option: echarts.EChartsOption;
  height?: number;
  /** Cross-filtering: a click on any mark reports its category. */
  onSelect?: (name: string) => void;
  loading?: boolean;
  ariaLabel: string;
}

export default function Chart({ option, height = 280, onSelect, loading, ariaLabel }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts>();

  useEffect(() => {
    if (!ref.current) return;
    inst.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const ro = new ResizeObserver(() => inst.current?.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); inst.current?.dispose(); };
  }, []);

  useEffect(() => {
    const c = inst.current;
    if (!c) return;
    // notMerge so a series disappearing from the data disappears from the chart.
    c.setOption(option, { notMerge: true });
    c.off("click");
    if (onSelect) {
      c.on("click", (p: { name?: string }) => { if (p.name) onSelect(p.name); });
      c.getZr().on("click", () => { /* keeps the cursor affordance honest */ });
    }
  }, [option, onSelect]);

  return (
    <div
      ref={ref}
      role="img"
      aria-label={ariaLabel}
      style={{
        height,
        width: "100%",
        // Hold the previous render at reduced opacity on refetch rather than
        // flashing a skeleton, so nothing jumps.
        opacity: loading ? 0.55 : 1,
        transition: "opacity .15s ease",
        cursor: onSelect ? "pointer" : "default",
      }}
    />
  );
}
