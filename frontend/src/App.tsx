import { useEffect, useState } from "react";
import FilterBar from "./components/FilterBar";
import { Button, Card, Pill } from "./components/ui";
import { api } from "./api";
import { AppProvider, currentView, useApp } from "./state";
import Accounts from "./views/Accounts";
import Activity from "./views/Activity";
import Admin from "./views/Admin";
import BasicOverview from "./views/BasicOverview";
import Consolidated from "./views/Consolidated";
import Analytics from "./views/Analytics";
import Daily from "./views/Daily";
import Leaders from "./views/Leaders";
import Overview from "./views/Overview";
import Rates from "./views/Rates";
import Upload from "./views/Upload";

//: Basic overview is first and is where a session lands after sign-in.
//: `currentView` defaults to the same id, so the landing page and the first
//: nav item cannot drift.
const NAV = [
  { id: "basic", label: "Basic overview", group: "Analyse" },
  { id: "daily", label: "Daily", group: "Analyse" },
  { id: "overview", label: "Overview", group: "Analyse" },
  { id: "analytics", label: "Analytics", group: "Analyse" },
  { id: "leaders", label: "Leaders", group: "Analyse" },
  { id: "accounts", label: "Accounts", group: "Analyse" },
  { id: "consolidated", label: "Consolidated", group: "Analyse" },
  { id: "upload", label: "Upload", group: "Operate", perm: "UPLOAD_VIEW" },
  { id: "admin", label: "Master data", group: "Operate", perm: "MASTER_BRANCH_VIEW" },
  { id: "rates", label: "Rate configuration", group: "Operate", perm: "CONFIG_RATE_VIEW" },
  { id: "activity", label: "Activity log", group: "Operate", perm: "AUDIT_VIEW" },
];

export default function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}

