import { useState } from "react";
import { api } from "../api";
import { Card, Empty, Grid, MiniButton, Pill, Stat, Table } from "../components/ui";
import { compact, longDate, money, n, rate } from "../format";
import { useApp, useAsync } from "../state";

const PAGE = 50;

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
