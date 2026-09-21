/** Number formatting. Values arrive as strings to preserve Decimal precision,
 *  so parse only at the moment of display. */

export const n = (v: unknown): number => {
  const x = typeof v === "number" ? v : parseFloat(String(v ?? 0));
  return Number.isFinite(x) ? x : 0;
};

const nf = (min: number, max: number) =>
  new Intl.NumberFormat("en-IN", { minimumFractionDigits: min, maximumFractionDigits: max });

export const money = (v: unknown, dp = 2) => nf(dp, dp).format(n(v));

/** Compact for axis ticks and dense tiles. Full precision stays in the tooltip
 *  and the table view, so an abbreviation never hides the real number. */
export function compact(v: unknown): string {
  const x = n(v);
  const a = Math.abs(x);
  const s = x < 0 ? "-" : "";
  if (a >= 1e7) return `${s}${(a / 1e7).toFixed(2)}Cr`;
  if (a >= 1e5) return `${s}${(a / 1e5).toFixed(2)}L`;
  if (a >= 1e3) return `${s}${(a / 1e3).toFixed(1)}K`;
  return `${s}${a.toFixed(a < 10 ? 2 : 0)}`;
}

export const pct = (v: unknown, dp = 2) => `${nf(dp, dp).format(n(v))}%`;
export const rate = (v: unknown, dp = 4) => nf(dp, dp).format(n(v));

export const signed = (v: unknown, dp = 2) => {
  const x = n(v);
  return `${x > 0 ? "+" : ""}${nf(dp, dp).format(x)}`;
};

export const shortDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });

export const longDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB",
    { day: "2-digit", month: "short", year: "numeric" });

/** Download any table as CSV -- the escape hatch that keeps a chart from being
 *  the only way to reach a value. */
export function toCsv(rows: Record<string, unknown>[], filename: string) {
  if (!rows.length) return;
  const cols = Object.keys(rows[0]);
  const esc = (v: unknown) => {
    const s = String(v ?? "");
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
