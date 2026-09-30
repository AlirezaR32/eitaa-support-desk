/**
 * API client.
 *
 * - Production: `VITE_API_BASE_URL` (absolute URL) or same-origin relative
 *   paths behind a reverse proxy.
 * - Sandbox/preview gateway: set `VITE_API_XFORM_PORT` — every request and
 *   the WebSocket then carry `?XTransformPort=<port>` so the gateway routes
 *   them to the backend. This is a deployment shim, not used in normal builds.
 */

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";
const XFORM_PORT = (import.meta.env.VITE_API_XFORM_PORT as string | undefined) ?? "";

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function withGatewayParams(url: string): string {
  if (!XFORM_PORT) return url;
  return url + (url.includes("?") ? "&" : "?") + "XTransformPort=" + XFORM_PORT;
}

export function apiUrl(path: string): string {
  return withGatewayParams(`${BASE}${path}`);
}

export function wsUrl(token: string): string {
  const base = BASE || window.location.origin;
  const url = new URL(`${base.replace(/^http/, "ws")}/api/v1/ws`);
  url.searchParams.set("token", token);
  if (XFORM_PORT) url.searchParams.set("XTransformPort", XFORM_PORT);
  return url.toString();
}

let accessToken: string | null = null;
export function setAccessToken(token: string | null) {
  accessToken = token;
}
export function getAccessToken() {
  return accessToken;
}

/** refresh queue — parallel 401s wait for one refresh */
let refreshing: Promise<boolean> | null = null;

/** Single-flight refresh — ALWAYS use this (never call the endpoint directly)
 * so concurrent callers cannot rotate the same cookie family twice. */
export async function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const response = await fetch(withGatewayParams(`${BASE}/api/v1/auth/refresh`), {
        method: "POST",
        credentials: "include",
      });
      if (!response.ok) return false;
      const data = (await response.json()) as { access_token: string };
      accessToken = data.access_token;
      return true;
    } catch {
      return false;
    } finally {
      setTimeout(() => (refreshing = null), 0);
    }
  })();
  return refreshing;
}

async function tryRefresh(): Promise<boolean> {
  return refreshSession();
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  formData?: FormData;
  raw?: boolean;
  retry?: boolean;
}

export async function api<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, formData, raw = false, retry = true } = options;
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(apiUrl(path), {
    method,
    headers,
    credentials: "include",
    body: formData ?? (body !== undefined ? JSON.stringify(body) : undefined),
  });

  if (response.status === 401 && retry && !path.startsWith("/api/v1/auth/login")) {
    const refreshed = await tryRefresh();
    if (refreshed) return api<T>(path, { ...options, retry: false });
  }

  if (!response.ok) {
    let code = "http_error";
    let message = `خطای سرور (${response.status})`;
    let details: Record<string, unknown> = {};
    try {
      const parsed = (await response.json()) as { error?: { code: string; message: string; details?: Record<string, unknown> } };
      if (parsed?.error) {
        code = parsed.error.code;
        message = parsed.error.message;
        details = parsed.error.details ?? {};
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, code, message, details);
  }

  if (raw) return response as unknown as T;
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
