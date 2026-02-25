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
      throw new Error(reason ? `No active session (${reason})` : "No active session");
    }
    token = authClient.getAccessToken();
  }
  if (!token) {
    const reason = authClient.getLastAuthError();
    throw new Error(reason ? `Session expired (${reason})` : "Session expired");
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
      throw new Error("Session expired");
    }
    token = await getBearerToken();
    res = await fetch(apiUrl(endpoint), { headers: { "Authorization": `Bearer ${token}` } });
  }

  if (!res.ok) {
    console.error(`API Error ${endpoint}:`, res.statusText);
    throw new Error(res.statusText);
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
      throw new Error("Session expired");
    }
    token = await getBearerToken();
    res = await fetch(apiUrl(endpoint), { headers: { "Authorization": `Bearer ${token}` } });
  }

  if (!res.ok) {
    console.error(`API Error ${endpoint}:`, res.statusText);
    throw new Error(res.statusText);
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
      throw new Error("Session expired");
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
    let detail = res.statusText;
    try {
      const payload = await res.json();
      detail = payload?.detail || payload?.error || res.statusText;
    } catch {
      // No JSON payload to parse
    }
    console.error(`API Error ${method} ${endpoint}:`, detail);
    throw new Error(detail || "Request failed");
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
      throw new Error("Session expired");
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
    let detail = res.statusText;
    try {
      const payload = await res.json();
      detail = payload?.detail || payload?.error || res.statusText;
    } catch {
      // No JSON payload to parse
    }
    console.error(`API Error ${method} ${endpoint}:`, detail);
    throw new Error(detail || "Request failed");
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
  },
  sage: {
     history: () => fetchJson<any[]>("/sage/history"),
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
  }
};
