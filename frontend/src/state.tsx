import {
  createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState,
} from "react";
import { api, Branch, Filters, Me, Node_, Product, setToken } from "./api";

interface Ctx {
  me: Me | null;
  ready: boolean;
  login: (u: string, p: string) => Promise<void>;
  logout: () => void;
  can: (perm: string) => boolean;

  filters: Filters;
  setFilters: (f: Filters | ((p: Filters) => Filters)) => void;
  resetFilters: () => void;

  branches: Branch[];
  products: Product[];
  divisions: Node_[];
  districts: Node_[];
  refreshMasters: () => Promise<void>;

  theme: "light" | "dark";
  toggleTheme: () => void;
}

const C = createContext<Ctx>(null!);
export const useApp = () => useContext(C);

/** Filters live in the URL hash, so any view is a shareable link and the back
 *  button works across drilldowns. */
function readFilters(): Filters {
  const raw = new URLSearchParams(location.hash.replace(/^#\/?[^?]*\??/, ""));
  const f: Filters = {};
  const s = (k: keyof Filters) => raw.get(k as string) ?? undefined;
  f.date_from = s("date_from");
  f.date_to = s("date_to");
  f.branch_category = s("branch_category");
  f.account_no = s("account_no");
  f.side = s("side") as Filters["side"];
  f.ftp_sign = s("ftp_sign") as Filters["ftp_sign"];
  const div = raw.get("division_id"); if (div) f.division_id = +div;
  const dis = raw.get("district_id"); if (dis) f.district_id = +dis;
  const b = raw.getAll("branch_id").map(Number).filter(Boolean);
  if (b.length) f.branch_id = b;
  const p = raw.getAll("product_code").filter(Boolean);
  if (p.length) f.product_code = p;
  return Object.fromEntries(Object.entries(f).filter(([, v]) => v !== undefined)) as Filters;
}

function writeFilters(view: string, f: Filters) {
  const p = new URLSearchParams();
  Object.entries(f).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") return;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x)));
    else p.append(k, String(v));
  });
  const q = p.toString();
  const next = `#/${view}${q ? `?${q}` : ""}`;
  if (location.hash !== next) history.replaceState(null, "", next);
}

export function currentView(): string {
  return location.hash.replace(/^#\/?/, "").split("?")[0] || "overview";
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const [filters, setFiltersRaw] = useState<Filters>(readFilters);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [divisions, setDivisions] = useState<Node_[]>([]);
  const [districts, setDistricts] = useState<Node_[]>([]);
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (localStorage.getItem("ftp_theme") as "light" | "dark") ??
          (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"),
  );

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("ftp_theme", theme);
  }, [theme]);

  const refreshMasters = useCallback(async () => {
    const [b, p, dv, ds] = await Promise.all([
      api.branches(true).catch(() => []),
      api.products().catch(() => []),
      api.divisions().catch(() => []),
      api.districts().catch(() => []),
    ]);
    setBranches(b); setProducts(p); setDivisions(dv); setDistricts(ds);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const m = await api.me();
        setMe(m);
        await refreshMasters();
      } catch { setToken(null); }
      finally { setReady(true); }
    })();
  }, [refreshMasters]);

  const setFilters = useCallback((f: Filters | ((p: Filters) => Filters)) => {
    setFiltersRaw((prev) => {
      const next = typeof f === "function" ? f(prev) : f;
      writeFilters(currentView(), next);
      return next;
    });
  }, []);

  const value = useMemo<Ctx>(() => ({
    me, ready,
    login: async (u, p) => {
      const r = await api.login(u, p);
      setToken(r.access_token);
      const m = await api.me();
      setMe(m);
      await refreshMasters();
    },
    logout: () => { setToken(null); setMe(null); location.hash = "#/overview"; },
    can: (perm) => Boolean(me?.permissions.includes(perm)),
    filters, setFilters,
    resetFilters: () => setFilters({}),
    branches, products, divisions, districts, refreshMasters,
    theme, toggleTheme: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
  }), [me, ready, filters, setFilters, branches, products, divisions, districts,
       theme, refreshMasters]);

  return <C.Provider value={value}>{children}</C.Provider>;
}

/** Tiny async hook: keeps the previous value visible while refetching, so the
 *  page dims rather than flashing a skeleton. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn()
      .then((d) => { if (alive) { setData(d); setError(null); } })
      .catch((e) => { if (alive) setError(e?.message ?? String(e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, loading, error };
}
