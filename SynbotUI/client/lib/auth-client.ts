import { apiUrl } from "@/lib/api-base";

type TokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  roles: string[];
};

const REFRESH_TOKEN_KEY = "refresh_token";

/** Sign-in failure carrying a message safe to show the user. */
export class AuthError extends Error {}

class AuthClient {
  private accessToken: string | null = null;
  private roles: string[] = [];
  private refreshPromise: Promise<boolean> | null = null;
  private lastAuthError: string | null = null;

  getAccessToken(): string | null {
    return this.accessToken;
  }

  isAuthenticated(): boolean {
    return !!this.accessToken;
  }

  getRoles(): string[] {
    return this.roles;
  }

  getLastAuthError(): string | null {
    return this.lastAuthError;
  }

  getSubject(): string | null {
    if (!this.accessToken) return null;
    try {
      const parts = this.accessToken.split(".");
      if (parts.length < 2) return null;
      const payloadJson = atob(parts[1].replace(/-/g, "+").replace(/_/g, "/"));
      const payload = JSON.parse(payloadJson) as { sub?: string; user_id?: string };
      return payload.sub || payload.user_id || null;
    } catch {
      return null;
    }
  }

  async login(email: string, password: string): Promise<void> {
    const body = new URLSearchParams();
    body.set("username", email);
    body.set("password", password);

    let res: Response;
    try {
      res = await fetch(apiUrl("/token"), {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString(),
      });
    } catch {
      // Never reached the server: backend down, DNS/CORS failure, offline.
      this.lastAuthError = "login_unreachable";
      throw new AuthError(
        "Cannot reach the server. Check that the backend is running.",
      );
    }
    if (!res.ok) {
      this.lastAuthError = `login_failed:${res.status}`;
      throw new AuthError(
        res.status === 401 || res.status === 400
          ? "Invalid email or password. Please try again."
          : `Sign-in failed (server error ${res.status}). Please try again.`,
      );
    }
    const data = (await res.json()) as TokenResponse;
    this.applyTokenResponse(data);
    this.lastAuthError = null;
  }

  async refresh(): Promise<boolean> {
    if (this.refreshPromise) {
      return this.refreshPromise;
    }

    this.refreshPromise = this.refreshInternal();
    try {
      return await this.refreshPromise;
    } finally {
      this.refreshPromise = null;
    }
  }

  private async refreshInternal(): Promise<boolean> {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (!refreshToken) {
      this.lastAuthError = "refresh_failed:no_refresh_token";
      return false;
    }

    const res = await fetch(apiUrl("/refresh"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) {
      let detail = `${res.status}`;
      try {
        const payload = (await res.json()) as { detail?: string; error?: string };
        detail = payload?.detail || payload?.error || detail;
      } catch {
        // Ignore parse errors; keep status-only detail
      }
      this.lastAuthError = `refresh_failed:${detail}`;
      this.clear();
      return false;
    }
    const data = (await res.json()) as TokenResponse;
    this.applyTokenResponse(data);
    this.lastAuthError = null;
    return true;
  }

  async logout(): Promise<void> {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (refreshToken) {
      try {
        await fetch(apiUrl("/logout"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
      } catch {
        // Ignore network failures during local logout.
      }
    }
    this.clear();
  }

  private applyTokenResponse(data: TokenResponse): void {
    this.accessToken = data.access_token;
    this.roles = Array.isArray(data.roles) ? data.roles : [];
    localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
    this.lastAuthError = null;
  }

  clear(): void {
    this.accessToken = null;
    this.roles = [];
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("auth:expired"));
    }
  }
}

export const authClient = new AuthClient();
