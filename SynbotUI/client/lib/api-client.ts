import {
  InventoryDashboardData,
  WorkforceDashboardData,
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
    res = await fetch(apiUrl(endpoint), { headers: { "Authorization": `Bearer ${token}` } });
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
  let res = await fetch(apiUrl(endpoint), { headers: { "Authorization": `Bearer ${token}` } });

  if (res.status === 401) {
    const refreshed = await authClient.refresh();
    if (!refreshed) {
      redirectToLoginIfNeeded();
      throw new ApiError("Session expired", 401, "session");
    }
    token = await getBearerToken();
    res = await fetch(apiUrl(endpoint), { headers: { "Authorization": `Bearer ${token}` } });
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
    inventory: () => fetchJson<InventoryDashboardData>("/dashboard/inventory"),
    workforce: () => fetchJson<WorkforceDashboardData>("/dashboard/workforce"),
    crm: () => fetchJson<any>("/dashboard/crm"),
    alerts: () => fetchJson<Alert[]>("/dashboard/alerts"),
    briefing: () => fetchJson<ExecutiveBriefing>("/dashboard/executive-briefing"),
    finance: () => fetchJson<any>("/dashboard/finance"),
  },
  staff: {
    list: (dept?: string) => fetchJson<StaffMember[]>(`/staff${dept ? `?department=${dept}` : ""}`),
    snapshot: () => fetchJson<StaffMember[]>(`/staff/snapshot`),
    timesheets: (department?: string, limit: number = 50) =>
      fetchJson<any[]>(`/timesheets${department ? `?department=${encodeURIComponent(department)}&limit=${limit}` : `?limit=${limit}`}`),
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
      fetchJson<{ jobs: any[]; count: number }>(`/sage/import/jobs?limit=${limit}`),
    supportedTypes: () =>
      fetchJson<{ file_types: any[] }>("/sage/import/supported"),
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
    create: (payload: {
      email: string;
      password: string;
      roles: string[];
      approval_reason: string;
      attestation_text: string;
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
     arAging: () => fetchRaw<any>("/reports/ar_aging"),
      arAgingCustomers: (bucket: string) =>
       fetchRaw<any>(`/reports/ar_aging/customers?bucket=${encodeURIComponent(bucket)}`),
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
    list: (limit: number = 100) => fetchJson<any[]>(`/admin/leads?limit=${limit}`),
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
  },
    ops: {
      kpis: () => fetchRaw<OpsKpis>("/ops/kpis"),
      forecastStockTurnover: (window: number = 3, horizon: number = 3) =>
        fetchRaw<OpsForecast>(`/ops/forecast/stock_turnover?window=${window}&horizon=${horizon}`),
    },
  inventory: {
    stock: async (skus?: string[]) => {
      // TODO: support skus param via POST body if needed
      const data = await fetchRaw("/stock");
      return data.stock as any[];
    },
    latestSnapshot: () => fetchJson<any[]>("/stock"),
    // simple search endpoint used by staff UI autocomplete
    search: (query: string) => fetchJson<any[]>(`/inventory?query=${encodeURIComponent(query)}`),
    recordMovement: (payload: {
      item_id: string;
      change: number;
      movement_type: string;
      source?: string;
      destination?: string;
      created_by?: string;
      metadata?: Record<string, any>;
    }) => sendJson<{ status: string; movement: any }>("/inventory/movements", "POST", payload),
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
    }) => sendJson<{ data: any }>("/calendar/events", "POST", payload),
    update: (eventId: string, payload: Record<string, any>) =>
      sendJson<{ data: any }>(`/calendar/events/${eventId}`, "PATCH", payload),
    delete: (eventId: string) =>
      fetchRaw<{ status: string }>(`/calendar/events/${eventId}`).then(() => ({ status: "deleted" })),
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
      sendJson<{ status: string }>(`/tasks/${taskId}`, "POST", { _method: "DELETE" })
        .catch(() => fetchRaw(`/tasks/${taskId}`)),
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
};
