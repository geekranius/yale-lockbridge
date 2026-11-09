"use strict";
/* LockBridge – web UI (no build step, plain JavaScript) */

// ======================================================================= helpers
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const svg = (p, cls = "i") => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const I = {
  lock: svg('<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>'),
  unlock: svg('<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.8-1.2"/>'),
  door: svg('<path d="M5 21V4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v17"/><path d="M3 21h18"/><circle cx="15" cy="12" r="1"/>'),
  doorOpen: svg('<path d="M13 4h5a1 1 0 0 1 1 1v16"/><path d="M3 21h18"/><path d="M5 21V4.5l8-1.5v18"/><circle cx="10" cy="12" r="1"/>'),
  battery: svg('<rect x="2" y="7" width="18" height="10" rx="2"/><path d="M22 11v2"/>'),
  signal: svg('<path d="M2 20h.01M7 20v-4M12 20v-8M17 20V8M22 4v16"/>'),
  clock: svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
  home: svg('<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/>'),
  list: svg('<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>'),
  bolt: svg('<path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>'),
  gear: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
  user: svg('<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>'),
  users: svg('<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0"/><path d="M16 4a4 4 0 0 1 0 8M22 21a7 7 0 0 0-4-6.3"/>'),
  plug: svg('<path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0V8zM12 18v4"/>'),
  server: svg('<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>'),
  bell: svg('<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>'),
  shield: svg('<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'),
  alert: svg('<path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>'),
  check: svg('<path d="M20 6L9 17l-5-5"/>'),
  x: svg('<path d="M18 6L6 18M6 6l12 12"/>'),
  chev: svg('<path d="M9 18l6-6-6-6"/>', "i chev"),
  plus: svg('<path d="M12 5v14M5 12h14"/>'),
  play: svg('<path d="M6 4l14 8-14 8z"/>'),
  edit: svg('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>'),
  trash: svg('<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>'),
  download: svg('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>'),
  phone: svg('<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>'),
  bt: svg('<path d="M7 7l10 10-5 5V2l5 5L7 17"/>'),
  refresh: svg('<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>'),
  key: svg('<circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.7 12.3L21 2M16 7l3 3M18 5l2 2"/>'),
  logout: svg('<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>'),
  light: svg('<path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/>'),
};
const bigLock = svg('<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/><path d="M12 15v2"/>', "big");
const bigUnlock = svg('<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.8-1.2"/><path d="M12 15v2"/>', "big");
const bigAlert = svg('<path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>', "big");

const S = { boot: null, user: null, status: null, sse: null, installPrompt: null, live: [] };
const ROLE = { admin: "Administrator", user: "User", guest: "Guest" };
const RANK = { guest: 0, user: 1, admin: 2 };
const isAdmin = () => S.user && S.user.role === "admin";
const canLogs = () => S.user && RANK[S.user.role] >= 1;
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

class ApiError extends Error {
  constructor(status, msg) { super(msg); this.status = status; }
}

async function api(path, method = "GET", data) {
  const opt = { method, credentials: "same-origin", headers: { "X-LB": "1" } };
  if (data !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(data); }
  let res;
  try { res = await fetch(path, opt); } catch (e) { throw new ApiError(0, "Server unavailable. Check your connection."); }
  const ct = res.headers.get("content-type") || "";
  const body = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
    const msg = (body && body.detail) || `Error ${res.status}`;
    if (res.status === 401 && !path.startsWith("/api/login") && !path.startsWith("/api/setup")) { boot(); }
    throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return body;
}

function toast(msg, type = "") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), type === "err" ? 6000 : 3500);
}

