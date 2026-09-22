import { useMemo, useState } from "react";
import {
  api, GlobalConfig, GlobalConfigUpdate, Product, ProductRates,
} from "../api";
import { Button, Card, Grid, MiniButton, Pill, Table } from "../components/ui";
import { longDate, rate } from "../format";
import { useApp, useAsync } from "../state";

const BASES = ["ACT_365", "ACT_360"] as const;

const field: React.CSSProperties = {
  background: "var(--surface-1)", border: "1px solid var(--border-strong)",
  borderRadius: 7, padding: "7px 9px", fontSize: 13, width: "100%",
};
const label: React.CSSProperties = {
  fontSize: 10.5, fontWeight: 600, letterSpacing: ".05em",
  textTransform: "uppercase", color: "var(--text-muted)",
  marginBottom: 4, display: "block",
};

const today = () => new Date().toISOString().slice(0, 10);

/** Where a component came from, as the label the resolver uses. */
function Source({ source }: { source: string }) {
  return source === "PRODUCT_OVERRIDE"
    ? <Pill tone="info">override</Pill>
    : <Pill tone="neutral">global</Pill>;
}

export default function Rates() {
  const { can, me } = useApp();
  const [refresh, setRefresh] = useState(0);
  const [editing, setEditing] = useState<"version" | "correct" | null>(null);
  const [editingProduct, setEditingProduct] = useState<Product | null>(null);
  const [message, setMessage] =
    useState<{ tone: "good" | "critical"; text: string } | null>(null);

  const current = useAsync(() => api.globalConfig(), [refresh]);
  const history = useAsync(() => api.globalConfigHistory(50), [refresh]);

  // Five products, so five requests is cheaper than a new endpoint. If the
  // product master grows past a screenful this wants a batch route.
  const productRates = useAsync(async () => {
    const list = await api.products(false);
    const settled = await Promise.all(list.map(async (p) => {
      try { return { p, r: await api.productRates(p.product_code) }; }
      // A product with no resolvable benchmark 404s here. That is the state
      // worth showing, not hiding: it will fail at the next validation.
      catch { return { p, r: null }; }
    }));
    return settled;
  }, [refresh]);

  // Editing the global layer reprices every branch, so HO scope is required in
  // addition to the permission. The API enforces the same rule.
  const editable = can("CONFIG_RATE_EDIT") && me?.scope_level === "HO";
  const reload = () => { setRefresh((r) => r + 1); setEditing(null); setEditingProduct(null); };

  const cfg = current.data;

  // A product benchmark always overrides the global one, so these are the
  // products that depend on the global benchmark being set. An unresolved row
  // (no rate at all) counts the same as one inheriting the global default.
  const dependsOnGlobalBenchmark = (productRates.data ?? [])
    .filter(({ r }) => r === null || r.benchmark_source === "GLOBAL_DEFAULT")
    .map(({ p }) => p.product_code);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {message && (
        <div style={{
          padding: "9px 12px", borderRadius: 8, fontSize: 13,
          border: `1px solid ${message.tone === "good"
            ? "var(--status-good)" : "var(--status-critical)"}`,
          background: "var(--surface-2)",
        }}>
          <Pill tone={message.tone}>{message.tone === "good" ? "Done" : "Refused"}</Pill>
          <span style={{ marginLeft: 8, color: "var(--text-secondary)" }}>{message.text}</span>
        </div>
      )}

      <Card
        title="Global rate defaults"
        subtitle={cfg
          ? `Version ${cfg.version}, effective from ${longDate(cfg.effective_from)}`
          : current.error ?? "Loading…"}
        actions={editable && cfg && (
          <>
            {cfg.editable_in_place && (
              <MiniButton onClick={() => { setEditing("correct"); setMessage(null); }}>
                Correct this version
              </MiniButton>
            )}
            <Button variant="primary"
                    onClick={() => { setEditing("version"); setMessage(null); }}>
              Change from a date
            </Button>
          </>
        )}>
        {current.error && !cfg && (
          <p style={{ fontSize: 13, color: "var(--status-critical)", margin: "6px 4px" }}>
            {current.error}
          </p>
        )}
        {cfg && (
          <>
            <Grid cols="repeat(auto-fit, minmax(150px, 1fr))" gap={12}>
              <Field name="Benchmark rate"
                     value={cfg.benchmark_rate === null
                       ? "not set globally" : `${rate(cfg.benchmark_rate, 4)} %`}
                     hint={cfg.benchmark_rate === null
                       ? "Each product defines its own"
                       : "Applies where no override exists"} />
              <Field name="Liquidity cost" value={`${rate(cfg.liquidity_cost, 4)} %`}
                     hint="Deducted from every spread" />
              <Field name="Other cost" value={`${rate(cfg.other_cost, 4)} %`}
                     hint="Deducted from every spread" />
              <Field name="Day-count basis"
                     value={cfg.day_count_basis.replace("_", "/")}
                     hint={cfg.day_count_basis === "ACT_365"
                       ? "Divisor 36,500" : "Divisor 36,000"} />
            </Grid>
          </>
        )}
      </Card>

      {editing && cfg && editable && (
        <GlobalForm
          mode={editing}
          cfg={cfg}
          dependsOnGlobalBenchmark={dependsOnGlobalBenchmark}
          onCancel={() => setEditing(null)}
          onSaved={(text) => { setMessage({ tone: "good", text }); reload(); }}
          onError={(text) => setMessage({ tone: "critical", text })}
        />
      )}

      <Card title="Effective rates by product"
            subtitle={`${productRates.data?.length ?? 0} active products, as at today`}
            footnote="Rates currently applied. Each component is tagged with its source: the product's own override, or the global default.">
        <Table
          rows={productRates.data ?? []}
          csvName="effective-rates.csv"
          empty={productRates.error ?? "No active products."}
          cols={[
            { key: "code", label: "Product",
              render: ({ p }) => <b>{p.product_code}</b>,
              value: ({ p }) => p.product_code },
            { key: "name", label: "Short name", render: ({ p }) => p.short_name,
              value: ({ p }) => p.short_name },
            { key: "side", label: "Side",
              render: ({ p }) => <Pill tone={p.side === "ASSET" ? "info" : "neutral"}>
                {p.side}</Pill>, value: ({ p }) => p.side },
            { key: "bm", label: "Benchmark", align: "right",
              render: ({ r }) => r
                ? <span>{rate(r.benchmark_rate, 4)} <Source source={r.benchmark_source} /></span>
                : <Pill tone="critical">unresolved</Pill>,
              value: ({ r }) => r?.benchmark_rate ?? "" },
            { key: "lq", label: "Liquidity", align: "right",
              render: ({ r }) => r
                ? <span>{rate(r.liquidity_cost, 4)} <Source source={r.liquidity_source} /></span>
                : "—",
              value: ({ r }) => r?.liquidity_cost ?? "" },
            { key: "oc", label: "Other", align: "right",
              render: ({ r }) => r
                ? <span>{rate(r.other_cost, 4)} <Source source={r.other_source} /></span>
                : "—",
              value: ({ r }) => r?.other_cost ?? "" },
            ...(can("CONFIG_RATE_EDIT") ? [{
              key: "act", label: "", align: "right" as const,
              render: ({ p }: { p: Product; r: ProductRates | null }) => (
                <MiniButton onClick={() => {
                  setEditingProduct(p); setEditing(null); setMessage(null);
                }}>Set rates</MiniButton>
              ),
            }] : []),
          ]}
        />
      </Card>

      {editingProduct && can("CONFIG_RATE_EDIT") && (
        <ProductRateForm
          product={editingProduct}
          rates={productRates.data?.find(
            (x) => x.p.product_code === editingProduct.product_code)?.r ?? null}
          onCancel={() => setEditingProduct(null)}
          onSaved={(text) => { setMessage({ tone: "good", text }); reload(); }}
          onError={(text) => setMessage({ tone: "critical", text })}
        />
      )}

      <Card title="Global version history"
            subtitle={`${history.data?.length ?? 0} versions`}
            footnote="Superseded versions are retained rather than overwritten, so past figures remain traceable to the rates that produced them.">
        <Table rows={history.data ?? []} csvName="global-rate-history.csv"
               empty={history.error ?? "No configuration versions."}
               cols={[
                 { key: "v", label: "Version", render: (h) => <b>v{h.version}</b>,
                   value: (h) => h.version },
                 { key: "from", label: "Effective from",
                   render: (h) => longDate(h.effective_from),
                   value: (h) => h.effective_from },
                 { key: "to", label: "Until",
                   render: (h) => h.effective_to
                     ? longDate(h.effective_to)
                     : <Pill tone="good">in force</Pill>,
                   value: (h) => h.effective_to ?? "" },
                 { key: "bm", label: "Benchmark", align: "right",
                   render: (h) => h.benchmark_rate === null ? "—" : rate(h.benchmark_rate, 4),
                   value: (h) => h.benchmark_rate ?? "" },
                 { key: "lq", label: "Liquidity", align: "right",
                   render: (h) => rate(h.liquidity_cost, 4),
                   value: (h) => h.liquidity_cost ?? "" },
                 { key: "oc", label: "Other", align: "right",
                   render: (h) => rate(h.other_cost, 4),
                   value: (h) => h.other_cost ?? "" },
                 { key: "dc", label: "Basis",
                   render: (h) => h.day_count_basis.replace("_", "/"),
                   value: (h) => h.day_count_basis },
                 { key: "rows", label: "Rows priced", align: "right",
                   render: (h) => h.rows_priced.toLocaleString("en-IN"),
                   value: (h) => h.rows_priced },
                 { key: "note", label: "Note",
                   render: (h) => <span style={{ color: "var(--text-muted)" }}>{h.note}</span>,
                   value: (h) => h.note ?? "" },
               ]} />
      </Card>

      {!editable && can("CONFIG_RATE_VIEW") && (
        <p style={{ fontSize: 12, color: "var(--text-muted)", margin: "0 4px",
                    lineHeight: 1.5 }}>
          {can("CONFIG_RATE_EDIT")
            ? "Global defaults apply to every branch and can only be changed at "
              + `head office. Your scope is ${me?.scope_label ?? "below head office"}.`
            : "You have view-only access to the rate configuration."}
        </p>
      )}
    </div>
  );
}

