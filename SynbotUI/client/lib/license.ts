// Licence status store. The backend enforces the lock (src/licensing); this only drives
// the locked screen / grace banner so users see why requests are refused.
import { apiUrl } from "@/lib/api-base";

export type LicenseState = "unconfigured" | "valid" | "grace" | "expired" | "missing" | "invalid" | "clock_rollback";

export interface LicenseStatus {
  state: LicenseState;
  locked: boolean;
  lock_mode: "full" | "read_only";
  message: string;
  license_id: string | null;
  licensee: string | null;
  starts_on: string | null;
  expires_on: string | null;
  grace_ends_on: string | null;
  days_remaining: number | null;
  support_contact: string;
}

let current: LicenseStatus | null = null;
const listeners = new Set<() => void>();
let inflight: Promise<void> | null = null;
let lastRefresh = 0;

export function getLicenseStatus(): LicenseStatus | null {
  return current;
}

export function subscribeLicense(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function refreshLicense(): Promise<void> {
  if (inflight) return inflight;
  lastRefresh = Date.now();
  inflight = (async () => {
    try {
      const res = await nativeFetch(apiUrl("/license/status"), { cache: "no-store" });
      if (res.ok) {
        current = (await res.json()) as LicenseStatus;
        listeners.forEach((fn) => fn());
      }
    } catch {
      // backend unreachable: keep the last known status
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

// Any 403 might be the licence lock (from any of the app's many fetch call sites), so
// re-check status - at most every 10s.
const nativeFetch: typeof fetch = typeof window !== "undefined" ? window.fetch.bind(window) : fetch;
let watching = false;

export function watchFetchForLicenseLock(): void {
  if (watching || typeof window === "undefined") return;
  watching = true;
  window.fetch = async (...args: Parameters<typeof fetch>) => {
    const res = await nativeFetch(...args);
    if (res.status === 403 && Date.now() - lastRefresh > 10_000) void refreshLicense();
    return res;
  };
}
