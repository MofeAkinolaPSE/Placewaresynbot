import {
  InventoryDashboardData,
  WorkforceDashboardData,
  WorkstationSummary,
  ExecutiveBriefing,
  Alert,
  StaffMember,
  OpsKpis,
  OpsForecast,
  ExecutiveSummaryResponse,
  ArTrendsResponse,
  HrSummaryResponse,
  RiskSignalsResponse,
  RecommendationsResponse,
  AnomaliesResponse,
  ProcurementAnalysis,
  ProcurementShipment,
  SupplierScorecardRow,
} from "@shared/dashboard-types";
import { authClient } from "@/lib/auth-client";
import { apiUrl } from "@/lib/api-base";

export type ApiErrorKind = "session" | "permission" | "validation" | "not_found" | "transport" | "server" | "unknown";

export class ApiError extends Error {
  status: number;
  code?: string;
  kind: ApiErrorKind;
  detail?: unknown;

  constructor(message: string, status: number, kind: ApiErrorKind, code?: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.kind = kind;
    this.code = code;
    this.detail = detail;
  }
}

function classifyApiErrorKind(status: number): ApiErrorKind {
  if (status === 401) return "session";
  if (status === 403) return "permission";
  if (status === 404) return "not_found";
  if (status === 400 || status === 422) return "validation";
  if (status >= 500) return "server";
  if (status === 0) return "transport";
  return "unknown";
}

async function toApiError(res: Response, fallbackMessage: string): Promise<ApiError> {
  let detail: any = null;
  try {
    detail = await res.json();
  } catch {
    detail = null;
  }

  const detailPayload = detail?.detail ?? detail?.error ?? detail;
  const message =
    (typeof detailPayload === "string" ? detailPayload : detailPayload?.message) ||
    res.statusText ||
    fallbackMessage;
  const code = typeof detailPayload === "object" ? detailPayload?.code : undefined;

  return new ApiError(message, res.status, classifyApiErrorKind(res.status), code, detailPayload);
}

function redirectToLoginIfNeeded() {
  if (typeof window === "undefined") return;
  if (window.location.hash !== "#/login") {
    window.location.hash = "#/login";
  }
}

async function getBearerToken(): Promise<string> {
  let token = authClient.getAccessToken();
  if (!token) {
    const refreshed = await authClient.refresh();
    if (!refreshed) {
      const reason = authClient.getLastAuthError();
      throw new ApiError(
        reason ? `No active session (${reason})` : "No active session",
        401,
        "session",
      );
    }
    token = authClient.getAccessToken();
  }
  if (!token) {
    const reason = authClient.getLastAuthError();
    throw new ApiError(
      reason ? `Session expired (${reason})` : "Session expired",
      401,
      "session",
    );
  }
  return token;
}

async function fetchJson<T>(endpoint: string): Promise<T> {
  let token = await getBearerToken();
  let res = await fetch(apiUrl(endpoint), {
    cache: "no-store",
    headers: {
      "Authorization": `Bearer ${token}`
    }
  });

  if (res.status === 401) {
    const refreshed = await authClient.refresh();
    if (!refreshed) {
      redirectToLoginIfNeeded();
      throw new ApiError("Session expired", 401, "session");
    }
    token = await getBearerToken();
    res = await fetch(apiUrl(endpoint), { cache: "no-store", headers: { "Authorization": `Bearer ${token}` } });
  }

  if (!res.ok) {
    const apiError = await toApiError(res, `Request failed for ${endpoint}`);
    console.error(`API Error ${endpoint}:`, apiError.message);
    throw apiError;
  }
  return res.json().then(d => d.data ?? d);
}

async function fetchRaw<T = any>(endpoint: string): Promise<T> {
  let token = await getBearerToken();
  let res = await fetch(apiUrl(endpoint), { cache: "no-store", headers: { "Authorization": `Bearer ${token}` } });

  if (res.status === 401) {
    const refreshed = await authClient.refresh();
    if (!refreshed) {
      redirectToLoginIfNeeded();
      throw new ApiError("Session expired", 401, "session");
    }
    token = await getBearerToken();
    res = await fetch(apiUrl(endpoint), { cache: "no-store", headers: { "Authorization": `Bearer ${token}` } });
  }

  if (!res.ok) {
    const apiError = await toApiError(res, `Request failed for ${endpoint}`);
    console.error(`API Error ${endpoint}:`, apiError.message);
    throw apiError;
  }
  return res.json();
}

