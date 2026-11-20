/**
 * Calls for the public (visitor / host-link / pass) pages. These never use the staff
 * session: each call carries the short-lived token for this one flow, kept in
 * sessionStorage so a reload on a phone doesn't lose the check-in.
 */
import { ApiError } from "@/lib/errors";

const BASE = "/api/v1/public";

export async function pub<T>(path: string, opts: { token?: string | null; method?: string; body?: unknown } = {}): Promise<T> {
  const isForm = opts.body instanceof FormData;
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method: opts.method ?? (opts.body === undefined ? "GET" : "POST"),
      headers: {
        ...(opts.token ? { Authorization: `Bearer ${opts.token}` } : {}),
        ...(opts.body === undefined || isForm ? {} : { "Content-Type": "application/json" }),
      },
      body: isForm ? (opts.body as FormData) : opts.body === undefined ? undefined : JSON.stringify(opts.body),
    });
  } catch {
    throw new ApiError(0, "network", "No connection");
  }
  const data = (res.headers.get("content-type") ?? "").includes("json") ? await res.json() : null;
  if (!res.ok) {
    const e = data?.error;
    throw new ApiError(res.status, e?.code ?? (res.status >= 500 ? "server_unavailable" : "error"), e?.message ?? "Something went wrong", e?.details);
  }
  return data as T;
}

export const store = {
  get(key: string): string | null {
    try {
      return sessionStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key: string, value: string | null) {
    try {
      if (value === null) sessionStorage.removeItem(key);
      else sessionStorage.setItem(key, value);
    } catch {
      /* private mode: the flow still works, it just won't survive a reload */
    }
  },
};

// ---------- Types (mirror app/schemas/visits.py) ----------

export interface Purpose { id: string; label: string; label_i18n: Record<string, string>; requires_id_proof: boolean }
export interface CustomField {
  key: string; label: string; label_i18n: Record<string, string>; help_i18n: Record<string, string>;
  type: "text" | "number" | "select" | "checkbox" | "declaration"; options: string[]; required: boolean;
}
export interface GateInfo {
  org_name: string; branding: { primary_color?: string; accent_color?: string }; logo_url: string | null; privacy_url: string | null; locales: string[]; default_locale: string;
  require_selfie: boolean; id_proof_mode: "off" | "optional" | "required"; site_name: string; site_address: string | null;
  gate_name: string; verify_phone?: boolean; purposes: Purpose[]; fields: CustomField[]; notices: Record<string, { id: string; version: number; body: string }>;
}
export interface HostOption { id: string; full_name: string; department: string | null; designation: string | null }
export interface Prefill { full_name: string | null; company: string | null; email: string | null; has_photo: boolean; last_host: HostOption | null }
export type VisitStatusName = "pending" | "waiting" | "approved" | "rejected" | "checked_in" | "checked_out" | "expired" | "cancelled";
export interface VisitStatus {
  id: string; status: VisitStatusName; visitor_name: string | null; host_name: string; site_name: string; gate_name: string | null;
  host_message: string | null; requested_at: string; responded_at: string | null; valid_until: string; escalated: boolean;
  pass: { token: string; url: string } | null;
  whatsapp?: boolean; // false: nothing is sent to the visitor; this page is where they see it
}
export interface PassView {
  state: "valid" | "not_yet" | "checked_in" | "used" | "expired" | "revoked"; kind?: "visit" | "invite"; status: string; org_name: string; branding: { primary_color?: string };
  visitor_name: string | null; visitor_company: string | null; photo_url: string | null; host_name: string; site_name: string;
  site_address: string | null; directions: string | null; map_url: string | null; accompanying_count: number; valid_until: string; qr_svg: string | null;
  title?: string | null; valid_from?: string | null; daily_start_time?: string | null; daily_end_time?: string | null;
  needs_consent?: boolean; notices?: Record<string, { id: string; version: number; body: string }> | null; locales?: string[];
}
export interface VisitForHost {
  id: string; status: VisitStatusName; visitor_name: string | null; visitor_company: string | null; visitor_phone: string | null;
  photo_url: string | null; purpose: string | null; purpose_i18n: Record<string, string>; purpose_note: string | null; accompanying_count: number; vehicle_number: string | null;
  custom_values: Record<string, unknown>; id_type: string | null; id_last4: string | null; site_name: string; gate_name: string | null;
  host_name: string; requested_at: string; responded_at: string | null; host_message: string | null; can_respond: boolean;
}

export function label(item: { label: string; label_i18n: Record<string, string> }, lang: string) {
  return item.label_i18n[lang] || item.label;
}
