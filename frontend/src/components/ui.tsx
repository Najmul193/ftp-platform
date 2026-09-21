import { ReactNode, useState } from "react";
import { compact, money, n, pct, signed, toCsv } from "../format";

// --------------------------------------------------------------------------
// Card
// --------------------------------------------------------------------------

export function Card({
  title, subtitle, children, actions, footnote, pad = true,
}: {
  title?: ReactNode; subtitle?: ReactNode; children: ReactNode;
  actions?: ReactNode; footnote?: ReactNode; pad?: boolean;
}) {
  return (
    <section style={{
      background: "var(--surface-1)", border: "1px solid var(--border)",
      borderRadius: "var(--radius)", boxShadow: "var(--shadow)",
      display: "flex", flexDirection: "column", minWidth: 0,
    }}>
      {(title || actions) && (
        <header style={{
          display: "flex", alignItems: "flex-start", justifyContent: "space-between",
          gap: 12, padding: "14px 16px 0", flexWrap: "wrap",
        }}>
          <div style={{ minWidth: 0 }}>
            {title && <h3 style={{
              margin: 0, fontSize: 13, fontWeight: 600, letterSpacing: ".01em",
              color: "var(--text-primary)",
            }}>{title}</h3>}
            {subtitle && <p style={{
              margin: "2px 0 0", fontSize: 12, color: "var(--text-muted)",
            }}>{subtitle}</p>}
          </div>
          {actions && <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>{actions}</div>}
        </header>
      )}
      <div style={{ padding: pad ? "8px 12px 12px" : 0, flex: 1, minWidth: 0 }}>{children}</div>
      {footnote && (
        <footer style={{
          padding: "0 16px 12px", fontSize: 11, color: "var(--text-muted)",
          lineHeight: 1.45,
        }}>{footnote}</footer>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------
// Stat tile -- the form for "the story is one number"
// --------------------------------------------------------------------------

export function Stat({
  label, value, delta, deltaPct, hint, spark, tone = "neutral", invertDelta = false,
}: {
  label: string; value: string; delta?: string | null; deltaPct?: string | null;
  hint?: string; spark?: number[]; tone?: "neutral" | "good" | "bad";
  invertDelta?: boolean;
}) {
  const d = delta == null ? null : n(delta);
  const improving = d == null ? null : invertDelta ? d < 0 : d > 0;
  const deltaColor = improving == null ? "var(--text-muted)"
    : improving ? "var(--delta-up)" : "var(--delta-down)";

  return (
    <div style={{
      background: "var(--surface-1)", border: "1px solid var(--border)",
      borderRadius: "var(--radius)", padding: "14px 16px",
      boxShadow: "var(--shadow)", display: "flex", flexDirection: "column", gap: 4,
      minWidth: 0,
    }}>
      <span style={{
        fontSize: 11, fontWeight: 600, letterSpacing: ".06em", textTransform: "uppercase",
        color: "var(--text-muted)",
      }}>{label}</span>

      {/* Proportional figures: tabular-nums reads loose at display size. */}
      <strong style={{
        fontSize: 26, fontWeight: 650, lineHeight: 1.15, letterSpacing: "-.02em",
        color: tone === "good" ? "var(--delta-up)"
             : tone === "bad" ? "var(--delta-down)" : "var(--text-primary)",
      }}>{value}</strong>

      {(d != null || hint) && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {d != null && (
            <span style={{ fontSize: 12, fontWeight: 600, color: deltaColor,
                           display: "inline-flex", alignItems: "center", gap: 3 }}>
              {/* Direction is carried by the arrow glyph and the sign, not by
                  colour alone. */}
              <span aria-hidden>{improving ? "▲" : "▼"}</span>
              {signed(delta)}
              {deltaPct != null && <span style={{ opacity: .85 }}>({pct(deltaPct, 1)})</span>}
            </span>
          )}
          {hint && <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{hint}</span>}
        </div>
      )}

      {spark && spark.length > 1 && <Sparkline values={spark} />}
    </div>
  );
}

function Sparkline({ values }: { values: number[] }) {
  const w = 120, h = 24;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w;
    const y = h - ((v - min) / span) * (h - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ marginTop: 2 }} aria-hidden>
      <polyline points={pts} fill="none" stroke="var(--series-1)" strokeWidth="2"
                strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// --------------------------------------------------------------------------
// Table -- every chart's accessible twin
// --------------------------------------------------------------------------

export interface Col<T> {
  key: string;
  label: string;
  align?: "left" | "right";
  render?: (row: T) => ReactNode;
  value?: (row: T) => unknown;
  width?: number | string;
}

export function Table<T>({
  cols, rows, empty = "No data for this selection.", maxHeight, csvName, onRowClick,
}: {
  cols: Col<T>[]; rows: T[]; empty?: string; maxHeight?: number;
  csvName?: string; onRowClick?: (row: T) => void;
}) {
  if (!rows.length) {
    return <p style={{ padding: "18px 4px", color: "var(--text-muted)", fontSize: 13, margin: 0 }}>
      {empty}
    </p>;
  }
  return (
    <>
      {csvName && (
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}>
          <MiniButton onClick={() => toCsv(
            rows.map((r) => Object.fromEntries(
              cols.map((c) => [c.label, c.value ? c.value(r) : (r as never)[c.key]]),
            )), csvName,
          )}>Export CSV</MiniButton>
        </div>
      )}
      <div style={{ overflowX: "auto", maxHeight, overflowY: maxHeight ? "auto" : undefined }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c.key} scope="col" style={{
                  textAlign: c.align ?? "left", padding: "7px 10px",
                  position: maxHeight ? "sticky" : undefined, top: 0,
                  background: "var(--surface-1)",
                  borderBottom: "1px solid var(--border)",
                  color: "var(--text-muted)", fontWeight: 600, fontSize: 11,
                  letterSpacing: ".04em", textTransform: "uppercase",
                  whiteSpace: "nowrap", width: c.width,
                }}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}
                  onClick={onRowClick ? () => onRowClick(r) : undefined}
                  style={{
                    borderBottom: "1px solid var(--grid)",
                    cursor: onRowClick ? "pointer" : undefined,
                  }}>
                {cols.map((c) => (
                  <td key={c.key} className="tnum" style={{
                    textAlign: c.align ?? "left", padding: "7px 10px",
                    color: "var(--text-secondary)", whiteSpace: "nowrap",
                  }}>
                    {c.render ? c.render(r) : String((r as never)[c.key] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// --------------------------------------------------------------------------
// Small pieces
// --------------------------------------------------------------------------

export function MiniButton({ children, onClick, active, title }: {
  children: ReactNode; onClick?: () => void; active?: boolean; title?: string;
}) {
  return (
    <button type="button" onClick={onClick} title={title} style={{
      border: "1px solid var(--border)", background: active ? "var(--surface-2)" : "transparent",
      color: active ? "var(--text-primary)" : "var(--text-secondary)",
      borderRadius: 6, padding: "3px 9px", fontSize: 11.5, cursor: "pointer",
      fontWeight: active ? 600 : 500, whiteSpace: "nowrap",
    }}>{children}</button>
  );
}

export function Button({ children, onClick, variant = "default", disabled, type = "button" }: {
  children: ReactNode; onClick?: () => void;
  variant?: "default" | "primary" | "danger"; disabled?: boolean;
  type?: "button" | "submit";
}) {
  const styles = {
    default: { bg: "var(--surface-1)", fg: "var(--text-primary)", bd: "var(--border-strong)" },
    primary: { bg: "var(--series-1)", fg: "#fff", bd: "var(--series-1)" },
    danger:  { bg: "var(--status-critical)", fg: "#fff", bd: "var(--status-critical)" },
  }[variant];
  return (
    <button type={type} onClick={onClick} disabled={disabled} style={{
      background: styles.bg, color: styles.fg, border: `1px solid ${styles.bd}`,
      borderRadius: 7, padding: "7px 14px", fontSize: 13, fontWeight: 550,
      cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? .5 : 1,
    }}>{children}</button>
  );
}

/** Status pill. Always icon + label -- colour never carries the meaning alone. */
export function Pill({ tone, children }: {
  tone: "good" | "warning" | "critical" | "neutral" | "info"; children: ReactNode;
}) {
  const map = {
    good:     { c: "var(--status-good)", i: "✓" },
    warning:  { c: "var(--status-warning)", i: "△" },
    critical: { c: "var(--status-critical)", i: "✕" },
    info:     { c: "var(--series-1)", i: "ℹ" },
    neutral:  { c: "var(--text-muted)", i: "·" },
  }[tone];
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      fontSize: 11, fontWeight: 600, color: map.c,
      border: `1px solid ${map.c}`, borderRadius: 999, padding: "1px 8px",
      whiteSpace: "nowrap",
    }}>
      <span aria-hidden>{map.i}</span>{children}
    </span>
  );
}

/** Toggle between a chart and its table twin. */
export function ViewToggle({ view, setView }: {
  view: "chart" | "table"; setView: (v: "chart" | "table") => void;
}) {
  return (
    <div style={{ display: "flex", gap: 2 }}>
      <MiniButton active={view === "chart"} onClick={() => setView("chart")}>Chart</MiniButton>
      <MiniButton active={view === "table"} onClick={() => setView("table")}>Table</MiniButton>
    </div>
  );
}

export function useView() {
  return useState<"chart" | "table">("chart");
}

export function Empty({ title, hint, action }: {
  title: string; hint?: string; action?: ReactNode;
}) {
  return (
    <div style={{
      padding: "36px 20px", textAlign: "center", color: "var(--text-muted)",
    }}>
      <p style={{ margin: 0, fontSize: 14, color: "var(--text-secondary)", fontWeight: 550 }}>
        {title}
      </p>
      {hint && <p style={{ margin: "6px 0 0", fontSize: 12.5, maxWidth: 460,
                           marginInline: "auto", lineHeight: 1.5 }}>{hint}</p>}
      {action && <div style={{ marginTop: 14 }}>{action}</div>}
    </div>
  );
}

export function Grid({ cols, children, gap = 14 }: {
  cols: string; children: ReactNode; gap?: number;
}) {
  return <div style={{ display: "grid", gridTemplateColumns: cols, gap }}>{children}</div>;
}

export { money, compact, pct };