function fmtTime(ts) { return new Date(ts * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }); }
function fmtDateTime(ts) { return ts ? new Date(ts * 1000).toLocaleString("en-GB", { day: "numeric", month: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "–"; }
function fmtDay(ts) {
  const d = new Date(ts * 1000), t = new Date();
  const y = new Date(); y.setDate(t.getDate() - 1);
  if (d.toDateString() === t.toDateString()) return "Today";
  if (d.toDateString() === y.toDateString()) return "Yesterday";
  return d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
}
function ago(ts) {
  if (!ts) return "–";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return fmtDateTime(ts);
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function formData(form) {
  const o = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") o[el.name] = el.checked;
    else if (el.type === "number") o[el.name] = el.value === "" ? null : Number(el.value);
    else o[el.name] = el.value;
  }
  return o;
}
async function withBusy(btn, fn) {
  if (btn) btn.disabled = true;
  try { return await fn(); } catch (e) { toast(e.message, "err"); } finally { if (btn) btn.disabled = false; }
}

function modal(title, html, { wide } = {}) {
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal" role="dialog" aria-modal="true" ${wide ? 'style="max-width:760px"' : ""}>
    <div class="head"><h2>${esc(title)}</h2><button class="btn ghost small" data-close aria-label="Close">${I.x}</button></div>
    <div class="body">${html}</div></div>`;
  const close = () => { bg.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) close(); });
  document.addEventListener("keydown", onKey);
  document.body.append(bg);
  return { el: $(".modal", bg), close };
}

function confirmDialog(title, text, okLabel = "Confirm", danger = false) {
  return new Promise((resolve) => {
    const m = modal(title, `<p>${esc(text)}</p><div class="row" style="justify-content:flex-end">
      <button class="btn" data-no>Cancel</button><button class="btn ${danger ? "danger" : "primary"}" data-yes>${esc(okLabel)}</button></div>`);
    $("[data-no]", m.el).onclick = () => { m.close(); resolve(false); };
    $("[data-yes]", m.el).onclick = () => { m.close(); resolve(true); };
  });
}

// ======================================================================= PWA: instalacija i push
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); S.installPrompt = e; if (location.hash === "" || location.hash === "#/") route(); });
window.addEventListener("appinstalled", () => { S.installPrompt = null; toast("App installed ✓", "ok"); route(); });
const isStandalone = () => window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const pubUrl = () => (S.boot && S.boot.public_url) || "";

function qrBlock() {
  const pub = pubUrl();
  if (!pub) return "";
  return `<div class="qr"><img src="/api/install/qr" alt="QR code" style="width:200px;height:200px"></div>
    <p style="text-align:center"><a class="btn small primary" href="${esc(pub)}" target="_blank" rel="noopener">Open ${esc(pub.replace(/^https?:\/\//, ""))}</a></p>`;
}

async function installApp() {
  if (S.installPrompt) {
    S.installPrompt.prompt();
    const choice = await S.installPrompt.userChoice.catch(() => null);
    if (choice && choice.outcome === "accepted") toast("Installation started…", "ok");
    S.installPrompt = null;
    route();
    return;
  }
  if (!window.isSecureContext) {
    modal("HTTPS required", `<p>Your browser only allows app installation and notifications over a <b>HTTPS</b> connection, and this address is plain HTTP (<code>${esc(location.origin)}</code>).</p>
      ${pubUrl() ? `<p>Open this address on your phone (scan the QR code):</p>${qrBlock()}`
        : `<p class="muted">Public address is not set yet. On the Pi, run:<br><code>sudo ./install.sh --public-url=https://door.yourdomain.com</code></p>`}`);
    return;
  }
  if (isIOS()) {
    modal("Install on iPhone", `<ol class="steps">
      <li>Open this page in <b>Safari</b>.</li>
      <li>Tap the <b>Share</b> button (square with an arrow pointing up).</li>
      <li>Choose <b>Add to Home Screen</b>.</li>
      <li>Open the app from the Home Screen and turn on notifications in Settings → My Account.</li></ol>
      <p class="muted">Notifications on iPhone work from iOS 16.4 onwards, and only when the app is added to the Home Screen.</p>`);
    return;
  }
  modal("Install app", `<p>In the browser menu (⋮), choose <b>Install app</b> or <b>Add to Home Screen</b>.</p>
    <p class="muted">If the button isn't available, refresh the page and wait a few seconds.</p>`);
}

function installCard() {
  if (isStandalone()) return `<div class="alert ok">${I.check} App installed.</div>
    <p class="muted">Turn on notifications in the card below.</p>`;
  if (!window.isSecureContext) return `
    <div class="alert warn">${I.alert}<div>This address is <b>HTTP</b> – your browser won't allow installation or notifications here. Open the app over an HTTPS address.</div></div>
    ${pubUrl() ? `<p>Scan the QR code with your phone:</p>${qrBlock()}` : `<p class="muted">Public address is not set (LB_PUBLIC_URL).</p>`}`;
  return `<p>Install LockBridge on your Home Screen – it works like a real app, with an icon and notifications.</p>
    <button class="btn primary" id="inst">${I.download} Install app</button>`;
}

function b64ToU8(b64) {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}
const pushSupported = () => "serviceWorker" in navigator && "PushManager" in window && window.isSecureContext;

async function pushState() {
  if (!pushSupported()) return "unsupported";
  const reg = await navigator.serviceWorker.getRegistration();
  if (!reg) return "off";
  const sub = await reg.pushManager.getSubscription();
  if (Notification.permission === "denied") return "denied";
  return sub ? "on" : "off";
}

async function enablePush() {
  if (!pushSupported()) throw new Error(window.isSecureContext ? "This browser doesn't support push notifications." : "Notifications require an HTTPS connection – open the app via the Cloudflare address.");
  if (isIOS() && !isStandalone()) throw new Error("On iPhone, first add the app to your Home Screen.");
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("Notifications are blocked in your browser.");
  const reg = await navigator.serviceWorker.ready;
  const { key } = await api("/api/push/key");
  let sub = await reg.pushManager.getSubscription();
  if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToU8(key) });
  await api("/api/push/subscribe", "POST", sub.toJSON());
}

async function disablePush() {
  const reg = await navigator.serviceWorker.getRegistration();
  const sub = reg && (await reg.pushManager.getSubscription());
  if (sub) {
    await api("/api/push/unsubscribe", "POST", { endpoint: sub.endpoint });
    await sub.unsubscribe();
  }
}

if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
}

// ======================================================================= live veza (SSE)
function connectStream() {
  if (S.sse) S.sse.close();
  const es = new EventSource("/api/stream");
  S.sse = es;
  es.addEventListener("status", (e) => { S.status = JSON.parse(e.data); onStatus(); });
  es.addEventListener("event", (e) => {
    const ev = JSON.parse(e.data);
    S.live.unshift(ev);
    S.live = S.live.slice(0, 50);
    onLiveEvent(ev);
  });
  es.addEventListener("event_update", (e) => {
    const ev = JSON.parse(e.data);
    const old = S.live.find((x) => x.id === ev.id);
    if (old) Object.assign(old, ev);
    onLiveEvent(ev, true);
  });
  es.onopen = () => setConn(true);
  es.onerror = () => { setConn(false); };
}
function setConn(ok) {
  $$(".conn-dot").forEach((d) => (d.className = "dot conn-dot " + (ok ? "ok" : "err")));
  $$(".conn-text").forEach((t) => (t.textContent = ok ? "live" : "offline"));
}

// ======================================================================= boot i auth
async function boot() {
  try { S.boot = await api("/api/bootstrap"); } catch (e) { $("#root").innerHTML = authCard("No connection", `<p class="lead">${esc(e.message)}</p><button class="btn primary block" onclick="location.reload()">Try again</button>`); return; }
  const b = S.boot;
  document.title = `LockBridge – ${b.site_name}`;
  if (b.setup_needed) return renderSetup();
  if (b.stage === "enroll") return renderEnroll(b);
  if (b.stage === "totp") return renderTotp();
  if (!b.user) return renderLogin();
  S.user = b.user;
  if (S.user.must_change_pw) return renderForcePw();
  renderShell();
  connectStream();
  route();
}

function authCard(title, inner) {
  return `<div class="auth"><div class="card"><img class="logo" src="/static/icons/icon-192.png" alt="">
    <h1>${esc(title)}</h1>${inner}</div></div>`;
}
function bindAuthForm(handler) {
  const f = $("#root form");
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("button[type=submit]", f);
    const err = $(".form-err", f);
    err.classList.add("hide");
    btn.disabled = true;
    try { await handler(formData(f)); } catch (ex) { err.textContent = ex.message; err.classList.remove("hide"); }
    finally { btn.disabled = false; }
  });
  const first = $("input", f); if (first) first.focus();
}

function renderSetup() {
  $("#root").innerHTML = authCard("Welcome!", `<p class="lead">Create an administrator account. You'll set up two-factor authentication (2FA) next.</p>
    <form autocomplete="on">
      <div class="alert err hide form-err"></div>
      <div class="field"><label>Display name</label><input type="text" name="display_name" placeholder="e.g. Alex" required></div>
      <div class="field"><label>Username</label><input type="text" name="username" autocomplete="username" autocapitalize="none" required minlength="3"></div>
      <div class="field"><label>Password</label><input type="password" name="password" autocomplete="new-password" required minlength="10">
        <div class="hint">At least 10 characters, including uppercase, lowercase and a number.</div></div>
      <button class="btn primary block" type="submit">Continue</button>
    </form>`);
  bindAuthForm(async (d) => { const r = await api("/api/setup/admin", "POST", d); renderEnroll(r); });
}

function renderLogin() {
  $("#root").innerHTML = authCard(S.boot.site_name, `<p class="lead">Sign in to manage your door.</p>
    <form autocomplete="on">
      <div class="alert err hide form-err"></div>
      <div class="field"><label>Username</label><input type="text" name="username" autocomplete="username" autocapitalize="none" required></div>
      <div class="field"><label>Password</label><input type="password" name="password" autocomplete="current-password" required></div>
      <button class="btn primary block" type="submit">Sign in</button>
    </form>${S.boot.https ? "" : `<p class="muted" style="margin-top:14px;font-size:.8rem;text-align:center">⚠️ Connection is not HTTPS – use the Cloudflare address for the app and notifications.</p>`}`);
  bindAuthForm(async (d) => {
    const r = await api("/api/login", "POST", d);
    if (r.stage === "enroll") renderEnroll(r); else renderTotp();
  });
}

function renderTotp() {
  $("#root").innerHTML = authCard("Two-factor verification", `<p class="lead">Enter the 6-digit code from your authenticator app.</p>
    <form autocomplete="off">
      <div class="alert err hide form-err"></div>
      <div class="field"><input class="otp" type="text" name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}" required></div>
      <button class="btn primary block" type="submit">Confirm</button>
      <button class="btn ghost block" type="button" id="back">Back</button>
    </form>`);
  $("#back").onclick = async () => { await api("/api/logout", "POST").catch(() => {}); boot(); };
  bindAuthForm(async (d) => { await api("/api/login/totp", "POST", d); boot(); });
  autoSubmitOtp();
}

function renderEnroll(r) {
  $("#root").innerHTML = authCard("Set up 2FA", `<ol class="steps">
      <li>Install an authenticator app (Google Authenticator, Microsoft Authenticator, 2FAS, Aegis, 1Password…).</li>
      <li>Scan the QR code or enter the secret key manually.</li>
      <li>Enter the 6-digit code shown in the app.</li></ol>
    <div class="qr">${r.qr}</div>
    <details style="margin-bottom:14px"><summary class="muted">Enter key manually</summary><div class="secret" style="margin-top:8px">${esc(r.secret)}</div></details>
    <form autocomplete="off">
      <div class="alert err hide form-err"></div>
      <div class="field"><input class="otp" type="text" name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" required></div>
      <button class="btn primary block" type="submit">Activate 2FA</button>
    </form>`);
  bindAuthForm(async (d) => { await api("/api/login/enroll", "POST", d); toast("2FA activated ✓", "ok"); boot(); });
  autoSubmitOtp();
}

function autoSubmitOtp() {
  const inp = $("input.otp");
  inp.addEventListener("input", () => {
    inp.value = inp.value.replace(/\D/g, "").slice(0, 6);
    if (inp.value.length === 6) $("#root form").requestSubmit();
  });
}

function renderForcePw() {
  $("#root").innerHTML = authCard("New password", `<p class="lead">An administrator has set a temporary password for you. Set your own.</p>
    <form><div class="alert err hide form-err"></div>
      <div class="field"><label>Temporary password</label><input type="password" name="old" autocomplete="current-password" required></div>
      <div class="field"><label>New password</label><input type="password" name="new" autocomplete="new-password" required minlength="10">
        <div class="hint">At least 10 characters, including uppercase, lowercase and a number.</div></div>
      <button class="btn primary block" type="submit">Save</button></form>`);
  bindAuthForm(async (d) => { await api("/api/me/password", "POST", d); toast("Password changed ✓", "ok"); boot(); });
}

// ======================================================================= ljuska i router
function navItems() {
  const items = [["#/", "Home", I.home]];
  if (canLogs()) items.push(["#/logs", "Log", I.list]);
  if (isAdmin()) items.push(["#/automations", "Automations", I.bolt]);
  items.push(["#/settings", "Settings", I.gear]);
  return items;
}

function renderShell() {
  const nav = navItems();
  $("#root").innerHTML = `<div class="app">
    <nav class="sidebar"><div class="brand"><img src="/static/icons/icon-192.png" alt="">LockBridge</div>
      ${nav.map(([h, t, i]) => `<a href="${h}" data-nav="${h}">${i}<span>${t}</span></a>`).join("")}
      <div style="position:absolute;bottom:18px;left:12px;right:12px" class="muted">
        <div class="conn"><span class="dot conn-dot"></span><span class="conn-text">connecting…</span></div>
        <div style="font-size:.8rem;margin-top:6px">${esc(S.user.display_name)} · ${ROLE[S.user.role]}</div></div>
    </nav>
    <main id="page"></main>
    <nav class="bottomnav">${nav.map(([h, t, i]) => `<a href="${h}" data-nav="${h}">${i}<span>${t}</span></a>`).join("")}</nav>
  </div>`;
}

const ROUTES = {
  "": pageHome, "logs": pageLogs, "automations": pageAutomations, "settings": pageSettings,
  "settings/account": pageAccount, "settings/users": pageUsers, "settings/lock": pageLockSetup,
  "settings/integrations": pageIntegrations, "settings/system": pageSystem,
};
let currentPage = "";
function route() {
  if (!S.user || !$("#page")) return;
  const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
  const fn = ROUTES[path] || pageHome;
  currentPage = ROUTES[path] ? path : "";
  const top = "#/" + currentPage.split("/")[0];
  $$("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === (top === "#/" ? "#/" : top)));
  const page = $("#page");
  page.innerHTML = "";
  window.scrollTo(0, 0);
  fn(page, new URLSearchParams(query || "")).catch((e) => { page.innerHTML = `<div class="alert err">${esc(e.message)}</div>`; });
}
window.addEventListener("hashchange", route);

function topbar(title, extra = "") {
  return `<div class="topbar"><h1>${esc(title)}</h1><div class="row">${extra}
    <span class="conn"><span class="dot conn-dot ${S.sse && S.sse.readyState === 1 ? "ok" : ""}"></span><span class="conn-text">${S.sse && S.sse.readyState === 1 ? "live" : ""}</span></span></div></div>`;
}
function backbar(title) {
  return `<div class="topbar"><div class="row"><a class="btn ghost small" href="#/settings" aria-label="Back">${svg('<path d="M15 18l-6-6 6-6"/>')}</a><h1>${esc(title)}</h1></div></div>`;
}

function onStatus() {
  if (currentPage === "") updateHome();
}
function onLiveEvent(ev, isUpdate) {
  if (currentPage === "") renderRecent();
  if (currentPage === "logs" && !isUpdate && logsAppendLive) logsAppendLive(ev);
  if (!isUpdate && ["jammed", "battery_critical", "lock_unavailable"].includes(ev.type)) toast(ev.message, "err");
}

// ======================================================================= POČETNA
const EV_STYLE = {
  unlocked: ["warn", I.unlock], unlatched: ["warn", I.doorOpen], locked: ["ok", I.lock],
  door_opened: ["accent", I.doorOpen], door_closed: ["accent", I.door], door_ajar: ["warn", I.doorOpen],
  battery_low: ["warn", I.battery], battery_critical: ["err", I.battery], battery_ok: ["ok", I.battery],
  jammed: ["err", I.alert], error: ["err", I.alert], lock_unavailable: ["err", I.bt], lock_available: ["ok", I.bt],
  login: ["", I.user], login_failed: ["err", I.shield], user_changed: ["", I.users], automation: ["accent", I.bolt],
  system: ["", I.server],
};
function evRow(e) {
  const [cls, ic] = EV_STYLE[e.type] || (e.level === "error" ? ["err", I.alert] : ["", I.clock]);
  return `<div class="ev" data-id="${e.id ?? ""}"><div class="ico-wrap ${cls}">${ic}</div>
    <div class="m">${esc(e.message)}<div class="t">${fmtTime(e.ts)}${e.source ? " · " + esc(e.source) : ""}</div></div></div>`;
}

async function pageHome(el, q) {
  el.innerHTML = `${topbar(S.boot.site_name)}
    <div id="home-alerts"></div>
    <div class="card hero">
      <button class="lockbtn" id="lockbtn" aria-label="Lock"><svg class="ring" viewBox="0 0 222 222"><circle cx="111" cy="111" r="108"/></svg><span id="lockicon">${bigLock}</span></button>
      <div class="state-text" id="state-text">…</div>
      <div class="state-sub" id="state-sub"></div>
      <div class="actions" id="actions"></div>
    </div>
    <div class="grid" id="stats"></div>
    ${canLogs() ? `<div class="card" style="margin-top:14px"><div class="row between"><h2>Recent</h2><a href="#/logs" class="btn ghost small">View all ${I.chev}</a></div><div id="recent"></div></div>` : ""}`;
  setupLockButton();
  if (!S.status) S.status = await api("/api/status");
  updateHome();
  if (canLogs()) {
    if (!S.live.length) S.live = await api("/api/events?limit=8");
    renderRecent();
  }
  renderHomeAlerts();
  if (q.get("action") === "lock") { history.replaceState(null, "", "#/"); doCmd("lock"); }
}

function renderRecent() {
  const r = $("#recent");
  if (!r) return;
  const evs = S.live.filter((e) => !["login", "system"].includes(e.type)).slice(0, 6);
  r.innerHTML = evs.length ? evs.map(evRow).join("") : `<div class="empty">No events yet.</div>`;
}

async function renderHomeAlerts() {
  const box = $("#home-alerts");
  if (!box) return;
  const s = S.status || {};
  let h = "";
  if (s.demo) h += `<div class="alert info">${I.alert}<div><b>DEMO mode</b> – the lock is simulated.</div></div>`;
  if (!s.configured && isAdmin()) h += `<div class="alert warn">${I.key}<div>The lock isn't set up yet.</div><a class="btn small primary" href="#/settings/lock">Set up</a></div>`;
  if (!isStandalone() && (S.installPrompt || isIOS() || (!window.isSecureContext && pubUrl())))
    h += `<div class="alert info">${I.phone}<div>Install the app on your phone for quicker access and notifications.</div><button class="btn small primary" id="inst">Install</button></div>`;
  const ps = await pushState().catch(() => "unsupported");
  if (ps === "off" && (!isIOS() || isStandalone())) h += `<div class="alert info">${I.bell}<div>Turn on notifications on this device.</div><button class="btn small primary" id="pushon">Turn on</button></div>`;
  box.innerHTML = h;
  const inst = $("#inst"); if (inst) inst.onclick = installApp;
  const po = $("#pushon"); if (po) po.onclick = () => withBusy(po, async () => { await enablePush(); toast("Notifications enabled ✓", "ok"); renderHomeAlerts(); });
}

function updateHome() {
  const s = S.status;
  if (!s || !$("#lockbtn")) return;
  const btn = $("#lockbtn");
  const isUnlocked = ["UNLOCKED", "UNLATCHED"].includes(s.lock);
  const isLocked = s.lock === "LOCKED";
  const moving = ["LOCKING", "UNLOCKING", "UNLATCHING"].includes(s.lock) || s.busy;
  let cls = "", icon = bigLock, text = s.lock_text, sub = "";
  if (!s.configured) { cls = ""; text = "Lock not set up"; }
  else if (s.lock === "JAMMED") { cls = "jammed"; icon = bigAlert; text = "Jammed!"; }
  else if (!s.available && s.lock === "UNKNOWN") { cls = "unavailable"; icon = bigAlert; text = "Connecting…"; sub = "Waiting for the lock's Bluetooth signal"; }
  else if (isUnlocked) { cls = "unlocked"; icon = bigUnlock; text = s.lock === "UNLATCHED" ? "Unlatched" : "Unlocked"; }
  else if (isLocked) { cls = "locked"; text = "Locked"; }
  if (moving) { cls += " busy"; text = s.lock === "LOCKING" ? "Locking…" : s.lock === "UNLOCKING" || s.lock === "UNLATCHING" ? "Unlocking…" : "Sending command…"; }
  if (!sub && s.configured) {
    if (isLocked && s.unlock_confirm) sub = "Hold the button to unlock";
    else if (isLocked) sub = "Tap to unlock";
    else if (isUnlocked) sub = "Tap to lock";
    if (s.last_change) sub += ` · ${ago(s.last_change)}`;
  }
  btn.className = "lockbtn " + cls;
  btn.dataset.state = isLocked ? "locked" : isUnlocked ? "unlocked" : "other";
  $("#lockicon").innerHTML = icon;
  $("#state-text").textContent = text;
  $("#state-sub").textContent = sub;
  btn.disabled = !s.configured;

  const acts = [];
  if (s.configured) {
    acts.push(`<button class="btn" data-cmd="lock" ${moving ? "disabled" : ""}>${I.lock} Lock</button>`);
    acts.push(`<button class="btn" data-cmd="unlock" ${moving ? "disabled" : ""}>${I.unlock} Unlock</button>`);
    if (s.unlatch) acts.push(`<button class="btn" data-cmd="unlatch" ${moving ? "disabled" : ""}>${I.doorOpen} Unlatch</button>`);
  }
  $("#actions").innerHTML = acts.join("");
  $$("#actions [data-cmd]").forEach((b) => b.onclick = async () => {
    const c = b.dataset.cmd;
    if (c !== "lock" && !(await confirmDialog(c === "unlatch" ? "Unlatch door?" : "Unlock door?", "The door will be unlocked.", c === "unlatch" ? "Unlatch" : "Unlock"))) return;
    doCmd(c);
  });

  const bat = s.battery;
  const batCls = bat == null ? "" : bat <= 10 ? "err" : bat <= 25 ? "warn" : "ok";
  const doorOpen = ["OPENED", "AJAR"].includes(s.door);
  const rssiTxt = s.rssi == null ? "–" : s.rssi > -65 ? "Excellent" : s.rssi > -80 ? "Good" : "Weak";
  $("#stats").innerHTML = `
    <div class="card stat"><div class="ico-wrap ${doorOpen ? "warn" : s.door === "CLOSED" ? "ok" : ""}">${doorOpen ? I.doorOpen : I.door}</div><div><div class="v">${esc(s.door === "UNKNOWN" ? "–" : s.door_text)}</div><div class="k">Door</div></div></div>
    <div class="card stat"><div class="ico-wrap ${batCls}">${I.battery}</div><div style="flex:1"><div class="v">${bat == null ? "–" : bat + " %"}</div><div class="k">Battery${s.voltage ? ` · ${Number(s.voltage).toFixed(2)} V` : ""}</div>
      ${bat == null ? "" : `<div class="battery-bar ${batCls}"><i style="width:${bat}%"></i></div>`}</div></div>
    <div class="card stat"><div class="ico-wrap ${s.available ? "ok" : "err"}">${I.bt}</div><div><div class="v">${s.available ? rssiTxt : "Unavailable"}</div><div class="k">Bluetooth${s.rssi != null ? ` · ${s.rssi} dBm` : ""}</div></div></div>
    <div class="card stat"><div class="ico-wrap">${I.user}</div><div style="min-width:0"><div class="v" style="font-size:.95rem;overflow-wrap:anywhere">${esc(s.last_actor || "–")}</div><div class="k">Last change · ${ago(s.last_change)}</div></div></div>`;
  if (s.battery != null && s.battery <= 25) {
    const ab = $("#home-alerts");
    if (ab && !$("#bat-alert")) ab.insertAdjacentHTML("afterbegin", `<div class="alert ${s.battery <= 10 ? "err" : "warn"}" id="bat-alert">${I.battery}<div><b>Lock battery: ${s.battery}%</b> – ${s.battery <= 10 ? "replace the batteries as soon as possible!" : "replace the batteries soon."}</div></div>`);
  }
}

async function doCmd(cmd) {
  try {
    S.status = { ...S.status, busy: true };
    updateHome();
    S.status = await api("/api/" + cmd, "POST");
    updateHome();
    if (navigator.vibrate) navigator.vibrate(40);
  } catch (e) {
    toast(e.message, "err");
    S.status = await api("/api/status").catch(() => S.status);
    updateHome();
  }
}

function setupLockButton() {
  const btn = $("#lockbtn");
  let timer = null;
  const cancel = () => { clearTimeout(timer); timer = null; btn.classList.remove("holding"); };
  btn.addEventListener("contextmenu", (e) => e.preventDefault());
  btn.addEventListener("pointerdown", (e) => {
    const s = S.status;
    if (!s || !s.configured || s.busy) return;
    if (btn.dataset.state === "locked" && s.unlock_confirm) {
      e.preventDefault();
      btn.classList.add("holding");
      timer = setTimeout(() => { cancel(); doCmd("unlock"); }, 900);
    }
  });
  ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => btn.addEventListener(ev, () => { if (timer) cancel(); }));
  btn.addEventListener("click", async () => {
    const s = S.status;
    if (!s || !s.configured || s.busy) return;
    if (btn.dataset.state === "unlocked") return doCmd("lock");
    if (btn.dataset.state === "locked" && !s.unlock_confirm) return doCmd("unlock");
    if (btn.dataset.state === "other") {
      if (await confirmDialog("Unknown state", "Do you want to lock the door?", "Lock")) doCmd("lock");
    }
  });
}

// ======================================================================= DNEVNIK
const LOG_FILTERS = [
  ["All", {}], ["Unlocks", { type: "unlocked,unlatched" }], ["Locks", { type: "locked" }],
  ["Door", { type: "door_opened,door_closed,door_ajar" }], ["Errors", { level: "error" }],
  ["Battery", { type: "battery_low,battery_critical,battery_ok" }], ["Security", { type: "login,login_failed,user_changed" }],
  ["Automations", { type: "automation" }],
];
let logsAppendLive = null;

async function pageLogs(el) {
  el.innerHTML = `${topbar("Log", isAdmin() ? `<a class="btn small" href="/api/events.csv" download>${I.download} CSV</a>` : "")}
    <div class="card" id="stats7"><h3>Unlocks in the last 7 days</h3><div class="bars" id="bars"></div></div>
    <div class="chips" id="chips">${LOG_FILTERS.map(([n], i) => `<button class="chip ${i ? "" : "active"}" data-i="${i}">${n}</button>`).join("")}</div>
    <div class="field"><input type="text" id="q" placeholder="Search (person, message, source)…"></div>
    <div class="card" id="loglist"></div>
    <button class="btn block" id="more">Load more</button>`;
  let filter = 0, lastId = null, items = [];
  const list = $("#loglist");
  const render = () => {
    if (!items.length) { list.innerHTML = `<div class="empty">No events.</div>`; return; }
    let h = "", day = "";
    for (const e of items) {
      const d = fmtDay(e.ts);
      if (d !== day) { h += `<div class="day">${esc(d)}</div>`; day = d; }
      h += evRow(e);
    }
    list.innerHTML = h;
  };
  const load = async (reset) => {
    const p = new URLSearchParams({ limit: 60, ...LOG_FILTERS[filter][1] });
    const q = $("#q").value.trim();
    if (q) p.set("q", q);
    if (!reset && lastId) p.set("before", lastId);
    const rows = await api("/api/events?" + p);
    items = reset ? rows : items.concat(rows);
    lastId = items.length ? items[items.length - 1].id : null;
    $("#more").classList.toggle("hide", rows.length < 60);
    render();
  };
  $("#chips").onclick = (e) => {
    const c = e.target.closest(".chip"); if (!c) return;
    $$(".chip", $("#chips")).forEach((x) => x.classList.toggle("active", x === c));
    filter = +c.dataset.i; load(true);
  };
  $("#q").oninput = debounce(() => load(true), 300);
  $("#more").onclick = () => load(false);
  logsAppendLive = (ev) => {
    if (currentPage !== "logs" || filter !== 0 || $("#q").value) return;
    items.unshift(ev); render();
  };
  await load(true);
  const st = await api("/api/stats");
  const days = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(); d.setDate(d.getDate() - i);
    const key = d.toLocaleDateString("sv-SE");
    const n = (st.unlocks_by_day.find((x) => x.d === key) || { n: 0 }).n;
    days.push([DAYS[(d.getDay() + 6) % 7], n]);
  }
  const max = Math.max(1, ...days.map((d) => d[1]));
  $("#bars").innerHTML = days.map(([l, n]) => `<div title="${n}"><i style="height:${(n / max) * 100}%"></i><span>${l} ${n || ""}</span></div>`).join("");
}

