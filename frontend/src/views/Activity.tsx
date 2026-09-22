import { useState } from "react";
import { api, AuditEntry, AuditEntryDetail } from "../api";
import { Button, Card, MiniButton, Pill, Table } from "../components/ui";
import { useAsync } from "../state";

/** The entity types the audit log actually carries, as the filter offers them.
 *  Derived from the services that write audit rows rather than from a DISTINCT
 *  over the log, which would scan an unbounded table on every page load. */
const ENTITIES: { value: string; label: string }[] = [
  { value: "", label: "Everything" },
  { value: "global_rate_config", label: "Global rate config" },
  { value: "product_rate_config", label: "Product rates" },
  { value: "product", label: "Products" },
  { value: "branch", label: "Branches" },
  { value: "upload_batch", label: "Uploads" },
  { value: "calculation_run", label: "Calculation runs" },
];

const PAGE = 50;

/** A create has no before, a delete has no after; only a change has a diff. */
function toneFor(action: string): "good" | "warning" | "critical" | "info" | "neutral" {
  if (action.startsWith("DELETE")) return "critical";
  if (action.startsWith("CREATE")) return "good";
  if (action.includes("CORRECT")) return "warning";
  return "info";
}

function when(iso: string) {
  return new Date(iso).toLocaleString("en-GB", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

/** The diff, as the one line a reviewer reads: `liquidity_cost 0.30 → 0.35`. */
function summarise(entry: AuditEntry): string {
  if (!entry.diff) return "—";
  const parts = Object.entries(entry.diff).map(([field, change]) => {
    const from = change.from ?? "—";
    const to = change.to ?? "—";
    return `${field.replace(/_/g, " ")} ${from} → ${to}`;
  });
  return parts.join(" · ");
}

export default function Activity() {
  const [entity, setEntity] = useState("");
  const [actor, setActor] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<AuditEntryDetail | null>(null);

  const log = useAsync(() => api.auditLog({
    entity_type: entity ? [entity] : undefined,
    actor: actor || undefined,
    date_from: from || undefined,
    date_to: to || undefined,
    limit: PAGE,
    offset,
  }), [entity, actor, from, to, offset]);

  const total = log.data?.total ?? 0;
  const shown = log.data?.items.length ?? 0;

  const field: React.CSSProperties = {
    background: "var(--surface-1)", border: "1px solid var(--border-strong)",
    borderRadius: 7, padding: "6px 8px", fontSize: 12.5,
  };

  async function show(entry: AuditEntry) {
    try { setOpen(await api.auditEntry(entry.id)); } catch { /* list stays usable */ }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Card
        title="Activity log"
        subtitle={log.error
          ? log.error
          : `${total.toLocaleString("en-IN")} events`
            + `${shown ? ` · showing ${offset + 1}–${offset + shown}` : ""}`}
        actions={
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <select style={field} value={entity} aria-label="Entity type"
                    onChange={(e) => { setEntity(e.target.value); setOffset(0); }}>
              {ENTITIES.map((x) => (
                <option key={x.value} value={x.value}>{x.label}</option>
              ))}
            </select>
            <input style={{ ...field, width: 120 }} value={actor} placeholder="Who"
                   aria-label="Actor username"
                   onChange={(e) => { setActor(e.target.value); setOffset(0); }} />
            <input style={field} type="date" value={from} aria-label="From date"
                   onChange={(e) => { setFrom(e.target.value); setOffset(0); }} />
            <input style={field} type="date" value={to} aria-label="To date"
                   onChange={(e) => { setTo(e.target.value); setOffset(0); }} />
          </div>
        }
        footnote="Append-only and hash-chained. Every change is recorded with the transaction that made it and cannot be altered afterwards.">
        <Table
          rows={log.data?.items ?? []}
          csvName="activity-log.csv"
          onRowClick={show}
          empty={log.error ?? "No activity matches these filters."}
          cols={[
            { key: "at", label: "When", render: (e) => when(e.occurred_at),
              value: (e) => e.occurred_at },
            { key: "who", label: "Who",
              render: (e) => e.actor_username ?? <i style={{ color: "var(--text-muted)" }}>
                system</i>,
              value: (e) => e.actor_username ?? "" },
            { key: "act", label: "Action",
              render: (e) => <Pill tone={toneFor(e.action)}>{e.action}</Pill>,
              value: (e) => e.action },
            { key: "ent", label: "Entity",
              render: (e) => <span>{e.entity_type.replace(/_/g, " ")}
                {e.entity_id && <b style={{ marginLeft: 5 }}>{e.entity_id}</b>}</span>,
              value: (e) => `${e.entity_type} ${e.entity_id ?? ""}`.trim() },
            { key: "diff", label: "What changed",
              render: (e) => <span style={{ color: "var(--text-secondary)",
                                            whiteSpace: "normal" }}>
                {summarise(e)}</span>,
              value: (e) => summarise(e) },
            { key: "more", label: "", align: "right",
              render: (e) => <MiniButton onClick={() => show(e)}>Detail</MiniButton> },
          ]}
        />

        {total > PAGE && (
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end",
                        marginTop: 10, alignItems: "center" }}>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
              Page {Math.floor(offset / PAGE) + 1} of {Math.ceil(total / PAGE)}
            </span>
            <MiniButton disabled={offset === 0}
                        onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              Newer
            </MiniButton>
            <MiniButton disabled={offset + PAGE >= total}
                        onClick={() => setOffset(offset + PAGE)}>
              Older
            </MiniButton>
          </div>
        )}
      </Card>

      {open && (
        <Card title={`${open.action} · ${open.entity_type.replace(/_/g, " ")}`
                     + `${open.entity_id ? ` ${open.entity_id}` : ""}`}
              subtitle={`${when(open.occurred_at)} by `
                        + `${open.actor_username ?? "the system"}`
                        + `${open.actor_scope ? ` (${open.actor_scope})` : ""}`}
              actions={<Button onClick={() => setOpen(null)}>Close</Button>}>
          <div style={{ display: "grid", gap: 12,
                        gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
            <Side title="Before" value={open.before} />
            <Side title="After" value={open.after} />
          </div>
        </Card>
      )}
    </div>
  );
}

function Side({ title, value }: { title: string; value: Record<string, unknown> | null }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, fontWeight: 600, letterSpacing: ".05em",
                    textTransform: "uppercase", color: "var(--text-muted)",
                    marginBottom: 6 }}>{title}</div>
      {value
        ? <pre style={{
            margin: 0, padding: "10px 12px", borderRadius: 8, fontSize: 12,
            background: "var(--surface-2)", border: "1px solid var(--border)",
            overflowX: "auto", lineHeight: 1.5,
          }}>{JSON.stringify(value, null, 2)}</pre>
        : <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: 0 }}>
            No {title.toLowerCase()} state for this event.
          </p>}
    </div>
  );
}
