import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { Series } from "../api";
import Chart, { axisCommon, baseOption, fixedDomain, useTokens } from "../components/Chart";
import { Card, Empty, Grid, RankFilter, Stat } from "../components/ui";
import ProfitSummary from "../components/ProfitSummary";
import { compact, longDate, money, n, pct, shortDate } from "../format";
import { useApp, useAsync } from "../state";

type Level = "division" | "district" | "branch";

const TILE_H = 104;
const GAP = 14;
const TOP_N = 5;

/** The three ranking basis the branch charts can be cut on. */
const BRANCH_RANKS = [
  { id: "net", label: "Net FTP profit" },
  { id: "asset", label: "Asset FTP profit" },
  { id: "liability", label: "Liability FTP profit" },
] as const;
type BranchRank = (typeof BRANCH_RANKS)[number]["id"];

const rankValue = (r: Series, rank: BranchRank) =>
  rank === "asset" ? n(r.asset_ftp_profit)
  : rank === "liability" ? n(r.liability_ftp_profit)
  : n(r.net_ftp_profit);

export default function BasicOverview() {
  const { filters } = useApp();
  const t = useTokens();
  // Start at the coarsest level: with eight divisions the whole book fits on
  // screen at once, and drilling down is a click. Starting at branch level
  // would open on a few hundred rows nobody asked for.
  const [level, setLevel] = useState<Level>("division");
  // Fit the top block in one viewport: the tallest fixed chrome above the
  // content (sticky dock + status row + page padding) is ~132px.
  const [avail, setAvail] = useState(Math.max(520, window.innerHeight - 132));
  // Width of the page container, measured so the left rail can match the top
  // tiles exactly: (containerWidth - 4 gaps) / 5 columns.
  const pageRef = useRef<HTMLDivElement>(null);
  const [pageW, setPageW] = useState(0);

  // The two branch charts are cut from the same ranking, so they share the
  // window and basis. The product chart ranks on net only, so it has just a
  // window of its own.
  const [branchRank, setBranchRank] = useState<BranchRank>("net");
  const [branchPage, setBranchPage] = useState(0);
  const [productPage, setProductPage] = useState(0);

  useEffect(() => {
    const onResize = () => setAvail(Math.max(520, window.innerHeight - 132));
    onResize();
    window.addEventListener("resize", onResize);

    // The container width changes whenever the collapsible sidebar toggles,
    // which never fires a window resize, so watch the page itself.
    let ro: ResizeObserver | undefined;
    if (pageRef.current) {
      ro = new ResizeObserver(() => setPageW(pageRef.current!.clientWidth));
      ro.observe(pageRef.current);
    }
    return () => {
      window.removeEventListener("resize", onResize);
      ro?.disconnect();
    };
  }, []);

  const leftWidth = Math.max(220, Math.round((pageW - GAP * 4) / 5));

  const k = useAsync(() => api.kpis(filters), [filters]);
  const branches = useAsync(() => api.byBranch(filters), [filters]);
  const products = useAsync(() => api.byProduct(filters), [filters]);
  const trend = useAsync(() => api.trend(filters), [filters]);
  const divisions = useAsync(() => api.byDivision(filters), [filters]);
  const districts = useAsync(() => api.byDistrict(filters), [filters]);

  const kpis = k.data;
  const branchRows = (branches.data ?? []).slice().sort(
    (a, b) => Number(a.key) - Number(b.key));
  const productRows = (products.data ?? []).slice().sort(
    (a, b) => n(b.net_ftp_profit) - n(a.net_ftp_profit));
  const points = trend.data?.points ?? [];

  // Rank the rows for the top-N window (the 2 branch charts share a basis;
  // products are always ranked by net). Slicing happens at render time below
  // so a change of basis or of filter scope is always consistent with the
  // current page.
  const rankedBranches = useMemo(
    () => branchRows.slice().sort((a, b) => rankValue(b, branchRank) - rankValue(a, branchRank)),
    [branchRows, branchRank]);
  const branchChunks = Math.max(1, Math.ceil(rankedBranches.length / TOP_N));
  const productChunks = Math.max(1, Math.ceil(productRows.length / TOP_N));

  // If a filter change shrinks the data (or the basis changes the total pool
  // of windows), step back so the dropdown never points off the end.
  useEffect(() => {
    if (branchPage >= branchChunks) setBranchPage(0);
  }, [branchChunks, branchPage]);
  useEffect(() => {
    if (productPage >= productChunks) setProductPage(0);
  }, [productChunks, productPage]);
  useEffect(() => { setBranchPage(0); }, [branchRank]);

  const branchSlice = rankedBranches.slice(
    branchPage * TOP_N, branchPage * TOP_N + TOP_N);
  const productSlice = productRows.slice(
    productPage * TOP_N, productPage * TOP_N + TOP_N);

  const levelRows = level === "division" ? (divisions.data ?? [])
                  : level === "district" ? (districts.data ?? [])
                  : (branches.data ?? []);
  const levelLoading = level === "division" ? divisions.loading
                     : level === "district" ? districts.loading
                     : branches.loading;
  const levelSubtitle: Record<Level, string> = {
    division: "Net FTP profit by division",
    district: "Net FTP profit by district, each within its division",
    branch: "Net FTP profit by branch, each within its district",
  };

  // The daily series in the shape the summary component expects. A day has no
  // meaningful asset/liability stack to draw, so that split is turned off.
  const dailyRows = points.map((p) => ({
    key: p.key, label: longDate(p.key as string),
    parent_label: null,
    asset_ftp_profit: p.asset_ftp_profit,
    liability_ftp_profit: p.liability_ftp_profit,
    net_ftp_profit: p.net_ftp_profit,
    asset_balance: p.asset_balance, liability_balance: p.liability_balance,
    total_balance: p.total_balance, account_count: p.account_count,
    negative_ftp_count: p.negative_ftp_count, avg_ftp_rate: p.avg_ftp_rate,
  }));

  // Both branch charts page through the same ranking five at a time, and the
  // axis is fixed across those pages rather than fitted to the five on screen:
  // otherwise the second five are stretched to the same heights as the first
  // and a branch earning half as much draws an identical bar.
  //
  // The scale is the leading five's, read off the data — so it moves with the
  // filters and with the ranking basis, and every later page is drawn against
  // the leaders. Nothing here is a fixed figure.
  const branchDomain = useMemo(
    () => fixedDomain(rankedBranches.slice(0, TOP_N).flatMap((r) => [
      n(r.asset_ftp_profit), n(r.liability_ftp_profit), n(r.net_ftp_profit)])),
    [rankedBranches]);
  const sideDomain = useMemo(
    () => fixedDomain(rankedBranches.slice(0, TOP_N).flatMap((r) => [
      n(r.asset_ftp_profit), n(r.liability_ftp_profit)])),
    [rankedBranches]);

  // The axis carries the branch code on its own. A label is "<code> <name>" —
  // up to 32 characters — and five of those do not fit a half-width card, so
  // ECharts was dropping whichever ones collided and some of the five went
  // unlabelled. The code always fits and is enough to tell the bars apart.
  //
  // The name is not lost, only moved: the tooltip heads each bar with the full
  // label. `valueFormatter` is ignored once `formatter` is a function, so the
  // rows are assembled here instead.
  const branchTooltip = useMemo(() => {
    const full = new Map(branchSlice.map(
      (r) => [String(r.code ?? r.label), r.label]));
    const esc = (v: string) => v.replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
    return {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (ps: { name: string; marker: string;
                        seriesName: string; value: number }[]) => {
        if (!ps.length) return "";
        const rows = ps.map((q) =>
          `${q.marker}${q.seriesName}<span style="float:right;margin-left:18px;` +
          `font-weight:600">${money(q.value)}</span>`).join("<br/>");
        return `<div style="margin-bottom:4px;font-weight:600">` +
               `${esc(full.get(ps[0].name) ?? ps[0].name)}</div>${rows}`;
      },
    };
  }, [branchSlice]);

  // ---- grouped bar: asset vs liability vs net ftp by branch ---------------
  const branchOption = useMemo(() => {
    const labels = branchSlice.map((r) => String(r.code ?? r.label));
    return {
      ...baseOption(t),
      grid: { left: 8, right: 16, top: 34, bottom: 4, containLabel: true },
      tooltip: { ...baseOption(t).tooltip, ...branchTooltip },
      xAxis: { type: "category", data: labels, ...axisCommon(t),
               axisLabel: { color: t.textSecondary, fontSize: 11 } },
      yAxis: { type: "value", ...axisCommon(t), ...branchDomain,
               axisLine: { show: false },
               splitLine: { lineStyle: { color: t.grid, width: 1 } },
               axisLabel: { color: t.muted, fontSize: 11,
                            formatter: (v: number) => compact(v) } },
      series: [
        { name: "Asset FTP profit", type: "bar",
          data: branchSlice.map((r) => n(r.asset_ftp_profit)),
          itemStyle: { color: t.series[0], borderRadius: [2, 2, 0, 0] },
          emphasis: { focus: "series" } },
        { name: "Liability FTP profit", type: "bar",
          data: branchSlice.map((r) => n(r.liability_ftp_profit)),
          itemStyle: { color: t.series[1], borderRadius: [2, 2, 0, 0] },
          emphasis: { focus: "series" } },
        { name: "Net FTP profit", type: "bar",
          data: branchSlice.map((r) => n(r.net_ftp_profit)),
          itemStyle: { color: t.series[3], borderRadius: [2, 2, 0, 0] },
          emphasis: { focus: "series" } },
      ],
    } as never;
  }, [branchSlice, branchDomain, branchTooltip, t]);

  // ---- grouped bar: asset vs liability only -------------------------------
  const sideOption = useMemo(() => {
    const labels = branchSlice.map((r) => String(r.code ?? r.label));
    return {
      ...baseOption(t),
      grid: { left: 8, right: 16, top: 34, bottom: 4, containLabel: true },
      tooltip: { ...baseOption(t).tooltip, ...branchTooltip },
      xAxis: { type: "category", data: labels, ...axisCommon(t),
               axisLabel: { color: t.textSecondary, fontSize: 11 } },
      yAxis: { type: "value", ...axisCommon(t), ...sideDomain,
               axisLine: { show: false },
               splitLine: { lineStyle: { color: t.grid, width: 1 } },
               axisLabel: { color: t.muted, fontSize: 11,
                            formatter: (v: number) => compact(v) } },
      series: [
        { name: "Asset FTP profit", type: "bar",
          data: branchSlice.map((r) => n(r.asset_ftp_profit)),
          itemStyle: { color: t.series[0], borderRadius: [2, 2, 0, 0] },
          emphasis: { focus: "series" } },
        { name: "Liability FTP profit", type: "bar",
          data: branchSlice.map((r) => n(r.liability_ftp_profit)),
          itemStyle: { color: t.series[1], borderRadius: [2, 2, 0, 0] },
          emphasis: { focus: "series" } },
      ],
    } as never;
  }, [branchSlice, sideDomain, branchTooltip, t]);

  // ---- line: daily net ftp trend ------------------------------------------
  const trendOption = useMemo(() => {
    const dates = points.map((p) => p.key as string);
    return {
      ...baseOption(t),
      grid: { left: 8, right: 56, top: 34, bottom: 4, containLabel: true },
      legend: { ...baseOption(t).legend, top: 0, left: 0 },
      tooltip: {
        ...baseOption(t).tooltip,
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: t.axis, width: 1 } },
        formatter: (ps: never) => {
          const arr = ps as unknown as { axisValue: string; seriesName: string;
            value: number; color: string }[];
          return `<b>${shortDate(arr[0].axisValue)}</b><br/>` +
            arr.map((x) => `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${x.color};margin-right:6px"></span>${x.seriesName}: <b>${money(x.value)}</b>`).join("<br/>");
        },
      },
      xAxis: { type: "category", data: dates, boundaryGap: false,
               ...axisCommon(t), splitLine: { show: false },
               axisLabel: { color: t.muted, fontSize: 11,
                            formatter: (v: string) => shortDate(v) } },
      yAxis: { type: "value", ...axisCommon(t), axisLine: { show: false },
               scale: true,
               axisLabel: { color: t.muted, fontSize: 11,
                            formatter: (v: number) => compact(v) } },
      series: [{
        name: "Net FTP profit", type: "line", data: points.map((p) => n(p.net_ftp_profit)),
        smooth: false, symbol: "circle", symbolSize: 8, showSymbol: points.length <= 40,
        lineStyle: { width: 2, color: t.series[0] },
        itemStyle: { color: t.series[0], borderColor: t.surface, borderWidth: 2 },
        endLabel: { show: true, color: t.textSecondary, fontSize: 11,
                    formatter: (p: { value: number }) => compact(p.value) },
        emphasis: { focus: "series" },
      }],
    } as never;
  }, [points, t]);

  // ---- bar: product ftp profit --------------------------------------------
  const productOption = useMemo(() => {
    const rows = productSlice;
    return {
      ...baseOption(t),
      grid: { left: 8, right: 60, top: 12, bottom: 4, containLabel: true },
      legend: { show: false },
      tooltip: {
        ...baseOption(t).tooltip,
        trigger: "item",
        formatter: (p: never) => {
          const x = p as unknown as { name: string; value: number };
          const r = rows.find((q) => q.label === x.name);
          return `<b>${x.name}</b><br/>FTP profit: <b>${money(x.value)}</b><br/>` +
            `<span style="color:${t.muted}">Balance ${compact(r?.total_balance)} · ` +
            `${r?.account_count ?? 0} account-days · avg rate ${r?.avg_ftp_rate ?? "—"}%</span>`;
        },
      },
      xAxis: { type: "value", ...axisCommon(t), axisLine: { show: false },
               axisLabel: { color: t.muted, fontSize: 11,
                            formatter: (v: number) => compact(v) } },
      yAxis: { type: "category", data: rows.map((r) => r.label), ...axisCommon(t),
               splitLine: { show: false },
               axisLabel: { color: t.textSecondary, fontSize: 11 } },
      series: [{
        type: "bar", name: "FTP profit",
        data: rows.map((r) => n(r.net_ftp_profit)),
        barWidth: "56%",
        itemStyle: {
          color: (p: { value: number }) => (p.value < 0 ? t.critical : t.series[2]),
          borderRadius: [0, 4, 4, 0],
        },
        label: { show: true, position: "right", color: t.textSecondary,
                 fontSize: 11, formatter: (p: { value: number }) => compact(p.value) },
        emphasis: { itemStyle: { opacity: .85 } },
      }],
    } as never;
  }, [productSlice, t]);

  if (k.error) return <Empty title="Could not load" hint={k.error} />;

  const hasBranchData = branchRows.length > 0;

  // Top row of balance stats: stretches across the full page width so the
  // tiles grow into the space the chart grid leaves empty on the right.
  const topStats = (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))",
                  gap: GAP }}>
      <div style={{ height: TILE_H, display: "grid" }}>
        <Stat label="Asset balance" value={compact(kpis?.asset_balance)}
              hint="total before liabilities" />
      </div>
      <div style={{ height: TILE_H, display: "grid" }}>
        <Stat label="Liability balance" value={compact(kpis?.liability_balance)}
              hint="total borrowings and deposits" />
      </div>
      <div style={{ height: TILE_H, display: "grid" }}>
        <Stat label="Interest receivable" value={money(kpis?.interest_receivable)}
              hint="earned on the book" />
      </div>
      <div style={{ height: TILE_H, display: "grid" }}>
        <Stat label="Interest payable" value={money(kpis?.interest_payable)}
              hint="cost of the book" />
      </div>
      <div style={{ height: TILE_H, display: "grid" }}>
        <Stat label="Branches" value={String(kpis?.branch_count ?? 0)}
              hint={`${kpis?.day_count ?? 0} day${(kpis?.day_count ?? 0) === 1 ? "" : "s"}`} />
      </div>
    </div>
  );

  // Left rail: the five FTP headline stats, same tile size as the top row.
  const ftpStats = (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, flex: 1, minHeight: 0 }}>
      {[
        ["Asset FTP profit", money(kpis?.asset_ftp_profit), "funding benefit on assets"],
        ["Liability FTP profit", money(kpis?.liability_ftp_profit), "funding cost on liabilities"],
        ["Net FTP profit", money(kpis?.net_ftp_profit), "asset + liability FTP"],
        ["FTP / balance", pct(kpis?.ftp_over_balance_pct, 4), "annualised rate"],
        ["No. of days", String(kpis?.day_count ?? 0), "covered by the filters"],
      ].map(([label, value, hint]) => (
        <div key={label} style={{ height: TILE_H, display: "grid" }}>
          <Stat label={label} value={value} hint={hint} />
        </div>
      ))}
    </div>
  );

  // One screen, nothing scrolls -- while the screen can hold it. Everything is
  // a multiple of `avail`, so the page reflows on resize. Top row keeps its
  // natural height (~104px); the chart rows split the remainder.
  //
  // Each row is a *minimum*: when a card's header wraps (the branch cards carry
  // the rank filters) the row grows to keep the chart readable and the page
  // scrolls, rather than the chart being squeezed to a sliver. When the chart
  // area is too narrow for two readable columns, the charts stack.
  const topRowHeight = 104;
  const mainAreaHeight = Math.max(240, avail - topRowHeight - 12);
  const chartRowHeight = (mainAreaHeight - 12) / 2;
  const oneColumn = pageW > 0 && pageW - leftWidth - 14 < TWO_COLUMN_MIN;

  return (
    <div ref={pageRef} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* ---- the fixed no-scroll block ----------------------------------- */}
      <div style={{ minHeight: avail, display: "flex", flexDirection: "column",
                    gap: 12 }}>
        {topStats}

        <div style={{ flex: 1, minHeight: 0, display: "flex", gap: 14 }}>
          {/* Left: five headline FTP stats stacked to full height */}