async function sendJson<T>(
  endpoint: string,
  method: "POST" | "PUT" | "PATCH",
  body: Record<string, any>,
): Promise<T> {
  let token = await getBearerToken();
  let res = await fetch(apiUrl(endpoint), {
    method,
    headers: {
      "Authorization": `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  if (res.status === 401) {
    const refreshed = await authClient.refresh();
    if (!refreshed) {
      redirectToLoginIfNeeded();
      throw new ApiError("Session expired", 401, "session");
    }
    token = await getBearerToken();
    res = await fetch(apiUrl(endpoint), {
      method,
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
  }

  if (!res.ok) {
    const apiError = await toApiError(res, `Request failed for ${method} ${endpoint}`);
    console.error(`API Error ${method} ${endpoint}:`, apiError.message);
    throw apiError;
  }

  return res.json();
}

async function sendFormData<T>(
  endpoint: string,
  method: "POST" | "PUT" | "PATCH",
  body: FormData,
): Promise<T> {
  let token = await getBearerToken();
  let res = await fetch(apiUrl(endpoint), {
    method,
    headers: {
      "Authorization": `Bearer ${token}`,
    },
    body,
  });

  if (res.status === 401) {
    const refreshed = await authClient.refresh();
    if (!refreshed) {
      redirectToLoginIfNeeded();
      throw new ApiError("Session expired", 401, "session");
    }
    token = await getBearerToken();
    res = await fetch(apiUrl(endpoint), {
      method,
      headers: {
        "Authorization": `Bearer ${token}`,
      },
      body,
    });
  }

  if (!res.ok) {
    const apiError = await toApiError(res, `Request failed for ${method} ${endpoint}`);
    console.error(`API Error ${method} ${endpoint}:`, apiError.message);
    throw apiError;
  }

  return res.json();
}

async function sendDelete<T>(endpoint: string): Promise<T> {
  let token = await getBearerToken();
  let res = await fetch(apiUrl(endpoint), {
    method: "DELETE",
    headers: {
      "Authorization": `Bearer ${token}`,
    },
  });

  if (res.status === 401) {
    const refreshed = await authClient.refresh();
    if (!refreshed) {
      redirectToLoginIfNeeded();
      throw new ApiError("Session expired", 401, "session");
    }
    token = await getBearerToken();
    res = await fetch(apiUrl(endpoint), {
      method: "DELETE",
      headers: {
        "Authorization": `Bearer ${token}`,
      },
    });
  }

  if (!res.ok) {
    const apiError = await toApiError(res, `Request failed for DELETE ${endpoint}`);
    console.error(`API Error DELETE ${endpoint}:`, apiError.message);
    throw apiError;
  }

  return res.json();
}

export const api = {
  dashboard: {
    workstation: () => fetchRaw<{ data: WorkstationSummary }>("/dashboard/workstation").then((r) => r.data),
    inventory: () => fetchJson<InventoryDashboardData>("/dashboard/inventory"),
    workforce: () => fetchJson<WorkforceDashboardData>("/dashboard/workforce"),
    crm: () => fetchJson<any>("/dashboard/crm"),
    alerts: () => fetchJson<Alert[]>("/dashboard/alerts"),
    briefing: () => fetchJson<ExecutiveBriefing>("/dashboard/executive-briefing"),
    finance: () => fetchJson<any>("/dashboard/finance"),
  },
  presence: {
    /** Called every 30s by PresenceHeartbeat.tsx for the whole authenticated session. */
    heartbeat: () => sendJson<{ status: string }>("/presence/heartbeat", "POST", {}),
    /** Global "who's online right now" roster -- not department-scoped. */
    online: () =>
      fetchRaw<{ users: { user_id: string; email: string; roles: string[]; last_seen: string }[]; count: number }>("/presence/online"),
  },
  staff: {
    list: (dept?: string) => fetchJson<StaffMember[]>(`/staff${dept ? `?department=${dept}` : ""}`),
    snapshot: () => fetchJson<StaffMember[]>(`/staff/snapshot`),
    timesheets: (department?: string, limit: number = 50) =>
      fetchJson<any[]>(`/timesheets${department ? `?department=${encodeURIComponent(department)}&limit=${limit}` : `?limit=${limit}`}`),
    timesheetsForStaff: (staffId: string, limit: number = 20) =>
      fetchJson<any[]>(`/timesheets/staff/${encodeURIComponent(staffId)}?limit=${limit}`),
    submitTimesheet: (payload: {
      staff_id: string;
      date: string;
      hours_worked: number;
      department: string;
      activity_note?: string;
    }) => sendJson<{ success: boolean; data: any }>("/timesheets", "POST", payload),
    create: (payload: { full_name: string; email: string; department: string; role?: string }) =>
      sendJson<{ success: boolean; data: any }>("/staff", "POST", payload),
    dashboard: (userId: string) => fetchRaw<any>(`/staff/${encodeURIComponent(userId)}/dashboard`),
    createTask: (userId: string, payload: Record<string, any>) =>
      sendJson<any>(`/staff/${encodeURIComponent(userId)}/tasks`, "POST", payload),
    updateTask: (userId: string, taskId: string, payload: Record<string, any>) =>
      sendJson<any>(`/staff/${encodeURIComponent(userId)}/tasks/${encodeURIComponent(taskId)}`, "PUT", payload),
  },
  sage: {
    /** @deprecated use importJobs() */
    history: () => fetchJson<any[]>("/sage/history"),
    importJobs: (limit = 20) =>
      fetchJson<{ data: any[] }>(`/imports/jobs?limit=${limit}&domain=sage`),
    supportedTypes: () =>
      Promise.resolve({ file_types: ["customers", "ar", "ap", "gl", "inventory", "staff"] }),
    /** Last-imported timestamps for the daily invoice-refresh tables. */
    freshness: () =>
      fetchJson<{ last_imported: { sales_invoices: string | null; sales_invoice_lines: string | null } }>(
        "/sage/import/freshness",
      ),
  },
  audit: {
    logs: () => fetchJson<any[]>("/audit/logs"),
  },
  workflow: {
     pending: () => fetchJson<any[]>("/workflow/pending"),
     approve: (
      intentId: string,
      approved: boolean,
      approverNote?: string | null,
      approvalReason?: string | null,
      attestationText?: string | null,
    ) =>
      sendJson<any>("/workflow/approve", "POST", {
        intent_id: intentId,
        approved,
        approver_note: approverNote ?? null,
        approval_reason: approvalReason ?? null,
        attestation_text: attestationText ?? null,
      }),
  },
  users: {
    list: async (limit: number = 100) => {
      const payload = await fetchRaw<{ users?: any[] }>(`/users?limit=${limit}`);
      return Array.isArray(payload?.users) ? payload.users : [];
    },
    /** Lightweight user list for task/project assignment dropdowns.
     *  Accessible by admin, management, manager, hr, finance. */
    directory: () => fetchRaw<Array<{ id: string; email: string; display_name?: string; roles: string[] }>>("/users/directory"),
    create: (payload: {
      email: string;
      password: string;
      roles: string[];
      approval_reason: string;
      attestation_text: string;
      /** Optional -- when full_name + department are both given, also creates a linked placeware_staff record. */
      full_name?: string;
      department?: string;
      job_title?: string;
    }) => sendJson<any>("/users", "POST", payload),
    resetPassword: (
      userId: string,
      payload: {
        password: string;
        approval_reason: string;
        attestation_text: string;
      },
    ) => sendJson<any>(`/users/${userId}/password`, "PUT", payload),
    setStatus: (
      userId: string,
      payload: {
        is_active: boolean;
        approval_reason: string;
        attestation_text: string;
      },
    ) => sendJson<any>(`/users/${userId}/status`, "PATCH", payload),
  },
  imports: {
    sage: (payload: FormData, asyncMode: boolean = false) =>
      sendFormData<any>(`/sage/import${asyncMode ? "?async_mode=true" : ""}`, "POST", payload),
    /**
     * Upload a single Sage CSV file for one document type.
     * POST /sage/import/csv  { file_type, file }
     */
    importCsv: (fileType: string, file: File) => {
      const fd = new FormData();
      fd.append("file_type", fileType);
      fd.append("file", file);
      return sendFormData<{
        file_type: string;
        target_table: string;
        batch_id: string;
        rows_parsed: number;
        rows_inserted: number;
        validation_error_count: number;
        validation_errors: string[];
        status: string;
        imported_at: string;
      }>("/sage/import/csv", "POST", fd);
    },
    hr: (payload: FormData, asyncMode: boolean = false) =>
      sendFormData<any>(`/hr/import${asyncMode ? "?async_mode=true" : ""}`, "POST", payload),
    ops: (payload: FormData, asyncMode: boolean = false) =>
      sendFormData<any>(`/ops/import${asyncMode ? "?async_mode=true" : ""}`, "POST", payload),
    crm: (payload: FormData, asyncMode: boolean = false) =>
      sendFormData<any>(`/crm/import${asyncMode ? "?async_mode=true" : ""}`, "POST", payload),
  },
  finance: {
    gl: () => fetchJson<any[]>("/analytics/gl"),
    trend: () => fetchJson<any>("/analytics/trend"),
    transactions: () => fetchJson<any[]>("/analytics/transactions"),
    profitability: () => fetchJson<any>("/analytics/profitability"),
    // Backed by GET /finance/ar/aging ({summary, customers, ...}) — the old
    // /reports/ar_aging route never existed on the backend.
    arAging: () =>
      fetchRaw<any>("/finance/ar/aging").then((r) => r?.summary ?? r),

    // --- Tier-1 Finance Module (from 078 requirements) ---

    /** Unified AR aging: buckets + per-customer rows + triggered alerts */
    arAgingDetail: (bucket?: string) => {
      const q = bucket ? `?bucket=${encodeURIComponent(bucket)}` : "";
      return fetchRaw<any>(`/finance/ar/aging${q}`);
    },
    /** AR aging as audit-stamped PDF download URL (caller fetches with auth header) */
    agingPdfUrl: (bucket?: string) => {
      const q = bucket ? `?bucket=${encodeURIComponent(bucket)}` : "";
      return `/finance/ar/aging/pdf${q}`;
    },

    /** List active alert rules + unacknowledged events */
    listArAlerts: () => fetchRaw<any>("/finance/ar/alerts"),
    /** Create a new threshold alert rule */
    createArAlert: (payload: {
      threshold_amount: number;
      days_overdue_min?: number;
      customer_id?: string;
      description?: string;
      notify_emails?: string[];
    }) => sendJson<any>("/finance/ar/alerts", "POST", payload),
    /** Deactivate an alert rule */
    deleteArAlert: (ruleId: string) => sendDelete<any>(`/finance/ar/alerts/${encodeURIComponent(ruleId)}`),
    /** Acknowledge (dismiss) a triggered alert event */
    ackAlertEvent: (eventId: string) => sendJson<any>(`/finance/ar/alerts/${encodeURIComponent(eventId)}/ack`, "POST", {}),

    /** Invoice-to-payment matching */
    matchInvoices: (payload: { period?: string }) =>
      sendJson<any>("/finance/ar/match", "POST", payload),

    /** P&L from GL journal entries */
    pl: (period?: string) => {
      const q = period ? `?period=${encodeURIComponent(period)}` : "";
      return fetchRaw<any>(`/finance/reports/pl${q}`);
    },
    /** P&L as audit-stamped PDF — returns URL for direct browser download */
    plPdfUrl: (period?: string) => {
      const q = period ? `?period=${encodeURIComponent(period)}` : "";
      return `/finance/reports/pl/pdf${q}`;
    },

    /** Audit export log */
    exportLog: (limit = 50) => fetchRaw<any>(`/finance/exports/log?limit=${limit}`),

    /** Tier-2: 12-week rolling cash flow forecast */
    cashflowForecast: (weeks = 12) => fetchRaw<any>(`/finance/forecast/cashflow?weeks=${weeks}`),

    /** Tier-2: Payroll summary + period variance */
    payrollSummary: (period?: string) => {
      const q = period ? `?period=${encodeURIComponent(period)}` : "";
      return fetchRaw<any>(`/finance/payroll/summary${q}`);
    },

    /** Tier-2: Payroll PDF download URL (caller fetches with auth header) */
    payrollPdfUrl: (period?: string) => {
      const q = period ? `?period=${encodeURIComponent(period)}` : "";
      return `/finance/payroll/pdf${q}`;
    },

    // -----------------------------------------------------------------------
    // Tier 3 — Vendor Payment Approval Workflow
    // -----------------------------------------------------------------------

    /** List vendor payment requests. Optional status filter. */
    listVendorPayments: (status?: string, limit = 50, offset = 0) => {
      const p = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      if (status) p.set("status", status);
      return fetchRaw<any>(`/finance/vendor/payments?${p}`);
    },

    /** Create a new vendor payment request. */
    createVendorPayment: (payload: {
      vendor_id: string;
      vendor_name?: string;
      amount: number;
      currency?: string;
      payment_date?: string;
      reference?: string;
      description?: string;
    }) => sendJson<any>("/finance/vendor/payments", "POST", payload),

    /** Approve a pending vendor payment. */
    approveVendorPayment: (id: string, note?: string) =>
      sendJson<any>(`/finance/vendor/payments/${id}/approve`, "PATCH", { note: note ?? null }),

    /** Reject a vendor payment. */
    rejectVendorPayment: (id: string, note?: string) =>
      sendJson<any>(`/finance/vendor/payments/${id}/reject`, "PATCH", { note: note ?? null }),

    /** Mark an approved vendor payment as paid. */
    markVendorPaymentPaid: (id: string) =>
      sendJson<any>(`/finance/vendor/payments/${id}/mark-paid`, "PATCH", {}),

    /** Cancel (soft-delete) a pending vendor payment. */
    cancelVendorPayment: (id: string) =>
      sendDelete<any>(`/finance/vendor/payments/${id}`),

    // -----------------------------------------------------------------------
    // Customer Receipts & Accounts (AR write-side counterpart to arAging/matchInvoices)
    // -----------------------------------------------------------------------

    /** List AR receipts. Optional filters + a server-computed summary block. */
    listArReceipts: (params?: {
      status?: string;
      customer_id?: string;
      payment_method?: string;
      date_from?: string;
      date_to?: string;
      q?: string;
      limit?: number;
      offset?: number;
    }) => {
      const p = new URLSearchParams();
      if (params?.status) p.set("status", params.status);
      if (params?.customer_id) p.set("customer_id", params.customer_id);
      if (params?.payment_method) p.set("payment_method", params.payment_method);
      if (params?.date_from) p.set("date_from", params.date_from);
      if (params?.date_to) p.set("date_to", params.date_to);
      if (params?.q) p.set("q", params.q);
      p.set("limit", String(params?.limit ?? 50));
      p.set("offset", String(params?.offset ?? 0));
      return fetchRaw<any>(`/finance/ar/receipts?${p}`);
    },

    /** Get one receipt with its invoice allocations. */
    getArReceipt: (id: string) => fetchRaw<any>(`/finance/ar/receipts/${encodeURIComponent(id)}`),

    /** Record and post a new receipt (immutable after posting). */
    createArReceipt: (payload: {
      customer_id: string;
      customer_name?: string;
      amount: number;
      payment_method: string;
      reference?: string;
      collector?: string;
      receipt_date?: string;
      notes?: string;
      applications?: { invoice_id: string; amount_applied: number }[];
    }) => sendJson<any>("/finance/ar/receipts", "POST", payload),

    /** Void a posted receipt (reason required — never edit/delete). */
    voidArReceipt: (id: string, reason: string) =>
      sendJson<any>(`/finance/ar/receipts/${encodeURIComponent(id)}/void`, "PATCH", { reason }),

    /** Customer autocomplete for the Record Receipt flow. */
    searchArReceiptCustomers: (q: string) =>
      fetchRaw<any>(`/finance/ar/receipts/customers/search?q=${encodeURIComponent(q)}`),

    /** A customer's open invoices with true outstanding balance (net of prior receipts). */
    getCustomerOpenInvoices: (customerId: string) =>
      fetchRaw<any>(`/finance/ar/receipts/customers/${encodeURIComponent(customerId)}/open-invoices`),

    // -----------------------------------------------------------------------
    // Tier 3 — Credit Risk Scoring
    // -----------------------------------------------------------------------

    /** Get credit risk scores for all customers. */
    creditRiskScores: () => fetchRaw<any>("/finance/credit/risk"),

    // -----------------------------------------------------------------------
    // Tier 3 — Budget vs. Actual
    // -----------------------------------------------------------------------

    /** List budget targets, optional period/department filters. */
    listBudgetTargets: (period?: string, department?: string) => {
      const p = new URLSearchParams();
      if (period) p.set("period", period);
      if (department) p.set("department", department);
      return fetchRaw<any>(`/finance/budget/targets${p.toString() ? "?" + p : ""}`);
    },

    /** Upsert a budget target. */
    upsertBudgetTarget: (payload: {
      department: string;
      category?: string;
      period: string;
      budgeted_amount: number;
      note?: string;
    }) => sendJson<any>("/finance/budget/targets", "POST", payload),

    /** Delete a budget target by ID. */
    deleteBudgetTarget: (id: string) => sendDelete<any>(`/finance/budget/targets/${id}`),

    /** Get budget vs. actual variance for a period. */
    budgetVariance: (period?: string) => {
      const q = period ? `?period=${encodeURIComponent(period)}` : "";
      return fetchRaw<any>(`/finance/budget/variance${q}`);
    },

    /** Chart of Accounts from Sage 50 snapshot */
    coa: (limit = 500) => fetchRaw<any>(`/finance/coa?limit=${limit}`),

    /** Bank reconciliation snapshot freshness for all tracked accounts */
    reconciliationStatus: () => fetchRaw<any>("/finance/reconciliation/status"),

    /** Log a completed reconciliation (manual entry or post-Sage-import confirmation) */
    logReconciliation: (payload: {
      account_code: string;
      account_name?: string;
      snapshot_type: string;
      reconciled_period?: string;
      gl_balance?: number;
      bank_balance?: number;
      outstanding_count?: number;
      outstanding_total?: number;
      notes?: string;
    }) => fetchRaw<any>("/finance/reconciliation/log", { method: "POST", body: JSON.stringify(payload) }),

    /** Transaction-level GL entries from sage_gl_detail_snapshot */
    glDetail: (params?: { limit?: number; offset?: number; account_code?: string; journal_type?: string }) => {
      const q = new URLSearchParams();
      if (params?.limit)        q.set("limit",        String(params.limit));
      if (params?.offset)       q.set("offset",       String(params.offset));
      if (params?.account_code) q.set("account_code", params.account_code);
      if (params?.journal_type) q.set("journal_type", params.journal_type);
      return fetchRaw<any>(`/analytics/gl-detail?${q.toString()}`);
    },

    /** GL account beginning/ending balances from sage_gl_account_summary_snapshot */
    glSummary: () => fetchRaw<any>("/analytics/gl-summary"),

    /** Cash account register with running balance from sage_cash_register_snapshot */
    cashRegister: (params?: { limit?: number; offset?: number }) => {
      const q = new URLSearchParams();
      if (params?.limit)  q.set("limit",  String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));
      return fetchRaw<any>(`/analytics/cash-register?${q.toString()}`);
    },
  },
  intelligence: {
    executiveSummary: () => fetchRaw<ExecutiveSummaryResponse>("/intelligence/executive_summary"),
    riskSignals: () => fetchRaw<RiskSignalsResponse>("/intelligence/risk_signals"),
    recommendations: () => fetchRaw<RecommendationsResponse>("/intelligence/recommendations"),
    anomalies: () => fetchRaw<AnomaliesResponse>("/intelligence/anomalies"),
  },
  analytics: {
    arTrends: (periods: number = 6) => fetchRaw<ArTrendsResponse>(`/analytics/ar_trends?periods=${periods}`),
  },
  hr: {
    summary: (periods: number = 3) => fetchRaw<HrSummaryResponse>(`/hr/analytics/summary?periods=${periods}`),
  },
  crm: {
    riskScores: () => fetchRaw<any>("/crm/risk_scores"),
    customers: (limit: number = 300) => fetchRaw<any>(`/crm/customers?limit=${limit}`),
    customer360: (id: number) => fetchRaw<any>(`/crm/customers/${id}/360`),
    updateCustomer: (id: number, patch: Record<string, any>) =>
      sendJson<any>(`/crm/customers/${id}`, "PATCH", patch),
    /** Customer search for EntityAutocomplete — id is customers.id (numeric PK). */
    searchCustomers: (q: string, limit?: number) => {
      const qs = new URLSearchParams({ q });
      if (limit) qs.set("limit", String(limit));
      return fetchRaw<any>(`/crm/customers/search?${qs.toString()}`);
    },
    /** Customers ranked by reorder urgency, from real dated AR history. */
    reorderQueue: (limit: number = 50) =>
      fetchRaw<{ data: any[] }>(`/crm/reorder-queue?limit=${limit}`).then((r) => r.data ?? []),
  },
  dataIntel: {
    tables: () => fetchRaw<any>("/data-intel/tables"),
    relationships: () => fetchRaw<any>("/data-intel/relationships"),
    orphans: (relationshipName: string, limit: number = 50) =>
      fetchRaw<any>(`/data-intel/relationships/${encodeURIComponent(relationshipName)}/orphans?limit=${limit}`),
    integrityScore: () => fetchRaw<any>("/data-intel/integrity-score"),
    coverage: () => fetchRaw<any>("/data-intel/coverage"),
    search: (q: string, limitPerEntity: number = 8) =>
      fetchRaw<any>(`/explorer/search?q=${encodeURIComponent(q)}&limit_per_entity=${limitPerEntity}`),
    record: (entityType: string, key: string) =>
      fetchRaw<any>(`/explorer/record/${encodeURIComponent(entityType)}/${encodeURIComponent(key)}`),
  },
  threads: {
    list: () => fetchRaw<any[]>("/threads"),
    listChannels: () => fetchRaw<any[]>("/threads/channels"),
    createChannel: (payload: {
      title: string;
      channel_key: string;
      member_ids?: string[];
      context_type?: string;
      context_id?: string;
    }) => sendJson<any>("/threads/channels", "POST", payload),
    listMessages: (threadId: string, limit: number = 100, offset: number = 0) =>
      fetchRaw<any[]>(`/threads/${encodeURIComponent(threadId)}/messages?limit=${limit}&offset=${offset}`),
    postMessage: (threadId: string, payload: { content: string; metadata?: Record<string, any> }) =>
      sendJson<any>(`/threads/${encodeURIComponent(threadId)}/messages`, "POST", payload),
    addMember: (threadId: string, payload: { user_id: string; role?: string }) =>
      sendJson<any>(`/threads/${encodeURIComponent(threadId)}/members`, "POST", payload),
    removeMember: (threadId: string, userId: string) =>
      sendDelete<any>(`/threads/${encodeURIComponent(threadId)}/members/${encodeURIComponent(userId)}`),
    setPresence: (threadId: string, status: "online" | "away" | "offline") =>
      sendJson<any>(`/threads/${encodeURIComponent(threadId)}/presence`, "POST", { status }),
    getPresence: (threadId: string) => fetchRaw<any[]>(`/threads/${encodeURIComponent(threadId)}/presence`),
    markRead: (threadId: string, last_read_message_id?: string) =>
      sendJson<any>(`/threads/${encodeURIComponent(threadId)}/read`, "POST", { last_read_message_id }),
    unreadSummary: () => fetchRaw<{ items: any[] }>("/threads/unread/summary"),
  },
  leadFinder: {
    sourceProspects: (payload: {
      industry?: string;
      region?: string;
      source?: string;
      limit?: number;
      seed_companies?: Array<Record<string, any>>;
    }) => sendJson<any>("/crm/lead-finder/prospects/source", "POST", payload),
    scoreIngestProspect: (
      prospectId: string,
      payload: {
        expected_value?: number;
        urgency?: "low" | "medium" | "high";
        fit_signals?: Record<string, any>;
        source?: string;
        assigned_rep?: string;
        stage?: string;
      },
    ) => sendJson<any>(`/crm/lead-finder/prospects/${encodeURIComponent(prospectId)}/score-ingest`, "POST", payload),
    assignLead: (payload: {
      lead_id: number;
      rep_user_id: string;
      follow_up_type?: string;
      follow_up_hours?: number;
      notes?: string;
    }) => sendJson<any>("/crm/lead-finder/assign", "POST", payload),
    pipeline: (limit: number = 100) => fetchRaw<any>(`/crm/lead-finder/pipeline?limit=${limit}`),

    /** Google Places-powered location search (mock fallback when no API key) */
    searchByLocation: (payload: {
      location: string;
      business_type?: string;
      radius_m?: number;
      limit?: number;
      industry?: string;
      region?: string;
    }) => sendJson<any>("/crm/lead-finder/search", "POST", payload),

    /** Download all prospects as CSV — returns a fetch Response (caller handles blob) */
    exportProspects: (limit: number = 1000) =>
      fetchRaw<any>(`/crm/lead-finder/export?limit=${limit}`),
  },
  events: {
    trace: (eventId: string) => fetchRaw<any>(`/events/${encodeURIComponent(eventId)}/trace`),
  },
  kg: {
    nodes: (params?: { node_type?: string; search?: string; limit?: number }) => {
      const q = new URLSearchParams();
      if (params?.node_type) q.set("node_type", params.node_type);
      if (params?.search) q.set("search", params.search);
      q.set("limit", String(params?.limit ?? 100));
      return fetchRaw<{ count: number; nodes: any[] }>(`/kg/nodes?${q.toString()}`);
    },
    subgraph: (nodeId: number, params?: { depth?: number; limit?: number }) => {
      const q = new URLSearchParams();
      if (params?.depth != null) q.set("depth", String(params.depth));
      if (params?.limit != null) q.set("limit", String(params.limit));
      const query = q.toString();
      return fetchRaw<any>(`/kg/subgraph/${nodeId}${query ? `?${query}` : ""}`);
    },
    reason: (payload: {
      source_node_id: number;
      target_node_id: number;
      max_depth?: number;
      edge_types?: string[];
      limit?: number;
    }) => sendJson<any>("/kg/reason", "POST", payload),
  },
  leads: {
    // Create a lead via existing backend `/submit_lead`
    create: (payload: Record<string, any>) => sendJson<any>("/submit_lead", "POST", payload),
    // Try to fetch a lead by id (backend route optional)
    get: (leadId: number) => fetchJson<any>(`/leads/${leadId}`),
    // Admin list (backend may expose `/admin/leads` in future)
    // Real response shape is {data, count}, not a bare array — mistyped as
    // any[] previously, which let a genuine Array.isArray(data) bug in
    // LeadsQueue.tsx go unnoticed (always false, queue silently empty).
    list: (limit: number = 100) => fetchJson<{ data: any[]; count: number }>(`/admin/leads?limit=${limit}`),
  },
  orders: {
    // Submit order endpoint (uses `lead_id` when present)
    submit: (payload: Record<string, any>) => sendJson<any>("/submit_order", "POST", payload),
    // Recent orders list (backend route optional)
    recent: (limit: number = 50) => fetchJson<any[]>(`/orders?limit=${limit}`),
  },
  procurement: {
    shipments: (params?: { status?: string; supplier_name?: string; limit?: number }) => {
      const q = new URLSearchParams();
      if (params?.status) q.set("status", params.status);
      if (params?.supplier_name) q.set("supplier_name", params.supplier_name);
      q.set("limit", String(params?.limit ?? 100));
      return fetchRaw<{ data: ProcurementShipment[]; count: number }>(`/procurement/import-agent/shipments?${q.toString()}`);
    },
    analyze: (payload?: { threshold_days?: number; daily_cost?: number }) =>
      sendJson<{ data: ProcurementAnalysis }>("/procurement/import-agent/analyze", "POST", payload ?? {}),
    scorecard: () =>
      fetchRaw<{ data: SupplierScorecardRow[] }>("/procurement/import-agent/scorecard"),
    transition: (shipmentId: string, payload: { next_status: string; reason?: string }) =>
      sendJson<{ data: ProcurementShipment }>(`/procurement/import-agent/shipments/${shipmentId}/status`, "PATCH", payload),
    escalate: (
      shipmentId: string,
      payload?: { reason?: string; notify_regulatory?: boolean; notify_executive_dashboard?: boolean },
    ) =>
      sendJson<{ status: string; shipment_id: string; reason: string }>(
        `/procurement/import-agent/shipments/${shipmentId}/escalate`,
        "POST",
        payload ?? {},
      ),
    purchaseOrders: (params?: { status?: string; vendor_id?: string; limit?: number }) => {
      const q = new URLSearchParams();
      if (params?.status) q.set("status", params.status);
      if (params?.vendor_id) q.set("vendor_id", params.vendor_id);
      if (params?.limit) q.set("limit", String(params.limit));
      return fetchRaw<any[]>(`/procurement/purchase-orders${q.toString() ? `?${q}` : ""}`);
    },
    purchaseOrdersSummary: () => fetchRaw<any>("/procurement/purchase-orders/summary"),
    updatePoStatus: (poId: string, payload: { status: "closed" | "cancelled"; reason?: string }) =>
      sendJson<{ success: boolean; po_id: string; status: string }>(
        `/procurement/purchase-orders/${encodeURIComponent(poId)}/status`,
        "PATCH",
        payload,
      ),
  },
    ops: {
      kpis: () => fetchRaw<OpsKpis>("/ops/kpis"),
      forecastStockTurnover: (window: number = 3, horizon: number = 3) =>
        fetchRaw<OpsForecast>(`/ops/forecast/stock_turnover?window=${window}&horizon=${horizon}`),
    },
  inventory: {
    stock: async (skus?: string[]) => {
      // limit=2000 covers the full catalog — the backend default of 200
      // returns an arbitrary subset and hides most stocked items.
      const data = await fetchRaw("/inventory/items?limit=2000");
      return (data.data ?? data.stock ?? []) as any[];
    },
    latestSnapshot: () => fetchRaw<any>("/inventory/items?limit=2000").then(d => d.data ?? []),
    // simple search endpoint used by staff UI autocomplete
    search: (query: string) =>
      fetchRaw<{ data: any[] }>(`/inventory/search?q=${encodeURIComponent(query)}`).then((r) => r.data ?? []),
    addStock: (payload: {
      sku: string;
      quantity_change: number;
      event_type: string;
      reference?: string;
    }) => sendJson<{ success: boolean; event: any }>("/inventory/event", "POST", payload),
    workspaceCards: (params?: { company_id?: string; search?: string }) => {
      const q = new URLSearchParams();
      if (params?.company_id) q.set("company_id", params.company_id);
      if (params?.search) q.set("search", params.search);
      return fetchRaw<{ data: any[]; total: number }>(`/inventory/workspace/cards${q.toString() ? `?${q}` : ""}`).then((r) => r.data ?? []);
    },
    analytics: (companyId?: string) => {
      const q = companyId ? `?company_id=${encodeURIComponent(companyId)}` : "";
      return fetchRaw<{ data: any }>(`/inventory/workspace/analytics${q}`).then((r) => r.data);
    },
    familyDetail: (family: string, companyId?: string) => {
      const q = new URLSearchParams({ family });
      if (companyId) q.set("company_id", companyId);
      return fetchRaw<{ data: any }>(`/inventory/workspace/families/detail?${q.toString()}`).then((r) => r.data);
    },
    topSellers: (limit: number = 10, companyId?: string) => {
      const q = new URLSearchParams({ limit: String(limit) });
      if (companyId) q.set("company_id", companyId);
      return fetchRaw<{ data: any[] }>(`/inventory/workspace/top-sellers?${q.toString()}`).then((r) => r.data ?? []);
    },
    pendingReordersCount: () =>
      fetchRaw<{ count: number }>("/inventory/workspace/pending-reorders-count").then((r) => r.count ?? 0),
  },
  replenishment: {
    create: (payload: { sku: string; product_id?: string; requested_qty: number }) =>
      sendJson<{ id: string; sku: string; requested_qty: number; status: string }>("/replenishment/create", "POST", payload),

    list: (params?: { status?: string; limit?: number }) => {
      const q = new URLSearchParams();
      if (params?.status) q.set("status", params.status);
      q.set("limit", String(params?.limit ?? 100));
      return fetchRaw<{ data: any[]; total: number }>(`/replenishment?${q.toString()}`).then(
        (r: any) => r?.data ?? [],
      );
    },

    summary: () =>
      fetchRaw<{ counts: Record<string, number>; total: number }>("/replenishment/summary"),

    approve: (requestId: string) =>
      sendJson<any>("/replenishment/approve", "POST", { request_id: requestId }),

    createPo: (requestId: string, poId: string) =>
      sendJson<any>("/replenishment/create_po", "POST", { request_id: requestId, po_id: poId }),

    /** Marks delivered and adds the units back into stock. */
    received: (requestId: string, receivedQty?: number) =>
      sendJson<{ ok: boolean; sku: string; stock_added: number; already_received?: boolean }>(
        "/replenishment/received",
        "POST",
        { request_id: requestId, received_qty: receivedQty },
      ),

    cancel: (requestId: string, reason?: string) =>
      sendJson<{ ok: boolean; sku: string; status: string; already_cancelled?: boolean }>(
        "/replenishment/cancel",
        "POST",
        { request_id: requestId, reason },
      ),
  },
  projects: {
    readiness: () => fetchRaw<{ ready: boolean; reason?: string; checks?: Record<string, boolean> }>("/controls/readiness"),
    list: (limit: number = 50, status?: string) => {
      const q = new URLSearchParams({ limit: String(limit) });
      if (status) q.set("status", status);
      return fetchRaw<{ data: any[] }>(`/controls/projects?${q.toString()}`).then(r => r.data);
    },
    create: (payload: {
      name: string;
      description?: string;
      status?: string;
      activity_type?: string;
      supplier_name?: string;
      assigned_staff_id?: string;
      workflow_stage?: string;
      po_reference?: string;
      temperature_profile?: string;
      nafdac_sampling_status?: string;
      quality_check_status?: string;
      quality_notes?: string;
    }) =>
      sendJson<any>("/controls/projects", "POST", payload).then((r) => r?.data ?? r),
    transitionStage: (
      projectId: string,
      payload: {
        workflow_stage: string;
        reason_code?: string;
        nafdac_sampling_status?: string;
        quality_check_status?: string;
        quality_notes?: string;
      },
    ) =>
      sendJson<any>(`/controls/projects/${encodeURIComponent(projectId)}/stage`, "POST", payload)
        .then((r) => r?.data ?? r),
  },
  suppliers: {
    list: () => fetchRaw<any[]>("/suppliers"),
    create: (payload: Record<string, any>) => sendJson<any>("/suppliers", "POST", payload),
    metrics: (supplierName: string) =>
      fetchRaw<any>(`/suppliers/${encodeURIComponent(supplierName)}/metrics`),
  },
  calendar: {
    list: (month?: string) => {
      const q = month ? `?month=${month}` : "";
      return fetchRaw<{ events: any[] }>(`/calendar/events${q}`);
    },
    create: (payload: {
      title: string;
      description?: string;
      event_type?: string;
      start_time: string;
      end_time?: string;
      location?: string;
      all_day?: boolean;
      metadata?: Record<string, any>;
    }) => sendJson<{ data: any }>("/calendar/events", "POST", payload),
    update: (eventId: string, payload: Record<string, any>) =>
      sendJson<{ data: any }>(`/calendar/events/${eventId}`, "PATCH", payload),
    delete: (eventId: string) =>
      sendDelete<{ status: string }>(`/calendar/events/${eventId}`),
    /** Pharma logistics: returns batches expiring within window_days (default 30). */
    logisticsAlerts: (windowDays = 30) =>
      fetchRaw<{
        alerts: Array<{
          event_id: string;
          title: string;
          event_type: string;
          batch_id?: string;
          product_name?: string;
          expiry_date: string;
          days_until_expiry: number;
          is_cold_chain: boolean;
          is_nafdac_regulated: boolean;
        }>;
        total: number;
        window_days: number;
      }>(`/calendar/logistics/alerts?window_days=${windowDays}`),
  },
  tasks: {
    list: (status?: string) => {
      const q = status ? `?status=${status}` : "";
      return fetchRaw<{ tasks: any[] }>(`/tasks${q}`);
    },
    create: (payload: {
      title: string;
      description?: string;
      priority?: string;
      due_date?: string;
      assigned_to?: string;
    }) => sendJson<{ data: any }>("/tasks", "POST", payload),
    update: (taskId: string, payload: Record<string, any>) =>
      sendJson<{ data: any }>(`/tasks/${taskId}`, "PATCH", payload),
    delete: (taskId: string) =>
      sendDelete<{ status: string }>(`/tasks/${taskId}`),
  },
  agents: {
    list: () => fetchRaw<{ agents: any[]; count: number }>("/agents/list"),
    execute: (question: string, mode?: string) =>
      sendJson<{
        agents_executed: string[];
        merged: any;
        insights: any[];
        errors?: any[];
      }>("/agents/execute", "POST", { question, mode }),
    run: (agentName: string, context?: Record<string, any>) =>
      sendJson<{ agent: string; insight: any; success: boolean }>(
        `/agents/run/${agentName}`,
        "POST",
        context || {},
      ),
    cached: (agentName: string) =>
      fetchRaw<{ key: string; value: any }>(`/cache/get/${agentName}`),
    cacheTtl: (agentName: string) =>
      fetchRaw<{ key: string; ttl_seconds: number | null }>(`/cache/ttl/${agentName}`),
  },
  compliance: {
    status: () => fetchRaw<any>("/compliance/status"),
    audits: (status?: string) => {
      const q = status ? `?status=${status}` : "";
      return fetchRaw<{ audits: any[] }>(`/compliance/audits${q}`);
    },
    startAudit: (auditId: string) =>
      sendJson<any>(`/compliance/audits/${auditId}/start`, "POST", {}),
    completeAudit: (auditId: string, payload: { findings?: string[]; recommendations?: string[] }) =>
      sendJson<any>(`/compliance/audits/${auditId}/complete`, "POST", payload),
    generateAuditReport: (auditId: string, payload: {
      auditor_name?: string;
      summary?: string;
      findings?: string[];
      observations?: string[];
      recommendations?: string[];
      score?: number;
    }) => sendJson<any>(`/compliance/audits/${auditId}/generate-report`, "POST", payload),
    deviations: (status?: string) => {
      const q = status ? `?status=${status}` : "";
      return fetchRaw<{ deviations: any[] }>(`/compliance/deviations${q}`);
    },
    createDeviation: (payload: {
      title: string;
      severity: string;
      category: string;
      description: string;
      detected_by: string;
      product_batch?: string;
      sop_reference?: string;
    }) => sendJson<any>("/compliance/deviations", "POST", payload),
    updateDeviation: (devId: string, payload: Record<string, any>) =>
      sendJson<any>(`/compliance/deviations/${devId}`, "PUT", payload),
    generateDeviationReport: (devId: string) =>
      sendJson<any>(`/compliance/deviations/${devId}/generate-report`, "POST", {}),
    equipment: () => fetchRaw<{ data: any[] }>("/compliance/equipment"),
    // Real query param is `status` (list_maintenance's only filter) — the
    // previous `?filter=overdue|upcoming` param doesn't exist on this
    // endpoint at all, so selecting either pill silently did nothing.
    maintenance: (status?: string) => {
      const q = status ? `?status=${status}` : "";
      return fetchRaw<{ maintenance: any[] }>(`/compliance/maintenance${q}`);
    },
    completeMaintenance: (maintenanceId: string, payload: {
      performed_by: string;
      completion_notes?: string;
      next_maintenance_date?: string;
    }) => sendJson<any>(`/compliance/maintenance/${maintenanceId}/complete`, "POST", payload),
    generateMaintenanceCertificate: (maintenanceId: string, payload: {
      performed_by: string;
      maintenance_type?: string;
      completion_notes?: string;
      next_maintenance_date?: string;
    }) => sendJson<any>(`/compliance/maintenance/${maintenanceId}/generate-certificate`, "POST", payload),
    recalls: (status?: string) => {
      const q = status ? `?status=${status}` : "";
      return fetchRaw<{ recalls: any[] }>(`/compliance/recalls${q}`);
    },
    initiateRecall: (payload: {
      product_name: string;
      batch_number: string;
      recall_reason: string;
      severity: string;
      nafdac_notified?: boolean;
    }) => sendJson<any>("/compliance/recalls", "POST", payload),
    updateRecall: (recallId: string, payload: Record<string, any>) =>
      sendJson<any>(`/compliance/recalls/${recallId}`, "PUT", payload),
    generateRecallDocuments: (recallId: string) =>
      sendJson<any>(`/compliance/recalls/${recallId}/generate-documents`, "POST", {}),
    sopList: (category?: string) => {
      const q = category ? `?category=${category}` : "";
      return fetchRaw<{ data: any[] }>(`/compliance/sop${q}`);
    },
    ingestSopDocx: (formData: FormData) =>
      sendFormData<any>("/compliance/sop/ingest-docx", "POST", formData),
    documentArchive: (docType?: string) => {
      const q = docType ? `?doc_type=${docType}` : "";
      return fetchRaw<{ data: any[] }>(`/documents/archive${q}`);
    },
  },
  knowledge: {
    getDocuments: (docType?: string, department?: string, page = 1) => {
      const params = new URLSearchParams();
      if (docType) params.set("doc_type", docType);
      if (department) params.set("department", department);
      params.set("page", String(page));
      return fetchRaw<{ data: any[]; page: number; page_size: number }>(
        `/api/documents?${params.toString()}`
      );
    },
    getDocument: (id: string) => fetchRaw<any>(`/api/documents/${encodeURIComponent(id)}`),
    ingestFile: (formData: FormData) =>
      sendFormData<{ status: string; document_id: string; chunks: number; filename: string; message: string }>(
        "/knowledge/ingest",
        "POST",
        formData
      ),
    search: (q: string, department?: string, docType?: string) => {
      const params = new URLSearchParams({ q });
      if (department) params.set("department", department);
      if (docType) params.set("doc_type", docType);
      return fetchRaw<any>(`/knowledge/search?${params.toString()}`);
    },
    getGaps: (status?: string, page = 1) => {
      const params = new URLSearchParams({ page: String(page) });
      if (status) params.set("status", status);
      return fetchRaw<{ data: any[]; page: number }>(`/knowledge/gaps?${params.toString()}`);
    },
    resolveGap: (gapId: number) =>
      fetchRaw<any>(`/knowledge/gaps/${gapId}/resolve`),
  },
  salesCrm: {
    pipeline: (limit: number = 200) =>
      fetchRaw<any>(`/crm/sales/pipeline?limit=${limit}`),

    moveStage: (leadId: number, stage: string, notes?: string) =>
      sendJson<any>(`/crm/sales/leads/${leadId}/stage`, "PATCH", { stage, notes }),

    createFollowUp: (payload: {
      lead_id?: number;
      customer_id?: number;
      assigned_rep?: string;
      reminder_type?: string;
      due_at: string;
      note?: string;
    }) => sendJson<any>("/crm/sales/followups", "POST", payload),

    dueReminders: (hours: number = 24, repId?: string) => {
      const q = new URLSearchParams({ hours: String(hours) });
      if (repId) q.set("rep_id", repId);
      return fetchRaw<any>(`/crm/sales/followups/due?${q.toString()}`);
    },

    updateReminder: (reminderId: string, status: string, note?: string) =>
      sendJson<any>(`/crm/sales/followups/${encodeURIComponent(reminderId)}`, "PATCH", {
        status,
        note,
      }),

    queueBulkMessage: (payload: {
      channel: "sms" | "email";
      message_text: string;
      subject?: string;
      // Explicit picker selection, or a segment filter like {facility_type}
      recipient_filter?: {
        customer_ids?: (string | number)[];
        supplier_ids?: (string | number)[];
        facility_type?: string;
      };
    }) => sendJson<any>("/crm/sales/bulk-message", "POST", payload),

    listBulkMessages: (limit: number = 20) =>
      fetchRaw<any[]>(`/crm/sales/bulk-message?limit=${limit}`),

    weeklyReport: (weekStart?: string) => {
      const q = weekStart ? `?week_start=${weekStart}` : "";
      return fetchRaw<any>(`/crm/sales/weekly-report${q}`);
    },

    query: (query: string) =>
      sendJson<{ query: string; answer: string }>("/crm/sales/query", "POST", { query }),

    leaderboard: (days: number = 30) =>
      fetchRaw<any>(`/crm/sales/leaderboard?days=${days}`),

    dispatchBulkMessage: (jobId: string) =>
      sendJson<any>(`/crm/sales/bulk-message/${encodeURIComponent(jobId)}/dispatch`, "POST", {}),

    getLeadBrief: (leadId: number) =>
      fetchRaw<any>(`/crm/sales/leads/${leadId}/brief`),

    getProductAvailability: (leadId: number) =>
      fetchRaw<any>(`/crm/sales/leads/${leadId}/product-availability`),

    getPurchaseHistory: (leadId: number, limit = 20) =>
      fetchRaw<any>(`/crm/sales/leads/${leadId}/purchase-history?limit=${limit}`),

    weeklyReportPdfUrl: (weekStart?: string) => {
      const q = weekStart ? `?week_start=${weekStart}` : "";
      return apiUrl(`/crm/sales/weekly-report/pdf${q}`);
    },

    // Gap-fill: Lead CRUD
    createLead: (payload: {
      company_name: string;
      contact_person?: string;
      contact_phone?: string;
      product_interest?: string[];
      stage?: string;
      expected_value?: number;
      payment_terms?: string;
      notes?: string;
      next_action?: string;
      assigned_rep?: string;
    }) => sendJson<any>("/crm/sales/leads", "POST", payload),

    updateLead: (leadId: number, payload: Record<string, any>) =>
      sendJson<any>(`/crm/sales/leads/${leadId}`, "PATCH", payload),

    // Gap-fill: Interaction log
    logInteraction: (leadId: number, payload: {
      interaction_type: string;
      summary: string;
      outcome?: string;
      next_step?: string;
      occurred_at?: string;
    }) => sendJson<any>(`/crm/sales/leads/${leadId}/interactions`, "POST", payload),

    listInteractions: (leadId: number, limit = 50) =>
      fetchRaw<any>(`/crm/sales/leads/${leadId}/interactions?limit=${limit}`),

    // Gap-fill: Sales targets
    createTarget: (payload: {
      rep_id?: string;
      period: string;
      period_type: string;
      target_value: number;
      target_deals?: number;
    }) => sendJson<any>("/crm/sales/targets", "POST", payload),

    listTargets: (period?: string, repId?: string) => {
      const q = new URLSearchParams();
      if (period) q.set("period", period);
      if (repId) q.set("rep_id", repId);
      return fetchRaw<any>(`/crm/sales/targets${q.toString() ? `?${q.toString()}` : ""}`);
    },

    targetsVsActuals: (period: string) =>
      fetchRaw<any>(`/crm/sales/targets/vs-actuals?period=${encodeURIComponent(period)}`),
  },

  frontdesk: {
    registerWalkIn: (payload: {
      customer_name: string;
      company_name?: string;
      contact_phone?: string;
      email?: string;
      has_appointment?: boolean;
      purpose: string;
      products_requested?: string[];
      notes?: string;
    }) => sendJson<any>("/frontdesk/walk-ins", "POST", payload),

    listWalkIns: (date?: string, status?: string) => {
      const q = new URLSearchParams();
      if (date) q.set("date", date);
      if (status) q.set("status", status);
      return fetchRaw<any>(`/frontdesk/walk-ins${q.toString() ? `?${q.toString()}` : ""}`);
    },

    getWalkIn: (id: string) => fetchRaw<any>(`/frontdesk/walk-ins/${id}`),

    createInvoice: (walkInId: string, payload: {
      items: { product: string; quantity: number; unit_price: number; batch_number?: string; manufacture_date?: string; expiry_date?: string }[];
      payment_method?: string;
      notes?: string;
      billing_address?: string;
      shipping_address?: string;
      customer_po?: string;
      payment_terms?: string;
      shipping_method?: string;
      tax_amount?: number;
    }) => sendJson<any>(`/frontdesk/walk-ins/${walkInId}/invoice`, "POST", payload),

    submitQc: (invoiceId: string, payload: {
      passed: boolean;
      inspector_name: string;
      notes?: string;
      batch_numbers?: string[];
    }) => sendJson<any>(`/frontdesk/invoices/${invoiceId}/qc`, "POST", payload),

    financeApproval: (invoiceId: string, payload: {
      approved: boolean;
      approver_name: string;
      reason?: string;
    }) => sendJson<any>(`/frontdesk/invoices/${invoiceId}/finance`, "POST", payload),

    notifyExecutive: (invoiceId: string, message?: string) =>
      sendJson<any>(`/frontdesk/invoices/${invoiceId}/notify`, "POST", { message }),

    /** Hand a finance-approved invoice off to Logistics (creates a `deliveries` row). */
    sendForDelivery: (invoiceId: string) =>
      sendJson<any>(`/frontdesk/invoices/${invoiceId}/send-for-delivery`, "POST", {}),

    // --- New endpoints ---

    searchClients: (q: string, limit?: number) => {
      const params = new URLSearchParams({ q });
      if (limit) params.set("limit", String(limit));
      return fetchRaw<any>(`/frontdesk/clients/search?${params.toString()}`);
    },

    clientHistory: (walkInId: string) =>
      fetchRaw<any>(`/frontdesk/clients/${walkInId}/history`),

    listInvoices: (params?: {
      status?: string;
      date_from?: string;
      date_to?: string;
      q?: string;
      limit?: number;
    }) => {
      const qs = new URLSearchParams();
      if (params?.status)    qs.set("status", params.status);
      if (params?.date_from) qs.set("date_from", params.date_from);
      if (params?.date_to)   qs.set("date_to", params.date_to);
      if (params?.q)         qs.set("q", params.q);
      if (params?.limit)     qs.set("limit", String(params.limit));
      return fetchRaw<any>(`/frontdesk/invoices${qs.toString() ? `?${qs.toString()}` : ""}`);
    },

    getInvoice: (invoiceId: string) =>
      fetchRaw<any>(`/frontdesk/invoices/${invoiceId}`),

    /** Full lifecycle trail (create -> QC -> finance -> dispatch -> completed), oldest first. */
    invoiceHistory: (invoiceId: string) =>
      fetchRaw<any>(`/frontdesk/invoices/${invoiceId}/history`),

    stockCheck: (products: string[]) => {
      const qs = new URLSearchParams({ products: products.join(",") });
      return fetchRaw<any>(`/frontdesk/stock-check?${qs.toString()}`);
    },

    dailyReport: (date?: string) => {
      const qs = new URLSearchParams();
      if (date) qs.set("date", date);
      return fetchRaw<any>(`/frontdesk/reports/daily${qs.toString() ? `?${qs.toString()}` : ""}`);
    },

    cancelWalkIn: (id: string, reason?: string) =>
      sendJson<any>(`/frontdesk/walk-ins/${id}/cancel`, "POST", reason ? { reason } : {}),

    /** Centralized Customer Workspace — raise an invoice request for a known CRM customer in one call. */
    quickRequest: (customerId: number, payload: {
      items: { product: string; quantity: number; unit_price: number; batch_number?: string; manufacture_date?: string; expiry_date?: string }[];
      payment_method?: string;
      notes?: string;
      purpose?: string;
      billing_address?: string;
      shipping_address?: string;
      customer_po?: string;
      payment_terms?: string;
      shipping_method?: string;
      tax_amount?: number;
    }) => sendJson<any>(`/frontdesk/customers/${customerId}/quick-request`, "POST", payload),
  },

  // -------------------------------------------------------------------------
  // Quality Control
  // -------------------------------------------------------------------------
  qc: {
    /** Unified KPI dashboard: expiring count, open deviations, temp alerts, NAFDAC pending, recalls */
    dashboard: () =>
      fetchRaw<any>("/qc/dashboard"),

    /** Expiring stock grouped into expired/critical(≤30d)/high(≤60d)/medium(≤90d) buckets */
    expiryAlerts: (days?: number) => {
      const qs = new URLSearchParams();
      if (days) qs.set("days", String(days));
      return fetchRaw<any>(`/qc/expiry-alerts${qs.toString() ? `?${qs}` : ""}`);
    },

    // --- Temperature logs ---
    logTemperature: (payload: {
      location: string;
      reading_celsius: number;
      min_threshold?: number;
      max_threshold?: number;
      log_session?: "morning" | "midday" | "evening" | "ad_hoc";
      logged_by: string;
      logged_at?: string;
      equipment_id?: string;
      notes?: string;
    }) => sendJson<any>("/qc/temperature-logs", "POST", payload),

    listTemperatureLogs: (params?: {
      location?: string;
      date_from?: string;
      date_to?: string;
      deviations_only?: boolean;
      limit?: number;
    }) => {
      const qs = new URLSearchParams();
      if (params?.location)        qs.set("location", params.location);
      if (params?.date_from)       qs.set("date_from", params.date_from);
      if (params?.date_to)         qs.set("date_to", params.date_to);
      if (params?.deviations_only) qs.set("deviations_only", "true");
      if (params?.limit)           qs.set("limit", String(params.limit));
      return fetchRaw<any>(`/qc/temperature-logs${qs.toString() ? `?${qs}` : ""}`);
    },

    activeDeviations: () =>
      fetchRaw<any>("/qc/temperature-logs/deviations"),

    escalateDeviation: (logId: string, payload: { escalated_to: string; escalation_notes?: string }) =>
      sendJson<any>(`/qc/temperature-logs/${logId}/escalate`, "POST", payload),

    // --- CAPA Deviation reports ---
    createDeviation: (payload: {
      classification?: "minor" | "major" | "critical";
      trigger_type: string;
      trigger_ref?: string;
      observation: string;
      impact_assessment?: string;
      recommendations?: string;
      responsible_department: string;
      responsible_person?: string;
      capa_actions?: object[];
    }) => sendJson<any>("/qc/deviations", "POST", payload),

    listDeviations: (params?: {
      status?: string;
      classification?: string;
      department?: string;
      limit?: number;
    }) => {
      const qs = new URLSearchParams();
      if (params?.status)         qs.set("status", params.status);
      if (params?.classification) qs.set("classification", params.classification);
      if (params?.department)     qs.set("department", params.department);
      if (params?.limit)          qs.set("limit", String(params.limit));
      return fetchRaw<any>(`/qc/deviations${qs.toString() ? `?${qs}` : ""}`);
    },

    updateDeviation: (id: string, payload: {
      status?: string;
      impact_assessment?: string;
      recommendations?: string;
      responsible_person?: string;
      capa_actions?: object[];
    }) => sendJson<any>(`/qc/deviations/${id}`, "PATCH", payload),

    closeDeviation: (id: string, payload: { resolution: string; capa_actions?: object[] }) =>
      sendJson<any>(`/qc/deviations/${id}/close`, "POST", payload),

    // --- NAFDAC batch registry ---
    registerBatch: (payload: {
      batch_number: string;
      product_name: string;
      nafdac_reg_number?: string;
      supplier?: string;
      valid_from?: string;
      valid_to?: string;
      certificate_ref?: string;
      notes?: string;
    }) => sendJson<any>("/qc/nafdac/batches", "POST", payload),

    listBatches: (params?: {
      status?: string;
      product?: string;
      blocked?: boolean;
      limit?: number;
    }) => {
      const qs = new URLSearchParams();
      if (params?.status)            qs.set("status", params.status);
      if (params?.product)           qs.set("product", params.product);
      if (params?.blocked !== undefined) qs.set("blocked", String(params.blocked));
      if (params?.limit)             qs.set("limit", String(params.limit));
      return fetchRaw<any>(`/qc/nafdac/batches${qs.toString() ? `?${qs}` : ""}`);
    },

    approveBatch: (id: string, payload?: {
      valid_from?: string;
      valid_to?: string;
      certificate_ref?: string;
      nafdac_reg_number?: string;
      notes?: string;
    }) => sendJson<any>(`/qc/nafdac/batches/${id}/approve`, "PATCH", payload ?? {}),

    rejectBatch: (id: string, payload: { rejection_reason: string; notes?: string }) =>
      sendJson<any>(`/qc/nafdac/batches/${id}/reject`, "PATCH", payload),

    // --- Product recalls ---
    initiateRecall: (payload: {
      batch_number: string;
      product_name: string;
      recall_reason: string;
      scope?: "voluntary" | "mandatory";
      regulatory_authority?: string;
      distribution_data?: object[];
    }) => sendJson<any>("/qc/recalls", "POST", payload),

    listRecalls: (params?: { status?: string; product?: string; limit?: number }) => {
      const qs = new URLSearchParams();
      if (params?.status)  qs.set("status", params.status);
      if (params?.product) qs.set("product", params.product);
      if (params?.limit)   qs.set("limit", String(params.limit));
      return fetchRaw<any>(`/qc/recalls${qs.toString() ? `?${qs}` : ""}`);
    },

    updateRecallStatus: (id: string, payload: {
      status: "initiated" | "in_progress" | "completed" | "closed";
      distribution_data?: object[];
      notes?: string;
    }) => sendJson<any>(`/qc/recalls/${id}/status`, "PATCH", payload),
  },

  logistics: {
    createRider: (payload: { name: string; phone?: string; vehicle?: string }) =>
      sendJson<any>("/logistics/riders", "POST", payload),

    /** All riders (any status) — unlike livePositions() (active + GPS-having only). */
    listRiders: (active?: boolean) => {
      const qs = new URLSearchParams();
      if (active !== undefined) qs.set("active", String(active));
      return fetchRaw<any>(`/logistics/riders${qs.toString() ? `?${qs.toString()}` : ""}`);
    },

    // Real Delivery schema (backend/src/schemas/logistics.py, extra="forbid"):
    // {reference?, customer_id?, address?, quantity?, status?} — the previous
    // {destination, recipient_name, recipient_phone, dest_lat, dest_lng} shape
    // here didn't match any of those fields, so every create 422'd. destination/
    // recipient fields now nest into `address` (matching the shape Frontdesk's
    // send-for-delivery handoff already writes).
    createDelivery: (payload: {
      reference?: string;
      customer_id?: string;
      address?: { destination?: string; recipient_name?: string; recipient_phone?: string; [key: string]: any };
      quantity?: number;
      status?: string;
    }) => sendJson<any>("/logistics/deliveries", "POST", payload),

    /** All deliveries (any status), enriched with rider info — unlike
     * activeDeliveries() (assigned/in_transit only). */
    listDeliveries: (params?: { status?: string; limit?: number; offset?: number }) => {
      const qs = new URLSearchParams();
      if (params?.status) qs.set("status", params.status);
      if (params?.limit) qs.set("limit", String(params.limit));
      if (params?.offset) qs.set("offset", String(params.offset));
      return fetchRaw<any>(`/logistics/deliveries${qs.toString() ? `?${qs.toString()}` : ""}`);
    },

    assignRoutes: () => sendJson<any>("/logistics/assign", "POST", {}),

    /** Manually assign one specific rider to one specific delivery. */
    assignDelivery: (
      deliveryId: string,
      riderId: string,
      dest?: { dest_lat: number; dest_lng: number },
    ) =>
      sendJson<any>(`/logistics/deliveries/${encodeURIComponent(deliveryId)}/assign`, "POST", {
        rider_id: riderId,
        ...(dest ?? {}),
      }),

    getRiderRoute: (riderId: string) =>
      fetchRaw<any>(`/logistics/riders/${encodeURIComponent(riderId)}/route`),

    updateDeliveryStatus: (deliveryId: string, status: string) =>
      sendJson<any>(`/logistics/deliveries/${encodeURIComponent(deliveryId)}/status`, "POST", { status }),

    computeRoute: (payload: { origin: string; destinations: string[]; optimize?: boolean }) =>
      sendJson<any>("/logistics/compute-route", "POST", payload),

    // ---- Live tracking (Migration 084) ----

    /** Start a delivery → mints tracking_token, returns PWA URL */
    startDelivery: (deliveryId: string) =>
      sendJson<any>(`/logistics/deliveries/${encodeURIComponent(deliveryId)}/start`, "POST", {}),

    /** Rider PWA: resolve delivery info by token (no JWT) */
    getDeliveryByToken: (token: string) =>
      fetchRaw<any>(`/logistics/track/${encodeURIComponent(token)}`),

    /** Latest rider positions snapshot (dashboard poll fallback) */
    livePositions: () =>
      fetchRaw<any>("/logistics/live-positions"),

    /** All in-transit/assigned deliveries with rider location */
    activeDeliveries: () =>
      fetchRaw<any>("/logistics/active-deliveries"),

    /** GPS ping history / route replay for a delivery */
    deliveryPings: (deliveryId: string) =>
      fetchRaw<any>(`/logistics/deliveries/${encodeURIComponent(deliveryId)}/pings`),
  },

  // ── Report Intelligence API ────────────────────────────────────────────────
  reports: {
    /** Run the ReportGenerationAgent for any report type. Returns full narrative. */
    generate: (payload: { report_type?: string; intent_text?: string }) =>
      sendJson<{
        report_type: string;
        section_title: string;
        full_report: string;
        findings: string[];
        recommendations: string[];
        quality_score: number;
        rag_hits: number;
        data_rows: number;
        status: string;
      }>("/reports/generate", "POST", payload),

    /** URL for downloading a report as a Word document (.docx). Requires auth header. */
    generateDocxUrl: () => "/reports/generate/docx",

    /** Run the agent and download the result as a .docx — returns URL for fetch-with-auth. */
    generateDocx: (payload: { report_type?: string; intent_text?: string }) =>
      sendJson<Blob>("/reports/generate/docx", "POST", payload),

    /** List recently stored reports (optionally filtered by type). */
    history: (report_type?: string, limit = 10) => {
      const p = new URLSearchParams({ limit: String(limit) });
      if (report_type) p.set("report_type", report_type);
      return fetchRaw<{ reports: any[] }>(`/reports/history?${p}`);
    },

    /** Get full narrative of a single stored report by ID. */
    detail: (reportId: string) =>
      fetchRaw<any>(`/reports/history/${encodeURIComponent(reportId)}`),

    /** Download a stored report as .docx by ID — returns the fetch URL (caller adds auth). */
    detailDocxUrl: (reportId: string) =>
      `/reports/history/${encodeURIComponent(reportId)}/docx`,

    // ── Wizard / session endpoints ──────────────────────────────────────────

    /** List all supported report types with their scope fields. */
    types: () => fetchRaw<{
      report_types: Array<{
        type: string;
        name: string;
        required_scope_fields: Array<{ key: string; label: string; type: string; required: boolean; options?: string[] }>;
        is_invoice: boolean;
      }>;
    }>("/reports/types"),

    /**
     * Step 1 — create a session and get required scope fields.
     * Returns session_id, status, scope_fields_required.
     */
    createSession: (report_type: string) =>
      sendJson<{
        session_id: string;
        report_type: string;
        status: string;
        client_facing_name: string;
        sections: string[];
        scope_fields_required: any[];
        all_scope_fields: any[];
      }>("/reports/session", "POST", { report_type }),

    /**
     * Step 2 — save scope parameters and evidence notes.
     * Advances session to 'scoping'.
     */
    updateScope: (sessionId: string, scope: Record<string, any>, evidence_notes?: string) =>
      sendJson<{ session_id: string; status: string; scope: Record<string, any> }>(
        `/reports/session/${encodeURIComponent(sessionId)}/scope`,
        "PUT",
        { scope, evidence_notes },
      ),

    /** Get current session state. */
    getSession: (sessionId: string) =>
      fetchRaw<any>(`/reports/session/${encodeURIComponent(sessionId)}`),

    /**
     * Step 3 — trigger generation from a scoped session.
     * Returns a full ReportResponse including section_results.
     */
    generateFromSession: (sessionId: string) =>
      sendJson<{
        report_type: string;
        section_title: string;
        full_report: string;
        findings: string[];
        recommendations: string[];
        quality_score: number;
        rag_hits: number;
        data_rows: number;
        status: string;
        session_id?: string;
        report_memory_id?: string;
        sections?: Array<{
          id: string;
          title: string;
          content: string;
          order: number;
          status: string;
          confidence_score: number;
        }>;
        traceability?: {
          template_version: string;
          rag_hits: number;
          data_rows: number;
          past_reports_used: number;
          section_count: number;
        };
        template_version?: string;
      }>(
        `/reports/session/${encodeURIComponent(sessionId)}/generate`,
        "POST",
        {},
      ),

    /** Step 3 (invoice) — generate a branded invoice .docx from a session. */
    generateInvoiceDocx: async (sessionId: string): Promise<{ url: string; filename: string }> => {
      const token = authClient.getAccessToken();
      const res = await fetch(apiUrl(`/reports/session/${encodeURIComponent(sessionId)}/generate/invoice`), {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new ApiError(`Invoice generation failed`, res.status, classifyApiErrorKind(res.status));
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const disposition = res.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="([^"]+)"/);
      return { url, filename: match?.[1] ?? "invoice.docx" };
    },

    /**
     * Approve a completed report (admin / management only).
     * Returns { report_id, status: "approved", approved_by }.
     */
    approve: (reportId: string) =>
      sendJson<{ report_id: string; status: string; approved_by: string }>(
        `/reports/${encodeURIComponent(reportId)}/approve`,
        "POST",
        {},
      ),

    /**
     * Download a stored report as a branded .docx (DRAFT or FINAL based on approval).
     * Returns a blob object URL for <a download>.
     */
    downloadDocx: async (reportId: string): Promise<{ url: string; filename: string }> => {
      const token = authClient.getAccessToken();
      const res = await fetch(apiUrl(`/reports/history/${encodeURIComponent(reportId)}/docx`), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new ApiError(`DOCX download failed`, res.status, classifyApiErrorKind(res.status));
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const disposition = res.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="([^"]+)"/);
      return { url, filename: match?.[1] ?? `report_${reportId.slice(0, 8)}.docx` };
    },
  },

  adminBackup: {
    info: () =>
      fetchRaw<{
        format: string;
        restorable: boolean;
        table_count: number;
        database_size: string | null;
        excluded_tables: string[];
        note: string;
      }>("/admin/backup/info"),

    /** Streams the whole database, so it can take a while on a large deployment. */
    download: async (): Promise<{ url: string; filename: string }> => {
      const token = authClient.getAccessToken();
      const res = await fetch(apiUrl("/admin/backup/download"), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok)
        throw new ApiError("Backup download failed", res.status, classifyApiErrorKind(res.status));
      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="([^"]+)"/);
      return {
        url: URL.createObjectURL(blob),
        filename: match?.[1] ?? `placeware_backup_${new Date().toISOString().slice(0, 10)}.zip`,
      };
    },
  },
};