// ======================================================================= AUTOMATIZACIJE
let AUTO_META = null, IKEA_CACHE = null;
const TRIGGER_TYPES = {
  event: "When it happens…", state_for: "When a state lasts longer than…", time: "At a specific time",
  webhook: "Webhook (URL call)", ikea: "IKEA button / remote", mqtt: "MQTT message",
};
const COND_TYPES = {
  time_between: "Time between", weekday: "Day of week", lock_is: "Lock is", door_is: "Door is", door_not_open: "Door is not open",
};
const ACTION_TYPES = {
  lock: "Lock", unlock: "Unlock", unlatch: "Unlatch door", notify: "Send notification",
  delay: "Wait", webhook: "Call URL (webhook)", mqtt: "Publish MQTT message",
  ikea_light: "IKEA light / plug", ikea_scene: "IKEA scene",
};

function describeTrigger(t) {
  switch (t.type) {
    case "event": return (AUTO_META.event_triggers[t.event] || t.event);
    case "state_for": return `${t.what === "door_open" ? "Door open" : "Unlocked"} for more than ${t.minutes} min`;
    case "time": return `At ${t.at}${t.days && t.days.length < 7 ? " (" + t.days.map((d) => DAYS[d]).join(", ") + ")" : ""}`;
    case "webhook": return "Webhook";
    case "ikea": return "IKEA button" + (t.pattern ? ` (${t.pattern})` : "");
    case "mqtt": return `MQTT ${t.topic}`;
  }
  return t.type;
}

