import type {
  AiCategorizeSuggestResult,
  AiColumnMap,
  AiMapStatementResult,
  AiStatus,
  AlertsResponse,
  ApplyRulesResult,
  AuthMe,
  BootstrapRulesResult,
  ApplyMatchResult,
  BulkOverrideResult,
  Category,
  CategoryCoverage,
  CategoryRule,
  CleanupPreview,
  CleanupResult,
  DashboardSummary,
  DcaBoardResponse,
  Health,
  Lot,
  LotSummary,
  Paginated,
  PeriodKey,
  PortfolioSnapshot,
  PriceHistory,
  PriceHistoryRange,
  WindowPerformanceResponse,
  PriceRefresh,
  SheetsStatus,
  TickerDigestsResponse,
  Transaction,
  UploadResult,
  UsdCzkSeries,
  AdminJob,
  AdminJobsList,
  TaxReport,
  TaxYearsList,
  TaxYearsSummary,
  StatementFileRow,
  MvSeries,
  DrawMetrics,
  PublicAuthConfig,
} from "./types";

/**
 * Base URL for API calls.
 * - Dev: `/api` (Vite proxy → FastAPI) so cookies work same-origin
 * - Prod: set VITE_API_BASE to the FastAPI origin
 */
export const API_BASE = (import.meta.env.VITE_API_BASE ?? "/api").replace(/\/$/, "");

/**
 * Browser URL for the Google Sheets setup wizard (API-hosted HTML at /setup).
 * Dev Vite only proxies `/api`, so default to the API origin on port 8020.
 */
export function setupWizardUrl(): string {
  const override = (import.meta.env.VITE_SETUP_URL as string | undefined)?.trim();
  if (override) return override.replace(/\/$/, "");
  if (API_BASE.startsWith("http")) {
    return `${API_BASE.replace(/\/api\/?$/, "")}/setup`;
  }
  return "http://127.0.0.1:8020/setup";
}

/** Dispatched on any API 401 so AuthContext can clear session / show login. */
export const AUTH_UNAUTHORIZED_EVENT = "auth:unauthorized";

/** Optional hook for tests / custom hosts; also dispatches AUTH_UNAUTHORIZED_EVENT. */
let onUnauthorized: (() => void) | null = null;

export function setOnUnauthorized(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

function notifyUnauthorized(): void {
  try {
    onUnauthorized?.();
  } catch {
    /* ignore listener errors */
  }
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT));
  }
}

/**
 * Format FastAPI / Pydantic error `detail` for display.
 * Arrays of `{loc, msg, type}` become readable lines, not `[object Object]`.
 */
export function formatApiDetail(detail: unknown, fallback = "Request failed"): string {
  if (detail == null || detail === "") return fallback;
  if (typeof detail === "string") return detail;
  if (typeof detail === "number" || typeof detail === "boolean") return String(detail);

  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object") {
        const rec = item as { loc?: unknown; msg?: unknown; message?: unknown };
        const msg =
          typeof rec.msg === "string"
            ? rec.msg
            : typeof rec.message === "string"
              ? rec.message
              : null;
        const locParts = Array.isArray(rec.loc)
          ? rec.loc.filter(
              (x) => x !== "body" && x !== "query" && x !== "path" && x !== "header",
            )
          : [];
        const loc = locParts.map(String).join(".");
        if (msg) return loc ? `${loc}: ${msg}` : msg;
        try {
          return JSON.stringify(item);
        } catch {
          return String(item);
        }
      }
      return String(item);
    });
    const joined = parts.filter(Boolean).join("; ");
    return joined || fallback;
  }

  if (typeof detail === "object") {
    const rec = detail as { msg?: unknown; message?: unknown; detail?: unknown };
    if (typeof rec.msg === "string") return rec.msg;
    if (typeof rec.message === "string") return rec.message;
    if (rec.detail != null && rec.detail !== detail) {
      return formatApiDetail(rec.detail, fallback);
    }
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }

  return String(detail);
}

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (!res.ok) {
    if (res.status === 401) {
      notifyUnauthorized();
    }
    let detail: unknown = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      detail = body.detail ?? body;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, formatApiDetail(detail, res.statusText || "Request failed"));
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function qs(params: Record<string, string | number | boolean | undefined | null>) {
  const u = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") return;
    u.set(k, String(v));
  });
  const s = u.toString();
  return s ? `?${s}` : "";
}

