import { useMemo, useState } from "react";
import { api, Dim } from "../api";
import Chart, { axisCommon, baseOption, useTokens } from "../components/Chart";
import { Card, Empty, Grid, MiniButton, Pill, Table } from "../components/ui";
import { compact, money, n, pct } from "../format";
import { useApp, useAsync } from "../state";

const AREAS: Dim[] = ["division", "district", "category", "branch"];

export default function Leaders() {
  const { filters, setFilters, branches } = useApp();
  const t = useTokens();
  const [group, setGroup] = useState<Dim>("division");
  const [area, setArea] = useState<Dim>("district");
  const [metric, setMetric] = useState<"profit" | "yield">("profit");

  const head = useAsync(() => api.headlinePerformers(filters), [filters]);
  const board = useAsync(
    () => api.leaderboard(filters, group, "branch", 3, metric), [filters, group, metric]);
  const lead = useAsync(() => api.productLeadership(filters, area), [filters, area]);

  // Grouped bar: each area's products side by side, one hue per product in
  // fixed slot order so a product keeps its colour across every area.
  const leadOption = useMemo(() => {
    const areas = lead.data?.areas ?? [];
    if (!areas.length) return null;
    const products = Array.from(
      new Set(areas.flatMap((a) => a.breakdown.map((b) => b.product_code))),
    ).slice(0, 8);
    return {
      ...baseOption(t),
      grid: { left: 8, right: 16, top: 34, bottom: 4, containLabel: true },
      legend: { ...baseOption(t).legend, top: 0, left: 0 },
      tooltip: {
        ...baseOption(t).tooltip, trigger: "axis", axisPointer: { type: "shadow" },
        valueFormatter: (v: number) => money(v),
      },
      xAxis: { type: "category", data: areas.map((a) => a.area_label), ...axisCommon(t),
               splitLine: { show: false },
               axisLabel: { color: t.textSecondary, fontSize: 11, interval: 0,
                            width: 90, overflow: "truncate" } },
      yAxis: { type: "value", ...axisCommon(t), axisLine: { show: false },
               axisLabel: { color: t.muted, fontSize: 11,
                            formatter: (v: number) => compact(v) } },
      series: products.map((code, i) => ({
        name: code, type: "bar", stack: "p",
        // 2px surface gap between stacked segments instead of a border.
        itemStyle: { color: t.series[i], borderColor: t.surface, borderWidth: 2 },
        emphasis: { focus: "series" },
        data: areas.map((a) =>
          n(a.breakdown.find((b) => b.product_code === code)?.net_ftp_profit ?? 0)),
      })),
    } as never;
  }, [lead.data, t]);

  const h = head.data;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* --- headline performers across every dimension --- */}
      <Grid cols="repeat(auto-fit, minmax(260px, 1fr))">
        {(["branch", "product", "division", "district", "category"] as const).map((dim) => {
          const v = h?.[dim];
          if (!v) return null;
          return (
            <Card key={dim} title={`Top ${dim}`} subtitle={`${v.count} in this slice`}
                  footnote={v.profit_yield_diverge
                    ? "The profit leader is not the yield leader: this segment earns most on size, not on pricing."
                    : "The same segment leads on both profit and yield."}>
              <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "2px 4px" }}>
                <Row label="By profit" value={v.top_by_profit.label}
                     sub={`${money(v.top_by_profit.net_ftp_profit)} · ${pct(v.top_by_profit.share_pct, 1)} of book`}
                     tone="good" />
                <Row label="By yield" value={v.top_by_yield.label}
                     sub={`${pct(v.top_by_yield.yield_pct, 4)} annualised`}
                     tone={v.profit_yield_diverge ? "warning" : "good"} />
                <Row label="Weakest" value={v.bottom_by_profit.label}
                     sub={`${money(v.bottom_by_profit.net_ftp_profit)} · ${pct(v.bottom_by_profit.yield_pct, 4)}`}
                     tone="critical" />
              </div>
            </Card>
          );
        })}
      </Grid>

      {/* --- leaderboard within each group --- */}
      <Card title="Best branches within each group"
            subtitle="Ranked inside the group, so large and small groups compare fairly"
            actions={
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {(["division", "district", "category"] as Dim[]).map((g) => (
                  <MiniButton key={g} active={group === g} onClick={() => setGroup(g)}>
                    {g}
                  </MiniButton>
                ))}
                <span style={{ width: 8 }} />
                <MiniButton active={metric === "profit"} onClick={() => setMetric("profit")}>
                  by profit
                </MiniButton>
                <MiniButton active={metric === "yield"} onClick={() => setMetric("yield")}>
                  by yield
                </MiniButton>
              </div>
            }>
        {!board.data?.available
          ? <Empty title="No data" hint={board.data?.reason} />
          : (
            <Grid cols="repeat(auto-fit, minmax(300px, 1fr))" gap={12}>
              {board.data.groups.map((g) => (
                <div key={String(g.group_key)} style={{
                  border: "1px solid var(--border)", borderRadius: 8, padding: "10px 12px",
                  background: "var(--surface-2)",
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between",
                                alignItems: "baseline", marginBottom: 8, gap: 8 }}>
                    <b style={{ fontSize: 13 }}>{g.group_label}</b>
                    <span className="tnum" style={{ fontSize: 12, color: "var(--text-muted)" }}>
                      {money(g.group_net_ftp_profit)}
                    </span>
                  </div>
                  {g.entries.map((e) => (
                    <button key={e.rank} onClick={() => {
                      const b = branches.find((x) => e.label.startsWith(x.branch_code));
                      if (b) setFilters((f) => ({ ...f, branch_id: [b.id] }));
                    }} style={{
                      display: "grid", gridTemplateColumns: "20px 1fr auto",
                      gap: 8, alignItems: "center", width: "100%",
                      background: "transparent", border: "none", padding: "4px 0",
                      cursor: "pointer", textAlign: "left",
                      borderBottom: "1px solid var(--grid)",
                    }}>
                      <span style={{
                        fontSize: 11, fontWeight: 700,
                        color: e.rank === 1 ? "var(--series-1)" : "var(--text-muted)",
                      }}>#{e.rank}</span>
                      <span style={{ fontSize: 12.5, color: "var(--text-primary)",
                                     overflow: "hidden", textOverflow: "ellipsis",
                                     whiteSpace: "nowrap" }}>{e.label}</span>
                      <span className="tnum" style={{ fontSize: 12,
                                                      color: "var(--text-secondary)" }}>
                        {metric === "profit" ? money(e.net_ftp_profit) : pct(e.yield_pct, 4)}
                      </span>
                    </button>
                  ))}
                  {g.laggard && g.member_count > board.data!.top && (
                    <p style={{ margin: "8px 0 0", fontSize: 11, color: "var(--text-muted)" }}>
                      Weakest: {g.laggard.label} at {money(g.laggard.net_ftp_profit)}
                    </p>
                  )}
                </div>
              ))}
            </Grid>
          )}
      </Card>

      {/* --- which product leads where --- */}
      <Card title="Which product leads where"
            subtitle={lead.data?.available
              ? `${lead.data.area_count} areas · ${lead.data.product_count} products`
              : undefined}
            actions={
              <div style={{ display: "flex", gap: 6 }}>
                {AREAS.map((a) => (
                  <MiniButton key={a} active={area === a} onClick={() => setArea(a)}>{a}</MiniButton>
                ))}
              </div>
            }
            footnote="Dominance is the winner's share of that area's profit; margin is how far ahead of the runner-up it sits. A high share with a thin margin is a contested area, not a safe one.">
        {!lead.data?.available
          ? <Empty title="No data" hint={lead.data?.reason} />
          : (
            <>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
                {lead.data.wins_by_product.map((w) => (
                  <Pill key={w.product_code} tone={w.areas_won > 1 ? "good" : "neutral"}>
                    {w.product_name} wins {w.areas_won}
                  </Pill>
                ))}
              </div>
              {leadOption && (
                <Chart option={leadOption} height={250} loading={lead.loading}
                       ariaLabel={`Product profit stacked by ${area}`} />
              )}
              <div style={{ marginTop: 10 }}>
                <Table csvName={`ftp-product-leadership-${area}.csv`}
                       rows={lead.data.areas}
                       cols={[
                         { key: "a", label: area, render: (r) => r.area_label,
                           value: (r) => r.area_label },
                         { key: "w", label: "Leading product",
                           render: (r) => (
                             <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                               <span aria-hidden style={{ width: 8, height: 8, borderRadius: 2,
                                 background: "var(--series-1)", display: "inline-block" }} />
                               {r.winner.product_name}
                             </span>
                           ),
                           value: (r) => r.winner.product_code },
                         { key: "p", label: "Net FTP", align: "right",
                           render: (r) => money(r.winner.net_ftp_profit),
                           value: (r) => r.winner.net_ftp_profit },
                         { key: "d", label: "Dominance", align: "right",
                           render: (r) => pct(r.dominance_pct, 1),
                           value: (r) => r.dominance_pct },
                         { key: "m", label: "Margin over #2", align: "right",
                           render: (r) => r.margin_over_runner_up
                             ? `+${money(r.margin_over_runner_up)}` : "—",
                           value: (r) => r.margin_over_runner_up },
                         { key: "r", label: "Runner-up",
                           render: (r) => r.runner_up?.product_code ?? "—",
                           value: (r) => r.runner_up?.product_code },
                       ]} />
              </div>
            </>
          )}
      </Card>
    </div>
  );
}

function Row({ label, value, sub, tone }: {
  label: string; value: string; sub: string;
  tone: "good" | "warning" | "critical";
}) {
  const color = { good: "var(--status-good)", warning: "var(--status-warning)",
                  critical: "var(--status-critical)" }[tone];
  const icon = { good: "▲", warning: "△", critical: "▼" }[tone];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 8,
                  alignItems: "start" }}>
      <span aria-hidden style={{ color, fontSize: 11, lineHeight: "18px" }}>{icon}</span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 10.5, fontWeight: 600, letterSpacing: ".05em",
                      textTransform: "uppercase", color: "var(--text-muted)" }}>{label}</div>
        <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text-primary)",
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {value}
        </div>
        <div className="tnum" style={{ fontSize: 11.5, color: "var(--text-secondary)" }}>
          {sub}
        </div>
      </div>
    </div>
  );
}
