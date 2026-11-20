/**
 * Web push alerts for staff (hosts, mostly): visitor requests show up as phone
 * notifications, with Approve / Decline buttons, even when the app is closed.
 * The service worker is public/sw.js; the server side is api/app/notifications/push.py.
 */
import { api } from "./api";

export type PushState =
  | "unsupported" // this browser can't do push
  | "needs-install" // iPhone/iPad: only works from an app added to the home screen
  | "denied" // the person blocked notifications for this site
  | "off"
  | "on";

const SW = "/sw.js";

function supported() {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function isIOS() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

function standalone() {
  return window.matchMedia?.("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone === true;
}

async function currentSubscription(): Promise<PushSubscription | null> {
  const reg = await navigator.serviceWorker.getRegistration(SW);
  return (await reg?.pushManager.getSubscription()) ?? null;
}

export async function pushState(): Promise<PushState> {
  if (!supported()) return isIOS() && !standalone() ? "needs-install" : "unsupported";
  if (Notification.permission === "denied") return "denied";
  if (Notification.permission !== "granted") return "off";
  return (await currentSubscription()) ? "on" : "off";
}

function keyBytes(b64url: string): Uint8Array<ArrayBuffer> {
  const b64 = (b64url + "=".repeat((4 - (b64url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export interface PushInfo { public_key: string; devices: number }

/** Ask for permission, subscribe this browser and register it for the signed-in person. */
export async function enablePush(): Promise<PushInfo> {
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error(perm === "denied" ? "denied" : "dismissed");
  const reg = await navigator.serviceWorker.register(SW);
  await navigator.serviceWorker.ready;
  const info = await api<PushInfo>("/push");
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(info.public_key) });
  }
  return api<PushInfo>("/push/subscriptions", { method: "POST", body: sub.toJSON() });
}

/** Re-register an existing subscription (the browser may be shared, or the server reset). */
export async function syncPush(): Promise<void> {
  if (!supported() || Notification.permission !== "granted") return;
  const sub = await currentSubscription();
  if (sub) await api("/push/subscriptions", { method: "POST", body: sub.toJSON() });
}

export async function disablePush(): Promise<void> {
  if (!supported()) return;
  const sub = await currentSubscription();
  if (!sub) return;
  await api("/push/unsubscribe", { method: "POST", body: { endpoint: sub.endpoint } }).catch(() => undefined);
  await sub.unsubscribe();
}

export function testPush(): Promise<PushInfo> {
  return api<PushInfo>("/push/test", { method: "POST" });
}
