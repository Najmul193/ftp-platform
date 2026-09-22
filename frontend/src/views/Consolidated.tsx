import { useMemo, useState } from "react";
import { api } from "../api";
import { Card, Empty, Grid, MiniButton, Pill, Stat, Table } from "../components/ui";
import { compact, longDate, money, rate } from "../format";
import { useApp, useAsync } from "../state";

const PAGE = 50;

/** A page shaped like the "Consolidated Data" sheet of the workbook: every
 *  account-day as one row, all fifteen columns, nothing computed on the fly.
 *  Defaults to the latest upload date: that is the snapshot that says which
 *  account stands in which state today. */
export default function Consolidated() {
  const { filters, can, dataInfo } = useApp();
  const [scope, setScope] = useState<"latest" | "all">("latest");
  const [offset, setOffset] = useState(0);
  const [order, setOrder] = useState("business_date");
  const [desc, setDesc] = useState(false);

  const latest = dataInfo?.latest_business_date;
  const f = useMemo(
    () => scope === "latest" && latest
      ? { ...filters, date_from: latest, date_to: latest }
      : filters,
    [filters, scope, latest],
  );

  const page = useAsync(
    () => api.accounts(f, { limit: PAGE, offset, order, desc }),
    [f, offset, order, desc],
  );

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
      <Grid cols="repeat(auto-fit, minmax(200px, 1fr))">
        <Stat label="Snapshot" value={scope === "latest" && latest ? longDate(latest) : `${filters.date_from ?? "…"} – ${filters.date_to ?? "…"}`}
              hint={scope === "latest" ? "last upload date" : "whole filter window"} />
        <Stat label="Account-days" value={total.toLocaleString()} />
        <Stat label="Asset FTP profit" value={money(
          rows.reduce((a, r) => a + Number(r.asset_ftp_profit), 0))} hint="on this page" />
        <Stat label="Liability FTP profit" value={money(
          rows.reduce((a, r) => a + Number(r.liability_ftp_profit), 0))} hint="on this page" />
        <Stat label="Net FTP profit" value={money(
          rows.reduce((a, r) => a + Number(r.ftp_income), 0))} hint="on this page" />
      </Grid>

      <Card title="Consolidated data"
            subtitle={scope === "latest" && latest
              ? `${total.toLocaleString()} account-days · every account as of ${longDate(latest)} · the latest upload`
              : `${total.toLocaleString()} account-days · all dates in the filter window · same layout as the workbook sheet`}
            actions={
              <div style={{ display: "flex", gap: 6 }}>
                <MiniButton active={scope === "latest"} onClick={() => { setScope("latest"); setOffset(0); }}>
                  Latest date
                </MiniButton>
                <MiniButton active={scope === "all"} onClick={() => { setScope("all"); setOffset(0); }}>
                  Full window
                </MiniButton>
              </div>
            }
            footnote="The latest date is the last upload's snapshot: each account appears once, in the state it stands today. Switch to the full window to read every account-day in the filter, like the workbook sheet.">
        <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
          {[["business_date", "Date"], ["balance", "Balance"], ["normalized_roi", "ROI"],
            ["ftp_rate", "FTP rate"], ["ftp_income", "FTP profit"]].map(([k, lbl]) => (
            <MiniButton key={k} active={order === k} onClick={() => sortBy(k)}>
              {lbl}{arrow(k)}
            </MiniButton>
          ))}
        </div>

        <Table rows={rows} maxHeight={430} csvName="ftp-consolidated.csv"
               empty="No rows match this selection."
               cols={[
                 { key: "d", label: "Date", render: (r) => longDate(r.business_date),
                   value: (r) => r.business_date },
                 { key: "b", label: "Branch", render: (r) => r.branch_code },
                 { key: "a", label: "Account", render: (r) => r.account_no },
                 { key: "t", label: "Type",
                   render: (r) => <Pill tone={r.side === "ASSET" ? "info" : "neutral"}>
                     {r.side === "ASSET" ? "A" : "L"}</Pill>,
                   value: (r) => r.side },
                 { key: "p", label: "Product", render: (r) => r.product_code },
                 { key: "bal", label: "Balance", align: "right",
                   render: (r) => compact(r.balance), value: (r) => r.balance },
                 { key: "roi", label: "ROI", align: "right",
                   render: (r) => rate(r.normalized_roi, 2), value: (r) => r.normalized_roi },
                 { key: "bm", label: "Benchmark rate", align: "right",
                   render: (r) => rate(r.benchmark_rate, 2), value: (r) => r.benchmark_rate },
                 { key: "lq", label: "Liquidity cost", align: "right",
                   render: (r) => rate(r.liquidity_cost, 2), value: (r) => r.liquidity_cost },
                 { key: "oc", label: "Other cost", align: "right",
                   render: (r) => rate(r.other_cost, 2), value: (r) => r.other_cost },
                 { key: "fr", label: "FTP rate", align: "right",
                   render: (r) => (
                     <span style={{ color: r.negative_ftp_flag
                       ? "var(--status-critical)" : "var(--text-secondary)",
                       fontWeight: r.negative_ftp_flag ? 600 : 400 }}>
                       {rate(r.ftp_rate, 4)}
                     </span>
                   ),
                   value: (r) => r.ftp_rate },
                 { key: "fi", label: "FTP profit", align: "right",
                   render: (r) => money(r.ftp_income), value: (r) => r.ftp_income },
                 { key: "ci", label: "Customer interest", align: "right",
                   render: (r) => money(r.customer_interest), value: (r) => r.customer_interest },
                 { key: "af", label: "Asset FTP profit", align: "right",
                   render: (r) => money(r.asset_ftp_profit), value: (r) => r.asset_ftp_profit },
                 { key: "lf", label: "Liability FTP profit", align: "right",
                   render: (r) => money(r.liability_ftp_profit), value: (r) => r.liability_ftp_profit },
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
    </div>
  );
}