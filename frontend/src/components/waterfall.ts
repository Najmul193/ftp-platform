import type { EChartsOption } from "echarts";
import { axisCommon, baseOption, Tokens } from "./Chart";
import { compact, money } from "../format";

export interface Step {
  label: string;
  value: number;
  /** `total` is an anchor (opening, closing, subtotal); `delta` is a movement. */
  kind: "total" | "delta";
}

/**
 * A waterfall whose y-axis is fitted to the data rather than anchored at zero.
 *
 * Anchoring at zero is the usual default and it silently destroys this chart
 * whenever the movements are small relative to the totals: an opening of 26.6K
 * with deltas of 50 renders the deltas as invisible hairlines. Fitting the axis
 * to the actual range of the running total is what makes the movements legible,
 * which is the entire point of a waterfall.
 *
 * The y-axis therefore does not start at zero. That is a deliberate exception:
 * a waterfall reads *differences between adjacent steps*, not bar areas against
 * a zero baseline, so a fitted range does not exaggerate anything. The step
 * values are direct-labelled so the magnitudes are never inferred from height
 * alone.
 */
export function waterfallOption(
  steps: Step[],
  t: Tokens,
  opts: { labelWidth?: number; valueFormatter?: (v: number) => string } = {},
): EChartsOption {
  const fmt = opts.valueFormatter ?? compact;

  // Walk the steps once to find every segment's extent.
  const segments: { lo: number; hi: number }[] = [];
  let running = 0;
  let min = Infinity;
  let max = -Infinity;

  steps.forEach((s) => {
    if (s.kind === "total") {
      running = s.value;
      segments.push({ lo: Math.min(0, s.value), hi: Math.max(0, s.value) });
      min = Math.min(min, 0, s.value);
      max = Math.max(max, 0, s.value);
    } else {
      const lo = Math.min(running, running + s.value);
      const hi = Math.max(running, running + s.value);
      segments.push({ lo, hi });
      running += s.value;
      min = Math.min(min, lo);
      max = Math.max(max, hi);
    }
  });

  const span = max - min || Math.abs(max) || 1;
  const pad = span * 0.12;
  const yMin = min - pad;
  const yMax = max + pad;

  // Bars are drawn as a transparent spacer stacked under a visible segment, so
  // each one floats between its own lo and hi.
  const base: number[] = [];
  const rise: number[] = [];
  const fall: number[] = [];
  const totals: number[] = [];

  steps.forEach((s, i) => {
    const { lo, hi } = segments[i];
    if (s.kind === "total") {
      base.push(0); rise.push(0); fall.push(0);
      totals.push(hi - yMin);
    } else {
      totals.push(0);
      base.push(lo - yMin);
      if (s.value >= 0) { rise.push(hi - lo); fall.push(0); }
      else { rise.push(0); fall.push(hi - lo); }
    }
  });

  const labelFor = (i: number) =>
    steps[i].kind === "total" ? fmt(steps[i].value)
      : `${steps[i].value >= 0 ? "+" : "−"}${fmt(Math.abs(steps[i].value))}`;

  const b = baseOption(t);
  return {
    ...b,
    grid: { left: 8, right: 16, top: 34, bottom: 6, containLabel: true },
    legend: { show: false },
    tooltip: {
      ...b.tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (ps: unknown) => {
        const i = (ps as { dataIndex: number }[])[0].dataIndex;
        const s = steps[i];
        return `<b>${s.label.replace(/\n/g, " ")}</b><br/>` +
          `${s.kind === "total" ? "" : s.value >= 0 ? "increase " : "decrease "}` +
          `<b>${money(Math.abs(s.value))}</b>`;
      },
    },
    xAxis: {
      type: "category",
      data: steps.map((s) => s.label),
      ...axisCommon(t),
      splitLine: { show: false },
      axisLabel: {
        color: t.textSecondary, fontSize: 10.5, interval: 0, lineHeight: 13,
        width: opts.labelWidth ?? 84, overflow: "break",
      },
    },
    yAxis: {
      type: "value",
      min: yMin,
      max: yMax,
      ...axisCommon(t),
      axisLine: { show: false },
      // Ticks are offset by yMin because the stacked bars are drawn relative
      // to the axis floor rather than to zero.
      axisLabel: {
        color: t.muted, fontSize: 11,
        formatter: (v: number) => fmt(v),
      },
    },
    series: [
      { type: "bar", stack: "w", silent: true, data: base.map((v) => v + yMin),
        itemStyle: { color: "transparent" }, barWidth: "52%" },
      { type: "bar", stack: "w", name: "increase", data: rise, barWidth: "52%",
        itemStyle: { color: t.series[0], borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: "top", color: t.textSecondary, fontSize: 10.5,
                 formatter: (p: { dataIndex: number; value: number }) =>
                   (p.value ? labelFor(p.dataIndex) : "") } },
      { type: "bar", stack: "w", name: "decrease", data: fall, barWidth: "52%",
        itemStyle: { color: t.diverging[5], borderRadius: [0, 0, 4, 4] },
        label: { show: true, position: "bottom", color: t.textSecondary, fontSize: 10.5,
                 formatter: (p: { dataIndex: number; value: number }) =>
                   (p.value ? labelFor(p.dataIndex) : "") } },
      // Anchors take a neutral dark step: they are structure, not direction, so
      // the only hues carrying meaning are the increase/decrease pair.
      { type: "bar", name: "total", data: totals, barWidth: "52%",
        itemStyle: { color: t.sequential[3], borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: "top", color: t.text, fontSize: 11,
                 fontWeight: 600,
                 formatter: (p: { dataIndex: number; value: number }) =>
                   (p.value ? labelFor(p.dataIndex) : "") } },
    ],
  } as EChartsOption;
}