async function pageAutomations(el) {
  AUTO_META = await api("/api/automations");
  const items = AUTO_META.items;
  el.innerHTML = `${topbar("Automations", `<button class="btn primary small" id="new">${I.plus} New</button>`)}
    <div class="card">${items.length ? `<ul class="list">${items.map((a) => `
      <li><div class="ico-wrap ${a.enabled ? "accent" : ""}">${I.bolt}</div>
        <div class="grow"><div class="title">${esc(a.name)}</div>
          <div class="sub">${esc(describeTrigger(a.trigger))} → ${a.actions.map((x) => esc(ACTION_TYPES[x.type] || x.type)).join(", ")}${a.last_run ? ` · last run ${ago(a.last_run)}` : ""}</div></div>
        <label class="switch" title="Enabled"><input type="checkbox" data-toggle="${a.id}" ${a.enabled ? "checked" : ""}><span></span></label>
        <button class="btn ghost small" data-run="${a.id}" title="Run now">${I.play}</button>
        <button class="btn ghost small" data-edit="${a.id}" title="Edit">${I.edit}</button></li>`).join("")}</ul>`
      : `<div class="empty">No automations yet. Start from a template:</div>`}</div>
    <div class="card"><h2>Templates</h2><ul class="list">${AUTO_META.templates.map((t, i) => `
      <li><div class="ico-wrap">${I.bolt}</div><div class="grow"><div class="title">${esc(t.name)}</div></div>
      <button class="btn small" data-tpl="${i}">${I.plus} Add</button></li>`).join("")}</ul></div>`;
  $("#new").onclick = () => editAutomation({ name: "", enabled: true, trigger: { type: "event", event: "unlocked" }, conditions: [], actions: [{ type: "notify", message: "" }] });
  el.addEventListener("click", async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.tpl) editAutomation(JSON.parse(JSON.stringify(AUTO_META.templates[b.dataset.tpl])));
    if (b.dataset.edit) editAutomation(JSON.parse(JSON.stringify(items.find((a) => a.id == b.dataset.edit))));
    if (b.dataset.run) withBusy(b, async () => { await api(`/api/automations/${b.dataset.run}/run`, "POST"); toast("Started ✓", "ok"); });
  });
  el.addEventListener("change", (e) => {
    const t = e.target.closest("[data-toggle]"); if (!t) return;
    const a = items.find((x) => x.id == t.dataset.toggle);
    a.enabled = t.checked;
    api(`/api/automations/${a.id}`, "PUT", a).then(() => toast(a.enabled ? "Enabled" : "Disabled")).catch((er) => toast(er.message, "err"));
  });
}

async function ikeaData() {
  if (IKEA_CACHE) return IKEA_CACHE;
  try { IKEA_CACHE = await api("/api/ikea/devices"); } catch { IKEA_CACHE = { devices: [], scenes: [], recent: [], error: true }; }
  setTimeout(() => (IKEA_CACHE = null), 60000);
  return IKEA_CACHE;
}

const opt = (val, label, cur) => `<option value="${esc(val)}" ${String(cur) === String(val) ? "selected" : ""}>${esc(label)}</option>`;
const daysPicker = (name, days) => `<div class="row">${DAYS.map((d, i) => `<label class="check" style="margin:0 6px 0 0"><input type="checkbox" data-day="${name}" value="${i}" ${(days || [0, 1, 2, 3, 4, 5, 6]).includes(i) ? "checked" : ""}>${d}</label>`).join("")}</div>`;