function Shell() {
  const { me, ready, logout, can, theme, toggleTheme, dataInfo, lastSync, refreshData, filters } = useApp();
  const [view, setView] = useState(currentView());
  const [navOpen, setNavOpen] = useState(
    () => (localStorage.getItem("ftp_nav_open") ?? "1") === "1",
  );
  const [filtersOpen, setFiltersOpen] = useState(
    () => (localStorage.getItem("ftp_filters_open") ?? "1") === "1",
  );

  useEffect(() => { localStorage.setItem("ftp_nav_open", navOpen ? "1" : "0"); }, [navOpen]);
  useEffect(() => { localStorage.setItem("ftp_filters_open", filtersOpen ? "1" : "0"); }, [filtersOpen]);

  useEffect(() => {
    const onHash = () => setView(currentView());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (!ready) {
    return <Centered><p style={{ color: "var(--text-muted)" }}>Loading…</p></Centered>;
  }
  if (!me) return <Login />;
  // A seeded password is a shared secret until it is replaced, so the flag
  // gates the application rather than merely suggesting a change.
  if (me.must_change_password) return <ForcePasswordChange />;

  const visible = NAV.filter((n) => !n.perm || can(n.perm));
  const Current = { basic: BasicOverview, consolidated: Consolidated,
                    daily: Daily, overview: Overview, analytics: Analytics,
                    leaders: Leaders, accounts: Accounts, upload: Upload,
                    admin: Admin, rates: Rates, activity: Activity }[view] ?? Daily;

  const activeFilterCount = (Object.entries(filters) as [string, unknown][]).reduce(
    (n, [, v]) => n + (Array.isArray(v) ? v.length : v ? 1 : 0), 0,
  );

  return (
    <div style={{ display: "flex", minHeight: "100%", background: "var(--page)" }}>
      {navOpen && (
        <aside style={{
          width: 196, flexShrink: 0, background: "var(--surface-1)",
          borderRight: "1px solid var(--border)", display: "flex",
          flexDirection: "column", position: "sticky", top: 0, height: "100vh",
          paddingTop: "env(safe-area-inset-top, 0px)",
        }}>
          <div style={{ padding: "14px 16px 12px" }}>
            <img src="/dataedge_logo.png" alt="Data Edge Ltd" style={{
              width: "100%", maxHeight: 40, objectFit: "contain", objectPosition: "left",
              display: "block",
            }} />
            <div style={{ fontSize: 10.5, color: "var(--text-muted)", marginTop: 6,
                          fontWeight: 600, letterSpacing: ".04em" }}>
              Funds Transfer Pricing · FTP Profitability
            </div>
          </div>

          <nav style={{ flex: 1, padding: "0 8px", overflowY: "auto" }}>
            {["Analyse", "Operate"].map((group) => {
              const items = visible.filter((n) => n.group === group);
              if (!items.length) return null;
              return (
                <div key={group} style={{ marginBottom: 14 }}>
                  <div style={{
                    fontSize: 10, fontWeight: 600, letterSpacing: ".08em",
                    textTransform: "uppercase", color: "var(--text-muted)",
                    padding: "0 8px 6px",
                  }}>{group}</div>
                  {items.map((n) => (
                    <a key={n.id} href={`#/${n.id}`} style={{
                      display: "block", padding: "7px 10px", borderRadius: 7,
                      fontSize: 13, textDecoration: "none", marginBottom: 1,
                      background: view === n.id ? "var(--surface-2)" : "transparent",
                      color: view === n.id ? "var(--text-primary)" : "var(--text-secondary)",
                      fontWeight: view === n.id ? 600 : 450,
                    }}>{n.label}</a>
                  ))}
                </div>
              );
            })}
          </nav>

          <div style={{ padding: 12, borderTop: "1px solid var(--border)", fontSize: 11.5 }}>
            <div style={{ fontWeight: 600, color: "var(--text-primary)" }}>{me.full_name}</div>
            <div style={{ color: "var(--text-muted)", marginBottom: 8 }}>{me.scope_label}</div>
            <div style={{ display: "flex", gap: 6 }}>
              <button onClick={toggleTheme} title="Switch theme" style={btn}>
                {theme === "dark" ? "Light" : "Dark"}
              </button>
              <button onClick={logout} style={btn}>Sign out</button>
            </div>
          </div>
        </aside>
      )}

      <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <div className="masthead" style={{
          position: "sticky", top: "env(safe-area-inset-top, 0px)", zIndex: 30,
          display: "flex", flexDirection: "column",
          borderBottom: "1px solid var(--border)",
        }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 8, padding: "6px 12px",
            minHeight: 40,
          }}>
            <button onClick={() => setNavOpen((v) => !v)} title="Toggle navigation" style={{
              ...btn, padding: "4px 8px", fontSize: 15, lineHeight: 1,
            }} aria-label="Show or hide navigation">
              <span aria-hidden>☰</span>
            </button>

            {!navOpen && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                <img src="/dataedge_logo.png" alt="Data Edge Ltd" style={{
                  height: 24, width: "auto", maxWidth: 170, objectFit: "contain",
                }} />
              </div>
            )}

            <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center" }}>
              {!filtersOpen && <FilterBar collapsed />}
            </div>

            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
              {activeFilterCount > 0 && (
                <span style={{
                  fontSize: 10.5, fontWeight: 600, color: "var(--series-1)",
                }}>{activeFilterCount} filter{activeFilterCount === 1 ? "" : "s"}</span>
              )}
              <button onClick={() => setFiltersOpen((v) => !v)} title="Show or hide global filters"
                      style={{ ...btn, fontWeight: filtersOpen ? 600 : 500 }}
                      aria-expanded={filtersOpen}>
                <span aria-hidden>{filtersOpen ? "◦" : "◦"}</span> Filters
              </button>
            </div>
          </div>

          {filtersOpen && <FilterBar />}
        </div>

        <div className="canvas" style={{
          display: "flex", alignItems: "center", gap: 10, padding: "8px 20px 0",
          fontSize: 11.5, color: "var(--text-muted)", flexWrap: "wrap",
        }}>
          {/* Live state is stated, never implied: the page says how fresh it is
              rather than silently showing stale numbers. */}
          <Pill tone={dataInfo?.last_batch_status === "COMPLETED" ? "good" : "warning"}>
            {dataInfo?.latest_business_date
              ? `data to ${dataInfo.latest_business_date}`
              : "no data"}
          </Pill>
          {lastSync && <span>checked {lastSync.toLocaleTimeString("en-GB")}</span>}
          {dataInfo?.last_batch_ref && <span>· last batch {dataInfo.last_batch_ref}</span>}
          <button onClick={refreshData} style={{ ...btn, marginLeft: "auto" }}>
            Refresh now
          </button>
        </div>

        <div className="canvas" style={{ padding: "12px 20px 28px", flex: 1, minWidth: 0 }}>
          <Current />
        </div>

        <footer style={{
          display: "flex", alignItems: "center", justifyContent: "center",
          gap: 8, padding: "14px 20px 20px", fontSize: 11.5,
          color: "var(--text-muted)", flexWrap: "wrap",
          borderTop: "1px solid var(--border)", background: "var(--surface-1)",
        }}>
          <span>© {new Date().getFullYear()} Data Edge Ltd</span>
          <span aria-hidden style={{ opacity: .6 }}>·</span>
          <span>Powered by Data Edge</span>
          <span aria-hidden style={{ opacity: .6 }}>·</span>
          <span>FTP Profitability — Funds Transfer Pricing analytics</span>
        </footer>
      </main>
    </div>
  );
}

