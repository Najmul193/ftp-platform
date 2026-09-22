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

  // Walk the steps once to find every segment's extent. Anchors are pinned at
  // their value (the far edge is 0 by definition), deltas float between the
  // running totals — zero itself is never a plot feature, so it takes no part
  // in fitting the axis.
  const segments: { lo: number; hi: number }[] = [];
  let running = 0;
  let min = Infinity;
  let max = -Infinity;
  const grow = (v: number) => {
    if (v < min) min = v;
    if (v > max) max = v;
  };

  steps.forEach((s) => {
    if (s.kind === "total") {
      running = s.value;
      segments.push({ lo: Math.min(0, s.value), hi: Math.max(0, s.value) });
      grow(s.value);
    } else {
      const lo = Math.min(running, running + s.value);
      const hi = Math.max(running, running + s.value);
      segments.push({ lo, hi });
      grow(lo);
      grow(hi);
      running += s.value;
    }
  });

  const span = max - min || Math.abs(max) || 1;
  const pad = span * 0.12;
  // Fitting band rather than anchoring at zero: an anchor IS a full span from
  // zero, so its zero-tail simply runs off the bottom of the plot. Only pad
  // below zero when the data actually goes there, otherwise the axis grows a
  // negative tick that nothing in the chart reaches.
  const yMin = min >= 0 ? Math.max(0, min - pad) : min - pad;
  const yMax = max <= 0 ? Math.min(0, max + pad) : max + pad;

  // Everything — anchors included — is a segment in one stack, so bars float
  // exactly between their own lo and hi and adjacent steps always touch. The
  // invisible spacer under each visible segment is what parks the bar on lo.
  const base: number[] = [];
  const rise: number[] = [];
  const fall: number[] = [];
  const totals: number[] = [];

  steps.forEach((s, i) => {
    const { lo, hi } = segments[i];
    if (s.kind === "total") {
      // Anchor spans 0..value: its spacer parks the bar at zero, its tail below
      // the fitted axis is clipped at the plot floor.
      base.push(lo - yMin);
      rise.push(0); fall.push(0);
      totals.push(hi - lo);
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
    grid: { left: 8, right: 16, top: 34, bottom: 10, containLabel: true },
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
        color: t.textSecondary, fontSize: 10, interval: 0, lineHeight: 12,
        // Narrow enough that five categories still fit side by side in a
        // half-width card; longer names wrap rather than run into each other.
        width: opts.labelWidth ?? 58,
        overflow: "break",
        hideOverlap: false,
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
        itemStyle: { color: "transparent" }, barWidth: "52%", clip: true },
      { type: "bar", stack: "w", name: "increase", data: rise, barWidth: "52%",
        clip: true,
        itemStyle: { color: t.series[0], borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: "top", color: t.textSecondary, fontSize: 10.5,
                 formatter: (p: { dataIndex: number; value: number }) =>
                   (p.value ? labelFor(p.dataIndex) : "") } },
      { type: "bar", stack: "w", name: "decrease", data: fall, barWidth: "52%",
        clip: true,
        itemStyle: { color: t.diverging[5], borderRadius: [0, 0, 4, 4] },
        label: { show: true, position: "bottom", color: t.textSecondary, fontSize: 10.5,
                 formatter: (p: { dataIndex: number; value: number }) =>
                   (p.value ? labelFor(p.dataIndex) : "") } },
      // Anchors take a neutral dark step: they are structure, not direction, so
      // the only hues carrying meaning are the increase/decrease pair.
      { type: "bar", stack: "w", name: "total", data: totals, barWidth: "52%",
        clip: true,
        itemStyle: { color: t.sequential[3], borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: "top", color: t.text, fontSize: 11,
                 fontWeight: 600,
                 formatter: (p: { dataIndex: number; value: number }) =>
                   (p.value ? labelFor(p.dataIndex) : "") } },
    ],
    // Adjacent steps sit so close that their value labels would collide at the
    // seam (a fall's bottom label beside the next anchor's top label): let the
    // layout engine shift one out of the way instead of letting them overlap.
    labelLayout: { hideOverlap: false, moveOverlap: "shiftY" },
  } as EChartsOption;
}
