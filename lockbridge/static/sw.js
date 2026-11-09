/* LockBridge service worker: offline app shell + push notifications */
const CACHE = "lockbridge-v4";
const SHELL = ["/static/app.css?v=4", "/static/app.js?v=4", "/static/icons/icon.svg", "/static/icons/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // Page loads go straight to the network, so the browser follows the Cloudflare Access login redirect itself
  if (e.request.mode === "navigate") return;
  // network first, cache as fallback (when the Pi is unreachable, at least the shell loads)
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data.json(); } catch (_) { d = { title: "LockBridge", body: e.data ? e.data.text() : "" }; }
  const actions = [];
  if (["unlock", "door", "automation"].includes(d.category)) actions.push({ action: "lock", title: "🔒 Lock" });
  e.waitUntil(
    self.registration.showNotification(d.title || "LockBridge", {
      body: d.body || "",
      tag: d.tag || undefined,
      renotify: true,
      icon: "/static/icons/icon-192.png",
      badge: "/static/icons/badge-96.png",
      data: { url: d.url || "/#/" },
      actions,
      requireInteraction: d.category === "error",
    })
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  if (e.action === "lock") {
    e.waitUntil(
      fetch("/api/lock", { method: "POST", credentials: "include", headers: { "X-LB": "1" } })
        .then((r) => self.registration.showNotification(r.ok ? "🔒 Locked" : "⚠️ Locking failed", {
          body: r.ok ? "The door is locked." : "Open the app for details.",
          icon: "/static/icons/icon-192.png", tag: "lock-result",
        }))
    );
    return;
  }
  const target = (e.notification.data && e.notification.data.url) || "/#/";
  e.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const c of list) {
        if ("focus" in c) { c.navigate(target).catch(() => {}); return c.focus(); }
      }
      return self.clients.openWindow(target);
    })
  );
});