async function editAutomation(a) {
  const ik = await ikeaData();
  const m = modal(a.id ? "Edit automation" : "New automation", `<form id="af"></form>`, { wide: true });
  const form = $("#af", m.el);
  const ikeaDevSel = (cur, filter) => `<select data-k="device_id"><option value="">— select —</option>${ik.devices.filter(filter || (() => true)).map((d) => opt(d.id, `${d.name}${d.room ? " (" + d.room + ")" : ""} · ${d.type}`, cur)).join("")}</select>${ik.error ? `<div class="hint">IKEA hub is not paired (Settings → Integrations).</div>` : ""}`;

  const trigFields = (t) => {
    switch (t.type) {
      case "event": return `<div class="field"><label>Event</label><select data-k="event">${Object.entries(AUTO_META.event_triggers).map(([k, v]) => opt(k, v, t.event)).join("")}</select></div>`;
      case "state_for": return `<div class="grid"><div class="field"><label>State</label><select data-k="what">${opt("unlocked", "Lock unlocked", t.what)}${opt("door_open", "Door open", t.what)}</select></div>
        <div class="field"><label>Minutes</label><input type="number" min="0.1" step="any" data-k="minutes" value="${esc(t.minutes ?? 2)}"></div></div>`;
      case "time": return `<div class="field"><label>Time</label><input type="time" data-k="at" value="${esc(t.at || "22:00")}"></div><div class="field"><label>Days</label>${daysPicker("trigger", t.days)}</div>`;
      case "webhook": return t.hook ? `<div class="field"><label>Call URL (GET or POST)</label><div class="secret">${esc(location.origin)}/api/hook/${esc(t.hook)}</div><div class="hint">Keep this URL secret – anyone who knows it can trigger the automation.</div></div>` : `<p class="muted">The URL will be generated after saving.</p>`;
      case "ikea": return `<div class="field"><label>Device (remote / button)</label>${ikeaDevSel(t.device_id, (d) => !d.controllable)}</div>
        <div class="field"><label>Press type</label><select data-k="pattern">${opt("", "Any", t.pattern)}${opt("singlePress", "Single press", t.pattern)}${opt("doublePress", "Double press", t.pattern)}${opt("longPress", "Long press", t.pattern)}</select></div>
        ${ik.recent.length ? `<details><summary class="muted">Recent events from the hub (selection help)</summary><div class="mono" style="font-size:.75rem">${ik.recent.slice(0, 10).map((r) => esc(`${r.time} ${r.type} ${r.device_id || ""} ${r.pattern || ""}`)).join("<br>")}</div></details>` : ""}`;
      case "mqtt": return `<div class="field"><label>Topic</label><input type="text" data-k="topic" value="${esc(t.topic || "")}" placeholder="e.g. home/doorbell"></div>
        <div class="field"><label>Payload (empty = any)</label><input type="text" data-k="payload" value="${esc(t.payload || "")}"></div>`;
    }
    return "";
  };
  const condFields = (c) => {
    switch (c.type) {
      case "time_between": return `<div class="grid"><div class="field"><label>From</label><input type="time" data-k="from" value="${esc(c.from || "22:00")}"></div><div class="field"><label>To</label><input type="time" data-k="to" value="${esc(c.to || "06:00")}"></div></div>`;
      case "weekday": return daysPicker("cond", c.days);
      case "lock_is": return `<select data-k="state">${opt("LOCKED", "Locked", c.state)}${opt("UNLOCKED", "Unlocked", c.state)}</select>`;
      case "door_is": return `<select data-k="state">${opt("CLOSED", "Closed", c.state)}${opt("OPENED", "Open", c.state)}</select>`;
    }
    return "";
  };
  const actFields = (x) => {
    switch (x.type) {
      case "notify": return `<div class="field"><label>Message</label><input type="text" data-k="message" value="${esc(x.message || "")}" placeholder="e.g. {user} unlocked the door at {time}"><div class="hint">Variables: {user} {time} {date} {battery} {lock} {door} {name}</div></div>`;
      case "delay": return `<div class="field"><label>Seconds</label><input type="number" min="1" data-k="seconds" value="${esc(x.seconds ?? 30)}"></div>`;
      case "webhook": return `<div class="grid"><div class="field"><label>Method</label><select data-k="method">${["POST", "GET", "PUT"].map((v) => opt(v, v, x.method || "POST")).join("")}</select></div></div>
        <div class="field"><label>URL</label><input type="url" data-k="url" value="${esc(x.url || "")}" placeholder="https://…"></div>
        <div class="field"><label>Body (JSON, optional)</label><input type="text" data-k="body" value="${esc(x.body || "")}" placeholder='{"text":"Door: {lock}"}'></div>`;
      case "mqtt": return `<div class="field"><label>Topic</label><input type="text" data-k="topic" value="${esc(x.topic || "")}"></div><div class="field"><label>Payload</label><input type="text" data-k="payload" value="${esc(x.payload || "")}"></div>`;
      case "ikea_light": return `<div class="field"><label>Device</label>${ikeaDevSel(x.device_id, (d) => d.controllable)}</div>
        <div class="grid"><div class="field"><label>Action</label><select data-k="on">${opt("true", "Turn on", String(x.on ?? true))}${opt("false", "Turn off", String(x.on ?? true))}</select></div>
        <div class="field"><label>Brightness % (optional)</label><input type="number" min="1" max="100" data-k="level" value="${esc(x.level ?? "")}"></div></div>`;
      case "ikea_scene": return `<div class="field"><label>Scene</label><select data-k="scene_id"><option value="">— select —</option>${ik.scenes.map((s) => opt(s.id, s.name, x.scene_id)).join("")}</select></div>`;
    }
    return "";
  };
  const block = (kind, idx, obj, types, fields) => `<div class="sub-block" data-kind="${kind}" data-idx="${idx}">
      <div class="row between"><select data-type style="width:auto;flex:1">${Object.entries(types).map(([k, v]) => opt(k, v, obj.type)).join("")}</select>
      <button type="button" class="btn ghost small" data-del>${I.trash}</button></div>${fields(obj)}</div>`;

  const draw = () => {
    form.innerHTML = `
      <div class="field"><label>Name</label><input type="text" id="a-name" value="${esc(a.name)}" required></div>
      <label class="check"><input type="checkbox" id="a-en" ${a.enabled !== false ? "checked" : ""}> Enabled</label>
      <h3 style="margin-top:16px">Trigger</h3>
      <div class="sub-block" data-kind="trigger"><select data-type>${Object.entries(TRIGGER_TYPES).map(([k, v]) => opt(k, v, a.trigger.type)).join("")}</select><div style="margin-top:10px">${trigFields(a.trigger)}</div></div>
      <h3 style="margin-top:16px">Conditions <small class="muted">(all must match)</small></h3>
      ${a.conditions.map((c, i) => block("cond", i, c, COND_TYPES, condFields)).join("")}
      <button type="button" class="btn small" data-add="cond">${I.plus} Condition</button>
      <h3 style="margin-top:16px">Actions <small class="muted">(in order)</small></h3>
      ${a.actions.map((x, i) => block("act", i, x, ACTION_TYPES, actFields)).join("")}
      <button type="button" class="btn small" data-add="act">${I.plus} Action</button>
      <div class="row" style="margin-top:20px">${a.id ? `<button type="button" class="btn danger" id="a-del">${I.trash} Delete</button>` : ""}<span class="spacer"></span>
        <button type="button" class="btn" data-close>Cancel</button><button type="submit" class="btn primary">Save</button></div>`;
  };
  const target = (blk) => blk.dataset.kind === "trigger" ? a.trigger : blk.dataset.kind === "cond" ? a.conditions[blk.dataset.idx] : a.actions[blk.dataset.idx];
  form.addEventListener("input", (e) => {
    const el = e.target;
    if (el.id === "a-name") a.name = el.value;
    if (el.id === "a-en") a.enabled = el.checked;
    const blk = el.closest(".sub-block"); if (!blk) return;
    const obj = target(blk);
    if (el.dataset.k) {
      let v = el.value;
      if (el.type === "number") v = v === "" ? null : Number(v);
      if (el.dataset.k === "on") v = v === "true";
      obj[el.dataset.k] = v;
    }
    if (el.dataset.day) obj.days = $$(`[data-day]`, blk).filter((x) => x.checked).map((x) => +x.value);
  });
  form.addEventListener("change", (e) => {
    const el = e.target;
    if (!el.hasAttribute("data-type")) return;
    const blk = el.closest(".sub-block");
    const fresh = { type: el.value };
    if (blk.dataset.kind === "trigger") a.trigger = fresh;
    else if (blk.dataset.kind === "cond") a.conditions[blk.dataset.idx] = fresh;
    else a.actions[blk.dataset.idx] = fresh;
    draw();
  });
  form.addEventListener("click", async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.add === "cond") { a.conditions.push({ type: "time_between", from: "22:00", to: "06:00" }); draw(); }
    if (b.dataset.add === "act") { a.actions.push({ type: "notify", message: "" }); draw(); }
    if (b.hasAttribute("data-del")) {
      const blk = b.closest(".sub-block");
      (blk.dataset.kind === "cond" ? a.conditions : a.actions).splice(+blk.dataset.idx, 1); draw();
    }
    if (b.id === "a-del" && (await confirmDialog("Delete?", `Delete automation "${a.name}"?`, "Delete", true))) {
      await api(`/api/automations/${a.id}`, "DELETE"); m.close(); route();
    }
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    // default values the user has not touched
    const defaults = { event: { event: "unlocked" }, state_for: { what: "unlocked", minutes: 2 }, time: { at: "22:00" } };
    a.trigger = { ...(defaults[a.trigger.type] || {}), ...a.trigger };
    for (const c of a.conditions) Object.assign(c, { ...({ time_between: { from: "22:00", to: "06:00" }, lock_is: { state: "LOCKED" }, door_is: { state: "CLOSED" } }[c.type] || {}), ...c });
    for (const x of a.actions) if (x.type === "ikea_light" && x.on === undefined) x.on = true;
    withBusy($("button[type=submit]", form), async () => {
      await api(a.id ? `/api/automations/${a.id}` : "/api/automations", a.id ? "PUT" : "POST", a);
      toast("Saved ✓", "ok"); m.close(); route();
    });
  });
  draw();
}

// ======================================================================= SETTINGS (menu)
async function pageSettings(el) {
  const items = [["account", "My account", "Password, 2FA, notifications, installation", I.user, "accent"]];
  if (isAdmin()) items.push(
    ["users", "Users", "Add users, guests, permissions", I.users, ""],
    ["lock", "Lock", "Connection, key, Bluetooth", I.key, ""],
    ["integrations", "Integrations", "Home Assistant, Alexa, IKEA, ntfy, API", I.plug, ""],
    ["system", "System", "Settings, battery, backup", I.server, ""]);
  el.innerHTML = `${topbar("Settings")}<div class="card menu">${items.map(([p, t, d, i, c]) => `
    <a href="#/settings/${p}"><div class="ico-wrap ${c}">${i}</div><div><div class="title" style="font-weight:600">${t}</div><div class="muted" style="font-size:.82rem">${d}</div></div>${I.chev}</a>`).join("")}</div>
    <button class="btn block" id="logout">${I.logout} Sign out</button>
    <p class="muted" style="text-align:center;font-size:.8rem;margin-top:16px">LockBridge ${esc(S.boot.version)}</p>`;
  $("#logout").onclick = async () => { await api("/api/logout", "POST"); if (S.sse) S.sse.close(); S.user = null; boot(); };
}

// ---------------------------------------------------------------- my account
async function pageAccount(el) {
  const me = await api("/api/me");
  const ps = await pushState().catch(() => "unsupported");
  const cats = { unlock: "Unlock", lock: "Lock", door: "Door opened/closed", battery: "Battery", error: "Errors and availability", security: "Security (sign-ins, users)", automation: "Automations" };
  const allowed = me.role === "admin" ? Object.keys(cats) : me.role === "user" ? ["unlock", "lock", "door", "battery", "error", "automation"] : ["unlock", "lock", "door"];
  el.innerHTML = `${backbar("My account")}
    <div class="card"><div class="row"><div class="ico-wrap accent">${I.user}</div><div><div style="font-weight:700">${esc(me.display_name)}</div><div class="muted">${esc(me.username)} · ${ROLE[me.role]} · 2FA ${me.totp_enabled ? "✓" : "✗"}</div></div></div></div>
    <div class="card"><h2>${I.phone} Mobile app</h2>
      ${installCard()}
    </div>
    <div class="card"><h2>${I.bell} Notifications</h2>
      <div class="row between"><div>Push notifications on this device<div class="muted" style="font-size:.82rem">${{ on: "Enabled", off: "Disabled", denied: "Blocked in browser", unsupported: window.isSecureContext ? "Not supported" : "HTTPS required" }[ps]} · subscribed devices: ${me.push_devices}</div></div>
        ${ps === "on" ? `<button class="btn small" id="poff">Turn off</button>` : ps === "off" ? `<button class="btn small primary" id="pon">Turn on</button>` : ""}</div>
      ${me.push_devices ? `<button class="btn small" id="ptest" style="margin-top:10px">Send test notification</button>` : ""}
      <h3 style="margin-top:18px">Notify me about:</h3>
      <form id="nf">${allowed.map((k) => `<label class="check"><input type="checkbox" name="${k}" ${me.notify[k] ? "checked" : ""}> ${cats[k]}</label>`).join("")}
        <label class="check"><input type="checkbox" name="own" ${me.notify.own ? "checked" : ""}> Also about my own actions</label></form>
    </div>
    <div class="card"><h2>${I.key} Change password</h2><form id="pf">
      <div class="field"><label>Current password</label><input type="password" name="old" autocomplete="current-password" required></div>
      <div class="field"><label>New password</label><input type="password" name="new" autocomplete="new-password" minlength="10" required></div>
      <button class="btn primary" type="submit">Change</button></form></div>
    <div class="card"><h2>${I.shield} Sessions</h2><p class="muted">Sign out on all devices (including this one).</p><button class="btn danger" id="lall">Sign out all devices</button></div>`;
  const inst = $("#inst"); if (inst) inst.onclick = installApp;
  const pon = $("#pon"); if (pon) pon.onclick = () => withBusy(pon, async () => { await enablePush(); toast("Enabled ✓", "ok"); route(); });
  const poff = $("#poff"); if (poff) poff.onclick = () => withBusy(poff, async () => { await disablePush(); route(); });
  const pt = $("#ptest"); if (pt) pt.onclick = () => withBusy(pt, async () => { const r = await api("/api/push/test", "POST"); toast(`Sent to ${r.sent} device(s)`, "ok"); });
  $("#nf").onchange = () => api("/api/me/notify", "PUT", formData($("#nf"))).then(() => toast("Saved ✓")).catch((e) => toast(e.message, "err"));
  $("#pf").onsubmit = (e) => { e.preventDefault(); withBusy($("#pf button"), async () => { await api("/api/me/password", "POST", formData($("#pf"))); toast("Password changed ✓", "ok"); $("#pf").reset(); }); };
  $("#lall").onclick = async () => { if (await confirmDialog("Sign out", "Sign out all devices?", "Sign out", true)) { await api("/api/me/logout-all", "POST"); boot(); } };
}