<div style={{ display: "flex", minWidth: 200, width: leftWidth, flexShrink: 0,
                      justifyContent: "center" }}>
          {ftpStats}
        </div>

          {/* Right: the four charts in a 2x2 grid that fills the rest */}
          <div style={{ flex: 1, minWidth: 0, display: "grid", gap: 12,
                        gridTemplateRows:
                          `repeat(${oneColumn ? 4 : 2}, minmax(${chartRowHeight}px, auto))`,
                        gridTemplateColumns: oneColumn ? "1fr" : "1fr 1fr" }}>
            <Card expandable title="Branch FTP profitability"
                  subtitle="Asset, liability and net FTP profit per branch"
                  actions={<RankFilter
                    count={rankedBranches.length}
                    page={branchPage}
                    onPage={setBranchPage}
                    rank={branchRank}
                    ranks={[...BRANCH_RANKS]}
                    onRank={(r) => setBranchRank(r as BranchRank)}
                    unit="branches" />}>
              {!hasBranchData || branchSlice.length === 0
                ? <Empty title="No branches in this slice" />
                : <ChartFill>
                    <Chart option={branchOption} height="100%" loading={branches.loading}
                           ariaLabel="Branch FTP profitability by side" />
                  </ChartFill>}
            </Card>

            <Card expandable title="Asset vs Liability FTP"
                  subtitle="The two sides side-by-side per branch"
                  actions={<RankFilter
                    count={rankedBranches.length}
                    page={branchPage}
                    onPage={setBranchPage}
                    rank={branchRank}
                    ranks={[...BRANCH_RANKS]}
                    onRank={(r) => setBranchRank(r as BranchRank)}
                    unit="branches" />}>
              {!hasBranchData || branchSlice.length === 0
                ? <Empty title="No branches in this slice" />
                : <ChartFill>
                    <Chart option={sideOption} height="100%" loading={branches.loading}
                           ariaLabel="Asset versus liability FTP profit by branch" />
                  </ChartFill>}
            </Card>

            <Card expandable title="Daily FTP profit trend"
                  subtitle="Net FTP profit per day in the window">
              {points.length === 0
                ? <Empty title="No data in this window" hint="Widen the date range or clear a filter." />
                : <ChartFill>
                    <Chart option={trendOption} height="100%" loading={trend.loading}
                           ariaLabel="Daily net FTP profit trend" />
                  </ChartFill>}
            </Card>

            <Card expandable title="Product FTP profit"
                  subtitle="Net FTP profit by product"
                  actions={<RankFilter
                    count={productRows.length}
                    page={productPage}
                    onPage={setProductPage}
                    unit="products" />}>
              {productSlice.length === 0
                ? <Empty title="No products in this slice" />
                : <ChartFill>
                    <Chart option={productOption} height="100%" loading={products.loading}
                           ariaLabel="Net FTP profit by product" />
                  </ChartFill>}
            </Card>
          </div>
        </div>
      </div>

      {/* ---- the workbook's three summary sheets ------------------------- */}
      <div style={{ borderTop: "1px solid var(--border)", paddingTop: 16,
                    marginTop: 2 }}>
        <h2 style={{ margin: "0 0 2px", fontSize: 15, fontWeight: 650 }}>
          Profit summaries
        </h2>
        <p style={{ margin: "0 0 14px", fontSize: 12.5, color: "var(--text-muted)" }}>
          The workbook's Branch, Product and Daily profit sheets, rebuilt from
          the calculated results and scoped by the filters above.
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <ProfitSummary
            title="Branch profit"
            subtitle={levelSubtitle[level]}
            rows={levelRows}
            loading={levelLoading}
            unitLabel={level}
            csvName={`ftp-${level}-profit.csv`}
            levels={[
              { id: "division", label: "Division" },
              { id: "district", label: "District" },
              { id: "branch", label: "Branch" },
            ]}
            level={level}
            onLevel={(id) => setLevel(id as Level)}
            footnote="Roll up to division to see the whole book at a glance, or drill to branch for the detail. Each level is ranked on net FTP profit; the share column is of the total in scope."
          />

          <Grid cols="minmax(0, 1fr) minmax(0, 1fr)">
            <ProfitSummary
              title="Product profit"
              subtitle="Net FTP profit by product"
              rows={products.data ?? []}
              loading={products.loading}
              unitLabel="product"
              csvName="ftp-product-profit.csv"
              footnote="A product's FTP profit is the spread it earns over its own benchmark, after liquidity and other costs."
            />

            <ProfitSummary
              title="Daily profit"
              subtitle={points.length
                ? `${longDate(points[0].key as string)} to ${longDate(points[points.length - 1].key as string)}`
                : undefined}
              rows={dailyRows}
              loading={trend.loading}
              unitLabel="day"
              csvName="ftp-daily-profit.csv"
              showSides={false}
              footnote="Ranked by profit rather than by date, so the strongest and weakest days are the ones you see first. Sort by name for chronological order."
            />
          </Grid>
        </div>
      </div>
    </div>
  );
}

/** Fills whatever the card body has left once its header is laid out.
 *
 * The header carries the rank filters and wraps onto more lines as the page
 * narrows, so a chart sized to a precomputed pixel height ran out of the
 * bottom of its card. The chart sits in an absolutely positioned layer
 * instead, so its size follows the space the card has left and ECharts resizes
 * to match. The floor keeps it readable: below it the grid row grows. */
const MIN_CHART_HEIGHT = 160;
/** Narrower than this, two charts side by side are too cramped to read. */
const TWO_COLUMN_MIN = 640;
function ChartFill({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ position: "relative", height: "100%", minHeight: MIN_CHART_HEIGHT }}>
      <div style={{ position: "absolute", inset: 0 }}>{children}</div>
    </div>
  );
}
