/**
 * ACE Books API client (backend: /fin/*, backend/src/fin/api.py).
 *
 * Kept separate from api-client.ts because the finance workspace is large.
 * Money comes back from the server as decimal strings (never floats) and is
 * only formatted here, never re-calculated: the backend is the financial
 * authority (Backend & Frontend spec, Rule A).
 */
import { authClient } from "@/lib/auth-client";
import { apiUrl } from "@/lib/api-base";
import { ApiError } from "@/lib/api-client";

export type Money = string; // decimal string from the server, e.g. "12500.00"
export type Dict = Record<string, any>;

export class BooksError extends ApiError {
  declare code?: string;
  details?: Dict;
}

async function token(): Promise<string> {
  let t = authClient.getAccessToken();
  if (!t) {
    await authClient.refresh();
    t = authClient.getAccessToken();
  }
  if (!t) throw new ApiError("Session expired", 401, "session");
  return t;
}

function entityHeader(): Record<string, string> {
  try {
    const e = localStorage.getItem("ace_books_entity");
    return e ? { "X-Legal-Entity": e } : {};
  } catch {
    return {};
  }
}

async function request<T>(method: string, path: string, body?: unknown, form?: FormData, idem?: string): Promise<T> {
  const send = async () => {
    const headers: Record<string, string> = { Authorization: `Bearer ${await token()}`, ...entityHeader() };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (idem) headers["Idempotency-Key"] = idem;
    return fetch(apiUrl(`/fin${path}`), {
      method,
      headers,
      cache: "no-store",
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
    });
  };
  let res = await send();
  if (res.status === 401 && (await authClient.refresh())) res = await send();
  if (!res.ok) {
    let detail: any = null;
    try {
      detail = (await res.json())?.detail;
    } catch {
      /* non-JSON error */
    }
    const message =
      (typeof detail === "string" ? detail : detail?.message) || res.statusText || `Request failed (${res.status})`;
    const err = new BooksError(message, res.status, res.status === 403 ? "permission" : res.status >= 500 ? "server" : "validation");
    err.code = detail?.code;
    err.details = detail?.details;
    throw err;
  }
  return res.json();
}

const qs = (params?: Dict) => {
  if (!params) return "";
  const p = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return p.length ? "?" + p.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&") : "";
};

export const books = {
  get: <T = any>(path: string, params?: Dict) => request<T>("GET", path + qs(params)),
  post: <T = any>(path: string, body: unknown = {}, idem?: string) => request<T>("POST", path, body, undefined, idem),
  put: <T = any>(path: string, body: unknown) => request<T>("PUT", path, body),
  patch: <T = any>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: <T = any>(path: string) => request<T>("DELETE", path),
  upload: <T = any>(path: string, form: FormData) => request<T>("POST", path, undefined, form),
};

// ---------------------------------------------------------------------------
// Formatting (display only)
// ---------------------------------------------------------------------------

export function naira(v: Money | number | null | undefined, opts: { blankZero?: boolean; sign?: boolean } = {}): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return String(v);
  if (opts.blankZero && n === 0) return "";
  const s = Math.abs(n).toLocaleString("en-NG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (n < 0) return `(₦${s})`;
  return `${opts.sign && n > 0 ? "+" : ""}₦${s}`;
}

export function num(v: Money | number | null | undefined, dp = 0): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return n.toLocaleString("en-NG", { minimumFractionDigits: dp, maximumFractionDigits: Math.max(dp, 4) });
}

export function fmtDate(v?: string | null): string {
  if (!v) return "—";
  const d = new Date(v.length <= 10 ? v + "T00:00:00" : v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
// local dates (toISOString would shift to the previous day in Lagos, UTC+1)
export const today = () => ymd(new Date());
export const monthStart = (d = new Date()) => ymd(new Date(d.getFullYear(), d.getMonth(), 1));
export const yearStart = (d = new Date()) => `${d.getFullYear()}-01-01`;

export function downloadCsv(filename: string, rows: Dict[], columns?: { key: string; label: string }[]) {
  const cols = columns ?? Object.keys(rows[0] ?? {}).map((k) => ({ key: k, label: k }));
  const esc = (v: any) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const text = [cols.map((c) => esc(c.label)).join(","), ...rows.map((r) => cols.map((c) => esc(r[c.key])).join(","))].join("\r\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function newIdemKey() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** The batch number to print: the one on the pack. Placeware's Sage lot letters (the "(Q)" in
 *  HEXAXIM (Q)) are internal codes, never printed as a batch number. */
export function packBatch(x?: { pack_batch_number?: string | null; batch_number?: string | null; lot_code?: string | null } | null): string {
  if (!x) return "";
  if (x.pack_batch_number) return x.pack_batch_number;
  const b = (x.batch_number ?? "").trim();
  if (!b || b === x.lot_code || b === "SAGE" || /^[A-Z]{1,3}( ?[ivx]+)?$/i.test(b)) return "";
  return b;
}