// ---------------------------------------------------------------- korisnici
async function pageUsers(el) {
  const users = await api("/api/users");
  el.innerHTML = `${backbar("Users")}
    <div class="row" style="margin-bottom:12px"><span class="spacer"></span><button class="btn primary" id="add">${I.plus} Add user</button></div>
    <div class="card"><ul class="list">${users.map((u) => {
      const exp = u.valid_until && new Date(u.valid_until) < new Date();
      return `<li><div class="ico-wrap ${u.role === "admin" ? "accent" : ""}">${I.user}</div><div class="grow">
        <div class="title">${esc(u.display_name)} ${!u.active ? '<span class="badge err">disabled</span>' : exp ? '<span class="badge warn">expired</span>' : ""} ${!u.totp_enabled ? '<span class="badge warn">2FA not set up</span>' : ""}</div>
        <div class="sub">${esc(u.username)} · ${ROLE[u.role]}${u.valid_until ? " · until " + esc(new Date(u.valid_until).toLocaleString("en-GB")) : ""} · last sign-in ${u.last_login ? ago(u.last_login) : "never"}</div></div>
        <button class="btn ghost small" data-edit="${u.id}">${I.edit}</button></li>`;
    }).join("")}</ul></div>
    <div class="card"><h3>Roles</h3><ul class="list">
      <li><div class="grow"><b>Administrator</b><div class="sub">Everything: lock, users, automations, integrations, log.</div></div></li>
      <li><div class="grow"><b>User</b><div class="sub">Unlock/lock and view the activity log.</div></div></li>
      <li><div class="grow"><b>Guest</b><div class="sub">Unlock/lock only, optionally time-limited (e.g. contractor, cleaner, Airbnb guest).</div></div></li></ul></div>`;
  $("#add").onclick = () => editUser(null);
  el.onclick = (e) => { const b = e.target.closest("[data-edit]"); if (b) editUser(users.find((u) => u.id == b.dataset.edit)); };
}

function editUser(u) {
  const isNew = !u;
  u = u || { role: "user", active: true };
  const dt = (v) => (v ? v.slice(0, 16) : "");
  const m = modal(isNew ? "New user" : u.display_name, `<form id="uf">
    ${isNew ? `<div class="field"><label>Username</label><input type="text" name="username" autocapitalize="none" required minlength="3"></div>` : ""}
    <div class="field"><label>Display name</label><input type="text" name="display_name" value="${esc(u.display_name || "")}" required></div>
    <div class="field"><label>Role</label><select name="role">${Object.entries(ROLE).map(([k, v]) => opt(k, v, u.role)).join("")}</select></div>
    <div class="field"><label>${isNew ? "Temporary password" : "New temporary password (optional)"}</label><input type="text" name="password" autocomplete="off" ${isNew ? "required" : ""} minlength="10" value="${isNew ? genPassword() : ""}">
      <div class="hint">The user will have to change it and set up 2FA on first sign-in.</div></div>
    <div class="grid"><div class="field"><label>Access from</label><input type="datetime-local" name="valid_from" value="${dt(u.valid_from)}"></div>
      <div class="field"><label>Access until</label><input type="datetime-local" name="valid_until" value="${dt(u.valid_until)}"></div></div>
    ${isNew ? "" : `<label class="check"><input type="checkbox" name="active" ${u.active ? "checked" : ""}> Account active</label>
      <label class="check"><input type="checkbox" name="reset_2fa"> Reset 2FA (lost phone)</label>`}
    <div class="row" style="margin-top:16px">${isNew ? "" : `<button type="button" class="btn danger" id="udel">${I.trash} Delete</button>`}<span class="spacer"></span>
      <button type="button" class="btn" data-close>Cancel</button><button class="btn primary" type="submit">Save</button></div></form>`);
  const f = $("#uf", m.el);
  f.onsubmit = (e) => {
    e.preventDefault();
    const d = formData(f);
    if (!d.password) delete d.password;
    withBusy($("button[type=submit]", f), async () => {
      await api(isNew ? "/api/users" : `/api/users/${u.id}`, isNew ? "POST" : "PUT", d);
      if (d.password) {
        modal("Sign-in details", `<p>Send these details to the user through a secure channel:</p>
          <div class="secret">Address: ${esc(location.origin)}<br>Username: ${esc(d.username || u.username)}<br>Password: ${esc(d.password)}</div>
          <p class="muted" style="margin-top:10px">On first sign-in, the user sets their own password and 2FA.</p>`);
      } else toast("Saved ✓", "ok");
      m.close(); route();
    });
  };
  const del = $("#udel", m.el);
  if (del) del.onclick = async () => {
    if (await confirmDialog("Delete user?", `Permanently delete ${u.display_name}?`, "Delete", true)) {
      await api(`/api/users/${u.id}`, "DELETE").then(() => { m.close(); route(); }).catch((er) => toast(er.message, "err"));
    }
  };
}
function genPassword() {
  const a = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
  const r = crypto.getRandomValues(new Uint32Array(14));
  let p = [...r].map((x) => a[x % a.length]).join("");
  return p.slice(0, 4) + "-" + p.slice(4, 8) + "-" + p.slice(8, 12) + "A7";
}

