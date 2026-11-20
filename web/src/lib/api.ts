/**
 * Typed fetch wrapper.
 * - Access token lives in memory only (never localStorage); refresh token is an httpOnly cookie.
 * - On 401 it refreshes once (de-duplicated across concurrent calls) and retries.
 */

import { ApiError } from "./errors";

export { ApiError };

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onSessionLost: () => void = () => {};

export function setAccessToken(t: string | null) {
  accessToken = t;
}
export function getAccessToken() {
  return accessToken;
}
export function hasAccessToken() {
  return accessToken !== null;
}
export function setOnSessionLost(fn: () => void) {
  onSessionLost = fn;
}

const BASE = "/api/v1";

async function parse(res: Response): Promise<unknown> {
  if (res.status === 204) return undefined;
  const ct = res.headers.get("content-type") ?? "";
  return ct.includes("application/json") ? res.json() : res.text();
}

function toError(status: number, body: unknown): ApiError {
  const e = (body as { error?: { code: string; message: string; details?: unknown } })?.error;
  if (!e && status >= 500) {
    // Not our JSON error shape: the API is down, crashed, or the proxy couldn't reach it.
    return new ApiError(status, "server_unavailable", "The server is unavailable right now. Please try again in a moment.");
  }
  return new ApiError(status, e?.code ?? "error", e?.message ?? "Something went wrong", e?.details);
}

export function refreshSession(): Promise<boolean> {
  // Callers that arrive while a refresh is in flight share it; once it settles the
  // slot is cleared immediately so a stale result is never reused.
  refreshing ??= (async () => {
    try {
      const res = await fetch(`${BASE}/auth/refresh`, { method: "POST", credentials: "include" });
      if (!res.ok) return false;
      const body = (await res.json()) as { access_token: string };
      accessToken = body.access_token;
      return true;
    } catch {
      return false;
    }
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

type Opts = Omit<RequestInit, "body"> & { body?: unknown; query?: Record<string, unknown> };

export async function api<T>(path: string, opts: Opts = {}, retried = false): Promise<T> {
  const { body, query, headers, ...rest } = opts;
  let url = `${BASE}${path}`;
  if (query) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    }
    const s = qs.toString();
    if (s) url += `?${s}`;
  }
  const isForm = body instanceof FormData;
  const sentWith = accessToken;
  const res = await fetch(url, {
    ...rest,
    credentials: "include",
    headers: {
      ...(isForm || body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...headers,
    },
    body: isForm ? body : body === undefined ? undefined : JSON.stringify(body),
  });

  if (res.status === 401 && !retried && !path.startsWith("/auth/")) {
    // Another call may already have refreshed while this one was in flight.
    if (accessToken && accessToken !== sentWith) return api<T>(path, opts, true);
    if (await refreshSession()) return api<T>(path, opts, true);
    accessToken = null;
    onSessionLost();
  }
  const data = await parse(res);
  if (!res.ok) throw toError(res.status, data);
  return data as T;
}

/** Human message for a failed call; field errors from 422 are flattened. */
export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === "validation_error" && Array.isArray(e.details) && e.details.length) {
      return (e.details as { loc: string[]; msg: string }[])
        .map((d) => `${d.loc.filter((x) => x !== "body").join(".") || "Form"}: ${d.msg.replace(/^Value error, /, "")}`)
        .join("\n");
    }
    return e.message;
  }
  return "Network error. Check your connection and try again.";
}

/** Fetch a file that needs the session (PDF, CSV…) and hand it to the browser.
 *  ``open`` shows it in a new tab (PDFs) instead of saving. */
export async function downloadFile(path: string, opts: { query?: Record<string, unknown>; fallbackName?: string; open?: boolean } = {}): Promise<void> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(opts.query ?? {})) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  const url = `${BASE}${path}${qs.size ? `?${qs}` : ""}`;
  const go = () => fetch(url, { credentials: "include", headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {} });
  let res = await go();
  if (res.status === 401 && (await refreshSession())) res = await go();
  if (!res.ok) throw toError(res.status, await parse(res));
  const blob = await res.blob();
  const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? opts.fallbackName ?? "download";
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  if (opts.open) a.target = "_blank";
  else a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 60_000);
}
