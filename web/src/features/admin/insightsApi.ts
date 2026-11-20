import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { api, getAccessToken } from "@/lib/api";
import { subscribe } from "@/lib/sse";

export interface Live {
  at: string;
  on_site: number;
  people_on_site: number;
  waiting_for_host: number;
  approved_not_arrived: number;
  today: { requests: number; checked_in: number; checked_out: number; rejected: number; expired: number; blocked: number };
  median_wait_seconds_today: number | null;
  by_gate: { site: string; gate: string; check_ins: number }[];
  by_hour: number[];
  by_site: { site_id: string; site: string; on_site: number; people: number }[];
  recent: { at: string; visit_id: string; visitor: string | null; site: string; to: string; from: string | null; actor: string }[];
}

export interface VisitRow {
  id: string;
  status: string;
  source: string;
  visitor_name: string | null;
  visitor_company: string | null;
  visitor_phone: string | null;
  host_id: string;
  host_name: string;
  department: string | null;
  site_id: string;
  site_name: string;
  gate_name: string | null;
  purpose: string | null;
  purpose_note: string | null;
  accompanying_count: number;
  vehicle_number: string | null;
  requested_at: string;
  responded_at: string | null;
  response_channel: string | null;
  checked_in_at: string | null;
  checked_out_at: string | null;
  checkout_method: string | null;
  wait_seconds: number | null;
  guard_note: string | null;
  flagged: boolean;
  anonymized: boolean;
}

export interface VisitDetail extends VisitRow {
  photo_url: string | null;
  id_type: string | null;
  id_last4: string | null;
  custom_values: Record<string, unknown>;
  host_message: string | null;
  invite_title: string | null;
  alert_reason: string | null;
  consent: { version: number; locale: string; at: string } | null;
  timeline: { at: string; from_status: string | null; to_status: string; actor_type: string; actor_name: string | null; channel: string; meta: Record<string, unknown> }[];
  messages: { at: string; template: string; direction: string; status: string; to: string | null }[];
}

export interface VisitPage {
  items: VisitRow[];
  next_cursor: string | null;
  total: number | null;
}

export interface Filters {
  from?: string;
  to?: string;
  site_id?: string;
  host_id?: string;
  status?: string;
  q?: string;
}

export interface Traffic {
  days: { day: string; requests: number; checked_in: number; rejected: number; expired: number }[];
  totals: Record<"requests" | "visits" | "people" | "rejected" | "expired" | "cancelled" | "unique_visitors" | "flagged", number>;
  by_source: Record<"qr_self" | "guard_manual" | "invite", number>;
  by_purpose: { label: string; visits: number }[];
}
export interface PeakHours { grid: number[][]; busiest: { weekday: number; hour: number; check_ins: number } | null }
export interface TopHost { host_id: string; host_name: string; department: string | null; visits: number; approved: number; median_wait_seconds: number | null }
export interface DepartmentRow { department: string; visits: number; hosts: number }
export interface ApprovalTimes {
  answered: number;
  unanswered: number;
  median_seconds: number | null;
  p90_seconds: number | null;
  buckets: { label: string; max_seconds: number | null; count: number }[];
  by_channel: { whatsapp: number; web: number };
  escalated: number;
  overrides: number;
}

export interface ExportJob {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "failed" | "expired";
  file_name: string | null;
  row_count: number | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  expires_at: string | null;
}

export interface Evacuation {
  at: string;
  site_id: string | null;
  site_name: string | null;
  visits: number;
  people: number;
  rows: {
    visit_id: string; visitor_name: string | null; visitor_company: string | null; visitor_phone: string | null; photo_url: string | null;
    host_name: string; host_phone: string | null; site_name: string; gate_name: string | null; accompanying_count: number; checked_in_at: string | null;
  }[];
  contacts: { name: string; phone: string }[];
}

/** Refetch ``keys`` whenever a visit changes anywhere in the org (debounced). */
export function useOrgLive(keys: readonly (readonly unknown[])[]) {
  const qc = useQueryClient();
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const stop = subscribe("/api/v1/dashboard/stream", getAccessToken, (event) => {
      if (event !== "change") return;
      clearTimeout(timer);
      timer = setTimeout(() => keys.forEach((k) => void qc.invalidateQueries({ queryKey: k })), 400);
    });
    return () => {
      clearTimeout(timer);
      stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qc, JSON.stringify(keys)]);
}

export const useLive = (siteId: string) =>
  useQuery({
    queryKey: ["dashboard", "live", siteId],
    queryFn: () => api<Live>("/dashboard/live", { query: { site_id: siteId || undefined } }),
    refetchInterval: 30_000,
  });

/** IST date (YYYY-MM-DD) ``days`` ago. */
export function istDay(daysAgo = 0): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date(Date.now() - daysAgo * 86_400_000));
}

export const STATUS_LABEL: Record<string, string> = {
  pending: "Waiting for host",
  waiting: "Asked to wait",
  approved: "Approved",
  rejected: "Declined",
  checked_in: "On site",
  checked_out: "Left",
  expired: "Expired",
  cancelled: "Cancelled",
};
export const STATUS_TONE: Record<string, "ok" | "warn" | "bad" | "neutral" | "brand"> = {
  pending: "warn", waiting: "warn", approved: "ok", checked_in: "brand", checked_out: "neutral", rejected: "bad", expired: "neutral", cancelled: "neutral",
};
export const SOURCE_LABEL: Record<string, string> = { qr_self: "Self check-in", guard_manual: "At the desk", invite: "Invite" };