// ---------------------------------------------------------------- lock (wizard)
async function pageLockSetup(el) {
  const c = await api("/api/lockcfg");
  const s = await api("/api/status");
  el.innerHTML = `${backbar("Lock")}
    ${s.configured ? `<div class="card"><div class="row between"><div class="row"><div class="ico-wrap ${s.available ? "ok" : "err"}">${I.bt}</div>
      <div><b>${esc((s.info && s.info.model) || "Yale lock")}</b><div class="muted" style="font-size:.82rem">${esc(c.address)} · ${s.available ? "available" : "unavailable"}${s.info ? " · fw " + esc(s.info.firmware) : ""} · ${s.rssi ?? "–"} dBm</div></div></div>
      <button class="btn small" id="reconnect">${I.refresh} Reconnect</button></div></div>` : ""}
    <div class="card"><h2>1. Find the lock</h2>
      <p class="muted">The Raspberry Pi must be within ~5–10 m of the lock. The lock advertises over Bluetooth – turn off the Yale Connect bridge if it's still on.</p>
      <button class="btn" id="scan">${I.bt} Search for nearby locks</button><div id="scanres" style="margin-top:10px"></div></div>
    <div class="card"><h2>2. Lock key</h2>
      <p class="muted">The lock uses a secret <b>offline key</b> (32 hex characters) and a <b>slot</b>. Get them using one of these methods:</p>
      <div class="tabs" id="ktabs"><button class="active" data-t="ha">Home Assistant</button><button data-t="cloud">Yale Access account</button><button data-t="manual">Manual</button></div>
      <div data-p="ha"><ol class="steps">
        <li>Temporarily run Home Assistant (e.g. a HAOS VM on Proxmox).</li>
        <li>Add the <b>Yale</b> integration and sign in with your Yale Home account.</li>
        <li>HA will also offer <b>Yale Access Bluetooth</b> – confirm it (the key is then fetched automatically).</li>
        <li>Open the file <code>/config/.storage/core.config_entries</code> (File editor or SSH add-on) and paste its full contents here:</li></ol>
        <textarea id="hajson" placeholder='{"version":1,"data":{"entries":[...]}}'></textarea>
        <button class="btn" id="haimp" style="margin-top:8px">Extract key</button><div id="hares"></div></div>
      <div data-p="cloud" class="hide"><div class="alert warn">${I.alert}<div><b>Yale Home</b> accounts (EU) require OAuth via Home Assistant, so this sign-in <b>won't work</b> for them. It works for older <b>Yale Access</b> and <b>August</b> accounts.</div></div>
        <form id="cf"><div class="field"><label>Account type</label><select name="brand">${opt("yale_access", "Yale Access", "yale_access")}${opt("august", "August", "")}${opt("yale_global", "Yale Home (Global)", "")}</select></div>
        <div class="field"><label>E-mail</label><input type="email" name="email" required></div>
        <div class="field"><label>Password</label><input type="password" name="password" required></div>
        <button class="btn" type="submit">Sign in and fetch key</button></form>
        <form id="cv" class="hide" style="margin-top:12px"><div class="field"><label>Code sent to email</label><input type="text" name="code" inputmode="numeric"></div><button class="btn" type="submit">Confirm</button></form>
        <div id="cres"></div><p class="muted" style="font-size:.8rem;margin-top:8px">The password is not stored – it's used only once to fetch the key.</p></div>
      <div data-p="manual" class="hide"><p class="muted">If you extracted the key another way (e.g. from the Yale app on a rooted Android device), enter it in the form below.</p></div>
    </div>
    <div class="card"><h2>3. Lock settings</h2><form id="lf">
      <div class="grid"><div class="field"><label>Bluetooth address</label><input type="text" name="address" value="${esc(c.address)}" placeholder="AA:BB:CC:DD:EE:FF" required></div>
        <div class="field"><label>Local name (optional)</label><input type="text" name="local_name" value="${esc(c.local_name)}"></div></div>
      <div class="grid"><div class="field"><label>Offline key</label><input type="password" name="key" placeholder="${c.has_key ? "•••••••• (saved – leave empty)" : "32 hex characters"}" autocomplete="off"></div>
        <div class="field"><label>Slot</label><input type="number" name="slot" min="0" max="255" value="${c.slot ?? ""}" required></div></div>
      <div class="field"><label>Bluetooth adapter</label><select name="adapter">${opt("", "Automatic", c.adapter)}${c.adapters.map((a) => opt(a, a, c.adapter)).join("")}</select>
        <div class="hint">If the built-in Bluetooth is weak, plug in a USB Bluetooth adapter and select it here.</div></div>
      <label class="check"><input type="checkbox" name="always_connected" ${c.always_connected ? "checked" : ""}> Always connected (faster response, higher lock battery drain)</label>
      <label class="check"><input type="checkbox" name="unlatch" ${c.unlatch ? "checked" : ""}> Lock supports "Unlatch" (retracts the latch, e.g. Linus L2)</label>
      <div class="row" style="margin-top:12px"><button class="btn primary" type="submit">Save and connect</button>${c.address ? `<button type="button" class="btn danger" id="lrm">Remove lock</button>` : ""}</div></form></div>`;
  const lf = $("#lf");
  const fill = (k) => {
    if (k.address) lf.address.value = k.address;
    if (k.local_name) lf.local_name.value = k.local_name;
    if (k.slot != null) lf.slot.value = k.slot;
    // Imported keys are kept on the server: the form only carries an index.
    if (k.index != null) {
      lf.dataset.importIndex = String(k.index);
      lf.key.value = "";
      lf.key.placeholder = "•••••••• (imported – leave empty)";
    } else if (k.key) {
      delete lf.dataset.importIndex;
      lf.key.value = k.key;
    }
    lf.scrollIntoView({ behavior: "smooth" });
    toast("Details filled into the form – check and save.", "ok");
  };
  const pickList = (items, render) => `<ul class="list">${items.map((x, i) => `<li><div class="grow">${render(x)}</div><button class="btn small" data-pick="${i}">Select</button></li>`).join("")}</ul>`;
  $("#ktabs").onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    $$("#ktabs button").forEach((x) => x.classList.toggle("active", x === b));
    $$("[data-p]").forEach((p) => p.classList.toggle("hide", p.dataset.p !== b.dataset.t));
  };
  $("#scan").onclick = () => withBusy($("#scan"), async () => {
    $("#scanres").innerHTML = `<p class="muted">Searching… (10 s)</p>`;
    const r = await api("/api/lockcfg/scan", "POST", { seconds: 10 });
    $("#scanres").innerHTML = r.length ? pickList(r, (d) => `<div class="title">${esc(d.local_name || "Unknown")} ${d.is_yale ? '<span class="badge ok">Yale</span>' : ""}</div><div class="sub">${esc(d.address)} · ${d.rssi} dBm</div>`)
      : `<div class="alert warn">No locks found. Move the Pi closer to the lock, check the batteries, and make sure Bluetooth is on.</div>`;
    $("#scanres").onclick = (e) => { const b = e.target.closest("[data-pick]"); if (b) fill({ address: r[b.dataset.pick].address, local_name: r[b.dataset.pick].local_name }); };
  });
  $("#haimp").onclick = () => withBusy($("#haimp"), async () => {
    const r = await api("/api/lockcfg/import_ha", "POST", { text: $("#hajson").value });
    $("#hares").innerHTML = pickList(r, (d) => `<div class="title">${esc(d.name)}</div><div class="sub">${esc(d.address)} · slot ${esc(d.slot)}${d.key_hint ? " · key " + esc(d.key_hint) : ""}</div>`);
    $("#hares").onclick = (e) => { const b = e.target.closest("[data-pick]"); if (b) fill(r[b.dataset.pick]); };
  });
  const showCloudLocks = async () => {
    const r = await api("/api/lockcfg/cloud/locks");
    $("#cres").innerHTML = r.length ? pickList(r, (d) => `<div class="title">${esc(d.name)}</div><div class="sub">${esc(d.address || "address unknown")} · ${d.key_hint ? "key ✓ slot " + esc(d.slot) : "no offline key"}</div>`) : `<div class="alert warn">No locks on this account.</div>`;
    $("#cres").onclick = (e) => { const b = e.target.closest("[data-pick]"); if (b) fill(r[b.dataset.pick]); };
  };
  $("#cf").onsubmit = (e) => { e.preventDefault(); withBusy($("#cf button"), async () => {
    const r = await api("/api/lockcfg/cloud/login", "POST", formData($("#cf")));
    $("#cf").password.value = "";
    if (r.state === "need_code") { $("#cv").classList.remove("hide"); toast("A code has been sent to your email."); } else await showCloudLocks();
  }); };
  $("#cv").onsubmit = (e) => { e.preventDefault(); withBusy($("#cv button"), async () => { await api("/api/lockcfg/cloud/verify", "POST", formData($("#cv"))); $("#cv").classList.add("hide"); await showCloudLocks(); }); };
  lf.onsubmit = (e) => { e.preventDefault(); withBusy($("button[type=submit]", lf), async () => {
    const d = formData(lf);
    if (!d.key) delete d.key;
    if (!d.key && lf.dataset.importIndex != null) d.import_index = Number(lf.dataset.importIndex);
    await api("/api/lockcfg", "PUT", d);
    delete lf.dataset.importIndex;
    toast("Saved – connecting to the lock…", "ok");
    setTimeout(route, 1500);
  }); };
  const rm = $("#lrm"); if (rm) rm.onclick = async () => { if (await confirmDialog("Remove lock?", "The lock key and settings will be deleted.", "Remove", true)) { await api("/api/lockcfg", "DELETE"); route(); } };
  const rc = $("#reconnect"); if (rc) rc.onclick = () => withBusy(rc, async () => { await api("/api/system/restart-lock", "POST"); toast("Reconnecting…"); });
}

