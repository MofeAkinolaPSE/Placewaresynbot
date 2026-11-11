/**
 * Branches (Lagos / Abuja). Every API request a signed-in person makes carries the branch this tab works in
 * (header X-Legal-Entity); the server checks it against their access and the database shows only that branch.
 *
 * - The branch is remembered per tab (sessionStorage), so two tabs can work in two branches without one
 *   silently changing the other. A new tab starts in the branch last chosen (localStorage).
 * - Nothing chosen: the server uses the person's home branch.
 * - Switching reloads the app, so no screen keeps figures from the other branch.
 * - A branch the person may no longer use (403 BRANCH_NOT_ALLOWED) is forgotten and the app reloads in their home branch.
 */
import { API_BASE_URL } from "@/lib/api-base";

const TAB_KEY = "ace:branch";
const LAST_KEY = "ace:branch-last";
const LEGACY_KEY = "ace_books_entity";
const RESET_GUARD = "ace:branch-reset";

export interface Branch {
  id: string;
  code: string;
  name: string;
  branch_name: string;
  is_primary: boolean;
}

export interface MyBranches {
  current: Branch | null;
  home: string | null;
  branches: Branch[];
  can_switch: boolean;
}

export function chosenBranch(): string | null {
  try {
    return sessionStorage.getItem(TAB_KEY) || localStorage.getItem(LAST_KEY) || null;
  } catch {
    return null;
  }
}

export function branchHeader(): Record<string, string> {
  const b = chosenBranch();
  return b ? { "X-Legal-Entity": b } : {};
}

/** Work in another branch: remembered for this tab (and new tabs), then the app reloads cleanly. */
export function switchBranch(id: string, path?: string) {
  try {
    sessionStorage.setItem(TAB_KEY, id);
    localStorage.setItem(LAST_KEY, id);
    localStorage.removeItem(LEGACY_KEY);
  } catch {
    /* private mode: the server falls back to the home branch */
  }
  if (path !== undefined) window.location.hash = path;
  window.location.reload();
}

function forgetBranch() {
  try {
    sessionStorage.removeItem(TAB_KEY);
    localStorage.removeItem(LAST_KEY);
    localStorage.removeItem(LEGACY_KEY);
  } catch {
    /* ignore */
  }
}

function isApiRequest(url: string): boolean {
  if (url.startsWith("/")) return !url.startsWith("//");
  try {
    const u = new URL(url, window.location.href);
    if (u.origin === window.location.origin) return true;
    return !!API_BASE_URL && url.startsWith(API_BASE_URL);
  } catch {
    return false;
  }
}

let installed = false;

/**
 * Add the branch header to every signed-in API call (any request that already carries an Authorization header),
 * whichever screen or helper makes it. Installed once, before the app renders.
 */
export function installBranchFetch() {
  if (installed || typeof window === "undefined") return;
  installed = true;
  const original = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const branch = chosenBranch();
    let nextInput = input;
    let nextInit = init;
    if (branch) {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (isApiRequest(url)) {
        if (input instanceof Request && !init) {
          if (input.headers.has("Authorization") && !input.headers.has("X-Legal-Entity")) {
            const h = new Headers(input.headers);
            h.set("X-Legal-Entity", branch);
            nextInput = new Request(input, { headers: h });
          }
        } else {
          const h = new Headers(init?.headers || (input instanceof Request ? input.headers : undefined));
          if (h.has("Authorization") && !h.has("X-Legal-Entity")) {
            h.set("X-Legal-Entity", branch);
            nextInit = { ...(init || {}), headers: h };
          }
        }
      }
    }
    const res = await original(nextInput, nextInit);
    if (res.status === 403 && branch) {
      try {
        const body = await res.clone().json();
        if (body?.code === "BRANCH_NOT_ALLOWED" && !sessionStorage.getItem(RESET_GUARD)) {
          sessionStorage.setItem(RESET_GUARD, "1");
          forgetBranch();
          window.location.reload();
        }
      } catch {
        /* not JSON - an ordinary 403 */
      }
    } else if (res.ok) {
      try {
        sessionStorage.removeItem(RESET_GUARD);
      } catch {
        /* ignore */
      }
    }
    return res;
  };
}
