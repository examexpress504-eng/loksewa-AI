export function getApiBaseUrl(): string {
  let url = process.env.NEXT_PUBLIC_API_URL || "";

  // In browser on a production domain, ensure NEXT_PUBLIC_API_URL is configured
  if (typeof window !== "undefined") {
    const isProdHost = window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1";
    if (isProdHost && (!url || url.includes("localhost") || url.includes("127.0.0.1") || url.includes("0.0.0.0"))) {
      console.error(
        "[API Configuration Error] NEXT_PUBLIC_API_URL is missing or pointing to localhost in production.\n" +
        "Configure NEXT_PUBLIC_API_URL in your Vercel Project Settings with your Render backend URL (e.g. https://<service-name>.onrender.com/api)."
      );
    }
  }

  if (!url) {
    url = "http://localhost:8000/api";
  }

  url = url.trim().replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(url)) {
    url = `https://${url}`;
  }

  // Ensure API base URL always ends with /api (immune to whether NEXT_PUBLIC_API_URL includes /api)
  if (!url.endsWith("/api")) {
    url = `${url}/api`;
  }

  return url;
}

export function getApiOrigin(): string {
  const apiUrl = getApiBaseUrl();
  return apiUrl.replace(/\/api\/?$/, "");
}

export function buildApiUrl(path: string): string {
  if (!path) return getApiBaseUrl();
  if (/^https?:\/\//i.test(path)) return path;
  const base = getApiBaseUrl();
  let cleanPath = path.startsWith("/") ? path : `/${path}`;
  if (cleanPath.startsWith("/api/")) {
    cleanPath = cleanPath.slice(4);
  }
  return `${base}${cleanPath}`;
}

export function getDriveFileId(path: string | null | undefined): string | null {
  if (!path || typeof path !== "string") return null;
  const proxyMatch = path.match(/\/api\/media\/drive\/([a-zA-Z0-9_-]+)/);
  if (proxyMatch && proxyMatch[1]) return proxyMatch[1];
  const directMatch = path.match(/googleusercontent\.com\/d\/([a-zA-Z0-9_-]+)/);
  if (directMatch && directMatch[1]) return directMatch[1];
  const nameMatch = path.match(/(?:^|\/)([a-zA-Z0-9_-]{15,})__[^\/]+$/);
  if (nameMatch && nameMatch[1]) return nameMatch[1];
  return null;
}

export function getMediaFallbackUrl(path: string | null | undefined): string | null {
  const fileId = getDriveFileId(path);
  if (!fileId) return null;
  if (path && (path.includes("googleusercontent.com") || path.includes("/d/"))) {
    return `${getApiOrigin()}/api/media/drive/${fileId}/`;
  }
  return `https://lh3.googleusercontent.com/d/${fileId}`;
}

export function buildMediaUrl(path: string | null | undefined): string {
  if (!path || typeof path !== "string") return "";
  const trimmed = path.trim();
  if (!trimmed) return "";

  // Guard against Django build_absolute_uri('') returning API endpoint URLs as images
  if (trimmed.includes("/marketplace/public/products") || trimmed.includes("/api/marketplace/")) {
    return "";
  }

  // If path contains localhost/127.0.0.1 (common when backend was serialized with localhost origin),
  // strip the localhost host/port and rebuild using the appropriate origin.
  if (/^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?(\/.*)?$/i.test(trimmed)) {
    const clean = trimmed.replace(/^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?/i, "");
    const origin = getApiOrigin();
    const cleanPath = clean.startsWith("/") ? clean : `/${clean}`;
    return `${origin}${cleanPath}`;
  }

  // If path is an absolute URL:
  if (/^https?:\/\//i.test(trimmed)) {
    // If the browser is on HTTPS and image has HTTP on current domain, upgrade to HTTPS to avoid Mixed Content
    if (typeof window !== "undefined" && window.location.protocol === "https:" && trimmed.startsWith("http://")) {
      try {
        const parsed = new URL(trimmed);
        if (
          parsed.hostname === window.location.hostname ||
          parsed.hostname.endsWith(window.location.hostname.replace(/^www\./, ""))
        ) {
          parsed.protocol = "https:";
          return parsed.toString();
        }
      } catch {}
    }
    return trimmed;
  }

  const origin = getApiOrigin();
  const cleanPath = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  return `${origin}${cleanPath}`;
}

export const API_URL = getApiBaseUrl();

function extractErrorMessage(data: any): string {
  if (!data) return "An API error occurred";
  if (typeof data === "string" && data.trim()) return data.trim();
  if (data.detail && typeof data.detail === "string" && data.detail.trim()) return data.detail.trim();
  if (data.error && typeof data.error === "string" && data.error.trim()) return data.error.trim();
  if (data.message && typeof data.message === "string" && data.message.trim()) return data.message.trim();
  if (typeof data === "object") {
    const parts: string[] = [];
    for (const [key, val] of Object.entries(data)) {
      const field = key === "non_field_errors" || key === "detail" ? "" : `${key.replace(/_/g, " ")}: `;
      if (Array.isArray(val)) {
        const valStr = val.map(v => typeof v === "object" ? JSON.stringify(v) : String(v)).filter(Boolean).join(", ");
        if (valStr.trim()) parts.push(`${field}${valStr.trim()}`);
      } else if (typeof val === "string" && val.trim()) {
        parts.push(`${field}${val.trim()}`);
      }
    }
    if (parts.length > 0) return parts.join(" | ");
  }
  return "An API error occurred";
}

export class ApiError extends Error {
  constructor(public status: number, public data: any) {
    super(extractErrorMessage(data));
    this.name = "ApiError";
  }
}

export const API_MUTATION_EVENT = "api-mutation-succeeded";

export const getAuthToken = () => {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
};

export const setAuthToken = (access: string, refresh: string) => {
  if (typeof window === "undefined") return;
  localStorage.setItem("access_token", access);
  localStorage.setItem("refresh_token", refresh);
};

export const clearAuthToken = () => {
  if (typeof window === "undefined") return;
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  try {
    localStorage.removeItem("loksewa_auth_user");
    Object.keys(localStorage).forEach((k) => {
      if (k.startsWith("loksewa_student_active_course")) {
        localStorage.removeItem(k);
      }
    });
  } catch {}
};

// Concurrency-safe single active session logout lock
let isRevokedRedirectInProgress = false;

export function triggerSessionRevokedLogout(): void {
  if (typeof window === "undefined") return;
  if (isRevokedRedirectInProgress) return;
  isRevokedRedirectInProgress = true;

  clearAuthToken();

  const path = window.location.pathname;
  if (!path.includes("/login")) {
    window.location.href = "/login?session_revoked=true";
  } else {
    isRevokedRedirectInProgress = false;
  }
}

// Single-flight: the backend rotates and blacklists a refresh token on first
// use (ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION), so when several
// requests hit 401 at the same time only ONE refresh call may be made - the
// rest must await it. Parallel calls with the same refresh token made all but
// the first fail, which then cleared the session and logged the user out.
let refreshInFlight: Promise<string | null> | null = null;

function refreshToken(): Promise<string | null> {
  if (!refreshInFlight) {
    refreshInFlight = doRefreshToken().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

async function doRefreshToken(): Promise<string | null> {
  try {
    const refresh = localStorage.getItem("refresh_token");
    if (!refresh) return null;

    const response = await fetch(`${API_URL}/token/refresh/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh }),
    });

    if (!response.ok) {
      let isSessionRevoked = false;
      try {
        const errorJson = await response.json();
        if (errorJson?.code === "session_revoked") {
          isSessionRevoked = true;
        }
      } catch {
        // Body was not JSON or could not be parsed
      }

      clearAuthToken();

      if (isSessionRevoked) {
        triggerSessionRevokedLogout();
      }
      return null;
    }

    const data = await response.json();
    localStorage.setItem("access_token", data.access);
    // The rotated refresh token replaces the old one (which is now
    // blacklisted); without storing it the next refresh would fail.
    if (data.refresh) localStorage.setItem("refresh_token", data.refresh);
    return data.access;
  } catch {
    // Network error: keep the session; the caller's request will fail
    // normally and can be retried.
    return null;
  }
}

export interface ApiClientOptions extends RequestInit {
  skipRedirect?: boolean;
  timeoutMs?: number;
}

const inFlightGetRequests = new Map<string, Promise<any>>();

export async function apiClient<T>(
  endpoint: string,
  options: ApiClientOptions = {}
): Promise<T> {
  const method = (options.method || "GET").toUpperCase();
  const isGet = (method === "GET" || method === "HEAD") && !options.body;

  if (!isGet) {
    return executeRequest<T>(endpoint, options);
  }

  const token = getAuthToken();
  const dedupKey = `${endpoint}::${token || "anon"}`;

  if (inFlightGetRequests.has(dedupKey)) {
    return inFlightGetRequests.get(dedupKey)! as Promise<T>;
  }

  const promise = executeRequest<T>(endpoint, options).finally(() => {
    inFlightGetRequests.delete(dedupKey);
  });

  inFlightGetRequests.set(dedupKey, promise);
  return promise;
}

async function executeRequest<T>(
  endpoint: string,
  options: ApiClientOptions = {}
): Promise<T> {
  const url = buildApiUrl(endpoint);
  
  const token = getAuthToken();
  const headers = new Headers(options.headers || {});
  
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  
  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const defaultTimeout = (options.body instanceof FormData) ? 90000 : 30000;
  const timeoutMs = options.timeoutMs ?? defaultTimeout;
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  let signal = options.signal;

  if (!signal && typeof AbortController !== "undefined" && timeoutMs > 0) {
    const controller = new AbortController();
    signal = controller.signal;
    timeoutId = setTimeout(() => {
      controller.abort();
    }, timeoutMs);
  }

  const config: RequestInit = {
    cache: 'no-store',
    ...options,
    headers,
    signal,
  };

  let response: Response;
  try {
    response = await fetch(url, config);
  } catch (err: any) {
    if (err?.name === "AbortError") {
      throw new ApiError(0, {
        detail: "The request timed out. Please check your internet connection or try again."
      });
    }
    throw new ApiError(0, {
      detail: err?.message === "Failed to fetch"
        ? "Unable to connect to the backend server. Please verify your connection and ensure the server is running."
        : (err?.message || "Network request failed")
    });
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }

  // Handle Token Expiration or Missing Token
  if (response.status === 401) {
    let isSessionRevoked = false;
    try {
      const cloned = response.clone();
      const errorJson = await cloned.json();
      if (errorJson?.code === "session_revoked") {
        isSessionRevoked = true;
      }
    } catch {
      // Body was not JSON or could not be parsed
    }

    if (isSessionRevoked) {
      triggerSessionRevokedLogout();
      return new Promise(() => {}); // never resolve to prevent further execution
    }

    if (token) {
      const newToken = await refreshToken();
      if (newToken) {
        headers.set("Authorization", `Bearer ${newToken}`);
        response = await fetch(url, { ...config, headers });
      }
    }
    
    if (response.status === 401 && !options.skipRedirect) {
      // Force logout if refresh failed or no token was present. Every role
      // signs in through the same /login form, so there's only one place
      // to send anyone back to.
      if (typeof window !== "undefined") {
        const path = window.location.pathname;
        if (!path.includes("/login")) {
          window.location.href = "/login?expired=true";
          return new Promise(() => {}); // never resolve to prevent further execution
        }
      }
    }
  }

  if (!response.ok) {
    let errorData;
    try {
      errorData = await response.json();
    } catch {
      const fallbackDetail = response.statusText || (
        response.status === 500 ? "Internal Server Error" :
        response.status === 502 ? "Bad Gateway" :
        response.status === 503 ? "Service Unavailable" :
        response.status === 504 ? "Gateway Timeout" :
        response.status === 403 ? "Forbidden" :
        response.status === 404 ? "Not Found" :
        `HTTP ${response.status} Error`
      );
      errorData = { detail: `${fallbackDetail} (${response.status})` };
    }
    
    // Intercept package lock
    if (response.status === 403 && errorData?.code === 'subscription_required' && !options.skipRedirect) {
      if (typeof window !== "undefined") {
        const path = window.location.pathname;
        if (path !== "/student" && !path.startsWith("/student/onboarding") && !path.startsWith("/student/plans")) {
          window.location.href = "/student";
          return new Promise(() => {}); // Prevent further execution
        }
      }
    }

    throw new ApiError(response.status, errorData);
  }

  // Any successful write may change dashboard aggregates; let the query
  // layer (see app/providers.tsx) revalidate the affected cached queries.
  const method = (options.method || "GET").toUpperCase();
  if (method !== "GET" && method !== "HEAD" && typeof window !== "undefined") {
    window.dispatchEvent(new Event(API_MUTATION_EVENT));
  }

  if (response.status === 204) {
    return {} as T;
  }

  // A 200 with an empty body (e.g. Response(status=200) in DRF with no
  // serializer data) is valid and common in this backend, but
  // response.json() throws SyntaxError on empty input - read the text
  // first so a genuinely empty success response doesn't look like a
  // parse failure.
  const text = await response.text();
  if (!text) {
    return {} as T;
  }
  return JSON.parse(text);
}

/**
 * Downloads a file from an authenticated endpoint and saves it via the browser.
 *
 * A plain link or window.open() navigates without the Authorization header, so
 * protected downloads come back as a 401 page. This fetches the bytes with the
 * bearer token (retrying once after a refresh, like apiClient) and hands the
 * resulting blob to a temporary object URL.
 */
export async function downloadFile(
  endpoint: string,
  fallbackFilename: string
): Promise<void> {
  const url = buildApiUrl(endpoint);
  const token = getAuthToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response = await fetch(url, { headers });

  if (response.status === 401) {
    try {
      const cloned = response.clone();
      const errorJson = await cloned.json();
      if (errorJson?.code === "session_revoked") {
        triggerSessionRevokedLogout();
        return;
      }
    } catch {
      // Body was not JSON or could not be parsed
    }

    if (token) {
      const newToken = await refreshToken();
      if (newToken) {
        headers.set("Authorization", `Bearer ${newToken}`);
        response = await fetch(url, { headers });
      }
    }
  }

  if (!response.ok) {
    let errorData;
    try {
      errorData = await response.json();
    } catch {
      const fallbackDetail = response.statusText || (
        response.status === 500 ? "Internal Server Error" :
        response.status === 502 ? "Bad Gateway" :
        response.status === 503 ? "Service Unavailable" :
        response.status === 504 ? "Gateway Timeout" :
        response.status === 403 ? "Forbidden" :
        response.status === 404 ? "Not Found" :
        `HTTP ${response.status} Error`
      );
      errorData = { detail: `${fallbackDetail} (${response.status})` };
    }
    throw new ApiError(response.status, errorData);
  }

  // Prefer the server's filename from Content-Disposition when it sends one.
  let filename = fallbackFilename;
  const disposition = response.headers.get("Content-Disposition");
  const match = disposition?.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  if (match?.[1]) filename = decodeURIComponent(match[1]);

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

/**
 * Downloads a file from an already-absolute, public (no-auth) URL - e.g. the
 * `/api/media/drive/<id>/` links returned by public endpoints like the
 * syllabus page. A plain `<a href target="_blank">` only opens the browser's
 * PDF viewer instead of actually saving the file, so this fetches the bytes
 * and hands them to a temporary object URL the same way downloadFile() does
 * for authenticated downloads.
 */
export async function downloadPublicFile(url: string, fallbackFilename: string): Promise<void> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new ApiError(response.status, { detail: response.statusText });
  }

  let filename = fallbackFilename;
  const disposition = response.headers.get("Content-Disposition");
  const match = disposition?.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  if (match?.[1]) filename = decodeURIComponent(match[1]);

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

export async function fetchBlob(path: string, options: RequestInit = {}): Promise<Blob> {
  const url = path.startsWith("http://") || path.startsWith("https://") ? path : buildApiUrl(path);
  const token = getAuthToken();
  const headers = new Headers(options.headers || {});
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  let res = await fetch(url, { ...options, headers });
  if (res.status === 401) {
    try {
      const cloned = res.clone();
      const errorJson = await cloned.json();
      if (errorJson?.code === "session_revoked") {
        triggerSessionRevokedLogout();
        throw new ApiError(401, errorJson);
      }
    } catch (_err) {
      // Body was already consumed or is non-JSON
    }

    if (!options.headers) {
      const newToken = await refreshToken();
      if (newToken) {
        headers.set("Authorization", `Bearer ${newToken}`);
        res = await fetch(url, { ...options, headers });
      }
    }
  }
  if (!res.ok) {
    throw new ApiError(res.status, await res.text().catch(() => ({ detail: res.statusText })));
  }
  return res.blob();
}
