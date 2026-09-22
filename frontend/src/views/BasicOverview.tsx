import { useMemo, useState } from "react";
import { api } from "../api";
import Chart, { axisCommon, baseOption, useTokens } from "../components/Chart";
import { Card, Empty, Grid, Stat } from "../components/ui";
import { compact, money, n, pct, shortDate } from "../format";
import ProfitSummary from "../components/ProfitSummary";
import { longDate } from "../format";
import { useApp, useAsync } from "../state";

type Level = "division" | "district" | "branch";

export default function BasicOverview() {
  const { filters } = useApp();
  const t = useTokens();
  // Start at the coarsest level: with eight divisions the whole book fits on
  // screen at once, and drilling down is a click. Starting at branch level
  // would open on a few hundred rows nobody asked for.
  const [level, setLevel] = useState<Level>("division");

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

  // ---- grouped bar: asset vs liability vs net ftp by branch ---------------
  const branchOption = useMemo(() => {
    const labels = branchRows.map((r) => r.label);
    return {
      ...baseOption(t),
      grid: { left: 8, right: 16, top: 34, bottom: 4, containLabel: true },
      tooltip: {
        ...baseOption(t).tooltip,
        trigger: "axis",
        axisPointer: { type: "shadow" },
        valueFormatter: (v: number) => money(v),
      },
      xAxis: { type: "category", data: labels, ...axisCommon(t),
               axisLabel: { color: t.textSecondary, fontSize: 11 } },
      yAxis: { type: "value", ...axisCommon(t), axisLine: { show: false },
               splitLine: { lineStyle: { color: t.grid, width: 1 } },
               axisLabel: { color: t.muted, fontSize: 11,
                            formatter: (v: number) => compact(v) } },
      series: [
        { name: "Asset FTP profit", type: "bar",
          data: branchRows.map((r) => n(r.asset_ftp_profit)),
          itemStyle: { color: t.series[0], borderRadius: [2, 2, 0, 0] },
          emphasis: { focus: "series" } },
        { name: "Liability FTP profit", type: "bar",
          data: branchRows.map((r) => n(r.liability_ftp_profit)),
          itemStyle: { color: t.series[1], borderRadius: [2, 2, 0, 0] },
          emphasis: { focus: "series" } },
        { name: "Net FTP profit", type: "bar",
          data: branchRows.map((r) => n(r.net_ftp_profit)),
          itemStyle: { color: t.series[3], borderRadius: [2, 2, 0, 0] },
          emphasis: { focus: "series" } },
      ],
    } as never;
  }, [branchRows, t]);

  // ---- grouped bar: asset vs liability only -------------------------------
  const sideOption = useMemo(() => {
    const labels = branchRows.map((r) => r.label);
    return {
      ...baseOption(t),
      grid: { left: 8, right: 16, top: 34, bottom: 4, containLabel: true },
      tooltip: {
        ...baseOption(t).tooltip,
        trigger: "axis",
        axisPointer: { type: "shadow" },
        valueFormatter: (v: number) => money(v),
      },
      xAxis: { type: "category", data: labels, ...axisCommon(t),
               axisLabel: { color: t.textSecondary, fontSize: 11 } },
      yAxis: { type: "value", ...axisCommon(t), axisLine: { show: false },
               splitLine: { lineStyle: { color: t.grid, width: 1 } },
               axisLabel: { color: t.muted, fontSize: 11,
                            formatter: (v: number) => compact(v) } },
      series: [
        { name: "Asset FTP profit", type: "bar",
          data: branchRows.map((r) => n(r.asset_ftp_profit)),
          itemStyle: { color: t.series[0], borderRadius: [2, 2, 0, 0] },
          emphasis: { focus: "series" } },
        { name: "Liability FTP profit", type: "bar",
          data: branchRows.map((r) => n(r.liability_ftp_profit)),
          itemStyle: { color: t.series[1], borderRadius: [2, 2, 0, 0] },
          emphasis: { focus: "series" } },
      ],
    } as never;
  }, [branchRows, t]);

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
    const rows = productRows;
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
  }, [productRows, t]);

  if (k.error) return <Empty title="Could not load" hint={k.error} />;

  const hasBranchData = branchRows.length > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div>
        <div style={{ fontSize: 17, fontWeight: 700, color: "var(--text-primary)" }}>
          Branch FTP Profitability Dashboard
        </div>
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
          Basic overview — balances, interest and FTP profit for the selected filters.
        </div>
      </div>

      <Grid cols="repeat(auto-fit, minmax(180px, 1fr))">
        <Stat label="Asset balance" value={compact(kpis?.asset_balance)}
              hint="total before liabilities" />
        <Stat label="Liability balance" value={compact(kpis?.liability_balance)}
              hint="total borrowings and deposits" />
        <Stat label="Interest receivable" value={money(kpis?.interest_receivable)}
              hint="earned on the book" />
        <Stat label="Interest payable" value={money(kpis?.interest_payable)}
              hint="cost of the book" />
        <Stat label="Branches" value={String(kpis?.branch_count ?? 0)}
              hint="in scope" />
      </Grid>

      <Grid cols="repeat(auto-fit, minmax(180px, 1fr))">
        <Stat label="Asset FTP profit" value={money(kpis?.asset_ftp_profit)}
              hint="funding benefit on assets" />
        <Stat label="Liability FTP profit" value={money(kpis?.liability_ftp_profit)}
              hint="funding cost on liabilities" />
        <Stat label="Net FTP profit" value={money(kpis?.net_ftp_profit)}
              hint="asset + liability FTP" />
        <Stat label="FTP / balance" value={pct(kpis?.ftp_over_balance_pct, 4)}
              hint="annualised rate" />
        <Stat label="No. of days" value={String(kpis?.day_count ?? 0)}
              hint="covered by the filters" />
      </Grid>

      <Grid cols="minmax(0, 1fr) minmax(0, 1fr)">
        <Card title="Branch FTP profitability"
              subtitle="Asset, liability and net FTP profit per branch">
          {!hasBranchData
            ? <Empty title="No branches in this slice" />
            : <Chart option={branchOption} height={286} loading={branches.loading}
                     ariaLabel="Branch FTP profitability by side" />}
        </Card>

        <Card title="Asset vs Liability FTP"
              subtitle="The two sides side-by-side per branch">
          {!hasBranchData
            ? <Empty title="No branches in this slice" />
            : <Chart option={sideOption} height={286} loading={branches.loading}
                     ariaLabel="Asset versus liability FTP profit by branch" />}
        </Card>
      </Grid>

      <Grid cols="minmax(0, 1fr) minmax(0, 1fr)">
        <Card title="Daily FTP profit trend"
              subtitle="Net FTP profit per day in the window">
          {points.length === 0
            ? <Empty title="No data in this window" hint="Widen the date range or clear a filter." />
            : <Chart option={trendOption} height={260} loading={trend.loading}
                     ariaLabel="Daily net FTP profit trend" />}
        </Card>

        <Card title="Product FTP profit"
              subtitle="Net FTP profit by product">
          {productRows.length === 0
            ? <Empty title="No products in this slice" />
            : <Chart option={productOption} height={260} loading={products.loading}
                     ariaLabel="Net FTP profit by product" />}
        </Card>
      </Grid>

      {/* ---- the workbook's three summary sheets ------------------------ */}
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