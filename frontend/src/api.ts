/** Typed client for the FTP API. */

const BASE = "/api/v1";

let token: string | null = localStorage.getItem("ftp_token");

export function setToken(t: string | null) {
  token = t;
  if (t) localStorage.setItem("ftp_token", t);
  else localStorage.removeItem("ftp_token");
}
export const hasToken = () => Boolean(token);

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = body?.detail;
    throw new ApiError(
      res.status,
      typeof detail === "string" ? detail : detail?.message ?? res.statusText,
      body,
    );
  }
  return body as T;
}

/** Filters are shared by every dashboard and analytics endpoint, which is what
 *  lets one filter row above the page scope all of them. */
export interface Filters {
  date_from?: string;
  date_to?: string;
  branch_id?: number[];
  division_id?: number;
  district_id?: number;
  branch_category?: string;
  product_code?: string[];
  side?: "ASSET" | "LIABILITY";
  account_no?: string;
  ftp_sign?: "POSITIVE" | "NEGATIVE";
}

export function qs(f: Filters, extra: Record<string, unknown> = {}) {
  const p = new URLSearchParams();
  const put = (k: string, v: unknown) => {
    if (v === undefined || v === null || v === "") return;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x)));
    else p.append(k, String(v));
  };
  Object.entries(f).forEach(([k, v]) => put(k, v));
  Object.entries(extra).forEach(([k, v]) => put(k, v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

// --- auth ------------------------------------------------------------------

export interface Me {
  id: number; username: string; full_name: string;
  scope_level: "HO" | "DIVISION" | "DISTRICT" | "BRANCH";
  scope_id: number | null; scope_label: string;
  roles: string[]; permissions: string[];
}

export const api = {
  login: (username: string, password: string) =>
    request<{ access_token: string; must_change_password: boolean }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  me: () => request<Me>("/auth/me"),

  // --- dashboard ----------------------------------------------------------
  kpis: (f: Filters) => request<Kpis>(`/dashboard/kpis${qs(f)}`),
  byBranch: (f: Filters) => request<Series[]>(`/dashboard/by-branch${qs(f)}`),
  byProduct: (f: Filters) => request<Series[]>(`/dashboard/by-product${qs(f)}`),
  byCategory: (f: Filters) => request<Series[]>(`/dashboard/by-category${qs(f)}`),
  heatmap: (f: Filters) => request<HeatCell[]>(`/dashboard/heatmap${qs(f)}`),
  accounts: (f: Filters, o: Record<string, unknown>) =>
    request<PageOf<AccountRow>>(`/dashboard/accounts${qs(f, o)}`),

  // --- analytics ----------------------------------------------------------
  summary: (f: Filters) => request<Summary>(`/analytics/summary${qs(f)}`),
  trend: (f: Filters, ma = 7) => request<Trend>(`/analytics/trend${qs(f, { ma_window: ma })}`),
  bridge: (f: Filters, by: Dim) => request<Bridge>(`/analytics/variance-bridge${qs(f, { by })}`),
  waterfall: (f: Filters, by?: Dim) =>
    request<Waterfall>(`/analytics/spread-waterfall${qs(f, by ? { by } : {})}`),
  concentration: (f: Filters, by: Dim) =>
    request<Concentration>(`/analytics/concentration${qs(f, { by })}`),
  rankings: (f: Filters, by: Dim) => request<Rankings>(`/analytics/rankings${qs(f, { by })}`),
  distribution: (f: Filters, buckets = 12) =>
    request<Distribution>(`/analytics/rate-distribution${qs(f, { buckets })}`),
  outliers: (f: Filters, z = 3) => request<Outliers>(`/analytics/outliers${qs(f, { z })}`),
  leakage: (f: Filters) => request<Leakage>(`/analytics/leakage${qs(f)}`),
  scatter: (f: Filters, by: Dim) => request<Scatter>(`/analytics/scatter${qs(f, { by })}`),
  balanceSheet: (f: Filters) => request<BalanceSheet>(`/analytics/balance-sheet${qs(f)}`),

  // --- master -------------------------------------------------------------
  branches: (includeInactive = false) =>
    request<Branch[]>(`/branches${qs({}, { include_inactive: includeInactive })}`),
  divisions: () => request<Node_[]>("/divisions"),
  districts: () => request<Node_[]>("/districts"),
  products: () => request<Product[]>("/products"),
  branchUsage: (code: string) => request<BranchUsage>(`/branches/${code}/usage`),
  createBranch: (b: NewBranch) =>
    request<Branch>("/branches", { method: "POST", body: JSON.stringify(b) }),
  updateBranch: (code: string, b: Partial<NewBranch> & { is_active?: boolean }) =>
    request<Branch>(`/branches/${code}`, { method: "PATCH", body: JSON.stringify(b) }),
  deleteBranch: (code: string) =>
    request<{ deleted: boolean }>(`/branches/${code}`, { method: "DELETE" }),
  deactivateBranch: (code: string) =>
    request<Branch>(`/branches/${code}/deactivate`, { method: "POST" }),
  reactivateBranch: (code: string) =>
    request<Branch>(`/branches/${code}/reactivate`, { method: "POST" }),

  // --- uploads ------------------------------------------------------------
  probe: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<Probe>("/uploads/probe", { method: "POST", body: fd });
  },
  upload: (file: File, opts: { business_date?: string; sheet_name?: string }) => {
    const fd = new FormData();
    fd.append("file", file);
    if (opts.business_date) fd.append("business_date", opts.business_date);
    if (opts.sheet_name) fd.append("sheet_name", opts.sheet_name);
    return request<UploadResult>("/uploads", { method: "POST", body: fd });
  },
  batches: () => request<Batch[]>("/uploads"),
  batchExceptions: (ref: string) => request<ExceptionRow[]>(`/uploads/${ref}/exceptions`),
};

// --- types -----------------------------------------------------------------

export type Dim = "branch" | "product" | "category" | "division" | "district";
export type Num = string; // Decimals cross the wire as strings to keep precision.

export interface Kpis {
  asset_balance: Num; liability_balance: Num; total_balance: Num;
  interest_receivable: Num; interest_payable: Num;
  asset_ftp_profit: Num; liability_ftp_profit: Num; net_ftp_profit: Num;
  ftp_over_balance_pct: Num;
  branch_count: number; product_count: number; account_count: number;
  day_count: number; negative_ftp_count: number;
  as_of: string | null;
}

export interface Delta {
  current: Num; prior: Num; change: Num; change_pct: Num | null;
}
export interface Summary extends Kpis {
  comparison: {
    current_period: { start: string; end: string; days: number };
    prior_period: { start: string; end: string; days: number };
    prior_has_data: boolean;
    deltas: Record<string, Delta>;
  } | null;
}

export interface Series {
  key: string | number; label: string;
  asset_ftp_profit: Num; liability_ftp_profit: Num; net_ftp_profit: Num;
  asset_balance: Num; liability_balance: Num; total_balance: Num;
  account_count: number; negative_ftp_count: number; avg_ftp_rate: Num;
}

export interface TrendPoint extends Series {
  moving_average: Num; cumulative: Num;
  day_over_day: Num | null; day_over_day_pct: Num | null;
}
export interface Trend {
  points: TrendPoint[];
  summary: {
    days: number; total: Num; mean_daily: Num; stdev_daily: Num;
    volatility_pct: Num | null;
    best_day: { date: string; value: Num };
    worst_day: { date: string; value: Num };
    annualised_run_rate: Num;
  } | null;
}

export interface BridgeSegment {
  label: string; status: "new" | "closed" | "continuing";
  prior_profit: Num; current_profit: Num; change: Num;
  volume_effect: Num; rate_effect: Num; interaction_effect: Num;
  prior_rate: Num; current_rate: Num;
  prior_balance: Num; current_balance: Num;
}
export interface Bridge {
  available: boolean; reason?: string; dimension?: Dim;
  current_period?: { start: string; end: string; days: number };
  prior_period?: { start: string; end: string; days: number };
  opening_profit?: Num; closing_profit?: Num; total_change?: Num;
  volume_effect?: Num; rate_effect?: Num; interaction_effect?: Num;
  residual?: Num; segments?: BridgeSegment[];
}

export interface Waterfall {
  components: { key: string; label: string; amount: Num; rate: Num }[];
  net_ftp_profit: Num; total_balance: Num; check: Num;
  by_segment: {
    label: string; benchmark: Num; customer_rate: Num;
    liquidity: Num; other: Num; net: Num;
  }[] | null;
}

export interface Concentration {
  available: boolean; dimension?: Dim; segment_count?: number;
  net_ftp_profit?: Num; hhi?: Num; hhi_interpretation?: string;
  top_1_pct?: Num; top_3_pct?: Num; top_5_pct?: Num;
  segments_to_80pct?: number;
  segments: { rank: number; label: string; net_ftp_profit: Num;
    share_pct: Num; cumulative_pct: Num; total_balance: Num;
    account_count: number }[];
}

export interface RankRow {
  rank: number; label: string; net_ftp_profit: Num; total_balance: Num;
  yield_pct: Num; account_count: number; negative_ftp_count: number;
  profit_per_account: Num; percentile: Num; quartile: number;
}
export interface Rankings {
  available: boolean; dimension?: Dim; median_yield_pct?: Num;
  best?: RankRow; worst?: RankRow; spread_pct?: Num; rows: RankRow[];
}

export interface Distribution {
  available: boolean; min_rate?: Num; max_rate?: Num;
  buckets: { bucket: number; from_rate: Num; to_rate: Num;
    account_count: number; account_pct: Num; balance: Num;
    balance_pct: Num; ftp_income: Num; is_negative: boolean }[];
}

export interface Outliers {
  z_threshold: number; count: number;
  rows: { business_date: string; branch_code: string; account_no: string;
    product_code: string; side: string; balance: Num; normalized_roi: Num;
    ftp_rate: Num; ftp_income: Num; z_rate: Num; z_roi: Num }[];
}

export interface Leakage {
  negative_account_days: number; negative_balance: Num; drag: Num;
  total_ftp_profit: Num; drag_as_pct_of_profit: Num | null; opportunity: Num;
  by_product: { label: string; account_count: number; balance: Num; ftp_income: Num }[];
  by_branch: { label: string; account_count: number; balance: Num; ftp_income: Num }[];
  worst_accounts: { business_date: string; branch_code: string; account_no: string;
    product_code: string; balance: Num; normalized_roi: Num;
    ftp_rate: Num; ftp_income: Num }[];
}

export interface Scatter {
  available: boolean; dimension?: Dim;
  median_balance?: Num; median_yield_pct?: Num;
  points: { label: string; balance: Num; ftp_income: Num; yield_pct: Num;
    account_count: number; quadrant: string }[];
}

export interface BalanceSheet {
  asset: SideStats | null; liability: SideStats | null;
  funding_gap: Num; coverage_ratio: Num | null; ftp_spread: Num;
}
export interface SideStats {
  balance: Num; ftp_profit: Num; avg_customer_rate: Num;
  avg_ftp_rate: Num; account_days: number;
}

export interface HeatCell {
  branch_code: string; product_code: string;
  net_ftp_profit: Num; total_balance: Num;
}

export interface AccountRow {
  business_date: string; branch_code: string; account_no: string;
  product_code: string; side: string; balance: Num; normalized_roi: Num;
  roi_source: string; benchmark_rate: Num; liquidity_cost: Num;
  other_cost: Num; ftp_rate: Num; ftp_income: Num;
  customer_interest: Num; negative_ftp_flag: boolean;
}
export interface PageOf<T> { items: T[]; total: number; limit: number; offset: number }

export interface Branch {
  id: number; branch_code: string; branch_name: string;
  division_id: number | null; district_id: number;
  category: string; opened_on: string | null; is_active: boolean;
  udf: Record<string, unknown> | null;
}
export interface NewBranch {
  branch_code: string; branch_name: string; district_code: string;
  category: string; opened_on?: string | null;
}
export interface BranchUsage {
  branch_code: string; fact_rows: number; bank_rows: number;
  aggregate_rows: number; deletable: boolean; note: string;
}
export interface Node_ { id: number; code: string; name: string;
  division_id?: number; is_active: boolean }
export interface Product {
  id: number; product_code: string; short_name: string; details: string | null;
  side: string; liability_nature: string | null; is_active: boolean;
}

export interface Probe {
  ok: boolean; errors: string[]; header_issues: string[];
  business_dates: string[]; total_data_rows: number;
  sheets: { name: string; business_date: string | null; included: boolean;
    reason: string; data_rows: number }[];
}
export interface UploadResult {
  batch_ref: string; status: string; total_rows: number; accepted_rows: number;
  warned_rows: number; rejected_rows: number; structural_rows: number;
  business_dates: string[]; run_ref: string | null;
  exceptions_by_rule: Record<string, number>;
}
export interface Batch {
  id: number; batch_ref: string; business_date: string | null; file_name: string;
  status: string; total_rows: number; accepted_rows: number; warned_rows: number;
  rejected_rows: number; is_current: boolean;
  supersedes_batch_id: number | null; superseded_by_batch_id: number | null;
  uploaded_at: string; committed_at: string | null;
}
export interface ExceptionRow {
  source_row_no: number | null; origin: string | null; severity: string;
  rule_code: string; field_name: string | null; raw_value: string | null;
  message: string;
}
