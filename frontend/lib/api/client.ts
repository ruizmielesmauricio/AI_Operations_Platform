import { getAccessToken } from "@/lib/supabase/client";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * All backend calls go through this module — components never construct a
 * fetch URL themselves, so the API base URL only needs to change in one
 * place when moving between local, staging, and production. Tenant-scoped
 * routes require a Supabase session; requests are sent unauthenticated if
 * none exists, and the backend rejects them with 401 (see app/security/auth.py).
 */
async function authHeaders(): Promise<Record<string, string>> {
  const token = await getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// A typed error carrying the real HTTP status, thrown instead of a plain
// Error — every existing `.catch(() => ...)` call site still works
// unchanged (ApiError still is an Error), but a call site that needs to
// distinguish e.g. 402 (no active subscription) from any other failure
// can now check `error instanceof ApiError && error.status === 402`
// rather than string-parsing a message. Confirmed there was zero
// status-code-aware handling anywhere in this frontend before this —
// every route just discarded the status into an opaque message string.
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function throwApiError(response: Response, path: string): Promise<never> {
  // FastAPI's HTTPException(detail=...) body is written to be shown to a
  // user directly (e.g. the 409 business-limit message, the 402
  // subscription message) — surfaced here when present, rather than
  // always falling back to a generic "request failed" string. Cloned
  // first: the body can only be read once, and a caller catching this as
  // a plain Error (every existing call site) never touches `response`.
  let detail: string | undefined;
  try {
    const body = await response.clone().json();
    if (typeof body?.detail === "string") detail = body.detail;
  } catch {
    // Not JSON, or no body — fall back to the generic message below.
  }
  throw new ApiError(response.status, detail ?? `API request to ${path} failed with ${response.status}`);
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    headers: await authHeaders(),
  });
  if (!response.ok) {
    await throwApiError(response, path);
  }
  return response.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    await throwApiError(response, path);
  }
  return response.json() as Promise<T>;
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "PATCH",
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    await throwApiError(response, path);
  }
  return response.json() as Promise<T>;
}

export async function apiDelete(path: string): Promise<void> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "DELETE",
    cache: "no-store",
    headers: await authHeaders(),
  });
  if (!response.ok) {
    await throwApiError(response, path);
  }
  // A successful delete returns 204 No Content — no body to parse.
}
