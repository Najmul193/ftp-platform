import { useMemo, useState } from "react";
import { api } from "../api";
import { Card, Empty, Grid, MiniButton, Pill, Stat, Table } from "../components/ui";
import { compact, longDate, money, rate } from "../format";
import { useApp, useAsync } from "../state";

const PAGE = 50;

/** A page shaped like the "Consolidated Data" sheet of the workbook: every
 *  account-day as one row, all fifteen columns, nothing computed on the fly.
 *
 *  A snapshot is one business date. It opens on the most recent one, because
 *  that is the state the book stands in today, but any loaded date can be
 *  selected -- reading a single day is the normal way to use this sheet, and
 *  across several days each account appears once per day, which is a different
 *  question. "Full window" answers that one instead. */
export default function Consolidated() {
  const { filters, can, dataInfo } = useApp();
  //: null means "every date in the filter window"; otherwise a single date.
  const [snapshot, setSnapshot] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const [offset, setOffset] = useState(0);
  const [order, setOrder] = useState("business_date");
  const [desc, setDesc] = useState(false);

  const latest = dataInfo?.latest_business_date;

  // Which dates actually hold data under the current filters.
  const trend = useAsync(() => api.trend(filters), [filters]);
  const availableDates = useMemo(
    () => (trend.data?.points ?? []).map((p) => String(p.key)).sort(),
    [trend.data],
  );

  // Default to the newest available date, but never override a choice the
  // user has made -- otherwise changing a filter would silently reset it.
  const effective = useMemo(() => {
    if (touched) return snapshot;
    return availableDates.length ? availableDates[availableDates.length - 1] : null;
  }, [touched, snapshot, availableDates]);

  const f = useMemo(
    () => (effective
      ? { ...filters, date_from: effective, date_to: effective }
      : filters),
    [filters, effective],
  );

  const pick = (d: string | null) => { setSnapshot(d); setTouched(true); setOffset(0); };

  const page = useAsync(
    () => api.accounts(f, { limit: PAGE, offset, order, desc }),
    [f, offset, order, desc],
  );
  // Totals for the whole snapshot, not for the fifty rows on screen. Summing
  // the visible page gave a "Net FTP profit" that changed every time you
  // paged, which is not a figure anyone can use.
  const totals = useAsync(() => api.kpis(f), [f]);

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
        <Stat label="Snapshot"
              value={effective ? longDate(effective)
                     : `${availableDates.length} ${availableDates.length === 1 ? "date" : "dates"}`}
              hint={effective
                ? (effective === latest ? "latest loaded date" : "selected date")
                : "whole filter window"} />
        <Stat label="Account-days" value={total.toLocaleString()} />
        <Stat label="Asset FTP profit" value={money(totals.data?.asset_ftp_profit)}
              hint="whole snapshot" />
        <Stat label="Liability FTP profit" value={money(totals.data?.liability_ftp_profit)}
              hint="whole snapshot" />
        <Stat label="Net FTP profit" value={money(totals.data?.net_ftp_profit)}
              hint="whole snapshot" />
      </Grid>

      <Card title="Consolidated data"
            subtitle={effective
              ? `${total.toLocaleString()} account-days · every account as of ${longDate(effective)}`
              : `${total.toLocaleString()} account-days · all ${availableDates.length} dates in the filter window · same layout as the workbook sheet`}
            actions={
              <div style={{ display: "flex", gap: 6, alignItems: "center",
                            flexWrap: "wrap" }}>
                {/* Step through the loaded dates without opening the list --
                    reading consecutive days is the common way to use this. */}
                <MiniButton
                  onClick={() => {
                    const i = effective ? availableDates.indexOf(effective) : 0;
                    if (i > 0) pick(availableDates[i - 1]);
                  }}
                  title="Previous business date">‹</MiniButton>

                <select
                  value={effective ?? ""}
                  onChange={(e) => pick(e.target.value || null)}
                  style={{ background: "var(--surface-1)", borderRadius: 6,
                           border: "1px solid var(--border-strong)",
                           padding: "3px 8px", fontSize: 11.5 }}>
                  <option value="">Full window ({availableDates.length} dates)</option>
                  {availableDates.slice().reverse().map((d) => (
                    <option key={d} value={d}>
                      {longDate(d)}{d === latest ? " (latest)" : ""}
                    </option>
                  ))}
                </select>

                <MiniButton
                  onClick={() => {
                    const i = effective ? availableDates.indexOf(effective) : -1;
                    if (i >= 0 && i < availableDates.length - 1) pick(availableDates[i + 1]);
                  }}
                  title="Next business date">›</MiniButton>

                {effective !== latest && latest && (
                  <MiniButton onClick={() => pick(latest)}>Latest</MiniButton>
                )}
              </div>
            }
            footnote="A snapshot is one business date: each account appears once, in the state it stood on that day. Step through the dates with the arrows, or switch to the full window to read every account-day in the filter, like the workbook sheet.">
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