// ---------------------------------------------------------------- integracije
async function pageIntegrations(el) {
  const d = await api("/api/integrations");
  const tokens = await api("/api/tokens");
  const st = (s) => `<span class="badge ${/^(connected|active|paired)/.test(s) ? "ok" : /error|failed/i.test(s) ? "err" : ""}">${esc(s)}</span>`;
  const sw = (name, on) => `<label class="check"><input type="checkbox" name="enabled" ${on ? "checked" : ""}> Enabled</label>`;
  const catChecks = (o) => Object.entries(d.categories).map(([k, v]) => `<label class="check" style="font-size:.85rem"><input type="checkbox" data-cat="${k}" ${(o.categories || []).includes(k) ? "checked" : ""}> ${esc(v)}</label>`).join("");
  el.innerHTML = `${backbar("Integrations")}
    <div class="card"><div class="row between"><h2>🏠 Home Assistant (MQTT)</h2>${st(d.status.mqtt)}</div>
      <p class="muted">The lock appears automatically in Home Assistant (MQTT Discovery): lock, battery, door, last event. <b>Alexa / Google / Apple Home</b> then work through HA too.</p>
      <form data-int="mqtt">${sw("mqtt", d.mqtt.enabled)}
        <div class="grid"><div class="field"><label>MQTT broker (IP)</label><input type="text" name="host" value="${esc(d.mqtt.host)}" placeholder="192.168.1.10"></div>
        <div class="field"><label>Port</label><input type="number" name="port" value="${esc(d.mqtt.port)}"></div></div>
        <div class="grid"><div class="field"><label>Username</label><input type="text" name="username" value="${esc(d.mqtt.username)}" autocomplete="off"></div>
        <div class="field"><label>Password</label><input type="password" name="password" placeholder="${d.mqtt.has_password ? "•••• (saved)" : ""}" autocomplete="new-password"></div></div>
        <div class="grid"><div class="field"><label>Base topic</label><input type="text" name="base_topic" value="${esc(d.mqtt.base_topic)}"></div>
        <div class="field"><label>Discovery prefix</label><input type="text" name="discovery_prefix" value="${esc(d.mqtt.discovery_prefix)}"></div></div>
        <label class="check"><input type="checkbox" name="discovery" ${d.mqtt.discovery ? "checked" : ""}> Home Assistant auto-discovery</label>
        <label class="check"><input type="checkbox" name="allow_unlock" ${d.mqtt.allow_unlock ? "checked" : ""}> Allow unlocking from Home Assistant</label>
        <button class="btn primary" type="submit">Save</button></form>
      <details style="margin-top:12px"><summary>Alexa via Home Assistant (recommended)</summary><p class="muted" style="margin-top:8px">In HA, enable the Alexa integration (Nabu Casa Cloud or a manual Alexa skill). The lock appears in the Alexa app as a <b>real lock</b>; to unlock by voice, Alexa asks for a <b>voice PIN</b> – safer than the emulation below.</p></details>
    </div>

    <div class="card"><div class="row between"><h2>🗣️ Amazon Alexa (local)</h2>${st(d.status.alexa)}</div>
      <p class="muted">Emulates a "smart plug" that Echo discovers without the cloud and without a skill. Alexa doesn't support every language – give the device an English or German name. <b>"Alexa, turn off front door"</b> = lock.</p>
      <form data-int="alexa">${sw("alexa", d.alexa.enabled)}
        <div class="grid"><div class="field"><label>Device name for Alexa</label><input type="text" name="name" value="${esc(d.alexa.name)}"></div>
        <div class="field"><label>Port</label><input type="number" name="port" value="${esc(d.alexa.port)}"></div></div>
        <label class="check"><input type="checkbox" name="allow_unlock" ${d.alexa.allow_unlock ? "checked" : ""}> Allow unlocking by voice ("turn on") – <b style="color:var(--err)">insecure: anyone outside can shout through the door</b></label>
        <button class="btn primary" type="submit">Save</button></form>
      <p class="muted" style="font-size:.8rem;margin-top:8px">After saving, say "Alexa, discover devices". The Echo and the Pi must be on the same network.</p></div>

    <div class="card"><div class="row between"><h2>🛋️ IKEA DIRIGERA</h2>${st(d.status.ikea)}</div>
      <p class="muted">Turn on lights when the door is unlocked, run IKEA scenes, or lock the door with an IKEA button (RODRET, SOMRIG, STYRBAR…). All local.</p>
      ${d.ikea.has_token ? `<div class="alert ok">${I.check} Paired with hub ${esc(d.ikea.host)}</div>
        <form data-int="ikea">${sw("ikea", d.ikea.enabled)}<button class="btn primary" type="submit">Save</button> <button class="btn" type="button" id="ikdev">Show devices</button></form><div id="ikdevs"></div>`
      : `<div class="field"><label>DIRIGERA hub IP address</label><input type="text" id="ikhost" value="${esc(d.ikea.host)}" placeholder="192.168.1.50"><div class="hint">You can find the IP in your router (device "dirigera…") or in the IKEA Home smart app.</div></div>
        <button class="btn primary" id="ikpair">Pair</button><div id="ikmsg"></div>`}
    </div>

    <div class="card"><h2>📣 ntfy notifications</h2><p class="muted">An extra notification channel (ntfy app for Android/iOS); works even without the installed PWA.</p>
      <form data-int="ntfy">${sw("ntfy", d.ntfy.enabled)}
        <div class="grid"><div class="field"><label>Server</label><input type="url" name="server" value="${esc(d.ntfy.server)}"></div>
        <div class="field"><label>Topic</label><input type="text" name="topic" value="${esc(d.ntfy.topic)}" placeholder="long-secret-name"></div></div>
        <div class="field"><label>Token (optional)</label><input type="password" name="token" placeholder="${d.ntfy.has_token ? "•••• (saved)" : ""}"></div>
        <details><summary>Categories</summary>${catChecks(d.ntfy)}</details>
        <div class="row" style="margin-top:10px"><button class="btn primary" type="submit">Save</button><button class="btn" type="button" data-test="ntfy">Test</button></div></form></div>

    <div class="card"><h2>✈️ Telegram</h2>
      <form data-int="telegram">${sw("telegram", d.telegram.enabled)}
        <div class="grid"><div class="field"><label>Bot token</label><input type="password" name="bot_token" placeholder="${d.telegram.has_bot_token ? "•••• (saved)" : "from @BotFather"}"></div>
        <div class="field"><label>Chat ID</label><input type="text" name="chat_id" value="${esc(d.telegram.chat_id)}"></div></div>
        <details><summary>Categories</summary>${catChecks(d.telegram)}</details>
        <div class="row" style="margin-top:10px"><button class="btn primary" type="submit">Save</button><button class="btn" type="button" data-test="telegram">Test</button></div></form></div>

    <div class="card"><div class="row between"><h2>🔑 API tokens</h2><button class="btn small primary" id="newtok">${I.plus} New token</button></div>
      <p class="muted">For Home Assistant (REST), iOS Shortcuts, Tasker, scripts… Sent as <code>Authorization: Bearer &lt;token&gt;</code>.</p>
      <ul class="list">${tokens.map((t) => `<li><div class="grow"><div class="title">${esc(t.name)}</div><div class="sub">${ROLE[t.role]} · last used ${t.last_used ? ago(t.last_used) : "never"}</div></div><button class="btn ghost small" data-deltok="${t.id}">${I.trash}</button></li>`).join("") || `<li class="muted">No tokens.</li>`}</ul>
      <details><summary>Examples</summary><div class="mono" style="font-size:.78rem;margin-top:8px;overflow-wrap:anywhere">
        curl -X POST -H "Authorization: Bearer TOKEN" ${esc(location.origin)}/api/lock<br>
        curl -X POST -H "Authorization: Bearer TOKEN" ${esc(location.origin)}/api/unlock<br>
        curl -H "Authorization: Bearer TOKEN" ${esc(location.origin)}/api/status</div></details></div>`;

  el.addEventListener("submit", (e) => {
    const f = e.target.closest("form[data-int]"); if (!f) return;
    e.preventDefault();
    const data = formData(f);
    if (f.querySelector("[data-cat]")) data.categories = $$("[data-cat]", f).filter((x) => x.checked).map((x) => x.dataset.cat);
    delete data.undefined;
    withBusy($("button[type=submit]", f), async () => { await api(`/api/integrations/${f.dataset.int}`, "PUT", data); toast("Saved ✓", "ok"); setTimeout(route, 1200); });
  });
  el.addEventListener("click", async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.test) withBusy(b, async () => { await api(`/api/integrations/test/${b.dataset.test}`, "POST"); toast("Sent"); });
    if (b.dataset.deltok && (await confirmDialog("Delete token?", "Apps using it will lose access.", "Delete", true))) { await api(`/api/tokens/${b.dataset.deltok}`, "DELETE"); route(); }
  });
  $("#newtok").onclick = () => {
    const m = modal("New API token", `<form id="tf"><div class="field"><label>Name</label><input type="text" name="name" placeholder="e.g. Home Assistant" required></div>
      <div class="field"><label>Permissions</label><select name="role">${opt("user", "User (lock/unlock, status)", "user")}${opt("guest", "Guest", "")}${opt("admin", "Administrator", "")}</select></div>
      <button class="btn primary" type="submit">Create</button></form>`);
    $("#tf", m.el).onsubmit = (e) => { e.preventDefault(); withBusy($("#tf button", m.el), async () => {
      const r = await api("/api/tokens", "POST", formData($("#tf", m.el)));
      $(".body", m.el).innerHTML = `<div class="alert warn">Copy the token now – it won't be shown again.</div><div class="secret">${esc(r.token)}</div>
        <div class="row" style="margin-top:12px"><button class="btn" id="cp">Copy</button><button class="btn primary" data-close>Done</button></div>`;
      $("#cp", m.el).onclick = () => navigator.clipboard.writeText(r.token).then(() => toast("Copied"));
      m.el.addEventListener("click", (ev) => { if (ev.target.closest("[data-close]")) route(); });
    }); };
  };
  const pair = $("#ikpair");
  if (pair) pair.onclick = () => withBusy(pair, async () => {
    await api("/api/ikea/pair/start", "POST", { host: $("#ikhost").value });
    $("#ikmsg").innerHTML = `<div class="alert info" style="margin-top:12px">${I.alert}<div><b>Now press the button on the back of the DIRIGERA hub.</b> Waiting up to 90 s…</div></div>`;
    for (let i = 0; i < 45; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      const r = await api("/api/ikea/pair/finish", "POST");
      if (r.done) { toast("IKEA hub paired ✓", "ok"); return route(); }
    }
    throw new Error("The button wasn't pressed in time.");
  });
  const dev = $("#ikdev");
  if (dev) dev.onclick = () => withBusy(dev, async () => {
    const r = await api("/api/ikea/devices");
    $("#ikdevs").innerHTML = `<ul class="list">${r.devices.map((x) => `<li><div class="ico-wrap">${x.controllable ? I.light : I.plug}</div><div class="grow"><div class="title">${esc(x.name)}</div><div class="sub">${esc(x.type)}${x.room ? " · " + esc(x.room) : ""}${x.controllable ? (x.is_on ? " · on" : " · off") : ""}</div></div></li>`).join("")}</ul>
      ${r.scenes.length ? `<h3>Scenes</h3><div class="muted">${r.scenes.map((s) => esc(s.name)).join(", ")}</div>` : ""}`;
  });
}

// ---------------------------------------------------------------- sustav
async function pageSystem(el) {
  const [s, sys] = await Promise.all([api("/api/settings"), api("/api/system")]);
  const up = (t) => { const d = Math.floor(t / 86400), h = Math.floor((t % 86400) / 3600), m = Math.floor((t % 3600) / 60); return `${d ? d + " d " : ""}${h} h ${m} min`; };
  el.innerHTML = `${backbar("System")}
    <div class="card"><h2>General settings</h2><form id="sf">
      <div class="field"><label>Door name</label><input type="text" name="site_name" value="${esc(s.site_name)}"></div>
      <div class="grid"><div class="field"><label>Battery warning (%)</label><input type="number" name="battery_warn" min="2" max="90" value="${s.battery_warn}"></div>
        <div class="field"><label>Critical battery (%)</label><input type="number" name="battery_critical" min="1" max="80" value="${s.battery_critical}"></div></div>
      <label class="check"><input type="checkbox" name="unlock_confirm" ${s.unlock_confirm ? "checked" : ""}> Hold the button to unlock (prevents accidental unlocking)</label>
      <div class="grid"><div class="field"><label>Keep activity log (days)</label><input type="number" name="log_keep_days" min="7" value="${s.log_keep_days}"></div>
        <div class="field"><label>Contact email (for push service)</label><input type="email" name="contact_email" value="${esc(s.contact_email)}"></div></div>
      <button class="btn primary" type="submit">Save</button></form></div>
    <div class="card"><h2>Information</h2><ul class="list">
      <li><div class="grow">Device</div><b>${esc(sys.model)}</b></li>
      <li><div class="grow">Hostname</div><b>${esc(sys.hostname)}</b></li>
      <li><div class="grow">Version</div><b>${esc(sys.version)} (Python ${esc(sys.python)})</b></li>
      <li><div class="grow">Uptime</div><b>${up(sys.uptime)}</b></li>
      ${sys.cpu_temp != null ? `<li><div class="grow">CPU temperature</div><b>${sys.cpu_temp.toFixed(1)} °C</b></li>` : ""}
      <li><div class="grow">Bluetooth scanner</div><b>${esc(sys.scanner)}</b></li>
      <li><div class="grow">Free disk space</div><b>${sys.disk_free_gb} GB</b></li>
      <li><div class="grow">Database / events</div><b>${sys.db_size_mb} MB / ${sys.events}</b></li></ul></div>
    <div class="card"><h2>${I.shield} Cloudflare Access</h2>${sys.cf_access.enabled ? `<ul class="list">
      <li><div class="grow">Status</div><span class="badge ok">enabled</span></li>
      <li><div class="grow">Team</div><b style="overflow-wrap:anywhere">${esc(sys.cf_access.team)}</b></li>
      <li><div class="grow">Allowed emails</div><b style="overflow-wrap:anywhere">${esc(sys.cf_access.emails.join(", ") || "anyone allowed by the Access policy")}</b></li>
      <li><div class="grow">Signed in as</div><b>${esc(sys.cf_access.you || "– (home network)")}</b></li>
      <li><div class="grow">cloudflared machine</div><b>${esc(sys.cf_access.proxy_ips.join(", ") || "–")}</b></li>
      <li><div class="grow">Home network access without Access</div><b>${sys.cf_access.lan_bypass ? "yes" : "no"}</b></li></ul>`
      : `<div class="alert warn">${I.alert}<div>Cloudflare Access token verification is not enabled. Re-run <code>sudo ./install.sh</code> with your Cloudflare details (see README).</div></div>`}</div>
    <div class="card"><h2>Backup</h2><p class="muted">Contains users, the lock key, settings and the activity log. Keep it safe!</p>
      <a class="btn" href="/api/system/backup" download>${I.download} Download backup</a></div>`;
  $("#sf").onsubmit = (e) => { e.preventDefault(); withBusy($("#sf button"), async () => { await api("/api/settings", "PUT", formData($("#sf"))); S.boot.site_name = $("#sf").site_name.value; toast("Saved ✓", "ok"); }); };
}

// ======================================================================= start
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && S.user && (!S.sse || S.sse.readyState === 2)) connectStream();
});
boot();
