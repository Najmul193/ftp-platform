import { useMemo, useState } from "react";
import { api, Dim } from "../api";
import Chart, { axisCommon, baseOption, useTokens } from "../components/Chart";
import { waterfallOption } from "../components/waterfall";
import { Card, Empty, Grid, MiniButton, Pill, Stat, Table, ViewToggle, useView } from "../components/ui";
import { compact, longDate, money, n, pct, signed } from "../format";
import { useApp, useAsync } from "../state";

const DIMS: Dim[] = ["branch", "product", "category", "division", "district"];

export default function Analytics() {
  const { filters } = useApp();
  const t = useTokens();
  const [dim, setDim] = useState<Dim>("product");

  const bridge = useAsync(() => api.bridge(filters, dim), [filters, dim]);
  const conc = useAsync(() => api.concentration(filters, dim), [filters, dim]);
  const rank = useAsync(() => api.rankings(filters, dim), [filters, dim]);
  const scat = useAsync(() => api.scatter(filters, dim), [filters, dim]);
  const dist = useAsync(() => api.distribution(filters, 12), [filters]);

  const [bView, setBView] = useView();
  const [cView, setCView] = useView();
  const [sView, setSView] = useView();

  const b = bridge.data;

  // ---- variance bridge: waterfall from opening to closing -----------------
  const bridgeOption = useMemo(() => {
    if (!b?.available) return null;
    return waterfallOption([
      { label: "Opening", value: n(b.opening_profit), kind: "total" },
      { label: "Volume", value: n(b.volume_effect), kind: "delta" },
      { label: "Rate", value: n(b.rate_effect), kind: "delta" },
      { label: "Interaction", value: n(b.interaction_effect), kind: "delta" },
      { label: "Closing", value: n(b.closing_profit), kind: "total" },
    ], t);
  }, [b, t]);

  // ---- Pareto: bars + cumulative line, both on ONE axis (percent) --------
  const paretoOption = useMemo(() => {
    const segs = conc.data?.segments ?? [];
    if (!segs.length) return null;
    return {
      ...baseOption(t),
      grid: { left: 8, right: 16, top: 30, bottom: 4, containLabel: true },
      legend: { ...baseOption(t).legend, top: 0, left: 0 },
      tooltip: {
        ...baseOption(t).tooltip, trigger: "axis", axisPointer: { type: "shadow" },
        formatter: (ps: never) => {
          const i = (ps as unknown as { dataIndex: number }[])[0].dataIndex;
          const s = segs[i];
          return `<b>${s.label}</b> (rank ${s.rank})<br/>` +
            `Net FTP ${money(s.net_ftp_profit)}<br/>` +
            `Share ${pct(s.share_pct)} · cumulative ${pct(s.cumulative_pct)}`;
        },
      },
      xAxis: { type: "category", data: segs.map((s) => s.label), ...axisCommon(t),
               splitLine: { show: false },
               axisLabel: { color: t.textSecondary, fontSize: 11 } },
      // One axis: both series are percentages, so no second scale is invented.
      yAxis: { type: "value", max: 100, ...axisCommon(t), axisLine: { show: false },
               axisLabel: { color: t.muted, fontSize: 11,
                            formatter: (v: number) => `${v}%` } },
      series: [
        { name: "Share of profit", type: "bar", barWidth: "52%",
          data: segs.map((s) => n(s.share_pct)),
          itemStyle: { color: t.series[0], borderRadius: [4, 4, 0, 0] } },
        { name: "Cumulative", type: "line", data: segs.map((s) => n(s.cumulative_pct)),
          symbol: "circle", symbolSize: 8,
          lineStyle: { width: 2, color: t.series[1] },
          itemStyle: { color: t.series[1], borderColor: t.surface, borderWidth: 2 },
          markLine: {
            silent: true, symbol: "none",
            lineStyle: { color: t.muted, width: 1, type: "solid" },
            label: { formatter: "80%", color: t.muted, fontSize: 10.5, position: "insideEndTop" },
            data: [{ yAxis: 80 }],
          } },
      ],
    } as never;
  }, [conc.data, t]);

  // ---- scatter: balance vs yield, quadranted on medians ------------------
  const scatterOption = useMemo(() => {
    const pts = scat.data?.points ?? [];
    if (!pts.length) return null;
    const mb = n(scat.data?.median_balance), my = n(scat.data?.median_yield_pct);
    return {
      ...baseOption(t),
      // Right padding leaves room for the point labels; top padding leaves
      // room for the y-axis name, which otherwise clips against the card.
      grid: { left: 8, right: 86, top: 30, bottom: 8, containLabel: true },
      legend: { show: false },
      tooltip: {
        ...baseOption(t).tooltip, trigger: "item",
        formatter: (p: never) => {
          const d = (p as unknown as { data: { name: string; value: number[]; q: string } }).data;
          return `<b>${d.name}</b><br/>Balance ${compact(d.value[0])}<br/>` +
            `Yield ${pct(d.value[1], 4)}<br/><span style="color:${t.muted}">${d.q}</span>`;
        },
      },
      xAxis: { type: "value", name: "Balance-days", nameLocation: "middle", nameGap: 28,
               nameTextStyle: { color: t.muted, fontSize: 11 }, scale: true,
               ...axisCommon(t), axisLabel: { color: t.muted, fontSize: 11,
                 formatter: (v: number) => compact(v) } },
      yAxis: { type: "value", name: "Yield %", nameGap: 12,
               nameTextStyle: { color: t.muted, fontSize: 11, align: "left" },
               scale: true, ...axisCommon(t), axisLine: { show: false },
               axisLabel: { color: t.muted, fontSize: 11,
                            formatter: (v: number) => `${v.toFixed(2)}` } },
      series: [{
        type: "scatter", symbolSize: 16,
        // One hue: the quadrant is carried by position against the median
        // lines and by the direct label, not by a fourth colour.
        itemStyle: { color: t.series[0], borderColor: t.surface, borderWidth: 2, opacity: .9 },
        label: { show: true, position: "right", color: t.textSecondary, fontSize: 11,
                 formatter: (p: { data: { name: string } }) => p.data.name },
        data: pts.map((p) => ({ name: p.label, q: p.quadrant,
                                value: [n(p.balance), n(p.yield_pct)] })),
        markLine: {
          silent: true, symbol: "none",
          lineStyle: { color: t.axis, width: 1, type: "solid" },
          label: { color: t.muted, fontSize: 10 },
          // Separated so the two labels cannot land on top of each other at
          // the crossing point.
          data: [{ xAxis: mb, label: { formatter: "median balance",
                                       position: "insideEndTop" } },
                 { yAxis: my, label: { formatter: "median yield",
                                       position: "insideStartTop" } }],
        },
      }],
    } as never;
  }, [scat.data, t]);

  // ---- FTP rate distribution, balance-weighted --------------------------
  const distOption = useMemo(() => {
    const bk = dist.data?.buckets ?? [];
    if (!bk.length) return null;
    return {
      ...baseOption(t),
      grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true },
      legend: { show: false },
      tooltip: {
        ...baseOption(t).tooltip, trigger: "axis", axisPointer: { type: "shadow" },
        formatter: (ps: never) => {
          const i = (ps as unknown as { dataIndex: number }[])[0].dataIndex;
          const x = bk[i];
          return `<b>FTP rate ${x.from_rate} to ${x.to_rate}</b><br/>` +
            `${x.account_count} account-days (${pct(x.account_pct, 1)})<br/>` +
            `Balance ${compact(x.balance)} (${pct(x.balance_pct, 1)})`;
        },
      },
      xAxis: { type: "category", data: bk.map((x) => `${x.from_rate}`), ...axisCommon(t),
               splitLine: { show: false },
               axisLabel: { color: t.muted, fontSize: 10.5, interval: 1 } },
      yAxis: { type: "value", ...axisCommon(t), axisLine: { show: false },
               name: "% of balance", nameGap: 12,
               nameTextStyle: { color: t.muted, fontSize: 11, align: "left" },
               axisLabel: { color: t.muted, fontSize: 11,
                            formatter: (v: number) => `${v}%` } },
      series: [{
        type: "bar", data: bk.map((x) => n(x.balance_pct)), barWidth: "88%",
        // Loss-making buckets take the reserved critical colour, paired with
        // the axis position so the meaning is not colour-only.
        itemStyle: {
          color: (p: { dataIndex: number }) =>
            (bk[p.dataIndex].is_negative ? t.critical : t.series[0]),
          borderRadius: [4, 4, 0, 0],
        },
      }],
    } as never;
  }, [dist.data, t]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: "var(--fs-sm)", color: "var(--text-muted)", fontWeight: 600,
                       letterSpacing: ".05em", textTransform: "uppercase" }}>
          Analyse by
        </span>
        {DIMS.map((d) => (
          <MiniButton key={d} active={dim === d} onClick={() => setDim(d)}>
            {d[0].toUpperCase() + d.slice(1)}
          </MiniButton>
        ))}
      </div>

      {/* --- variance bridge --- */}
      <Card expandable title={`Why profit moved — by ${dim}`}
            subtitle={b?.available
              ? `${longDate(b.prior_period!.start)} – ${longDate(b.prior_period!.end)} vs ${longDate(b.current_period!.start)} – ${longDate(b.current_period!.end)}` +
                (b.comparison_mode === "split_window"
                  ? "  ·  no earlier data, so the loaded window is split in half"
                  : "")
              : "Needs two comparable periods"}
            actions={<ViewToggle view={bView} setView={setBView} />}
            footnote={b?.available
              ? `Volume = balances moving at last period's rate. Rate = pricing moving on last period's balances. Interaction = the part attributable to both at once. Residual ${b.residual} — the three effects reconstruct the change exactly.`
              : undefined}>
        {!b?.available
          ? <Empty title="No comparison available" hint={b?.reason ??
              "Select a date range with an equal-length window of data before it."} />
          : bView === "chart"
            ? (
              <>
                <Grid cols="repeat(auto-fit, minmax(150px, 1fr))" gap={10}>
                  <Stat label="Total change" value={signed(b.total_change)}
                        tone={n(b.total_change) >= 0 ? "good" : "bad"} />
                  <Stat label="Volume effect" value={signed(b.volume_effect)} />
                  <Stat label="Rate effect" value={signed(b.rate_effect)} />
                  <Stat label="Interaction" value={signed(b.interaction_effect)} />
                </Grid>
                <div style={{ marginTop: 10 }}>
                  <Chart option={bridgeOption!} height={260} loading={bridge.loading}
                         ariaLabel="Variance bridge from opening to closing profit" />
                </div>
              </>
            )
            : <Table csvName={`ftp-bridge-${dim}.csv`} rows={b.segments ?? []} maxHeight={360}
                     cols={[
                       { key: "label", label: dim },
                       { key: "status", label: "Status",
                         render: (r) => <Pill tone={r.status === "new" ? "info"
                           : r.status === "closed" ? "warning" : "neutral"}>{r.status}</Pill>,
                         value: (r) => r.status },
                       { key: "prior", label: "Prior", align: "right",
                         render: (r) => money(r.prior_profit), value: (r) => r.prior_profit },
                       { key: "cur", label: "Current", align: "right",
                         render: (r) => money(r.current_profit), value: (r) => r.current_profit },
                       { key: "chg", label: "Change", align: "right",
                         render: (r) => signed(r.change), value: (r) => r.change },
                       { key: "vol", label: "Volume", align: "right",
                         render: (r) => signed(r.volume_effect), value: (r) => r.volume_effect },
                       { key: "rate", label: "Rate", align: "right",
                         render: (r) => signed(r.rate_effect), value: (r) => r.rate_effect },
                     ]} />}
      </Card>

      <Grid cols="minmax(0, 1fr) minmax(0, 1fr)">
        <Card expandable title={`Concentration by ${dim}`}
              subtitle={conc.data?.available
                ? `HHI ${conc.data.hhi} — ${conc.data.hhi_interpretation}`
                : undefined}
              actions={<ViewToggle view={cView} setView={setCView} />}
              footnote={conc.data?.available
                ? `Top 3 hold ${pct(conc.data.top_3_pct ?? 0, 1)} of profit; ${conc.data.segments_to_80pct} of ${conc.data.segment_count} reach 80%. HHI under 1500 is diffuse, over 2500 concentrated.`
                : undefined}>
          {!paretoOption
            ? <Empty title="No data" />
            : cView === "chart"
              ? <Chart option={paretoOption} height={272} loading={conc.loading}
                       ariaLabel={`Pareto of FTP profit by ${dim}`} />
              : <Table csvName={`ftp-concentration-${dim}.csv`} rows={conc.data?.segments ?? []}
                       cols={[
                         { key: "rank", label: "#", align: "right" },
                         { key: "label", label: dim },
                         { key: "p", label: "Net FTP", align: "right",
                           render: (r) => money(r.net_ftp_profit), value: (r) => r.net_ftp_profit },
                         { key: "s", label: "Share", align: "right",
                           render: (r) => pct(r.share_pct, 1), value: (r) => r.share_pct },
                         { key: "c", label: "Cumulative", align: "right",
                           render: (r) => pct(r.cumulative_pct, 1), value: (r) => r.cumulative_pct },
                       ]} />}
        </Card>

        <Card expandable title={`Balance vs yield — by ${dim}`}
              subtitle="Quadrants split on the medians"
              actions={<ViewToggle view={sView} setView={setSView} />}
              footnote="High balance with low yield is the repricing opportunity: a large book earning a thin spread.">
          {!scatterOption
            ? <Empty title="No data" />
            : sView === "chart"
              ? <Chart option={scatterOption} height={272} loading={scat.loading}
                       ariaLabel={`Balance against yield by ${dim}`} />
              : <Table csvName={`ftp-scatter-${dim}.csv`} rows={scat.data?.points ?? []}
                       cols={[
                         { key: "label", label: dim },
                         { key: "bal", label: "Balance", align: "right",
                           render: (r) => compact(r.balance), value: (r) => r.balance },
                         { key: "y", label: "Yield", align: "right",
                           render: (r) => pct(r.yield_pct, 4), value: (r) => r.yield_pct },
                         { key: "q", label: "Quadrant", render: (r) => r.quadrant },
                       ]} />}
        </Card>
      </Grid>

      <Grid cols="minmax(0, 1fr) minmax(0, 1fr)">
        <Card expandable title="FTP rate distribution"
              subtitle="Balance-weighted across account-days"
              footnote="Weighted by balance, not by count: a thousand small accounts at a good spread do not offset one large account priced below cost.">
          {!distOption ? <Empty title="No data" />
            : <Chart option={distOption} height={250} loading={dist.loading}
                     ariaLabel="Distribution of account FTP rate weighted by balance" />}
        </Card>

        <Card title={`League table — by ${dim}`}
              subtitle={rank.data?.available
                ? `Median yield ${pct(rank.data.median_yield_pct ?? 0, 4)} · best-worst spread ${pct(rank.data.spread_pct ?? 0, 4)}`
                : undefined}
              footnote="Ranked on annualised yield rather than absolute profit, which would only reward size.">
          <Table csvName={`ftp-rankings-${dim}.csv`} rows={rank.data?.rows ?? []} maxHeight={250}
                 cols={[
                   { key: "rank", label: "#", align: "right" },
                   { key: "label", label: dim },
                   { key: "y", label: "Yield", align: "right",
                     render: (r) => pct(r.yield_pct, 4), value: (r) => r.yield_pct },
                   { key: "q", label: "Quartile", align: "right",
                     render: (r) => <Pill tone={r.quartile === 1 ? "good"
                       : r.quartile === 4 ? "critical" : "neutral"}>Q{r.quartile}</Pill>,
                     value: (r) => r.quartile },
                   { key: "p", label: "Net FTP", align: "right",
                     render: (r) => money(r.net_ftp_profit), value: (r) => r.net_ftp_profit },
                 ]} />
        </Card>
      </Grid>
    </div>
  );
}
