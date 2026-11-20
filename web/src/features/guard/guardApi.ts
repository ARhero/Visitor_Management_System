import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useSyncExternalStore } from "react";
import { api, getAccessToken } from "@/lib/api";
import { defaultStore, Outbox, type QueuedAction } from "@/lib/offlineQueue";
import { subscribe } from "@/lib/sse";

export interface GuardSite {
  id: string;
  name: string;
  city: string | null;
  gates: { id: string; name: string }[];
}

export interface GuardCard {
  id: string;
  status: string;
  source: "qr_self" | "guard_manual" | "invite";
  visitor_name: string | null;
  visitor_company: string | null;
  phone_last4: string | null;
  phone_verified?: boolean; // false: typed in without a code, so check their ID
  photo_url: string | null;
  host_name: string;
  purpose: string | null;
  purpose_i18n: Record<string, string>;
  purpose_note: string | null;
  accompanying_count: number;
  vehicle_number: string | null;
  id_type: string | null;
  id_last4: string | null;
  gate_name: string | null;
  requested_at: string;
  approved_at: string | null;
  checked_in_at: string | null;
  checked_out_at: string | null;
  checkout_method: string | null;
  valid_until: string;
  host_message: string | null;
  guard_note: string | null;
  escalated: boolean;
  invite_title: string | null;
  invite_notes: string | null;
  alert: { action: "block" | "alert"; reason: string } | null;
}

export interface ExpectedGuest {
  guest_id: string;
  invite_id: string;
  name: string;
  company: string | null;
  phone_last4: string | null;
  host_name: string;
  kind: string;
  title: string | null;
  notes: string | null;
  valid_from: string;
  valid_until: string;
  daily_start_time: string | null;
  daily_end_time: string | null;
  consented: boolean;
}

export interface GuardQueue {
  site_id: string;
  awaiting: GuardCard[];
  expected: GuardCard[];
  on_site: GuardCard[];
  left: GuardCard[];
  alerts: GuardCard[];
  invites: ExpectedGuest[];
  people_on_site: number;
}

export type ScanResult =
  | "ok" | "inside" | "invalid" | "expired" | "not_yet" | "outside_hours" | "used" | "left"
  | "revoked" | "not_approved" | "wrong_site" | "blocked";

export interface ScanOut {
  result: ScanResult;
  message: string;
  visit: GuardCard | null;
  guest: ExpectedGuest | null;
  site_name: string | null;
}

export interface GuardForm {
  require_selfie: boolean;
  id_proof_mode: "off" | "optional" | "required";
  otp_required: boolean;
  purposes: { id: string; label: string; label_i18n: Record<string, string>; requires_id_proof: boolean }[];
  fields: { key: string; label: string; label_i18n: Record<string, string>; type: string; options: string[]; required: boolean }[];
  notices: Record<string, { id: string; version: number; body: string }>;
}

export const gk = {
  sites: ["guard", "sites"] as const,
  queue: (site: string) => ["guard", "queue", site] as const,
  form: (site: string) => ["guard", "form", site] as const,
};

export const useGuardSites = () => useQuery({ queryKey: gk.sites, queryFn: () => api<GuardSite[]>("/guard/sites") });

export function useQueue(siteId: string) {
  return useQuery({
    queryKey: gk.queue(siteId),
    queryFn: () => api<GuardQueue>("/guard/queue", { query: { site_id: siteId } }),
    refetchInterval: 15_000, // safety net under the live stream
    refetchOnWindowFocus: true,
  });
}

/** Refetch the queue whenever a visit at the site changes. */
export function useLiveQueue(siteId: string) {
  const qc = useQueryClient();
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const stop = subscribe(`/api/v1/guard/stream?site_id=${siteId}`, getAccessToken, (event) => {
      if (event !== "change") return;
      clearTimeout(timer); // a burst of changes → one refetch
      timer = setTimeout(() => void qc.invalidateQueries({ queryKey: gk.queue(siteId) }), 150);
    });
    return () => {
      clearTimeout(timer);
      stop();
    };
  }, [qc, siteId]);
}

// ---------- Check-in / out through the offline outbox ----------

function send(a: QueuedAction) {
  if (a.kind === "pass-check-in") {
    return api<ScanOut>("/guard/pass-check-in", {
      method: "POST",
      body: { ...a.body, occurred_at: a.occurredAt },
      headers: { "Idempotency-Key": a.id },
    });
  }
  return api<GuardCard>(`/guard/visits/${a.visitId}/${a.kind}`, {
    method: "POST",
    body: { ...a.body, occurred_at: a.occurredAt },
    headers: { "Idempotency-Key": a.id },
  });
}

export const outbox = new Outbox(defaultStore(), send);

let started = false;
export function startOutbox(onSynced: () => void) {
  if (started) return;
  started = true;
  void outbox.load().then(() => outbox.flush());
  window.addEventListener("online", () => void outbox.flush().then(onSynced));
  setInterval(() => {
    if (outbox.pending().length) void outbox.flush().then(onSynced);
  }, 15_000);
}

export function useOutbox() {
  const pending = useSyncExternalStore(
    (fn) => outbox.subscribe(fn),
    () => outbox.pending(),
  );
  const failed = useSyncExternalStore(
    (fn) => outbox.subscribe(fn),
    () => outbox.failed,
  );
  return { pending, failed };
}

export function useOnline() {
  return useSyncExternalStore(
    (fn) => {
      window.addEventListener("online", fn);
      window.addEventListener("offline", fn);
      return () => {
        window.removeEventListener("online", fn);
        window.removeEventListener("offline", fn);
      };
    },
    () => navigator.onLine,
  );
}

/** The queue with not-yet-synced taps applied, so the guard sees what they did. */
export function withPending(q: GuardQueue, pending: QueuedAction[]): GuardQueue & { syncing: Set<string> } {
  const syncing = new Set(pending.map((p) => p.visitId));
  if (!pending.length) return { ...q, syncing };
  const all = [...q.awaiting, ...q.expected, ...q.on_site, ...q.left];
  const byId = new Map(all.map((c) => [c.id, c]));
  const moved = new Map<string, GuardCard>();
  for (const p of pending) {
    const c = moved.get(p.visitId) ?? byId.get(p.visitId);
    if (!c) continue;
    moved.set(
      p.visitId,
      p.kind !== "check-out"
        ? { ...c, status: "checked_in", checked_in_at: p.occurredAt }
        : { ...c, status: "checked_out", checked_out_at: p.occurredAt, checkout_method: "guard" },
    );
  }
  const pick = (status: string[]) => all.map((c) => moved.get(c.id) ?? c).filter((c) => status.includes(c.status));
  const dedupe = (cs: GuardCard[]) => [...new Map(cs.map((c) => [c.id, c])).values()];
  const on_site = dedupe(pick(["checked_in"]));
  return {
    ...q,
    awaiting: dedupe(pick(["pending", "waiting"])),
    expected: dedupe(pick(["approved"])),
    on_site,
    left: dedupe(pick(["checked_out"])),
    people_on_site: on_site.reduce((n, c) => n + 1 + c.accompanying_count, 0),
    syncing,
  };
}
