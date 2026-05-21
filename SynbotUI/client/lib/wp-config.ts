export type SynbotConfig = {
  apiBaseUrl?: string;
  role?: string;
  wpUserId?: number;
};

export function getSynbotConfig(): SynbotConfig {
  if (typeof window === "undefined") {
    // Basic fallback for non-browser environments
    return {};
  }
  
  // 1. Try global window config (injected by WP/backend)
  try {
      const w = window as Window & { SYNBOT_CONFIG?: SynbotConfig };
    if (w.SYNBOT_CONFIG) {
       return w.SYNBOT_CONFIG;
    }
  } catch {
    // ignore
  }

  // 2. Fallback to localStorage if available (often set during dev login)
  try {
     const stored = localStorage.getItem("synbot_config");
     if (stored) {
        return JSON.parse(stored);
     }
  } catch {
     // ignore
  }

  // 3. Fallback to env vars (development mode)
  // Note: import.meta.env is available in Vite; access via string to avoid TS issues if needed or use type assertion
  const env = import.meta.env;
  if (env && env.DEV) {
     return {
        apiBaseUrl: env.VITE_API_BASE_URL || "http://localhost:8000",
        role: "admin", 
        wpUserId: 0
     };
  }

  return {};
}
