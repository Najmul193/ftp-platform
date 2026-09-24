import { useEffect, useRef, useState } from "react";
import { api, Branch, BranchUsage, Product } from "../api";
import { Button, Card, Grid, MiniButton, Pill, Table } from "../components/ui";
import { longDate } from "../format";
import { useApp, useAsync } from "../state";

const CATEGORIES = ["METRO", "URBAN", "SEMI_URBAN", "RURAL"];
const NATURES = ["DEMAND", "TIME"];

export default function Admin() {
  const { can, districts, refreshMasters } = useApp();
  const [editing, setEditing] = useState<Branch | null>(null);
  const [creating, setCreating] = useState(false);
  const [usage, setUsage] = useState<BranchUsage | null>(null);
  const [message, setMessage] = useState<{ tone: "good" | "critical"; text: string } | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [editingProduct, setEditingProduct] = useState<Product | null>(null);
  const [creatingProduct, setCreatingProduct] = useState(false);
  const branchFormRef = useRef<HTMLDivElement | null>(null);
  const productFormRef = useRef<HTMLDivElement | null>(null);

  const branches = useAsync(() => api.branches(true), [refresh]);
  const products = useAsync(() => api.products(true), [refresh]);

  // Opening a form lives below the table: pull the viewport down to it so the
  // action is actually on screen instead of silently appearing off-screen.
  useEffect(() => {
    const target = (creating || editing)
      ? branchFormRef.current
      : (creatingProduct || editingProduct) ? productFormRef.current : null;
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [creating, editing, creatingProduct, editingProduct]);

  const reload = async () => { setRefresh((r) => r + 1); await refreshMasters(); };
  const editable = can("MASTER_BRANCH_EDIT");
  const productEditable = can("MASTER_PRODUCT_EDIT");

  async function confirmDelete(b: Branch) {
    setMessage(null);
    try {
      const u = await api.branchUsage(b.branch_code);
      setUsage(u);
      setEditing(b);
    } catch (e) { setMessage({ tone: "critical", text: (e as Error).message }); }
  }

  async function doDelete(code: string) {
    try {
      await api.deleteBranch(code);
      setMessage({ tone: "good", text: `Branch ${code} deleted.` });
      setEditing(null); setUsage(null); await reload();
    } catch (e) { setMessage({ tone: "critical", text: (e as Error).message }); }
  }

  async function doDeactivate(code: string) {
    try {
      await api.deactivateBranch(code);
      setMessage({ tone: "good", text: `Branch ${code} deactivated; history retained.` });
      setEditing(null); setUsage(null); await reload();
    } catch (e) { setMessage({ tone: "critical", text: (e as Error).message }); }
  }

  async function confirmDeleteProduct(p: Product) {
    if (!window.confirm(
      `Delete product ${p.product_code}? Only possible while it has no history — ` +
      "once a feed references it, deactivate instead.")) return;
    try {
      await api.deleteProduct(p.product_code);
      setMessage({ tone: "good", text: `Product ${p.product_code} deleted.` });
      setEditingProduct(null); setCreatingProduct(false); await reload();
    } catch (e) { setMessage({ tone: "critical", text: (e as Error).message }); }
  }

  async function toggleProductActive(p: Product) {
    const want = !p.is_active;
    try {
      await api.updateProduct(p.product_code, { is_active: want });
      setMessage({ tone: "good", text:
        `Product ${p.product_code} ${want ? "reactivated" : "deactivated"}.` });
      setEditingProduct(null); setCreatingProduct(false); await reload();
    } catch (e) { setMessage({ tone: "critical", text: (e as Error).message }); }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {message && (
        <div style={{
          padding: "9px 12px", borderRadius: 8, fontSize: "var(--fs-base)",
          border: `1px solid ${message.tone === "good"
            ? "var(--status-good)" : "var(--status-critical)"}`,
          background: "var(--surface-2)",
        }}>
          <Pill tone={message.tone}>{message.tone === "good" ? "Done" : "Refused"}</Pill>
          <span style={{ marginLeft: 8, color: "var(--text-secondary)" }}>{message.text}</span>
        </div>
      )}

      <Card title="Branch master"
            subtitle={`${branches.data?.length ?? 0} branches`}
            actions={editable && (
              <Button variant="primary" onClick={() => {
                setCreating(true); setEditing(null);
                setCreatingProduct(false); setEditingProduct(null);
              }}>
                Add branch
              </Button>
            )}
            footnote="A branch with history cannot be deleted: every fact row carries its code, so removing it would orphan published figures. Deactivation retires it while keeping the audit trail intact.">
        <Table rows={branches.data ?? []} csvName="branch-master.csv"
               searchPlaceholder="Search code, branch, district or category…"
               search={(b) => [
                 b.branch_code, b.branch_name,
                 districts.find((x) => x.id === b.district_id)?.name,
                 b.category.replace("_", " "), b.is_active ? "active" : "inactive",
               ].join(" ")}
               cols={[
                 { key: "c", label: "Code", render: (b) => <b>{b.branch_code}</b>,
                   value: (b) => b.branch_code },
                 { key: "n", label: "Name", render: (b) => b.branch_name,
                   value: (b) => b.branch_name },
                 { key: "d", label: "District",
                   render: (b) => districts.find((x) => x.id === b.district_id)?.name ?? "—",
                   value: (b) => b.district_id },
                 { key: "cat", label: "Category",
                   render: (b) => b.category.replace("_", " "), value: (b) => b.category },
                 { key: "o", label: "Opened",
                   render: (b) => (b.opened_on ? longDate(b.opened_on) : "—"),
                   value: (b) => b.opened_on },
                 { key: "s", label: "Status",
                   render: (b) => b.is_active
                     ? <Pill tone="good">active</Pill>
                     : <Pill tone="neutral">inactive</Pill>,
                   value: (b) => b.is_active },
                 ...(editable ? [{
                   key: "act", label: "", align: "right" as const,
                   render: (b: Branch) => (
                     <span style={{ display: "inline-flex", gap: 5 }}>
                       <MiniButton onClick={() => {
                         setEditing(b); setCreating(false); setUsage(null);
                         setCreatingProduct(false); setEditingProduct(null);
                       }}>
                         Edit
                       </MiniButton>
                       <MiniButton onClick={() => confirmDelete(b)}>Delete</MiniButton>
                     </span>
                   ),
                 }] : []),
               ]} />
      </Card>

      {(creating || editing) && editable && (
        <div ref={branchFormRef}
             style={{ scrollMarginTop: 24, scrollSnapMarginTop: 24 }}>
          <BranchForm
            branch={creating ? null : editing}
            usage={usage}
            districts={districts}
            onCancel={() => { setCreating(false); setEditing(null); setUsage(null); }}
            onDelete={doDelete}
            onDeactivate={doDeactivate}
            onSaved={async (msg) => {
              setMessage({ tone: "good", text: msg });
              setCreating(false); setEditing(null); setUsage(null);
              await reload();
            }}
            onError={(text) => setMessage({ tone: "critical", text })}
          />
        </div>
      )}

      <Card title="Product master" subtitle={`${products.data?.length ?? 0} products`}
            actions={productEditable && (
              <Button variant="primary" onClick={() => {
                setCreatingProduct(true); setEditingProduct(null);
                setCreating(false); setEditing(null); setUsage(null);
              }}>
                Add product
              </Button>
            )}
            footnote="Rates are not held here. They live in effective-dated configuration so a rate change can be approved without re-approving the product. Delete is only possible before the feed references the code; after that, deactivate.">
        <Table rows={products.data ?? []} csvName="product-master.csv"
               searchPlaceholder="Search code, short name, side or details…"
               search={(p) => [
                 p.product_code, p.short_name, p.side, p.liability_nature,
                 p.details, p.is_active ? "active" : "inactive",
               ].join(" ")}
               cols={[
                 { key: "c", label: "Code", render: (p) => <b>{p.product_code}</b>,
                   value: (p) => p.product_code },
                 { key: "n", label: "Short name", render: (p) => p.short_name,
                   value: (p) => p.short_name },
                 { key: "s", label: "Side",
                   render: (p) => <Pill tone={p.side === "ASSET" ? "info" : "neutral"}>
                     {p.side}</Pill>, value: (p) => p.side },
                 { key: "ln", label: "Nature",
                   render: (p) => p.liability_nature ?? "—", value: (p) => p.liability_nature },
                 { key: "st", label: "Status",
                   render: (p) => p.is_active
                     ? <Pill tone="good">active</Pill>
                     : <Pill tone="neutral">inactive</Pill>,
                   value: (p) => p.is_active },
                 { key: "d", label: "Details",
                   render: (p) => <span style={{ color: "var(--text-muted)" }}>{p.details}</span>,
                   value: (p) => p.details },
                 ...(productEditable ? [{
                   key: "act", label: "", align: "right" as const,
                   render: (p: Product) => (
                     <span style={{ display: "inline-flex", gap: 5 }}>
                       <MiniButton onClick={() => {
                         setEditingProduct(p); setCreatingProduct(false);
                         setCreating(false); setEditing(null); setUsage(null);
                       }}>Edit</MiniButton>
                       <MiniButton onClick={() => confirmDeleteProduct(p)}>Delete</MiniButton>
                     </span>
                   ),
                 }] : []),
               ]} />
      </Card>

      {(creatingProduct || editingProduct) && productEditable && (
        <div ref={productFormRef}
             style={{ scrollMarginTop: 24, scrollSnapMarginTop: 24 }}>
          <ProductForm
            product={creatingProduct ? null : editingProduct}
            onCancel={() => { setCreatingProduct(false); setEditingProduct(null); }}
            onSave={async (msg) => {
              setMessage({ tone: "good", text: msg });
              setCreatingProduct(false); setEditingProduct(null);
              await reload();
            }}
            onError={(text) => setMessage({ tone: "critical", text })}
            onToggleActive={toggleProductActive}
          />
        </div>
      )}
    </div>
  );
}

function BranchForm({
  branch, usage, districts, onCancel, onSaved, onError, onDelete, onDeactivate,
}: {
  branch: Branch | null;
  usage: BranchUsage | null;
  districts: { id: number; code: string; name: string }[];
  onCancel: () => void;
  onSaved: (msg: string) => void;
  onError: (msg: string) => void;
  onDelete: (code: string) => void;
  onDeactivate: (code: string) => void;
}) {
  const [code, setCode] = useState(branch?.branch_code ?? "");
  const [name, setName] = useState(branch?.branch_name ?? "");
  const [district, setDistrict] = useState(
    districts.find((d) => d.id === branch?.district_id)?.code ?? districts[0]?.code ?? "");
  const [category, setCategory] = useState(branch?.category ?? "URBAN");
  const [opened, setOpened] = useState(branch?.opened_on ?? "");

  // Fields take the global form look; only the width is set here.
  const field: React.CSSProperties = { width: "100%" };
  const label: React.CSSProperties = {
    fontSize: "var(--fs-xs)", fontWeight: 600, letterSpacing: ".05em",
    textTransform: "uppercase", color: "var(--text-muted)",
    marginBottom: 4, display: "block",
  };

  async function save() {
    try {
      if (branch) {
        await api.updateBranch(branch.branch_code, {
          branch_name: name, district_code: district, category,
          opened_on: opened || null,
        });
        onSaved(`Branch ${branch.branch_code} updated.`);
      } else {
        await api.createBranch({
          branch_code: code, branch_name: name, district_code: district,
          category, opened_on: opened || null,
        });
        onSaved(`Branch ${code} created.`);
      }
    } catch (e) { onError((e as Error).message); }
  }

  return (
    <Card title={branch ? `Edit branch ${branch.branch_code}` : "Add a branch"}
          subtitle={branch
            ? "The division follows the district automatically."
            : "The division is derived from the district by the database."}>
      <Grid cols="repeat(auto-fit, minmax(170px, 1fr))" gap={12}>
        <div>
          <label style={label} htmlFor="b-code">Branch code</label>
          <input id="b-code" style={{ ...field, opacity: branch ? .6 : 1 }} value={code}
                 disabled={Boolean(branch)}
                 onChange={(e) => setCode(e.target.value)} placeholder="106" />
        </div>
        <div>
          <label style={label} htmlFor="b-name">Branch name</label>
          <input id="b-name" style={field} value={name}
                 onChange={(e) => setName(e.target.value)} placeholder="Dhaka Main Branch" />
        </div>
        <div>
          <label style={label} htmlFor="b-dist">District</label>
          <select id="b-dist" style={field} value={district}
                  onChange={(e) => setDistrict(e.target.value)}>
            {districts.map((d) => <option key={d.code} value={d.code}>{d.name}</option>)}
          </select>
        </div>
        <div>
          <label style={label} htmlFor="b-cat">Category</label>
          <select id="b-cat" style={field} value={category}
                  onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>{c.replace("_", " ")}</option>
            ))}
          </select>
        </div>
        <div>
          <label style={label} htmlFor="b-open">Opened on</label>
          <input id="b-open" type="date" style={field} value={opened ?? ""}
                 onChange={(e) => setOpened(e.target.value)} />
        </div>
      </Grid>

      {usage && (
        <div style={{
          marginTop: 12, padding: "10px 12px", borderRadius: 8,
          background: "var(--surface-2)",
          border: `1px solid ${usage.deletable
            ? "var(--status-good)" : "var(--status-warning)"}`,
        }}>
          <Pill tone={usage.deletable ? "good" : "warning"}>
            {usage.deletable ? "Safe to delete" : "Has history"}
          </Pill>
          <p style={{ margin: "6px 0 0", fontSize: "var(--fs-base)", color: "var(--text-secondary)" }}>
            {usage.note}
          </p>
          {!usage.deletable && (
            <p style={{ margin: "4px 0 0", fontSize: "var(--fs-sm)", color: "var(--text-muted)" }}
               className="tnum">
              {usage.fact_rows.toLocaleString()} calculated rows ·{" "}
              {usage.bank_rows.toLocaleString()} raw rows ·{" "}
              {usage.aggregate_rows.toLocaleString()} aggregate rows
            </p>
          )}
          <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
            {usage.deletable
              ? <Button variant="danger" onClick={() => onDelete(usage.branch_code)}>
                  Delete permanently
                </Button>
              : <Button variant="danger" onClick={() => onDeactivate(usage.branch_code)}>
                  Deactivate instead
                </Button>}
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <Button variant="primary" onClick={save} disabled={!code || !name || !district}>
          {branch ? "Save changes" : "Create branch"}
        </Button>
        <Button onClick={onCancel}>Cancel</Button>
      </div>
    </Card>
  );
}

