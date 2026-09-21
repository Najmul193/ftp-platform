import { useMemo } from "react";
import { api } from "../api";
import Chart, { axisCommon, baseOption, useTokens } from "../components/Chart";
import { Card, Empty, Grid, Pill, Stat, Table } from "../components/ui";
import { compact, longDate, money, n, pct } from "../format";
import { useApp, useAsync } from "../state";

/** The screen a bank runs on in the morning: what needs attention, where the
 *  margin went, and whether the ratios moved. */
export default function Daily() {
  const { filters } = useApp();
  const t = useTokens();

  const watch = useAsync(() => api.watchlist(filters), [filters]);
  const nii = useAsync(() => api.nii(filters), [filters]);
  const ratios = useAsync(() => api.ratios(filters), [filters]);
  const periods = useAsync(() => api.periodSummary(filters), [filters]);
  const repricing = useAsync(() => api.repricing(filters), [filters]);
  const summary = useAsync(() => api.summary(filters), [filters]);

  const r = ratios.data;
  const v = nii.data;

  // NII waterfall: customer margin down to what the business units keep.
  const niiOption = useMemo(() => {
    if (!v) return null;
    const steps = [
      { label: "Net interest\nincome", value: n(v.net_interest_income), kind: "total" },
      { label: "Treasury\nfunding", value: n(v.treasury_funding_of_gap), kind: "delta" },
      { label: "Liquidity\npremium", value: n(v.liquidity_premium), kind: "delta" },
      { label: "Other\ncost", value: n(v.other_cost), kind: "delta" },
      { label: "Business\nunits", value: n(v.business_units_total), kind: "total" },
    ];
    let run = 0;
    const base: number[] = [], up: number[] = [], down: number[] = [], tot: number[] = [];
    steps.forEach((s) => {
      if (s.kind === "total") {
        base.push(0); up.push(0); down.push(0); tot.push(s.value); run = s.value;
      } else {
        tot.push(0);
        if (s.value >= 0) { base.push(run); up.push(s.value); down.push(0); run += s.value; }
        else { run += s.value; base.push(run); up.push(0); down.push(-s.value); }
      }
    });
    return {
      ...baseOption(t),
      grid: { left: 8, right: 16, top: 24, bottom: 4, containLabel: true },
      legend: { show: false },
      tooltip: {
        ...baseOption(t).tooltip, trigger: "axis", axisPointer: { type: "shadow" },
        formatter: (ps: never) => {
          const i = (ps as unknown as { dataIndex: number }[])[0].dataIndex;
          const s = steps[i];
          return `<b>${s.label.replace("\n", " ")}</b><br/>${money(s.value)}`;
        },
      },
      xAxis: { type: "category", data: steps.map((s) => s.label), ...axisCommon(t),
               splitLine: { show: false },
               axisLabel: { color: t.textSecondary, fontSize: 10.5, interval: 0,
                            lineHeight: 13 } },
      yAxis: { type: "value", ...axisCommon(t), axisLine: { show: false }, scale: true,
               axisLabel: { color: t.muted, fontSize: 11,
                            formatter: (x: number) => compact(x) } },
      series: [
        { type: "bar", stack: "n", silent: true, data: base, barWidth: "50%",
          itemStyle: { color: "transparent" } },
        { type: "bar", stack: "n", data: up, barWidth: "50%",
          itemStyle: { color: t.series[0], borderRadius: [4, 4, 0, 0] } },
        { type: "bar", stack: "n", data: down, barWidth: "50%",
          itemStyle: { color: t.critical, borderRadius: [0, 0, 4, 4] },
          label: { show: true, position: "bottom", color: t.textSecondary, fontSize: 10.5,
                   formatter: (p: { value: number }) => (p.value ? `-${compact(p.value)}` : "") } },
        { type: "bar", data: tot, barWidth: "50%",
          itemStyle: { color: t.series[2], borderRadius: [4, 4, 0, 0] },
          label: { show: true, position: "top", color: t.text, fontSize: 11, fontWeight: 600,
                   formatter: (p: { value: number }) => (p.value ? compact(p.value) : "") } },
      ],
    } as never;
  }, [v, t]);

  const toneOf = (s: string) =>
    s === "critical" ? "critical" : s === "serious" ? "critical"
    : s === "warning" ? "warning" : "info";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* --- what needs attention --- */}
      <Card title="Needs attention"
            subtitle={watch.data
              ? `${watch.data.count} item${watch.data.count === 1 ? "" : "s"}` +
                (watch.data.critical_count ? ` · ${watch.data.critical_count} critical` : "")
              : undefined}
            footnote="Ordered by money at stake rather than by rule, so the largest exposure reads first.">
        {!watch.data?.items.length
          ? <Empty title="Nothing outstanding"
                   hint="No stale data, no rejected rows, no loss-making products in this slice." />
          : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {watch.data.items.map((item, i) => (
                <div key={i} style={{
                  display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 10,
                  alignItems: "start", padding: "9px 11px", borderRadius: 8,
                  background: "var(--surface-2)",
                  borderLeft: `3px solid ${
                    item.severity === "critical" || item.severity === "serious"
                      ? "var(--status-critical)"
                      : item.severity === "warning" ? "var(--status-warning)"
                      : "var(--series-1)"}`,
                }}>
                  <Pill tone={toneOf(item.severity)}>{item.severity}</Pill>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{item.title}</div>
                    <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                      {item.detail}
                    </div>
                  </div>
                  {item.amount && (
                    <span className="tnum" style={{ fontSize: 12.5, fontWeight: 600,
                                                    whiteSpace: "nowrap" }}>
                      {money(item.amount)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
      </Card>

      {/* --- the ratios a bank reports daily --- */}
      <Grid cols="repeat(auto-fit, minmax(180px, 1fr))">
        <Stat label="Yield on advances" value={pct(r?.yield_on_advances_pct, 2)}
              hint="annualised" />
        <Stat label="Cost of deposits" value={pct(r?.cost_of_deposits_pct, 2)}
              hint="annualised" />
        <Stat label="Gross spread" value={pct(r?.gross_spread_pct, 2)}
              hint="yield less cost" tone="good" />
        <Stat label="Net interest margin" value={pct(r?.nim_pct, 2)}
              hint="NII over advances" />
        <Stat label="CASA ratio" value={pct(r?.casa_ratio_pct, 1)}
              hint="demand over total deposits"
              tone={n(r?.casa_ratio_pct) < 30 ? "bad" : "neutral"} />
        <Stat label="Credit-deposit ratio" value={pct(r?.credit_deposit_ratio_pct, 1)}
              hint={n(r?.credit_deposit_ratio_pct) > 100
                ? "advances exceed deposits" : "self-funded"}
              tone={n(r?.credit_deposit_ratio_pct) > 100 ? "bad" : "good"} />
      </Grid>

      <Grid cols="minmax(0, 1.25fr) minmax(0, 1fr)">
        {/* --- NII reconciliation --- */}
        <Card title="Where the customer margin goes"
              subtitle="Net interest income split between business units and treasury"
              footnote={v
                ? `Business units keep ${pct(v.business_units_share_pct, 1)} of NII. The treasury retains ${money(v.treasury_retained)} — mostly the cost of funding the net asset position. Reconciliation check ${v.check}.`
                : undefined}>
          {!niiOption ? <Empty title="No data" />
            : <Chart option={niiOption} height={262} loading={nii.loading}
                     ariaLabel="Net interest income reconciled to FTP" />}
        </Card>

        {/* --- the split, as numbers --- */}
        <Card title="Margin allocation"
              subtitle="Every figure below reconciles to the chart">
          {!v ? <Empty title="No data" />
            : (
              <dl style={{ margin: 0, display: "grid",
                           gridTemplateColumns: "1fr auto", rowGap: 7, fontSize: 12.5,
                           padding: "4px 4px 0" }}>
                <Line label="Interest received" value={money(v.interest_received)} />
                <Line label="Interest paid" value={`(${money(v.interest_paid)})`} />
                <Line label="Net interest income" value={money(v.net_interest_income)} bold />
                <Divider />
                <Line label="Lending spread (asset)" value={money(v.lending_spread)} />
                <Line label="Deposit spread (liability)" value={money(v.deposit_spread)} />
                <Line label="Business units total" value={money(v.business_units_total)} bold />
                <Divider />
                <Line label="Funding of net position" value={money(v.treasury_funding_of_gap)} />
                <Line label="Liquidity premium" value={money(v.liquidity_premium)} />
                <Line label="Other cost" value={money(v.other_cost)} />
                <Line label="Treasury retained" value={money(v.treasury_retained)} bold />
              </dl>
            )}
        </Card>
      </Grid>

      <Grid cols="minmax(0, 1fr) minmax(0, 1.2fr)">
        {/* --- MTD / QTD / YTD --- */}
        <Card title="Period to date"
              subtitle={periods.data?.as_of ? `as of ${longDate(periods.data.as_of)}` : undefined}>
          <Table rows={periods.data?.periods ?? []}
                 cols={[
                   { key: "label", label: "Period",
                     render: (p) => <b>{p.label}</b>, value: (p) => p.label },
                   { key: "d", label: "Days", align: "right", render: (p) => String(p.days),
                     value: (p) => p.days },
                   { key: "net", label: "Net FTP", align: "right",
                     render: (p) => money(p.net_ftp_profit), value: (p) => p.net_ftp_profit },
                   { key: "avg", label: "Avg / day", align: "right",
                     render: (p) => money(p.avg_daily), value: (p) => p.avg_daily },
                 ]} />
          <p style={{ margin: "10px 4px 0", fontSize: 11.5, color: "var(--text-muted)" }}>
            Balance sheet: advances {compact(r?.advances)} against deposits{" "}
            {compact(r?.deposits)}, a funding gap of {compact(r?.funding_gap)}.
          </p>
        </Card>

        {/* --- repricing opportunity --- */}
        <Card title="Repricing opportunity"
              subtitle={repricing.data
                ? `${repricing.data.accounts_below_median.toLocaleString()} account-days below their product median`
                : undefined}
              footnote="Measured against each product's median spread, not its mean: a few deeply mispriced accounts would drag a mean target down and understate the prize.">
          {!repricing.data?.accounts_below_median
            ? <Empty title="Nothing below median" />
            : (
              <>
                <Grid cols="repeat(auto-fit, minmax(130px, 1fr))" gap={10}>
                  <Stat label="Opportunity" value={money(repricing.data.opportunity)}
                        tone="good"
                        hint={`+${pct(repricing.data.uplift_pct, 1)} on current`} />
                  <Stat label="Balance affected"
                        value={compact(repricing.data.balance_below_median)} />
                </Grid>
                <div style={{ marginTop: 10 }}>
                  <Table rows={repricing.data.by_product}
                         csvName="ftp-repricing-by-product.csv"
                         cols={[
                           { key: "p", label: "Product", render: (x) => x.product_code,
                             value: (x) => x.product_code },
                           { key: "a", label: "Account-days", align: "right",
                             render: (x) => x.accounts.toLocaleString(),
                             value: (x) => x.accounts },
                           { key: "o", label: "Upside", align: "right",
                             render: (x) => money(x.opportunity),
                             value: (x) => x.opportunity },
                         ]} />
                </div>
              </>
            )}
        </Card>
      </Grid>

      {summary.data?.comparison && (
        <p style={{ margin: 0, fontSize: 11.5, color: "var(--text-muted)", textAlign: "center" }}>
          Comparing {longDate(summary.data.comparison.current_period.start)} –{" "}
          {longDate(summary.data.comparison.current_period.end)} against the preceding{" "}
          {summary.data.comparison.prior_period.days} days.
        </p>
      )}
    </div>
  );
}

function Line({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <>
      <dt style={{ color: bold ? "var(--text-primary)" : "var(--text-muted)",
                   fontWeight: bold ? 600 : 400 }}>{label}</dt>
      <dd className="tnum" style={{ margin: 0, textAlign: "right",
                                    color: "var(--text-primary)",
                                    fontWeight: bold ? 600 : 400 }}>{value}</dd>
    </>
  );
}

function Divider() {
  return <div style={{ gridColumn: "1 / -1", height: 1, background: "var(--grid)",
                       margin: "3px 0" }} />;
}
