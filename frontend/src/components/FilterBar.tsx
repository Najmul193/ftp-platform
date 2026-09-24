import { useApp } from "../state";
import { MiniButton, Pill } from "./ui";

/** ONE filter row above everything it scopes. Never per-chart filters, and
 *  never a filter inside a chart card -- every chart on the page re-renders
 *  against the same slice. */
export default function FilterBar({ collapsed = false }: { collapsed?: boolean }) {
  const { filters, setFilters, resetFilters, branches, products, divisions, districts, me } = useApp();

  const field: React.CSSProperties = {
    background: "var(--surface-1)", border: "1px solid var(--border-strong)",
    borderRadius: 7, padding: "6px 9px", fontSize: 12.5, color: "var(--text-primary)",
    minWidth: 0,
  };
  const label: React.CSSProperties = {
    fontSize: 10.5, fontWeight: 600, letterSpacing: ".05em",
    textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 3,
    display: "block",
  };

  const visibleDistricts = filters.division_id
    ? districts.filter((d) => d.division_id === filters.division_id)
    : districts;

  // The branch list narrows the same way the district list does. District is
  // the tighter of the two, so it wins when both are set. A branch whose
  // division_id is absent is placed by its district, so a division selection
  // never silently drops it.
  const visibleBranches = branches.filter((b) => {
    if (!b.is_active) return false;
    if (filters.district_id) return b.district_id === filters.district_id;
    if (filters.division_id) {
      const division = b.division_id
        ?? districts.find((d) => d.id === b.district_id)?.division_id;
      return division === filters.division_id;
    }
    return true;
  });

  const chips: { k: string; text: string; clear: () => void }[] = [];
  if (filters.date_from || filters.date_to)
    chips.push({ k: "d", text: `${filters.date_from ?? "…"} → ${filters.date_to ?? "…"}`,
                 clear: () => setFilters((f) => ({ ...f, date_from: undefined, date_to: undefined })) });
  if (filters.division_id)
    chips.push({ k: "dv", text: divisions.find((d) => d.id === filters.division_id)?.name ?? "Division",
                 clear: () => setFilters((f) => ({ ...f, division_id: undefined })) });
  if (filters.district_id)
    chips.push({ k: "ds", text: districts.find((d) => d.id === filters.district_id)?.name ?? "District",
                 clear: () => setFilters((f) => ({ ...f, district_id: undefined })) });
  (filters.branch_id ?? []).forEach((id) =>
    chips.push({ k: `b${id}`, text: `Branch ${branches.find((b) => b.id === id)?.branch_code ?? id}`,
                 clear: () => setFilters((f) => ({
                   ...f, branch_id: (f.branch_id ?? []).filter((x) => x !== id) || undefined })) }));
  (filters.product_code ?? []).forEach((c) =>
    chips.push({ k: `p${c}`, text: c, clear: () => setFilters((f) => ({
      ...f, product_code: (f.product_code ?? []).filter((x) => x !== c) })) }));
  if (filters.branch_category)
    chips.push({ k: "cat", text: filters.branch_category.replace("_", " "),
                 clear: () => setFilters((f) => ({ ...f, branch_category: undefined })) });
  if (filters.side)
    chips.push({ k: "side", text: filters.side,
                 clear: () => setFilters((f) => ({ ...f, side: undefined })) });
  if (filters.ftp_sign)
    chips.push({ k: "sign", text: `${filters.ftp_sign} FTP`,
                 clear: () => setFilters((f) => ({ ...f, ftp_sign: undefined })) });

  if (collapsed) {
    return (
      <div style={{ display: "flex", gap: 4, alignItems: "center", minWidth: 0,
                    overflow: "hidden" }}>
        {chips.length === 0 ? (
          <span style={{ fontSize: 11.5, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
            No filters
          </span>
        ) : (
          chips.slice(0, 5).map((c) => (
            <button key={c.k} onClick={c.clear} title="Remove this filter" style={{
              display: "inline-flex", alignItems: "center", gap: 4, flexShrink: 0,
              background: "var(--surface-1)", border: "1px solid var(--border-strong)",
              borderRadius: 999, padding: "1px 6px 1px 9px", fontSize: 11,
              color: "var(--text-secondary)", cursor: "pointer", whiteSpace: "nowrap",
            }}>
              {c.text}<span aria-hidden style={{ fontSize: 12.5, lineHeight: 1 }}>×</span>
            </button>
          ))
        )}
      </div>
    );
  }

  return (
    <div style={{
      // Transparent: it always sits inside the masthead, whose print shows through.
      background: "transparent", borderBottom: "1px solid var(--border)",
      padding: "10px 20px", position: "sticky",
      top: "env(safe-area-inset-top, 0px)", zIndex: 20,
    }}>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
        <div>
          <label style={label} htmlFor="f-from">From</label>
          <input id="f-from" type="date" style={field} value={filters.date_from ?? ""}
                 onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value || undefined }))} />
        </div>
        <div>
          <label style={label} htmlFor="f-to">To</label>
          <input id="f-to" type="date" style={field} value={filters.date_to ?? ""}
                 onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value || undefined }))} />
        </div>

        {/* A branch-scoped user has no hierarchy to choose from, so the
            controls are absent rather than present-but-disabled. */}
        {me && me.scope_level !== "BRANCH" && (
          <>
            <div>
              <label style={label} htmlFor="f-div">Division</label>
              <select id="f-div" style={field} value={filters.division_id ?? ""}
                      onChange={(e) => setFilters((f) => ({
                        ...f, division_id: e.target.value ? +e.target.value : undefined,
                        district_id: undefined, branch_id: undefined }))}>
                <option value="">All</option>
                {divisions.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <div>
              <label style={label} htmlFor="f-dist">District</label>
              <select id="f-dist" style={field} value={filters.district_id ?? ""}
                      onChange={(e) => setFilters((f) => ({
                        ...f, district_id: e.target.value ? +e.target.value : undefined,
                        branch_id: undefined }))}>
                <option value="">All</option>
                {visibleDistricts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <div>
              <label style={label} htmlFor="f-branch">Branch</label>
              <select id="f-branch" style={field}
                      value={filters.branch_id?.[0] ?? ""}
                      onChange={(e) => setFilters((f) => ({
                        ...f, branch_id: e.target.value ? [+e.target.value] : undefined }))}>
                <option value="">All</option>
                {visibleBranches.map((b) => (
                  <option key={b.id} value={b.id}>{b.branch_code} — {b.branch_name}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={label} htmlFor="f-cat">Category</label>
              <select id="f-cat" style={field} value={filters.branch_category ?? ""}
                      onChange={(e) => setFilters((f) => ({
                        ...f, branch_category: e.target.value || undefined }))}>
                <option value="">All</option>
                {["METRO", "URBAN", "SEMI_URBAN", "RURAL"].map((c) => (
                  <option key={c} value={c}>{c.replace("_", " ")}</option>
                ))}
              </select>
            </div>
          </>
        )}

        <div>
          <label style={label} htmlFor="f-prod">Product</label>
          <select id="f-prod" style={field} value={filters.product_code?.[0] ?? ""}
                  onChange={(e) => setFilters((f) => ({
                    ...f, product_code: e.target.value ? [e.target.value] : undefined }))}>
            <option value="">All</option>
            {products.map((p) => (
              <option key={p.product_code} value={p.product_code}>{p.short_name}</option>
            ))}
          </select>
        </div>
        <div>
          <label style={label} htmlFor="f-side">Side</label>
          <select id="f-side" style={field} value={filters.side ?? ""}
                  onChange={(e) => setFilters((f) => ({
                    ...f, side: (e.target.value || undefined) as never }))}>
            <option value="">Both</option>
            <option value="ASSET">Asset</option>
            <option value="LIABILITY">Liability</option>
          </select>
        </div>

        <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignSelf: "flex-end" }}>
          <MiniButton onClick={resetFilters}>Reset</MiniButton>
        </div>
      </div>

      {chips.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 9 }}>
          {chips.map((c) => (
            <button key={c.k} onClick={c.clear} title="Remove this filter" style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              background: "var(--surface-1)", border: "1px solid var(--border-strong)",
              borderRadius: 999, padding: "2px 6px 2px 10px", fontSize: 11.5,
              color: "var(--text-secondary)", cursor: "pointer",
            }}>
              {c.text}<span aria-hidden style={{ fontSize: 13, lineHeight: 1 }}>×</span>
            </button>
          ))}
          <Pill tone="info">{chips.length} active</Pill>
        </div>
      )}
    </div>
  );
}
