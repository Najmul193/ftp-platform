import { ReactNode, useMemo, useState } from "react";
import type { Series } from "../api";
import Chart, { axisCommon, baseOption, useTokens } from "../components/Chart";
import { Card, Empty, MiniButton, Table } from "../components/ui";
import { compact, money, n, pct } from "../format";

/** How many bars to draw before the tail is folded away.
 *
 *  Past roughly this many, a bar chart stops being read and starts being
 *  scrolled: the labels collide, the short bars become indistinguishable, and
 *  the eye gives up. The chart shows the head; the table carries everything. */
const CHART_LIMIT = 12;
const PAGE = 15;

/** English plurals for the handful of nouns this component is given. */
const plural = (word: string, n: number) =>
  n === 1 ? word : /(ch|sh|s|x|z)$/.test(word) ? `${word}es` : `${word}s`;

export interface SummaryColumn {
  key: string;
  label: string;
  align?: "left" | "right";
  render: (r: Series) => ReactNode;
  value: (r: Series) => unknown;
}

/**
 * A ranked profit summary: one of the workbook's summary sheets, sized for a
 * real bank rather than for five branches.
 *
 * The same component serves a dimension with eight members and one with a
 * few hundred. What changes with size is what is *drawn*: the chart keeps to
 * the leaders plus an "Other" bar carrying the tail, and the full list lives
 * in a searchable, paginated table underneath. Nothing is hidden -- the tail
 * is aggregated in plain sight and every row is one search away.
 */
