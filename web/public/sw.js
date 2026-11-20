/*
 * Service worker for web push alerts only (see api/app/notifications/push.py).
 * It has no fetch handler on purpose: it never caches or intercepts pages, so the app
 * behaves exactly as it does without it.
 */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let d = {};
  try {
    d = event.data ? event.data.json() : {};
  } catch {
    d = { title: "VMS", body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(
    self.registration.showNotification(d.title || "VMS", {
      body: d.body || "",
      tag: d.tag,
      renotify: true,
      // A visitor waiting at the gate: keep it on screen until the host acts.
      requireInteraction: !!d.respond_token,
      icon: "/icon.svg",
      data: d,
      actions: d.actions || [],
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  const d = event.notification.data || {};
  event.notification.close();
  if (event.action && d.respond_token) {
    event.waitUntil(answer(d, event.action));
    return;
  }
  event.waitUntil(openPage(d.url || "/host"));
});

// Approve / Decline straight from the notification, through the host's respond link.
async function answer(d, action) {
  const done = d.done || {};
  try {
    const r = await fetch(`/api/v1/public/respond/${encodeURIComponent(d.respond_token)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    if (!r.ok) {
      const body = await r.json().catch(() => null);
      return note(d, body?.error?.message || done.failed || "Couldn't answer. Open the app.");
    }
    return note(d, done[action] || "Done");
  } catch {
    return openPage(d.url || "/host");
  }
}

function note(d, title) {
  return self.registration.showNotification(title, {
    tag: d.tag,
    icon: "/icon.svg",
    data: { url: d.url || "/host" },
  });
}

async function openPage(url) {
  const target = new URL(url, self.location.origin).href;
  const open = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  for (const c of open) {
    if (c.url === target && "focus" in c) return c.focus();
  }
  return self.clients.openWindow(target);
}
