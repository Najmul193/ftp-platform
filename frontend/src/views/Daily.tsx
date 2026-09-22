import { useMemo, useState } from "react";
import { api, type WatchItem } from "../api";
import Chart, { useTokens } from "../components/Chart";
import { waterfallOption } from "../components/waterfall";
import { Card, Empty, Grid, Pill, Stat, Table } from "../components/ui";
import { compact, longDate, money, n, pct } from "../format";
import { useApp, useAsync } from "../state";

/** The screen a bank runs on in the morning: what needs attention, where the
 *  margin went, and whether the ratios moved. */
export default function Daily() {
  const { filters, me } = useApp();
  const t = useTokens();

  const watch = useAsync(() => api.watchlist(filters), [filters]);
  const nii = useAsync(() => api.nii(filters), [filters]);
  const ratios = useAsync(() => api.ratios(filters), [filters]);
  const periods = useAsync(() => api.periodSummary(filters), [filters]);
  const repricing = useAsync(() => api.repricing(filters), [filters]);
  const summary = useAsync(() => api.summary(filters), [filters]);

  // -- acknowledged watchlist items ---------------------------------------- #
  // An operator acknowledges an item once and it stops imposing on every
  // reload; acking is personal, so the set is kept per user in localStorage.
  const ackKey = `ftp_acked_${me?.username ?? "local"}`;
  const readAcked = () => {
    try {
      return new Set<string>(JSON.parse(localStorage.getItem(ackKey) ?? "[]") as string[]);
    } catch {
      return new Set<string>();
    }
  };
  const [acked, setAcked] = useState<Set<string>>(readAcked);
  const fingerprint = (i: WatchItem) => `${i.severity}:${i.code}:${i.title}`;
  const writeAcked = (s: Set<string>) => {
    localStorage.setItem(ackKey, JSON.stringify([...s]));
    setAcked(s);
  };
  const ack = (i: WatchItem) => {
    const s = new Set(acked);
    s.add(fingerprint(i));
    writeAcked(s);
  };
  const restore = () => writeAcked(new Set());

  const visibleItems = (watch.data?.items ?? []).filter(
    (i) => !acked.has(fingerprint(i)));
  const ackedCount = (watch.data?.items.length ?? 0) - visibleItems.length;
  const nothingOutstanding = Boolean(watch.data) && visibleItems.length === 0;

  const r = ratios.data;
  const v = nii.data;

  // NII waterfall: customer margin down to what the business units keep.
  const niiOption = useMemo(() => {
    if (!v) return null;
    return waterfallOption([
      { label: "Net interest\nincome", value: n(v.net_interest_income), kind: "total" },
      { label: "Treasury\nfunding", value: n(v.treasury_funding_of_gap), kind: "delta" },
      { label: "Liquidity\npremium", value: n(v.liquidity_premium), kind: "delta" },
      { label: "Other\ncost", value: n(v.other_cost), kind: "delta" },
      { label: "Business\nunits", value: n(v.business_units_total), kind: "total" },
    ], t);
  }, [v, t]);

  const toneOf = (s: string) =>
    s === "critical" ? "critical" : s === "serious" ? "critical"
    : s === "warning" ? "warning" : "info";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* --- what needs attention --- */}
      <Card title="Needs attention"
            subtitle={watch.data
              ? `${visibleItems.length} item${visibleItems.length === 1 ? "" : "s"}` +
                (watch.data.critical_count ? ` · ${watch.data.critical_count} critical` : "") +
                (ackedCount ? ` · ${ackedCount} acknowledged` : "")
              : undefined}
            actions={ackedCount > 0
              ? <button onClick={restore} title="Bring all acknowledged items back"
                        style={{
                          border: "none", background: "transparent",
                          color: "var(--text-secondary)", fontSize: 12,
                          cursor: "pointer", padding: "4px 8px", borderRadius: 6,
                        }}>
                  Restore {ackedCount}
                </button>
              : undefined}
            footnote="Ordered by money at stake rather than by rule, so the largest exposure reads first. Acknowledge an item once and it stays hidden for you until it changes.">
        {!watch.data?.items.length
          ? <Empty title="Nothing outstanding"
                   hint="No stale data, no rejected rows, no loss-making products in this slice." />
          : nothingOutstanding
            ? <Empty title="Everything acknowledged"
                     hint="All items for this slice have been acknowledged." />
          : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {visibleItems.map((item, i) => (
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
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    {item.amount && (
                      <span className="tnum" style={{ fontSize: 12.5, fontWeight: 600,
                                                      whiteSpace: "nowrap" }}>
                        {money(item.amount)}
                      </span>
                    )}
                    <button onClick={() => ack(item)} title="Hide this item"
                            style={{
                              border: "1px solid var(--border)", background: "transparent",
                              color: "var(--text-secondary)", fontSize: 11.5,
                              cursor: "pointer", padding: "3px 9px", borderRadius: 6,
                              whiteSpace: "nowrap",
                            }}>
                      Ack
                    </button>
                  </div>
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
              footnote={!v ? undefined
                : v.nii_is_negative
                  ? `Net interest income is negative: this book pays more to depositors than it earns from borrowers, so there is no margin to share out. Business units still show ${money(v.business_units_total)} because FTP credits deposits for the funding they provide; the treasury carries the shortfall. Reconciliation check ${v.check}.`
                  : v.business_units_share_pct == null
                    ? `The treasury retains ${money(v.treasury_retained)} — mostly the cost of funding the net asset position. Reconciliation check ${v.check}.`
                    : `Business units keep ${pct(v.business_units_share_pct, 1)} of NII. The treasury retains ${money(v.treasury_retained)} — mostly the cost of funding the net asset position. Reconciliation check ${v.check}.`}>
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
          {summary.data.comparison.prior_has_data
            ? `Comparing ${longDate(summary.data.comparison.current_period.start)} – ` +
              `${longDate(summary.data.comparison.current_period.end)} against the ` +
              `preceding ${summary.data.comparison.prior_period.days} days.`
            : `Showing ${longDate(summary.data.comparison.current_period.start)} – ` +
              `${longDate(summary.data.comparison.current_period.end)}. No earlier ` +
              `data is loaded, so no period comparison is shown.`}
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