export default function ProfitSummary({
  title, subtitle, rows, loading, unitLabel, csvName,
  levels, level, onLevel, footnote, showSides = true,
}: {
  title: string;
  subtitle?: string;
  rows: Series[];
  loading?: boolean;
  /** Singular noun for the thing being ranked: "branch", "product", "day". */
  unitLabel: string;
  csvName: string;
  levels?: { id: string; label: string }[];
  level?: string;
  onLevel?: (id: string) => void;
  footnote?: ReactNode;
  /** Daily profit has no asset/liability split worth stacking. */
  showSides?: boolean;
}) {
  const t = useTokens();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState<"net" | "label">("net");

  const ranked = useMemo(
    () => [...rows].sort((a, b) => n(b.net_ftp_profit) - n(a.net_ftp_profit)),
    [rows],
  );
  const grandTotal = useMemo(
    () => ranked.reduce((s, r) => s + n(r.net_ftp_profit), 0),
    [ranked],
  );

  // ---- chart: the leaders, with the tail folded into one honest bar -------
  const chartOption = useMemo(() => {
    if (!ranked.length) return null;
    // The tail is deliberately NOT drawn as an "Other" bar. With 101 of 113
    // branches in it, that bar is larger than every individual one put
    // together and flattens the twelve the chart exists to compare. Its total
    // is stated underneath instead, where it informs without distorting.
    const bars = ranked.slice(0, CHART_LIMIT).map((r) => ({
      label: r.label,
      asset: n(r.asset_ftp_profit),
      liability: n(r.liability_ftp_profit),
      net: n(r.net_ftp_profit),
    }));
    // Drawn bottom-up, so the largest sits at the top of a horizontal chart.
    bars.reverse();

    const b = baseOption(t);
    const series = showSides
      ? [
          { name: "Asset FTP", type: "bar", stack: "s",
            data: bars.map((x) => x.asset),
            // 2px surface gap between the stacked segments rather than a border.
            itemStyle: { color: t.series[0], borderColor: t.surface, borderWidth: 2 } },
          { name: "Liability FTP", type: "bar", stack: "s",
            data: bars.map((x) => x.liability),
            itemStyle: { color: t.series[2], borderColor: t.surface, borderWidth: 2 },
            label: { show: true, position: "right", color: t.textSecondary,
                     fontSize: 10.5,
                     formatter: (p: { dataIndex: number }) => compact(bars[p.dataIndex].net) } },
        ]
      : [
          { name: "Net FTP", type: "bar", data: bars.map((x) => x.net),
            itemStyle: {
              color: (p: { value: number }) => (p.value < 0 ? t.critical : t.series[0]),
              borderRadius: [0, 4, 4, 0],
            },
            label: { show: true, position: "right", color: t.textSecondary,
                     fontSize: 10.5,
                     formatter: (p: { value: number }) => compact(p.value) } },
        ];

    return {
      ...b,
      grid: { left: 8, right: 62, top: showSides ? 30 : 8, bottom: 4, containLabel: true },
      legend: showSides ? { ...b.legend, top: 0, left: 0 } : { show: false },
      tooltip: {
        ...b.tooltip, trigger: "axis", axisPointer: { type: "shadow" },
        formatter: (ps: unknown) => {
          const arr = ps as { dataIndex: number }[];
          const x = bars[arr[0].dataIndex];
          const share = grandTotal ? (x.net / grandTotal) * 100 : 0;
          return `<b>${x.label}</b><br/>` +
            (showSides
              ? `Asset ${money(x.asset)}<br/>Liability ${money(x.liability)}<br/>` : "") +
            `<b>Net ${money(x.net)}</b><br/>` +
            `<span style="color:${t.muted}">${share.toFixed(1)}% of total</span>`;
        },
      },
      xAxis: { type: "value", ...axisCommon(t), axisLine: { show: false },
               axisLabel: { color: t.muted, fontSize: 11,
                            formatter: (v: number) => compact(v) } },
      yAxis: { type: "category", data: bars.map((x) => x.label), ...axisCommon(t),
               splitLine: { show: false },
               axisLabel: { color: t.textSecondary, fontSize: 11,
                            width: 150, overflow: "truncate" } },
      series,
    } as never;
  }, [ranked, t, unitLabel, showSides, grandTotal]);

  // ---- table: everything, searchable and paginated -----------------------
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const base = q
      ? ranked.filter((r) => r.label.toLowerCase().includes(q)
          || (r.parent_label ?? "").toLowerCase().includes(q))
      : ranked;
    return sort === "label"
      ? [...base].sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true }))
      : base;
  }, [ranked, query, sort]);

  const pageRows = filtered.slice(page * PAGE, page * PAGE + PAGE);
  const hasParents = ranked.some((r) => r.parent_label);
  const tailRows = ranked.slice(CHART_LIMIT);
  const tail = tailRows.length;
  const tailTotal = tailRows.reduce((s, r) => s + n(r.net_ftp_profit), 0);

  const cols: SummaryColumn[] = [
    { key: "rank", label: "#", align: "right",
      render: (r) => String(ranked.indexOf(r) + 1), value: (r) => ranked.indexOf(r) + 1 },
    { key: "label", label: unitLabel, render: (r) => <b>{r.label}</b>, value: (r) => r.label },
    ...(hasParents ? [{
      key: "parent", label: "within", align: "left" as const,
      render: (r: Series) => (
        <span style={{ color: "var(--text-muted)" }}>{r.parent_label ?? "—"}</span>
      ),
      value: (r: Series) => r.parent_label ?? "",
    }] : []),
    ...(showSides ? [
      { key: "asset", label: "Asset FTP", align: "right" as const,
        render: (r: Series) => money(r.asset_ftp_profit),
        value: (r: Series) => r.asset_ftp_profit },
      { key: "liab", label: "Liability FTP", align: "right" as const,
        render: (r: Series) => money(r.liability_ftp_profit),
        value: (r: Series) => r.liability_ftp_profit },
    ] : []),
    { key: "net", label: "Net FTP", align: "right",
      render: (r) => (
        <b style={{ color: n(r.net_ftp_profit) < 0
          ? "var(--status-critical)" : "var(--text-primary)" }}>
          {money(r.net_ftp_profit)}
        </b>
      ),
      value: (r) => r.net_ftp_profit },
    { key: "share", label: "Share", align: "right",
      render: (r) => (grandTotal
        ? pct((n(r.net_ftp_profit) / grandTotal) * 100, 1) : "—"),
      value: (r) => (grandTotal ? (n(r.net_ftp_profit) / grandTotal) * 100 : 0) },
    { key: "rate", label: "Avg FTP rate", align: "right",
      render: (r) => pct(r.avg_ftp_rate, 4), value: (r) => r.avg_ftp_rate },
    { key: "acct", label: "Account-days", align: "right",
      render: (r) => r.account_count.toLocaleString(), value: (r) => r.account_count },
  ];

  return (
    <Card expandable
      title={title}
      subtitle={subtitle}
      actions={
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          {levels && onLevel && levels.map((l) => (
            <MiniButton key={l.id} active={level === l.id}
                        onClick={() => { onLevel(l.id); setPage(0); setQuery(""); }}>
              {l.label}
            </MiniButton>
          ))}
          {ranked.length > PAGE && (
            <input
              value={query}
              onChange={(e) => { setQuery(e.target.value); setPage(0); }}
              placeholder={`Find a ${unitLabel}…`}
              style={{ background: "var(--surface-1)", borderRadius: 6,
                       border: "1px solid var(--border-strong)",
                       padding: "3px 8px", fontSize: 11.5, width: 150 }} />
          )}
        </div>
      }
      footnote={footnote}
    >
      {!ranked.length ? (
        <Empty title={`No ${plural(unitLabel, 2)} in this slice`}
               hint="Widen the date range or clear a filter." />
      ) : (
        <>
          {chartOption && (
            <Chart option={chartOption}
                   height={Math.max(180, Math.min(ranked.length, CHART_LIMIT + 1) * 26 + 54)}
                   loading={loading}
                   ariaLabel={`Net FTP profit by ${unitLabel}`} />
          )}
          {tail > 0 && (
            <p style={{ margin: "4px 4px 8px", fontSize: 11.5,
                        color: "var(--text-muted)" }}>
              Chart shows the top {CHART_LIMIT} of {ranked.length}. The other{" "}
              {tail} {plural(unitLabel, tail)} total{tail === 1 ? "s" : ""}{" "}
              <b style={{ color: "var(--text-secondary)" }}>{money(tailTotal)}</b>
              {grandTotal ? ` (${pct((tailTotal / grandTotal) * 100, 1)} of the book)` : ""}
              {" "}and are listed in full below.
            </p>
          )}

          <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "center", gap: 10, margin: "10px 2px 4px",
                        flexWrap: "wrap" }}>
            <span style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
              {query
                ? `${filtered.length} of ${ranked.length} ${plural(unitLabel, ranked.length)} match`
                : `${ranked.length} ${plural(unitLabel, ranked.length)}`}
              {filtered.length > PAGE &&
                ` · showing ${page * PAGE + 1}–${Math.min((page + 1) * PAGE, filtered.length)}`}
            </span>
            <div style={{ display: "flex", gap: 5 }}>
              <MiniButton active={sort === "net"} onClick={() => setSort("net")}>
                By profit
              </MiniButton>
              <MiniButton active={sort === "label"} onClick={() => setSort("label")}>
                By name
              </MiniButton>
            </div>
          </div>

          <Table cols={cols} rows={pageRows} csvName={csvName}
                 empty={`No ${unitLabel} matches “${query}”.`} />

          {filtered.length > PAGE && (
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 6,
                          marginTop: 8 }}>
              <MiniButton onClick={() => setPage((p) => Math.max(0, p - 1))}>
                Previous
              </MiniButton>
              <MiniButton
                onClick={() => setPage((p) =>
                  (p + 1) * PAGE < filtered.length ? p + 1 : p)}>
                Next
              </MiniButton>
            </div>
          )}

          <div style={{ display: "flex", justifyContent: "space-between",
                        borderTop: "1px solid var(--border)", marginTop: 10,
                        paddingTop: 8, fontSize: 12.5 }}>
            <b>Total</b>
            <b className="tnum">{money(grandTotal)}</b>
          </div>
        </>
      )}
    </Card>
  );
}
