/**
 * Checking passes with no connection.
 *
 * While online, the console keeps an "offline pack" for its site: the public key that
 * signs passes and today's expected passes (approved visits, people inside, invite
 * guests), each keyed by SHA-256 of the pass's random id. When a scan can't reach the
 * server, the pass's signature is checked on the device, the hash looked up, and the
 * guard sees who it is. A check-in made that way is queued and replayed through
 * /guard/pass-check-in, where the server repeats every check (revoked, used, blacklisted
 * since) before letting it count.
 *
 * The pack holds names for today only. It lives in this tab's sessionStorage and is
 * dropped at the end of the day and on sign-out.
 */
import { useEffect, useSyncExternalStore } from "react";
import { api } from "@/lib/api";

export interface OfflineEntry {
  h: string;
  kind: "visit" | "invite";
  ref_id: string;
  name: string;
  company: string | null;
  host_name: string;
  purpose: string | null;
  state: "approved" | "checked_in" | "invite";
  accompanying_count: number;
  valid_from: string | null;
  valid_until: string;
  daily_start_time: string | null;
  daily_end_time: string | null;
  consented: boolean;
  photo_url: string | null;
  alert: { action: "block" | "alert"; reason: string } | null;
}

export interface OfflinePack {
  site_id: string;
  generated_at: string;
  use_until: string;
  key: { kty: string; crv: string; x: string };
  entries: OfflineEntry[];
}

export type OfflineResult =
  | { status: "invalid" | "expired" | "unknown"; entry?: undefined }
  | { status: "ok" | "inside" | "not_yet" | "outside_hours" | "no_consent" | "blocked"; entry: OfflineEntry };

const REFRESH_MS = 60_000;
const storeKey = (site: string) => `vms.pack.${site}`;
const packs = new Map<string, OfflinePack>();
const listeners = new Set<() => void>();

function usable(p: OfflinePack | null | undefined): OfflinePack | null {
  return p && new Date(p.use_until).getTime() > Date.now() ? p : null;
}

export function getPack(siteId: string): OfflinePack | null {
  let p = packs.get(siteId);
  if (!p) {
    try {
      const raw = sessionStorage.getItem(storeKey(siteId));
      if (raw) packs.set(siteId, (p = JSON.parse(raw) as OfflinePack));
    } catch {
      /* private mode: memory only */
    }
  }
  return usable(p);
}

function setPack(p: OfflinePack) {
  packs.set(p.site_id, p);
  try {
    sessionStorage.setItem(storeKey(p.site_id), JSON.stringify(p));
  } catch {
    /* quota / private mode: memory only */
  }
  listeners.forEach((l) => l());
}

/** Forget every pack (sign-out). */
export function clearPacks() {
  packs.clear();
  try {
    for (const k of Object.keys(sessionStorage)) if (k.startsWith("vms.pack.")) sessionStorage.removeItem(k);
  } catch {
    /* nothing stored */
  }
  listeners.forEach((l) => l());
}

async function refresh(siteId: string) {
  if (!navigator.onLine) return;
  try {
    const p = await api<OfflinePack>("/guard/offline-pack", { query: { site_id: siteId } });
    setPack(p);
    // Warm the browser cache with today's photos, so they can show offline too.
    for (const e of p.entries) if (e.photo_url && e.state !== "checked_in") new Image().src = e.photo_url;
  } catch {
    /* keep the last pack; try again next time */
  }
}

/** Keep the site's pack fresh while the console is open (and get the QR decoder ready,
 *  so the camera works after the connection drops). Used once, by the console. */
export function useKeepPackFresh(siteId: string) {
  useEffect(() => {
    void refresh(siteId);
    void import("@/lib/scanner").then((m) => m.preloadDecoder());
    const id = setInterval(() => void refresh(siteId), REFRESH_MS);
    const online = () => void refresh(siteId);
    window.addEventListener("online", online);
    return () => {
      clearInterval(id);
      window.removeEventListener("online", online);
    };
  }, [siteId]);
}

export function usePack(siteId: string): OfflinePack | null {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    () => getPack(siteId),
  );
}

// ---------- Verifying a pass on the device ----------

const b64url = (s: string) => {
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
};

/** The QR holds the bare token; a pass link (…/p/<token>) works too. */
export function tokenFrom(payload: string): string {
  const s = payload.trim();
  const i = s.lastIndexOf("/p/");
  return (i >= 0 ? s.slice(i + 3) : s).split(/[?#]/)[0];
}

async function signatureOk(key: OfflinePack["key"], signed: Uint8Array, sig: Uint8Array): Promise<boolean> {
  try {
    const k = await crypto.subtle.importKey("jwk", { kty: "OKP", crv: "Ed25519", x: key.x }, { name: "Ed25519" }, false, ["verify"]);
    return await crypto.subtle.verify({ name: "Ed25519" }, k, sig, signed);
  } catch {
    // Older browsers without Ed25519 in WebCrypto: a small audited library instead.
    const ed = await import("@noble/ed25519");
    try {
      return await ed.verifyAsync(sig, signed, b64url(key.x));
    } catch {
      return false;
    }
  }
}

async function sha256Hex(s: string): Promise<string> {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
  return [...d].map((b) => b.toString(16).padStart(2, "0")).join("");
}

const IST_OFFSET_MIN = 330;
function istMinutes(d: Date) {
  return (d.getUTCHours() * 60 + d.getUTCMinutes() + IST_OFFSET_MIN) % 1440;
}
const hm = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));
const EARLY_MIN = 30; // as on the server: guests may arrive a little early

export async function checkOffline(payload: string, pack: OfflinePack, at = new Date()): Promise<OfflineResult> {
  const token = tokenFrom(payload);
  const parts = token.split(".");
  if (parts.length !== 3) return { status: "invalid" };
  let claims: { jti?: string; exp?: number };
  try {
    const header = JSON.parse(new TextDecoder().decode(b64url(parts[0]))) as { alg?: string };
    if (header.alg !== "EdDSA") return { status: "invalid" };
    claims = JSON.parse(new TextDecoder().decode(b64url(parts[1])));
  } catch {
    return { status: "invalid" };
  }
  const ok = await signatureOk(pack.key, new TextEncoder().encode(`${parts[0]}.${parts[1]}`), b64url(parts[2]));
  if (!ok || !claims.jti || !claims.exp) return { status: "invalid" };
  if (claims.exp * 1000 <= at.getTime()) return { status: "expired" };

  const h = await sha256Hex(claims.jti);
  const entry = pack.entries.find((e) => e.h === h);
  if (!entry) return { status: "unknown" };
  if (entry.state === "checked_in") return { status: "inside", entry };
  if (entry.alert?.action === "block") return { status: "blocked", entry };
  if (new Date(entry.valid_until).getTime() <= at.getTime()) return { status: "expired" };
  if (entry.kind === "invite") {
    if (entry.valid_from && new Date(entry.valid_from).getTime() - EARLY_MIN * 60_000 > at.getTime()) return { status: "not_yet", entry };
    if (entry.daily_start_time && entry.daily_end_time) {
      const m = istMinutes(at);
      if (m < hm(entry.daily_start_time) - EARLY_MIN || m > hm(entry.daily_end_time)) return { status: "outside_hours", entry };
    }
    if (!entry.consented) return { status: "no_consent", entry };
  }
  return { status: "ok", entry };
}