function ProductForm({
  product, onCancel, onSave, onError, onToggleActive,
}: {
  product: Product | null;
  onCancel: () => void;
  onSave: (msg: string) => void;
  onError: (msg: string) => void;
  onToggleActive: (p: Product) => void;
}) {
  const [code, setCode] = useState(product?.product_code ?? "");
  const [shortName, setShortName] = useState(product?.short_name ?? "");
  const [side, setSide] = useState<"ASSET" | "LIABILITY">(
    (product?.side as "ASSET" | "LIABILITY") ?? "ASSET");
  const [nature, setNature] = useState(product?.liability_nature ?? "DEMAND");
  const [bench, setBench] = useState("");
  const [details, setDetails] = useState(product?.details ?? "");

  // Fields take the global form look; only the width is set here.
  const field: React.CSSProperties = { width: "100%" };
  const label: React.CSSProperties = {
    fontSize: "var(--fs-xs)", fontWeight: 600, letterSpacing: ".05em",
    textTransform: "uppercase", color: "var(--text-muted)",
    marginBottom: 4, display: "block",
  };

  const needsNature = side === "LIABILITY";

  async function save() {
    try {
      if (product) {
        await api.updateProduct(product.product_code, {
          short_name: shortName,
          details: details || null,
          liability_nature: needsNature
            ? (nature as "DEMAND" | "TIME")
            : null,
        });
        onSave(`Product ${product.product_code} updated.`);
      } else {
        await api.createProduct({
          product_code: code, short_name: shortName, side,
          benchmark_rate: bench || undefined,
          liability_nature: needsNature ? (nature as "DEMAND" | "TIME") : null,
          details: details || null,
        });
        onSave(`Product ${code} created.`);
      }
    } catch (e) { onError((e as Error).message); }
  }

  return (
    <Card title={product ? `Edit product ${product.product_code}` : "Add a product"}
          subtitle={product
            ? "Code and side are set when the feed writes its first row."
            : "The benchmark rate makes the product priceable immediately; without one it would fail at first validation."}>
      <Grid cols="repeat(auto-fit, minmax(170px, 1fr))" gap={12}>
        <div>
          <label style={label} htmlFor="p-code">Product code</label>
          <input id="p-code" style={{ ...field, opacity: product ? .6 : 1 }}
                 value={code} disabled={Boolean(product)}
                 onChange={(e) => setCode(e.target.value)} placeholder="SAVINGS" />
        </div>
        <div>
          <label style={label} htmlFor="p-name">Short name</label>
          <input id="p-name" style={field} value={shortName}
                 onChange={(e) => setShortName(e.target.value)} placeholder="Savings Account" />
        </div>
        <div>
          <label style={label} htmlFor="p-side">Side</label>
          <select id="p-side" style={{ ...field, opacity: product ? .6 : 1 }}
                  value={side} disabled={Boolean(product)}
                  onChange={(e) => setSide(e.target.value as "ASSET" | "LIABILITY")}>
            <option value="ASSET">ASSET</option>
            <option value="LIABILITY">LIABILITY</option>
          </select>
        </div>
        {needsNature && (
          <div>
            <label style={label} htmlFor="p-nature">Liability nature</label>
            <select id="p-nature" style={field} value={nature}
                    onChange={(e) => setNature(e.target.value)}>
              {NATURES.map((nn) => <option key={nn} value={nn}>{nn}</option>)}
            </select>
          </div>
        )}
        {!product && (
          <div>
            <label style={label} htmlFor="p-bench">Benchmark rate %</label>
            <input id="p-bench" style={field} value={bench}
                   onChange={(e) => setBench(e.target.value)} placeholder="7.25"
                   inputMode="decimal" />
          </div>
        )}
        <div style={{ gridColumn: "1 / -1" }}>
          <label style={label} htmlFor="p-details">Details</label>
          <input id="p-details" style={field} value={details}
                 onChange={(e) => setDetails(e.target.value)} placeholder="Optional notes" />
        </div>
      </Grid>

      {product && !product.is_active && (
        <div style={{ marginTop: 12, padding: "10px 12px", borderRadius: 8,
                      background: "var(--surface-2)",
                      border: "1px solid var(--status-warning)" }}>
          <Pill tone="warning">Inactive</Pill>
          <span style={{ marginLeft: 8, fontSize: "var(--fs-base)", color: "var(--text-secondary)" }}>
            Deactivated products keep their history but accept no new feed rows.
          </span>
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 14, alignItems: "center" }}>
        <Button variant="primary" onClick={save}
                disabled={!shortName || (!code && !product) ||
                          (needsNature && !nature) || (!product && !bench)}>
          {product ? "Save changes" : "Create product"}
        </Button>
        {product && (
          <Button variant="danger" onClick={() => {
            if (product.is_active &&
                !window.confirm(`Deactivate product ${product.product_code}? ` +
                                "It keeps its history and stops accepting new feed rows.")) return;
            onToggleActive(product);
          }}>
            {product.is_active ? "Deactivate" : "Reactivate"}
          </Button>
        )}
        <Button onClick={onCancel}>Cancel</Button>
      </div>
    </Card>
  );
}
