import { useMemo, useState } from "react";
import { api, Dim } from "../api";
import Chart, { axisCommon, baseOption, useTokens } from "../components/Chart";
import { Card, Empty, Grid, MiniButton, Pill, Stat, Table } from "../components/ui";
import { compact, longDate, money, n, pct, rate } from "../format";
import { useApp, useAsync } from "../state";

const PAGE = 50;

/** The cuts the risk charts can be taken on, in the order a reader tries them. */
const RISK_DIMS: Dim[] = ["product", "branch", "district", "division", "category"];
/** Bars past a dozen stop being readable in a card, and 64 districts never fit. */
const TOP_N = 12;

/**
 * The two ways to rank a loss, kept switchable because each hides what the
 * other shows: the biggest drag is usually just the biggest book, while the
 * worst-priced book is often small enough that its drag never reaches the top.
 */
const BASES = [
  { id: "drag", label: "Money given up" },
  { id: "rate", label: "Loss rate" },
] as const;
type Basis = (typeof BASES)[number]["id"];

export default function Accounts() {
  const { filters, setFilters, can } = useApp();
  const [offset, setOffset] = useState(0);
  const [order, setOrder] = useState("ftp_income");
  const [desc, setDesc] = useState(true);
  const [search, setSearch] = useState(filters.account_no ?? "");

  const page = useAsync(
    () => api.accounts(filters, { limit: PAGE, offset, order, desc }),
    [filters, offset, order, desc],
  );
  const outliers = useAsync(() => api.outliers(filters, 2.5), [filters]);
  const leak = useAsync(() => api.leakage(filters), [filters]);

  const [dim, setDim] = useState<Dim>("product");
  const [basis, setBasis] = useState<Basis>("drag");
  const risk = useAsync(() => api.accountRisk(filters, dim), [filters, dim]);
  const t = useTokens();

  // Every hook runs before the permission gate below, so the early return
  // never changes the hook order.
  const esc = (v: string) => v.replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);

  const ranked = useMemo(() => {
    const rows = risk.data?.segments ?? [];
    // `drag` is negative, so the worst loss is the most negative number.
    const key = (r: (typeof rows)[number]) =>
      basis === "rate" ? n(r.loss_rate_pct) : -n(r.drag);
    return rows.slice().sort((a, b) => key(b) - key(a)).slice(0, TOP_N);
  }, [risk.data, basis]);

  // ---- where the money is given up -------------------------------------- #
  const leakOption = useMemo(() => {
    if (!ranked.length) return null;
    // Horizontal, because these categories are words and words read across.
    // Reversed so the worst sits at the top, where the eye starts.
    const rows = ranked.slice().reverse();
    const isRate = basis === "rate";
    // What the whole book runs at, so a member reads as better or worse than
    // the average rather than as a bare number.
    const days = risk.data?.totals.account_days ?? 0;
    const bookRate = days
      ? (risk.data!.totals.negative_days / days) * 100 : 0;
    return {
      ...baseOption(t),
      grid: { left: 8, right: 42, top: 10, bottom: 4, containLabel: true },
      legend: { show: false },   // one series; the card title names it
      tooltip: {
        ...baseOption(t).tooltip, trigger: "item",
        formatter: (p: never) => {
          const r = rows[(p as unknown as { dataIndex: number }).dataIndex];
          return `<b>${esc(r.label)}</b><br/>` +
            `Given up ${money(r.drag)}<br/>` +
            `Loss rate ${pct(r.loss_rate_pct)} · ` +
            `${r.negative_days.toLocaleString()} of ` +
            `${r.account_days.toLocaleString()} account-days<br/>` +
            `Balance below cost ${compact(r.negative_balance)} ` +
            `(${pct(r.balance_at_risk_pct)})`;
        },
      },
      xAxis: { type: "value", ...axisCommon(t), axisLine: { show: false },
               // Money is a length from zero. A rate is a position: these sit
               // between 10% and 13%, so a zero-based bar draws them all at
               // nearly full width and the differences vanish. Dots may be
               // scaled to the data; bars may never be.
               scale: isRate,
               axisLabel: { color: t.muted, fontSize: 11,
                            formatter: (v: number) => isRate ? `${v}%` : compact(v) } },
      yAxis: { type: "category", data: rows.map((r) => r.label), ...axisCommon(t),
               splitLine: { show: false },
               axisLabel: { color: t.textSecondary, fontSize: 11 } },
      series: [isRate ? {
        // Dot plot: no baseline to honour, so a narrow band of rates reads.
        type: "scatter", symbolSize: 11,
        data: rows.map((r) => n(r.loss_rate_pct)),
        itemStyle: { color: t.critical, borderColor: t.surface, borderWidth: 2 },
        markLine: {
          silent: true, symbol: "none",
          lineStyle: { color: t.muted, width: 1, type: "dashed" },
          label: { formatter: "book", color: t.muted, fontSize: 10.5,
                   position: "insideEndTop" },
          data: [{ xAxis: bookRate }],
        },
      } : {
        type: "bar", barWidth: "58%",
        // The magnitude of the loss. A bar reads as a length and a length is
        // never negative; the signed figure is in the tooltip.
        data: rows.map((r) => Math.abs(n(r.drag))),
        itemStyle: { color: t.critical, borderRadius: [0, 4, 4, 0] },
      }],
    } as never;
  }, [ranked, basis, risk.data, t]);

  // ---- how much balance sits below its own funding cost ------------------ #
  const mixOption = useMemo(() => {
    const rows = (risk.data?.segments ?? []).slice()
      .sort((a, b) => n(b.balance_at_risk_pct) - n(a.balance_at_risk_pct))
      .slice(0, TOP_N).reverse();
    if (!rows.length) return null;
    return {
      ...baseOption(t),
      grid: { left: 8, right: 42, top: 26, bottom: 4, containLabel: true },
      legend: { ...baseOption(t).legend, top: 0, left: 0 },
      tooltip: {
        ...baseOption(t).tooltip, trigger: "axis", axisPointer: { type: "shadow" },
        formatter: (ps: never) => {
          const r = rows[(ps as unknown as { dataIndex: number }[])[0].dataIndex];
          return `<b>${esc(r.label)}</b><br/>` +
            `Below cost ${pct(r.balance_at_risk_pct)} · ${compact(r.negative_balance)}<br/>` +
            `Total balance ${compact(r.balance)}<br/>` +
            `Given up ${money(r.drag)}`;
        },
      },
      // One axis: both segments are shares of the same balance.
      xAxis: { type: "value", max: 100, ...axisCommon(t), axisLine: { show: false },
               axisLabel: { color: t.muted, fontSize: 11,
                            formatter: (v: number) => `${v}%` } },
      yAxis: { type: "category", data: rows.map((r) => r.label), ...axisCommon(t),
               splitLine: { show: false },
               axisLabel: { color: t.textSecondary, fontSize: 11 } },
      series: [
        { name: "Priced above cost", type: "bar", stack: "bal", barWidth: "58%",
          data: rows.map((r) => 100 - n(r.balance_at_risk_pct)),
          // A hairline in the surface colour keeps the two fills from touching.
          itemStyle: { color: t.series[0], borderColor: t.surface, borderWidth: 1 } },
        { name: "Below cost", type: "bar", stack: "bal", barWidth: "58%",
          data: rows.map((r) => n(r.balance_at_risk_pct)),
          itemStyle: { color: t.critical, borderColor: t.surface, borderWidth: 1 } },
      ],
    } as never;
  }, [risk.data, t]);

  // ---- is the leakage concentrated, or spread everywhere? ---------------- #
  const paretoOption = useMemo(() => {
    const rows = (risk.data?.segments ?? []).slice()
      .sort((a, b) => n(a.drag) - n(b.drag)).slice(0, TOP_N);
    const total = Math.abs(n(risk.data?.totals.drag));
    if (!rows.length || !total) return null;
    const share = rows.map((r) => Math.abs(n(r.drag)) / total * 100);
    let run = 0;
    const cumulative = share.map((v) => (run += v));
    return {
      ...baseOption(t),
      grid: { left: 8, right: 16, top: 30, bottom: 4, containLabel: true },
      legend: { ...baseOption(t).legend, top: 0, left: 0 },
      tooltip: {
        ...baseOption(t).tooltip, trigger: "axis", axisPointer: { type: "shadow" },
        formatter: (ps: never) => {
          const i = (ps as unknown as { dataIndex: number }[])[0].dataIndex;
          const r = rows[i];
          return `<b>${esc(r.label)}</b> (rank ${i + 1})<br/>` +
            `Given up ${money(r.drag)}<br/>` +
            `Share of all leakage ${share[i].toFixed(1)}% · ` +
            `cumulative ${cumulative[i].toFixed(1)}%`;
        },
      },
      xAxis: { type: "category", data: rows.map((r) => r.label), ...axisCommon(t),
               splitLine: { show: false },
               axisLabel: { color: t.textSecondary, fontSize: 10.5,
                            rotate: 32, hideOverlap: false } },
      // One axis: a share and a running share are both percentages, so no
      // second scale is invented for the line.
      yAxis: { type: "value", ...axisCommon(t), axisLine: { show: false },
               axisLabel: { color: t.muted, fontSize: 11,
                            formatter: (v: number) => `${v}%` } },
      series: [
        { name: "Share of leakage", type: "bar", barWidth: "52%", data: share,
          itemStyle: { color: t.critical, borderRadius: [4, 4, 0, 0] } },
        { name: "Cumulative", type: "line", data: cumulative,
          symbol: "circle", symbolSize: 8,
          lineStyle: { width: 2, color: t.series[0] },
          itemStyle: { color: t.series[0], borderColor: t.surface, borderWidth: 2 } },
      ],
    } as never;
  }, [risk.data, t]);

  if (!can("ACCOUNT_DRILLDOWN")) {
    return <Empty title="Not permitted"
                  hint="Account-level drilldown needs the ACCOUNT_DRILLDOWN permission." />;
  }

  const rows = page.data?.items ?? [];
  const total = page.data?.total ?? 0;

  const sortBy = (col: string) => {
    if (order === col) setDesc((d) => !d);
    else { setOrder(col); setDesc(true); }
    setOffset(0);
  };
  const arrow = (col: string) => (order === col ? (desc ? " ↓" : " ↑") : "");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Grid cols="repeat(auto-fit, minmax(190px, 1fr))">
        <Stat label="Account-days in slice" value={total.toLocaleString()} />
        <Stat label="Loss-making"
              value={(leak.data?.negative_account_days ?? 0).toLocaleString()}
              tone={(leak.data?.negative_account_days ?? 0) > 0 ? "bad" : "neutral"}
              hint={leak.data?.drag ? `drag ${money(leak.data.drag)}` : undefined} />
        <Stat label="Unusually priced" value={String(outliers.data?.count ?? 0)}
              hint={`beyond ${outliers.data?.z_threshold ?? 2.5}σ within product`} />
      </Grid>

      {/* ---- pricing risk, cut whichever way the reader needs ------------ */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 11.5, color: "var(--text-muted)", fontWeight: 600,
                       letterSpacing: ".05em", textTransform: "uppercase" }}>
          Break down by
        </span>
        {RISK_DIMS.map((d) => (
          <MiniButton key={d} active={dim === d} onClick={() => setDim(d)}>
            {d[0].toUpperCase() + d.slice(1)}
          </MiniButton>
        ))}
      </div>

      <Grid cols="minmax(0, 1fr) minmax(0, 1fr)">
        <Card expandable title="Where the book loses money"
              subtitle={`Worst ${TOP_N} by ${basis === "rate" ? "loss rate" : "money given up"}, by ${dim}`}
              actions={
                <div style={{ display: "flex", gap: 6 }}>
                  {BASES.map((b) => (
                    <MiniButton key={b.id} active={basis === b.id}
                                onClick={() => setBasis(b.id)}>
                      {b.label}
                    </MiniButton>
                  ))}
                </div>
              }
              footnote="Drag is the FTP income given up on account-days priced below their own funding cost. Ranking by money finds the biggest books; ranking by rate finds the worst-priced ones, which are often too small to reach the top on money alone.">
          {!leakOption
            ? <Empty title="No loss-making accounts in this slice" />
            : <Chart option={leakOption} height={300} loading={risk.loading}
                     ariaLabel={`FTP income given up by ${dim}`} />}
        </Card>

        <Card expandable title="Balance above vs below cost"
              subtitle={`Highest ${TOP_N} by share at risk, by ${dim}`}
              footnote="The share of balance sitting on a negative spread. Not the same as the count of accounts: one large account below cost outweighs many small ones, which is why this is weighted by balance.">
          {!mixOption
            ? <Empty title="No balance in this slice" />
            : <Chart option={mixOption} height={300} loading={risk.loading}
                     ariaLabel={`Share of balance priced below cost by ${dim}`} />}
        </Card>
      </Grid>

      <Card expandable title="Is the leakage concentrated?"
            subtitle={`How much of the total drag the worst ${TOP_N} ${dim}s account for`}
            footnote="A steep curve means a handful of repricing decisions would recover most of the loss. A flat one means the problem is spread across the book and needs a policy change rather than a list of exceptions.">
        {!paretoOption
          ? <Empty title="Nothing to concentrate" hint="No loss-making account-days in this slice." />
          : <Chart option={paretoOption} height={300} loading={risk.loading}
                   ariaLabel={`Cumulative share of FTP leakage by ${dim}`} />}
      </Card>

      <Card title="Account explorer"
            subtitle={`${total.toLocaleString()} account-days · showing ${rows.length}`}
            actions={
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input
                  placeholder="Account number…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      setOffset(0);
                      setFilters((f) => ({ ...f, account_no: search || undefined }));
                    }
                  }}
                  style={{ background: "var(--surface-1)", borderRadius: 7,
                           border: "1px solid var(--border-strong)",
                           padding: "5px 9px", fontSize: 12.5, width: 160 }} />
                <MiniButton active={filters.ftp_sign === "NEGATIVE"}
                            onClick={() => { setOffset(0); setFilters((f) => ({
                              ...f, ftp_sign: f.ftp_sign === "NEGATIVE" ? undefined : "NEGATIVE" })); }}>
                  Loss-making only
                </MiniButton>
              </div>
            }
            footnote="Every row carries the rate it was priced at and where each component came from, so a figure can be explained without re-deriving it.">
        <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
          {[["ftp_income", "FTP income"], ["balance", "Balance"],
            ["ftp_rate", "FTP rate"], ["normalized_roi", "ROI"]].map(([k, lbl]) => (
            <MiniButton key={k} active={order === k} onClick={() => sortBy(k)}>
              {lbl}{arrow(k)}
            </MiniButton>
          ))}
        </div>

        <Table rows={rows} maxHeight={430} csvName="ftp-accounts.csv"
               empty="No accounts match this selection."
               cols={[
                 { key: "d", label: "Date", render: (r) => longDate(r.business_date),
                   value: (r) => r.business_date },
                 { key: "b", label: "Branch", render: (r) => r.branch_code },
                 { key: "a", label: "Account", render: (r) => r.account_no },
                 { key: "p", label: "Product", render: (r) => r.product_code },
                 { key: "s", label: "Side",
                   render: (r) => <Pill tone={r.side === "ASSET" ? "info" : "neutral"}>
                     {r.side === "ASSET" ? "A" : "L"}</Pill>,
                   value: (r) => r.side },
                 { key: "bal", label: "Balance", align: "right",
                   render: (r) => compact(r.balance), value: (r) => r.balance },
                 { key: "roi", label: "ROI", align: "right",
                   render: (r) => rate(r.normalized_roi, 2), value: (r) => r.normalized_roi },
                 { key: "bm", label: "Benchmark", align: "right",
                   render: (r) => rate(r.benchmark_rate, 2), value: (r) => r.benchmark_rate },
                 { key: "fr", label: "FTP rate", align: "right",
                   render: (r) => (
                     <span style={{ color: r.negative_ftp_flag
                       ? "var(--status-critical)" : "var(--text-secondary)",
                       fontWeight: r.negative_ftp_flag ? 600 : 400 }}>
                       {r.negative_ftp_flag && <span aria-hidden>▼ </span>}
                       {rate(r.ftp_rate, 4)}
                     </span>
                   ),
                   value: (r) => r.ftp_rate },
                 { key: "fi", label: "FTP income", align: "right",
                   render: (r) => money(r.ftp_income), value: (r) => r.ftp_income },
                 { key: "ci", label: "Cust. interest", align: "right",
                   render: (r) => money(r.customer_interest), value: (r) => r.customer_interest },
                 { key: "src", label: "ROI source",
                   render: (r) => (
                     <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                       {r.roi_source === "BANK_PROVIDED" ? "bank" : "derived"}
                     </span>
                   ),
                   value: (r) => r.roi_source },
               ]} />

        <div style={{ display: "flex", justifyContent: "space-between",
                      alignItems: "center", marginTop: 10 }}>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            {offset + 1}–{Math.min(offset + PAGE, total)} of {total.toLocaleString()}
          </span>
          <div style={{ display: "flex", gap: 6 }}>
            <MiniButton disabled={offset === 0}
                        onClick={() => setOffset((o) => Math.max(0, o - PAGE))}>
              Previous
            </MiniButton>
            <MiniButton disabled={offset + PAGE >= total}
                        onClick={() => setOffset((o) =>
                          (o + PAGE < total ? o + PAGE : o))}>
              Next
            </MiniButton>
          </div>
        </div>
      </Card>

      {(outliers.data?.rows.length ?? 0) > 0 && (
        <Card title="Unusually priced accounts"
              subtitle={`Compared within their own product, beyond ${outliers.data?.z_threshold}σ`}
              footnote="Compared within product: a home loan and a current account have no business being compared on rate. An account far from its product's mean is either a data error or a deal worth knowing about.">
          <Table rows={outliers.data?.rows ?? []} maxHeight={280}
                 csvName="ftp-outliers.csv"
                 cols={[
                   { key: "d", label: "Date", render: (r) => longDate(r.business_date),
                     value: (r) => r.business_date },
                   { key: "b", label: "Branch", render: (r) => r.branch_code },
                   { key: "a", label: "Account", render: (r) => r.account_no },
                   { key: "p", label: "Product", render: (r) => r.product_code },
                   { key: "bal", label: "Balance", align: "right",
                     render: (r) => compact(r.balance), value: (r) => r.balance },
                   { key: "roi", label: "ROI", align: "right",
                     render: (r) => rate(r.normalized_roi, 2), value: (r) => r.normalized_roi },
                   { key: "fr", label: "FTP rate", align: "right",
                     render: (r) => rate(r.ftp_rate, 4), value: (r) => r.ftp_rate },
                   { key: "z", label: "σ from product mean", align: "right",
                     render: (r) => (
                       <span style={{ color: Math.abs(n(r.z_rate)) >= 3
                         ? "var(--status-critical)" : "var(--text-secondary)" }}>
                         {r.z_rate}
                       </span>
                     ),
                     value: (r) => r.z_rate },
                 ]} />
        </Card>
      )}
    </div>
  );
}