function Field({ name, value, hint }: { name: string; value: string; hint?: string }) {
  return (
    <div style={{
      padding: "10px 12px", borderRadius: 8, background: "var(--surface-2)",
      border: "1px solid var(--border)",
    }}>
      <div style={label}>{name}</div>
      <div className="tnum" style={{ fontSize: 17, fontWeight: 600,
                                     color: "var(--text-primary)" }}>{value}</div>
      {hint && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
        {hint}</div>}
    </div>
  );
}

function GlobalForm({
  mode, cfg, dependsOnGlobalBenchmark, onCancel, onSaved, onError,
}: {
  mode: "version" | "correct";
  cfg: GlobalConfig;
  /** Products with no benchmark of their own, which a NULL global would leave
   *  unpriceable. Checked here so the refusal is not a round trip. */
  dependsOnGlobalBenchmark: string[];
  onCancel: () => void;
  onSaved: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [noBenchmark, setNoBenchmark] = useState(cfg.benchmark_rate === null);
  const [bench, setBench] = useState(
    cfg.benchmark_rate === null ? "" : String(cfg.benchmark_rate));
  const [liquidity, setLiquidity] = useState(String(cfg.liquidity_cost ?? ""));
  const [other, setOther] = useState(String(cfg.other_cost ?? ""));
  const [basis, setBasis] = useState(cfg.day_count_basis);
  const [from, setFrom] = useState(today());
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const correcting = mode === "correct";
  const wouldBreak = noBenchmark ? dependsOnGlobalBenchmark : [];
  // The new version must start after the current one, which is what keeps the
  // periods non-overlapping. Flagged here so the refusal is not a round trip.
  const dateTooEarly = !correcting && from <= cfg.effective_from;

  async function save() {
    setSaving(true);
    const body: GlobalConfigUpdate = {
      benchmark_rate: noBenchmark ? null : bench,
      liquidity_cost: liquidity,
      other_cost: other,
      day_count_basis: basis,
      note: note || null,
    };
    try {
      if (correcting) {
        const out = await api.correctGlobalConfig(body);
        onSaved(`Version ${out.version} updated.`);
      } else {
        const out = await api.setGlobalConfig({ ...body, effective_from: from });
        onSaved(`Version ${out.version} effective from `
                + `${longDate(out.effective_from)}. Version ${cfg.version} closed.`);
      }
    } catch (e) { onError((e as Error).message); }
    finally { setSaving(false); }
  }

  return (
    <Card
      title={correcting
        ? `Correct global version ${cfg.version}`
        : "Change the global defaults from a date"}
      subtitle={correcting
        ? "Rewrites this version. Use for a value that was incorrect from the "
          + "start, where a new version would imply a rate change that did not "
          + "occur."
        : "Closes the current version and opens a new one from the selected "
          + "date. Existing figures are unaffected."}>
      <Grid cols="repeat(auto-fit, minmax(170px, 1fr))" gap={12}>
        {!correcting && (
          <div>
            <label style={label} htmlFor="g-from">Effective from</label>
            <input id="g-from" type="date" style={field} value={from}
                   min={cfg.effective_from}
                   onChange={(e) => setFrom(e.target.value)} />
            {dateTooEarly && (
              <div style={{ fontSize: 11, color: "var(--status-critical)", marginTop: 4 }}>
                Must be later than {longDate(cfg.effective_from)}.
              </div>
            )}
          </div>
        )}
        <div>
          <label style={label} htmlFor="g-liq">Liquidity cost %</label>
          <input id="g-liq" style={field} value={liquidity} inputMode="decimal"
                 onChange={(e) => setLiquidity(e.target.value)} placeholder="0.30" />
        </div>
        <div>
          <label style={label} htmlFor="g-oth">Other cost %</label>
          <input id="g-oth" style={field} value={other} inputMode="decimal"
                 onChange={(e) => setOther(e.target.value)} placeholder="0.05" />
        </div>
        <div>
          <label style={label} htmlFor="g-basis">Day-count basis</label>
          <select id="g-basis" style={field} value={basis}
                  onChange={(e) => setBasis(e.target.value as typeof basis)}>
            {BASES.map((b) => (
              <option key={b} value={b}>{b.replace("_", "/")}</option>
            ))}
          </select>
        </div>
        <div>
          <label style={label} htmlFor="g-bench">Benchmark rate %</label>
          <input id="g-bench" style={{ ...field, opacity: noBenchmark ? .5 : 1 }}
                 value={noBenchmark ? "" : bench} disabled={noBenchmark}
                 inputMode="decimal"
                 onChange={(e) => setBench(e.target.value)} placeholder="7.25" />
          <label style={{ display: "flex", alignItems: "center", gap: 6,
                          marginTop: 6, fontSize: 11.5,
                          color: "var(--text-secondary)" }}>
            <input type="checkbox" checked={noBenchmark}
                   onChange={(e) => setNoBenchmark(e.target.checked)} />
            No global benchmark
          </label>
        </div>
        <div style={{ gridColumn: "1 / -1" }}>
          <label style={label} htmlFor="g-note">Reason for the change</label>
          <input id="g-note" style={field} value={note}
                 onChange={(e) => setNote(e.target.value)}
                 placeholder="Recorded in the activity log" />
        </div>
      </Grid>

      {noBenchmark && (
        <div style={{ marginTop: 12, padding: "10px 12px", borderRadius: 8,
                      background: "var(--surface-2)",
                      border: `1px solid var(--status-${
                        wouldBreak.length ? "critical" : "warning"})` }}>
          <Pill tone={wouldBreak.length ? "critical" : "warning"}>
            {wouldBreak.length ? "Not allowed" : "Every product needs its own"}
          </Pill>
          <span style={{ marginLeft: 8, fontSize: 12.5, color: "var(--text-secondary)" }}>
            {wouldBreak.length
              ? `${wouldBreak.join(", ")} `
                + `${wouldBreak.length === 1 ? "has" : "have"} no benchmark of `
                + `${wouldBreak.length === 1 ? "its" : "their"} own and would not `
                + "be priceable. Set a product benchmark first."
              : "Every product currently defines its own benchmark, so clearing "
                + "the global one is safe."}
          </span>
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 14, alignItems: "center" }}>
        <Button variant="primary" onClick={save}
                disabled={saving || dateTooEarly || !liquidity || !other
                          || wouldBreak.length > 0
                          || (!noBenchmark && !bench)}>
          {saving ? "Saving…" : correcting
            ? `Correct v${cfg.version}` : `Create v${cfg.version + 1}`}
        </Button>
        <Button onClick={onCancel}>Cancel</Button>
      </div>
    </Card>
  );
}

function ProductRateForm({ product, rates, onCancel, onSaved, onError }: {
  product: Product;
  rates: ProductRates | null;
  onCancel: () => void;
  onSaved: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const inherited = useMemo(() => ({
    liquidity: rates?.liquidity_source === "GLOBAL_DEFAULT",
    other: rates?.other_source === "GLOBAL_DEFAULT",
  }), [rates]);

  const [bench, setBench] = useState(
    rates?.benchmark_rate == null ? "" : String(rates.benchmark_rate));
  const [liqOverride, setLiqOverride] = useState(!inherited.liquidity);
  const [othOverride, setOthOverride] = useState(!inherited.other);
  const [liquidity, setLiquidity] = useState(String(rates?.liquidity_cost ?? ""));
  const [other, setOther] = useState(String(rates?.other_cost ?? ""));
  const [from, setFrom] = useState(today());
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      const out = await api.setProductRate(product.product_code, {
        benchmark_rate: bench,
        // null means inherit the global default; "0" would be an explicit zero.
        liquidity_cost: liqOverride ? liquidity : null,
        other_cost: othOverride ? other : null,
        effective_from: from,
      });
      onSaved(`${product.product_code} rates version ${out.version} effective `
              + `from ${longDate(out.effective_from)}.`);
    } catch (e) { onError((e as Error).message); }
    finally { setSaving(false); }
  }

  return (
    <Card title={`Set rates for ${product.product_code}`}
          subtitle={`${product.short_name} · new effective-dated version`}>
      <Grid cols="repeat(auto-fit, minmax(170px, 1fr))" gap={12}>
        <div>
          <label style={label} htmlFor="pr-from">Effective from</label>
          <input id="pr-from" type="date" style={field} value={from}
                 onChange={(e) => setFrom(e.target.value)} />
        </div>
        <div>
          <label style={label} htmlFor="pr-bench">Benchmark rate %</label>
          <input id="pr-bench" style={field} value={bench} inputMode="decimal"
                 onChange={(e) => setBench(e.target.value)} placeholder="7.25" />
        </div>
        <div>
          <label style={label} htmlFor="pr-liq">Liquidity cost %</label>
          <input id="pr-liq" style={{ ...field, opacity: liqOverride ? 1 : .5 }}
                 value={liqOverride ? liquidity : ""} disabled={!liqOverride}
                 inputMode="decimal"
                 onChange={(e) => setLiquidity(e.target.value)} />
          <label style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 6,
                          fontSize: 11.5, color: "var(--text-secondary)" }}>
            <input type="checkbox" checked={!liqOverride}
                   onChange={(e) => setLiqOverride(!e.target.checked)} />
            Inherit the global default
          </label>
        </div>
        <div>
          <label style={label} htmlFor="pr-oth">Other cost %</label>
          <input id="pr-oth" style={{ ...field, opacity: othOverride ? 1 : .5 }}
                 value={othOverride ? other : ""} disabled={!othOverride}
                 inputMode="decimal"
                 onChange={(e) => setOther(e.target.value)} />
          <label style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 6,
                          fontSize: 11.5, color: "var(--text-secondary)" }}>
            <input type="checkbox" checked={!othOverride}
                   onChange={(e) => setOthOverride(!e.target.checked)} />
            Inherit the global default
          </label>
        </div>
      </Grid>
      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <Button variant="primary" onClick={save}
                disabled={saving || !bench || (liqOverride && !liquidity)
                          || (othOverride && !other)}>
          {saving ? "Saving…" : "Save new version"}
        </Button>
        <Button onClick={onCancel}>Cancel</Button>
      </div>
    </Card>
  );
}