export const api = {
  base: API_BASE,

  health: () => request<Health>("/health"),

  me: () => request<AuthMe>("/auth/me"),

  logout: () => request<{ status: string; guest?: boolean }>("/auth/logout", { method: "POST" }),

  /** Clear guest flag under AUTH_MODE=dev so synthetic local user returns. */
  resumeLocalDev: () =>
    request<{ status: string; auth_mode: string }>("/auth/local-dev", { method: "POST" }),

  publicAuthConfig: () => request<PublicAuthConfig>("/auth/public-config"),

  passwordLogin: (email: string, password: string) =>
    request<{ status: string; email: string; is_demo: boolean; role?: string | null }>(
      "/auth/password",
      {
        method: "POST",
        body: JSON.stringify({ email, password }),
      },
    ),

  /** One-click empty ephemeral sandbox (no email/password). */
  enterDemoSandbox: () =>
    request<{
      status: string;
      email: string;
      is_demo: boolean;
      demo_kind: string;
      read_only: boolean;
    }>("/auth/demo/sandbox", { method: "POST" }),

  /** One-click synthetic read-only sample portfolio. */
  enterDemoTour: () =>
    request<{
      status: string;
      email: string;
      is_demo: boolean;
      demo_kind: string;
      read_only: boolean;
    }>("/auth/demo/tour", { method: "POST" }),

  /** Full URL for browser redirect to Google OAuth */
  loginUrl: () => `${API_BASE}/auth/login`,

  listInvites: (pendingOnly = false) =>
    request<{ items: Array<Record<string, unknown>> }>(
      `/admin/invites${qs({ pending_only: pendingOnly || undefined })}`,
    ),

  createInvite: (email: string) =>
    request<Record<string, unknown>>("/admin/invites", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  deleteInvite: (id: string) =>
    request<{ status: string; id: string }>(`/admin/invites/${id}`, {
      method: "DELETE",
    }),

  listTenantUsers: () =>
    request<{ items: Array<Record<string, unknown>> }>("/admin/invites/users"),

  tenantStatus: () =>
    request<{
      multi_tenant: boolean;
      message?: string;
      user?: {
        id: string;
        email: string;
        role: string;
        spreadsheet_id: string | null;
        tenant_ready: boolean;
      };
    }>("/tenant/status"),

  tenantProvision: () =>
    request<{
      status: string;
      spreadsheet_id?: string;
      backend?: string;
      user?: Record<string, unknown>;
    }>("/tenant/provision", { method: "POST" }),

  /** Platform admin: attach an existing spreadsheet to a user (legacy migration). */
  tenantBind: (spreadsheetId: string, userId?: string) =>
    request<{
      status: string;
      spreadsheet_id?: string;
      user?: Record<string, unknown>;
      bound_by?: string;
    }>("/tenant/bind", {
      method: "POST",
      body: JSON.stringify({
        spreadsheet_id: spreadsheetId,
        ...(userId ? { user_id: userId } : {}),
      }),
    }),

  /**
   * Platform admin one-shot: bind env SPREADSHEET_ID to the current admin
   * (single-tenant → multi-tenant cutover). Prefer over provision for legacy data.
   */
  migrateEnvSheet: () =>
    request<{
      status: string;
      spreadsheet_id?: string;
      user?: Record<string, unknown>;
      source?: string;
    }>("/admin/migrate-env-sheet", { method: "POST" }),

  sheetsStatus: () => request<SheetsStatus>("/sheets/status"),

  cleanupPreview: () => request<CleanupPreview>("/admin/cleanup/preview"),

  cleanupRun: (scopes: string[], confirm: string) =>
    request<CleanupResult>("/admin/cleanup", {
      method: "POST",
      body: JSON.stringify({ scopes, confirm }),
    }),

  adminJobs: (limit = 15) =>
    request<AdminJobsList>(`/admin/jobs${qs({ limit })}`),

  adminJob: (jobId: string) => request<AdminJob>(`/admin/jobs/${jobId}`),

  startAdminJob: (
    kind: string,
    body: {
      date_from?: string;
      date_to?: string;
      limit?: number;
      max_passes?: number;
    } = {},
  ) =>
    request<{ job_id: string; status: string; kind?: string }>(
      `/admin/jobs/${encodeURIComponent(kind)}`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    ),

  taxReport: (params: { year?: number; as_of?: string } = {}) =>
    request<TaxReport>(`/tax-report${qs(params)}`),

  taxYears: () => request<TaxYearsList>("/tax-report/years"),

  taxSummaryByYear: (params: { as_of?: string } = {}) =>
    request<TaxYearsSummary>(`/tax-report/summary-by-year${qs(params)}`),

  /** Year-end ZIP download URL (open in new tab / anchor download). */
  yearEndExportUrl: (year?: number) =>
    `${API_BASE}/exports/year-end${qs({ year: year ?? undefined })}`,

  statementFiles: (params: { limit?: number; status?: string } = {}) =>
    request<{ total: number; items: StatementFileRow[] }>(
      `/statement-files${qs(params)}`,
    ),

  retryStatementFile: (id: string) =>
    request<UploadResult>(`/statement-files/${id}/retry`, { method: "POST" }),

  dashboard: (params: {
    date_from?: string;
    date_to?: string;
    currency?: string;
    period_key?: PeriodKey | string;
  } = {}) =>
    request<DashboardSummary>(`/dashboard-summary${qs(params)}`),

  alerts: () => request<AlertsResponse>("/alerts"),

  investmentsSnapshot: (params: { as_of?: string } = {}) =>
    request<PortfolioSnapshot>(`/investments/snapshot${qs(params)}`),

  tickerDigests: (params: { as_of?: string } = {}) =>
    request<TickerDigestsResponse>(`/investments/ticker-digests${qs(params)}`),

  investmentsDcaOpportunities: (params: { as_of?: string } = {}) =>
    request<DcaBoardResponse>(`/investments/dca-opportunities${qs(params)}`),

  mvSeries: (params: { date_from?: string | null; date_to?: string | null } = {}) =>
    request<MvSeries>(
      `/investments/mv-series${qs({
        date_from: params.date_from ?? undefined,
        date_to: params.date_to ?? undefined,
      })}`,
    ),

  drawMetrics: (params: { as_of?: string } = {}) =>
    request<DrawMetrics>(`/investments/draw-metrics${qs(params)}`),

  recordMvSnapshot: () =>
    request<{ as_of: string; total_market_value_usd: string | null; source: string }>(
      "/investments/snapshots/record",
      { method: "POST" },
    ),

  /** CNB historical CZK per 1 USD; optional portfolio_usd for CZK wealth context */
  fxUsdCzk: (params: {
    date_from?: string | null;
    date_to?: string | null;
    portfolio_usd?: string | number | null;
  } = {}) =>
    request<UsdCzkSeries>(
      `/fx/usd-czk${qs({
        date_from: params.date_from ?? undefined,
        date_to: params.date_to ?? undefined,
        portfolio_usd:
          params.portfolio_usd != null && params.portfolio_usd !== ""
            ? String(params.portfolio_usd)
            : undefined,
      })}`,
    ),

  transactions: (params: {
    date_from?: string;
    date_to?: string;
    currency?: string;
    is_internal_transfer?: boolean;
    category_id?: string;
    /** Comma-separated StatementFiles UUIDs */
    source_file_ids?: string;
    /** Only txs from latest multi-file import batch (~15m) */
    latest_import_batch?: boolean | string;
    limit?: number;
    offset?: number;
  } = {}) =>
    request<
      Paginated<Transaction> & {
        latest_import_batch?: {
          file_ids: string[];
          filenames: string[];
          uploaded_at_max: string | null;
        };
      }
    >(`/transactions${qs(params)}`),

  categories: () => request<{ items: Category[] }>("/categories"),

  categoryCoverage: (days = 180) =>
    request<CategoryCoverage>(`/categories/coverage${qs({ days })}`),

  ruleSuggestions: (days = 180, limit = 20) =>
    request<{
      days: number;
      coverage_pct: number;
      items: Array<{
        label: string;
        match_field: string;
        match_type: string;
        match_value: string;
        amount_usd: string;
        tx_count: number;
        last_seen?: string;
        score: number;
        suggested_category_id?: string | null;
        suggested_category_name?: string | null;
        suggestion_confidence?: number | null;
        reason?: string;
      }>;
    }>(`/categories/rule-suggestions${qs({ days, limit })}`),

  merchantQueue: (days = 180, limit = 40) =>
    request<{
      days: number;
      items: Array<{
        label: string;
        match_field?: string;
        match_value?: string;
        amount_usd: string;
        tx_count: number;
        suggested_category_id?: string | null;
        suggested_category_name?: string | null;
        suggestion_confidence?: number | null;
      }>;
      coverage_pct: number;
    }>(`/categories/merchant-queue${qs({ days, limit })}`),

  merchantQueueApply: (body: {
    label: string;
    category_id: string;
    match_field?: string;
    match_value?: string;
    create_rule?: boolean;
    also_apply?: boolean;
  }) =>
    request<{
      updated?: number;
      matched?: number;
      removed_from_queue?: boolean;
      label?: string;
      [k: string]: unknown;
    }>("/categories/merchant-queue/apply", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  createCategory: (body: {
    name: string;
    necessity: string;
    life_domain: string;
    parent_id?: string | null;
    is_income?: boolean;
    is_transfer?: boolean;
    sort_order?: number;
  }) =>
    request<{ item: Category }>("/categories", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updateCategory: (
    id: string,
    body: Partial<{
      name: string;
      necessity: string;
      life_domain: string;
      parent_id: string | null;
      is_income: boolean;
      is_transfer: boolean;
      sort_order: number;
    }>,
  ) =>
    request<{ item: Category }>(`/categories/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  deleteCategory: (
    id: string,
    opts?: { reassign_to?: string; cascade_children?: boolean },
  ) =>
    request<Record<string, unknown>>(
      `/categories/${id}${qs({
        reassign_to: opts?.reassign_to,
        cascade_children: opts?.cascade_children,
      })}`,
      { method: "DELETE" },
    ),

  ensureCategories: () =>
    request<{ created: number; updated: number; total_defaults: number }>(
      "/categories/ensure-defaults",
      { method: "POST" },
    ),

  warmCache: () =>
    request<{ ok: boolean; counts: Record<string, unknown> }>("/admin/warm-cache", {
      method: "POST",
    }),

  bootstrapRules: (also_apply = true) =>
    request<BootstrapRulesResult>("/categories/bootstrap-rules", {
      method: "POST",
      body: JSON.stringify({ also_apply }),
    }),

  applyRules: () =>
    request<ApplyRulesResult>("/categories/apply-rules", { method: "POST" }),

  aiStatus: () => request<AiStatus>("/ai/status"),

  aiCategorizeSuggest: (body: {
    source_file_ids?: string[];
    limit?: number;
    exclude_merchant_keys?: string[];
    merchant_key?: string;
    hint?: string;
  } = {}) =>
    request<AiCategorizeSuggestResult>("/ai/categorize-suggest", {
      method: "POST",
      body: JSON.stringify({
        source_file_ids: body.source_file_ids || [],
        limit: body.limit ?? null,
        exclude_merchant_keys: body.exclude_merchant_keys || [],
        merchant_key: body.merchant_key ?? null,
        hint: body.hint ?? null,
      }),
    }),

  /** Undo category assigns — restore prior category_id / override flags. */
  restoreAssignments: (
    items: Array<{
      transaction_id: string;
      category_id: string | null;
      category_override: boolean;
      is_internal_transfer?: boolean | null;
    }>,
  ) =>
    request<{
      updated: number;
      missing: number;
      transaction_ids: string[];
    }>("/categories/restore-assignments", {
      method: "POST",
      body: JSON.stringify({ items }),
    }),

  /** Map unknown cash CSV via Grok (preview). Prefer content_sha256 from failed upload. */
  aiMapStatement: (opts: { content_sha256?: string; file?: File }) => {
    const fd = new FormData();
    if (opts.content_sha256) fd.append("content_sha256", opts.content_sha256);
    if (opts.file) fd.append("file", opts.file);
    return request<AiMapStatementResult>("/ai/map-statement", {
      method: "POST",
      body: fd,
    });
  },

  aiImportMapped: (body: {
    content_sha256: string;
    filename: string;
    mapping: AiColumnMap;
    headers?: string[];
  }) =>
    request<UploadResult>("/ai/import-mapped", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Global match apply — all ledger txs, not limited to current UI filter. */
  applyMatch: (body: {
    category_id: string;
    match_field: string;
    match_type: string;
    match_value: string;
    institution_scope?: string | null;
    set_internal_transfer?: boolean;
    mode?: "fill_blanks" | "reclassify_non_override" | "force";
    mark_override?: boolean;
  }) =>
    request<ApplyMatchResult>("/categories/apply-match", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  categoryRules: () => request<{ items: CategoryRule[] }>("/category-rules"),

  createCategoryRule: (body: Partial<CategoryRule> & {
    match_field: string;
    match_type: string;
    match_value: string;
    category_id: string;
  }) =>
    request<CategoryRule>("/category-rules", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updateCategoryRule: (id: string, body: Partial<CategoryRule>) =>
    request<CategoryRule>(`/category-rules/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  deleteCategoryRule: (id: string) =>
    request<{ status: string; id: string }>(`/category-rules/${id}`, {
      method: "DELETE",
    }),

  overrideCategory: (categoryId: string, transactionId: string) =>
    request<{ transaction_id: string; category_id: string; category_override: boolean }>(
      `/categories/${categoryId}/override`,
      {
        method: "POST",
        body: JSON.stringify({ transaction_id: transactionId }),
      },
    ),

  bulkOverrideCategory: (categoryId: string, transactionIds: string[]) =>
    request<BulkOverrideResult>("/categories/bulk-override", {
      method: "POST",
      body: JSON.stringify({
        category_id: categoryId,
        transaction_ids: transactionIds,
      }),
    }),

  lots: (params: { ticker?: string; open_only?: boolean; as_of?: string } = {}) =>
    request<{ items: Lot[]; summaries: LotSummary[] }>(`/lots${qs(params)}`),

  investments: (params: {
    date_from?: string;
    date_to?: string;
    ticker?: string;
    event_type?: string;
    limit?: number;
    offset?: number;
  } = {}) =>
    request<Paginated<Record<string, unknown>>>(`/investments${qs(params)}`),

  upload: async (file: File, onProgress?: (pct: number) => void) => {
    // fetch doesn't support upload progress easily; use XHR
    return new Promise<UploadResult>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_BASE}/upload`);
      xhr.withCredentials = true;
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      };
      xhr.onload = () => {
        try {
          const body = JSON.parse(xhr.responseText) as { detail?: unknown };
          if (xhr.status >= 200 && xhr.status < 300) resolve(body as UploadResult);
          else {
            if (xhr.status === 401) notifyUnauthorized();
            reject(
              new ApiError(
                xhr.status,
                formatApiDetail(body.detail ?? body, xhr.statusText || "Upload failed"),
              ),
            );
          }
        } catch (err) {
          reject(err);
        }
      };
      xhr.onerror = () => reject(new ApiError(0, "Network error"));
      const fd = new FormData();
      fd.append("file", file);
      xhr.send(fd);
    });
  },

  refreshPrices: (force = false) =>
    request<PriceRefresh>(`/prices/refresh${qs({ force })}`, { method: "POST" }),

  priceHistory: (params: {
    scope: "ticker" | "asset_class" | "all";
    range?: PriceHistoryRange | string;
    ticker?: string;
    asset_class?: string;
  }) =>
    request<PriceHistory>(
      `/prices/history${qs({
        scope: params.scope,
        range: params.range ?? "1y",
        ticker: params.ticker,
        asset_class: params.asset_class,
      })}`,
    ),

  priceWindowPerformance: (params: { range?: PriceHistoryRange | string } = {}) =>
    request<WindowPerformanceResponse>(
      `/prices/window-performance${qs({ range: params.range ?? "1y" })}`,
    ),
};
