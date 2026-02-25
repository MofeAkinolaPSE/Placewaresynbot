const rawBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim() || "";

export const API_BASE_URL = rawBaseUrl.replace(/\/+$/, "");

export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  if (!API_BASE_URL) {
    return normalizedPath;
  }
  return `${API_BASE_URL}${normalizedPath}`;
}
