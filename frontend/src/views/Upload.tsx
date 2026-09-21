import { useRef, useState } from "react";
import { api, Probe, UploadResult } from "../api";
import { Button, Card, Empty, Grid, Pill, Stat, Table } from "../components/ui";
import { longDate } from "../format";
import { useApp, useAsync } from "../state";

type Stage = "idle" | "probing" | "probed" | "uploading" | "done" | "error";

export default function Upload() {
  const { can, refreshData } = useApp();
  const [file, setFile] = useState<File | null>(null);
  const [probe, setProbe] = useState<Probe | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState<string | null>(null);
  const [businessDate, setBusinessDate] = useState("");
  const [sheet, setSheet] = useState("");
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const batches = useAsync(() => api.batches(), [stage === "done"]);
  const exceptions = useAsync(
    () => (result ? api.batchExceptions(result.batch_ref) : Promise.resolve([])),
    [result?.batch_ref],
  );

  const reset = () => {
    setFile(null); setProbe(null); setResult(null);
    setStage("idle"); setError(null); setBusinessDate(""); setSheet("");
  };

  async function handleFile(f: File) {
    reset();
    setFile(f);
    setStage("probing");
    try {
      const p = await api.probe(f);
      setProbe(p);
      setStage("probed");
      // A single qualifying sheet is the common daily case -- preselect it so
      // the operator confirms rather than retypes.
      const included = p.sheets.filter((s) => s.included);
      if (included.length === 1) {
        setSheet(included[0].name);
        if (included[0].business_date) setBusinessDate(included[0].business_date);
      }
    } catch (e) {
      setError((e as Error).message); setStage("error");
    }
  }

  async function submit() {
    if (!file) return;
    setStage("uploading"); setError(null);
    try {
      const r = await api.upload(file, {
        business_date: businessDate || undefined,
        sheet_name: sheet || undefined,
      });
      setResult(r);
      setStage("done");
      // Push the new numbers to every open view immediately rather than
      // waiting for the next poll.
      refreshData();
    } catch (e) {
      setError((e as Error).message); setStage("error");
    }
  }

  if (!can("UPLOAD_CREATE")) {
    return <Empty title="Not permitted"
                  hint="Uploading data needs the UPLOAD_CREATE permission." />;
  }

  const included = probe?.sheets.filter((s) => s.included) ?? [];
  const multiDate = included.length > 1;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Card title="Upload bank data"
            subtitle="Excel or CSV. A single daily sheet is the normal case; a multi-sheet workbook loads as a historical backfill."
            footnote="The file is fingerprinted on arrival, so re-uploading identical content is rejected rather than double-counted. Re-uploading a date that already has data supersedes it — nothing is deleted.">
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault(); setDrag(false);
            const f = e.dataTransfer.files?.[0];
            if (f) handleFile(f);
          }}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") inputRef.current?.click(); }}
          style={{
            border: `2px dashed ${drag ? "var(--series-1)" : "var(--border-strong)"}`,
            borderRadius: 10, padding: "30px 20px", textAlign: "center",
            background: drag ? "var(--surface-2)" : "transparent",
            cursor: "pointer", transition: "background .15s, border-color .15s",
          }}>
          <p style={{ margin: 0, fontSize: 14, fontWeight: 550 }}>
            {file ? file.name : "Drop a workbook here, or click to choose"}
          </p>
          <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--text-muted)" }}>
            {file
              ? `${(file.size / 1024).toFixed(0)} KB`
              : ".xlsx, .xlsm or .csv — macros are never opened"}
          </p>
          <input ref={inputRef} type="file" accept=".xlsx,.xlsm,.csv" hidden
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }} />
        </div>

        {error && (
          <div style={{
            marginTop: 12, padding: "10px 12px", borderRadius: 8,
            border: "1px solid var(--status-critical)",
            background: "var(--surface-2)", fontSize: 13,
          }}>
            <Pill tone="critical">Upload failed</Pill>
            <p style={{ margin: "6px 0 0", color: "var(--text-secondary)" }}>{error}</p>
          </div>
        )}

        {probe && stage !== "done" && (
          <div style={{ marginTop: 14 }}>
            <h4 style={{ margin: "0 0 8px", fontSize: 12.5, fontWeight: 600 }}>
              What the file contains
            </h4>
            <Table rows={probe.sheets}
                   cols={[
                     { key: "name", label: "Sheet" },
                     { key: "inc", label: "Status",
                       render: (r) => r.included
                         ? <Pill tone="good">will load</Pill>
                         : <Pill tone="neutral">skipped</Pill>,
                       value: (r) => (r.included ? "included" : "skipped") },
                     { key: "d", label: "Business date",
                       render: (r) => (r.business_date ? longDate(r.business_date) : "—"),
                       value: (r) => r.business_date },
                     { key: "rows", label: "Data rows", align: "right",
                       render: (r) => r.data_rows.toLocaleString(),
                       value: (r) => r.data_rows },
                     { key: "why", label: "Reason", render: (r) => r.reason },
                   ]} />

            {probe.header_issues.length > 0 && (
              <div style={{ marginTop: 10 }}>
                <Pill tone="warning">Header drift</Pill>
                <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 12,
                             color: "var(--text-secondary)" }}>
                  {probe.header_issues.map((h, i) => <li key={i}>{h}</li>)}
                </ul>
              </div>
            )}

            <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                          alignItems: "flex-end", marginTop: 14 }}>
              {multiDate ? (
                <p style={{ margin: 0, fontSize: 12.5, color: "var(--text-secondary)" }}>
                  {included.length} dated sheets will load as a backfill
                  ({probe.total_data_rows.toLocaleString()} rows).
                </p>
              ) : (
                <>
                  <label style={{ fontSize: 12 }}>
                    <span style={{ display: "block", color: "var(--text-muted)",
                                   fontSize: 10.5, fontWeight: 600, letterSpacing: ".05em",
                                   textTransform: "uppercase", marginBottom: 3 }}>
                      Business date
                    </span>
                    <input type="date" value={businessDate}
                           onChange={(e) => setBusinessDate(e.target.value)}
                           style={{ background: "var(--surface-1)", borderRadius: 7,
                                    border: "1px solid var(--border-strong)",
                                    padding: "6px 9px", fontSize: 12.5 }} />
                  </label>
                  <label style={{ fontSize: 12 }}>
                    <span style={{ display: "block", color: "var(--text-muted)",
                                   fontSize: 10.5, fontWeight: 600, letterSpacing: ".05em",
                                   textTransform: "uppercase", marginBottom: 3 }}>
                      Sheet
                    </span>
                    <select value={sheet} onChange={(e) => setSheet(e.target.value)}
                            style={{ background: "var(--surface-1)", borderRadius: 7,
                                     border: "1px solid var(--border-strong)",
                                     padding: "6px 9px", fontSize: 12.5 }}>
                      <option value="">auto-detect</option>
                      {probe.sheets.map((s) => (
                        <option key={s.name} value={s.name}>{s.name}</option>
                      ))}
                    </select>
                  </label>
                </>
              )}
              <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                <Button onClick={reset}>Cancel</Button>
                <Button variant="primary" onClick={submit}
                        disabled={!probe.ok || stage === "uploading"}>
                  {stage === "uploading" ? "Processing…" : "Load and calculate"}
                </Button>
              </div>
            </div>
          </div>
        )}

        {result && (
          <div style={{ marginTop: 14 }}>
            <Grid cols="repeat(auto-fit, minmax(140px, 1fr))" gap={10}>
              <Stat label="Rows read" value={result.total_rows.toLocaleString()} />
              <Stat label="Accepted" value={result.accepted_rows.toLocaleString()} tone="good" />
              <Stat label="Warned" value={result.warned_rows.toLocaleString()} />
              <Stat label="Rejected" value={result.rejected_rows.toLocaleString()}
                    tone={result.rejected_rows ? "bad" : "neutral"} />
              <Stat label="Subtotal rows" value={result.structural_rows.toLocaleString()}
                    hint="excluded by rule" />
            </Grid>
            <p style={{ marginTop: 10, fontSize: 12.5, color: "var(--text-secondary)" }}>
              Batch <b>{result.batch_ref}</b> · {result.status}
              {result.run_ref && <> · calculation {result.run_ref}</>}
              {result.business_dates.length > 0 && <>
                {" "}· {longDate(result.business_dates[0])}
                {result.business_dates.length > 1 &&
                  ` to ${longDate(result.business_dates.at(-1)!)}`}
              </>}
            </p>
            <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
              <Button variant="primary" onClick={() => { location.hash = "#/overview"; }}>
                View the dashboard
              </Button>
              <Button onClick={reset}>Upload another</Button>
            </div>

            {(exceptions.data ?? []).length > 0 && (
              <div style={{ marginTop: 14 }}>
                <h4 style={{ margin: "0 0 6px", fontSize: 12.5, fontWeight: 600 }}>
                  Exceptions
                </h4>
                <Table rows={exceptions.data ?? []} maxHeight={240}
                       csvName={`${result.batch_ref}-exceptions.csv`}
                       cols={[
                         { key: "sev", label: "Severity",
                           render: (r) => <Pill tone={r.severity === "REJECT" ? "critical"
                             : r.severity === "WARN" ? "warning" : "info"}>{r.severity}</Pill>,
                           value: (r) => r.severity },
                         { key: "rule_code", label: "Rule" },
                         { key: "origin", label: "Where",
                           render: (r) => r.origin ?? `row ${r.source_row_no ?? "—"}` },
                         { key: "message", label: "Message" },
                       ]} />
              </div>
            )}
          </div>
        )}
      </Card>

      <Card title="Upload history"
            subtitle="Every file, what it replaced, and what it produced"
            footnote="A superseded batch is retained and remains queryable; dashboards read only the current one.">
        <Table rows={batches.data ?? []} maxHeight={340} csvName="ftp-upload-history.csv"
               cols={[
                 { key: "batch_ref", label: "Batch" },
                 { key: "file_name", label: "File" },
                 { key: "bd", label: "Business date",
                   render: (r) => (r.business_date ? longDate(r.business_date) : "—"),
                   value: (r) => r.business_date },
                 { key: "st", label: "Status",
                   render: (r) => <Pill tone={r.status === "COMPLETED" ? "good"
                     : r.status === "FAILED" ? "critical" : "info"}>{r.status}</Pill>,
                   value: (r) => r.status },
                 { key: "rows", label: "Accepted", align: "right",
                   render: (r) => `${r.accepted_rows.toLocaleString()} / ${r.total_rows.toLocaleString()}`,
                   value: (r) => r.accepted_rows },
                 { key: "rej", label: "Rejected", align: "right",
                   render: (r) => r.rejected_rows.toLocaleString(),
                   value: (r) => r.rejected_rows },
                 { key: "cur", label: "Current",
                   render: (r) => r.is_current
                     ? <Pill tone="good">current</Pill>
                     : <Pill tone="neutral">superseded</Pill>,
                   value: (r) => r.is_current },
                 { key: "at", label: "Uploaded",
                   render: (r) => new Date(r.uploaded_at).toLocaleString("en-GB",
                     { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }),
                   value: (r) => r.uploaded_at },
               ]} />
      </Card>
    </div>
  );
}