const btn: React.CSSProperties = {
  border: "1px solid var(--border)", background: "transparent",
  color: "var(--text-secondary)", borderRadius: 6, padding: "3px 9px",
  fontSize: 11.5, cursor: "pointer",
};

function Centered({ children }: { children: React.ReactNode }) {
  return <div style={{ display: "grid", placeItems: "center", minHeight: "100vh",
                       background: "var(--page)" }}>{children}</div>;
}

function ForcePasswordChange() {
  const { me, refreshMe, logout } = useApp();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const field: React.CSSProperties = {
    width: "100%", background: "var(--surface-1)", borderRadius: 8,
    border: "1px solid var(--border-strong)", padding: "9px 11px", fontSize: 14,
  };
  const tooShort = next.length > 0 && next.length < 12;
  const mismatch = confirm.length > 0 && confirm !== next;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api.changePassword(current, next);
      await refreshMe();
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <Centered>
      <div style={{ width: "min(400px, 92vw)" }}>
        <div style={{ textAlign: "center", marginBottom: 14 }}>
          <img src="/dataedge_logo.png" alt="Data Edge Ltd" style={{
            height: 32, width: "auto", objectFit: "contain", marginInline: "auto",
          }} />
        </div>
        <Card title="Choose a new password"
              subtitle={`${me!.full_name} — the account is still on its initial password`}>
          <form onSubmit={submit} style={{ display: "flex", flexDirection: "column",
                                           gap: 12, padding: "6px 4px 2px" }}>
            <p style={{ margin: 0, fontSize: 12.5, color: "var(--text-secondary)" }}>
              The seeded password is known to anyone who can read the setup
              notes, so it has to be replaced before the account can be used.
            </p>
            {([["Current password", current, setCurrent, "current-password"],
               ["New password", next, setNext, "new-password"],
               ["Confirm new password", confirm, setConfirm, "new-password"]] as const)
              .map(([label, value, set, ac]) => (
              <label key={label} style={{ fontSize: 12 }}>
                <span style={{ display: "block", marginBottom: 4,
                               color: "var(--text-muted)" }}>{label}</span>
                <input style={field} type="password" value={value} autoComplete={ac}
                       onChange={(e) => set(e.target.value)} />
              </label>
            ))}
            {tooShort && (
              <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                At least 12 characters.
              </span>
            )}
            {mismatch && (
              <span style={{ fontSize: 12, color: "var(--status-critical)" }}>
                The two new passwords do not match.
              </span>
            )}
            {error && (
              <div style={{ fontSize: 12.5 }}>
                <Pill tone="critical">Could not change</Pill>
                <span style={{ marginLeft: 6, color: "var(--text-secondary)" }}>{error}</span>
              </div>
            )}
            <Button type="submit" variant="primary"
                    disabled={busy || !current || next.length < 12 || next !== confirm}>
              {busy ? "Saving…" : "Set password and continue"}
            </Button>
            <button type="button" onClick={logout} style={{
              background: "none", border: "none", color: "var(--text-muted)",
              fontSize: 12, cursor: "pointer", padding: 0, textAlign: "center",
            }}>Sign out instead</button>
          </form>
        </Card>
      </div>
    </Centered>
  );
}

function Login() {
  const { login } = useApp();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try { await login(username, password); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  const field: React.CSSProperties = {
    width: "100%", background: "var(--surface-1)", borderRadius: 8,
    border: "1px solid var(--border-strong)", padding: "10px 12px", fontSize: 14,
    transition: "border-color .12s ease",
  };
  const group: React.CSSProperties = {
    fontSize: 12, display: "block", marginBottom: 6, color: "var(--text-secondary)",
    fontWeight: 600, letterSpacing: ".02em",
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column",
                  background: "var(--page)" }}>
      <div style={{ flex: 1, display: "grid", placeItems: "center", padding: "36px 20px 60px" }}>
        <div style={{ width: "min(400px, 100%)", display: "flex", flexDirection: "column" }}>
          {/* Brand */}
          <div style={{ textAlign: "center", marginBottom: 26 }}>
            <img src="/dataedge_logo.png" alt="Data Edge Ltd"
                 style={{ height: 40, width: "auto", maxWidth: "100%",
                          objectFit: "contain", marginInline: "auto" }} />
          </div>

          {/* Card */}
          <div style={{
            background: "var(--surface-1)", borderRadius: 14,
            border: "1px solid var(--border)", boxShadow: "var(--shadow)",
            padding: "28px",
          }}>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700,
                         color: "var(--text-primary)" }}>Sign in</h1>
            <p style={{ margin: "4px 0 22px", fontSize: 13, color: "var(--text-muted)",
                        lineHeight: 1.5 }}>
              FTP Profitability — Funds Transfer Pricing analytics.
            </p>

            <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <label style={{ display: "block" }}>
                <span style={group}>Username</span>
                <input style={field} value={username} autoComplete="username"
                       onChange={(e) => setUsername(e.target.value)} />
              </label>
              <label style={{ display: "block" }}>
                <span style={group}>Password</span>
                <input style={field} type="password" value={password}
                       autoComplete="current-password"
                       onChange={(e) => setPassword(e.target.value)} />
              </label>

              {error && (
                <div style={{
                  display: "flex", gap: 8, alignItems: "flex-start", fontSize: 12.5,
                  color: "var(--status-critical)", background: "var(--surface-sunken)",
                  border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px",
                }}>
                  <span aria-hidden style={{ fontWeight: 700 }}>⚠</span>
                  <span>{error}</span>
                </div>
              )}

              <Button type="submit" variant="primary" disabled={busy || !password}
                      style={{ width: "100%", padding: "10px 14px", marginTop: 2 }}>
                {busy ? "Signing in…" : "Sign in"}
              </Button>
            </form>
          </div>

          {/* Footer */}
          <p style={{ textAlign: "center", margin: "20px 0 0", fontSize: 11.5,
                      color: "var(--text-muted)" }}>
            © {new Date().getFullYear()} Data Edge Ltd · Powered by Data Edge
          </p>
        </div>
      </div>
    </div>
  );
}
