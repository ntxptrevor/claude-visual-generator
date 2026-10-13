/* NTXP Admin — owner console front end. Vanilla JS, no build step. */
(function () {
  "use strict";

  /* =========================================================
     Utilities
     ========================================================= */
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
  const raw = (s) => new Raw(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"'`]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;" }[c]));
  const flat = (v) => (v == null || v === false ? "" : v instanceof Raw ? v.s : Array.isArray(v) ? v.map(flat).join("") : esc(v));
  function html(strings, ...vals) {
    let out = strings[0];
    vals.forEach((v, i) => { out += flat(v) + strings[i + 1]; });
    return new Raw(out);
  }
  const mount = (el, r) => { el.innerHTML = r instanceof Raw ? r.s : esc(r); return el; };
  const frag = (r) => { const t = document.createElement("template"); t.innerHTML = r.s; return t.content.firstElementChild; };
  const safeUrl = (u) => (/^https?:\/\//i.test(String(u || "")) ? String(u) : "#");
  const slug = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9_-]+/g, "-");
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  const store = {
    get(k, d) { try { const v = localStorage.getItem("ntxp-admin:" + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("ntxp-admin:" + k, JSON.stringify(v)); } catch (e) { /* storage unavailable */ } },
  };

  const decimalsOf = (v) => { const s = String(v); return s.includes(".") ? Math.min(2, s.split(".")[1].length) : 0; };
  const fmt = (v, dec) => (v == null || isNaN(v) ? "—" : Number(v).toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec }));
  const pct = (v) => (v == null ? "—" : Math.round(Number(v) * 100) + "%");
  const money = (v) => "$" + Number(v || 0).toFixed(Number(v) < 0.1 ? 3 : 2);
  function when(isoStr, withTime) {
    if (!isoStr) return "—";
    const d = new Date(isoStr);
    if (isNaN(d)) return String(isoStr);
    const opts = { month: "short", day: "numeric" };
    if (d.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
    if (withTime) { opts.hour = "numeric"; opts.minute = "2-digit"; }
    return d.toLocaleString("en-US", opts);
  }
  function ago(isoStr) {
    const d = new Date(isoStr); if (isNaN(d)) return "";
    const s = (Date.now() - d.getTime()) / 1000;
    if (s < 60) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " d ago";
  }
  const initials = (name) => String(name || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  const cap = (s) => String(s || "").charAt(0).toUpperCase() + String(s || "").slice(1);

  function animateNumber(el, from, to, dec, dur) {
    if (!el) return;
    if (REDUCED || from === to || isNaN(from)) { el.textContent = fmt(to, dec); return; }
    const t0 = performance.now(); dur = dur || 900;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur); const e = 1 - Math.pow(1 - k, 3);
      el.textContent = fmt(from + (to - from) * e, dec);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  /* =========================================================
     Icons (static, trusted markup)
     ========================================================= */
  const P = {
    home: '<path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.6 3.3-5.5 6.5-5.5s5.9 1.9 6.5 5.5"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.8c2 .7 3.2 2.5 3.5 5.2"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    book: '<path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h11"/>',
    grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    flag: '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3.5 6.5L12 13l8.5-6.5"/>',
    dollar: '<path d="M12 3v18M16.5 7.5c-.8-1.4-2.4-2-4.5-2-2.6 0-4.3 1.2-4.3 3.1 0 4.4 9 2.3 9 6.8 0 2-1.9 3.1-4.7 3.1-2.2 0-3.9-.8-4.6-2.3"/>',
    upload: '<path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    download: '<path d="M12 4v12M7 11l5 5 5-5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    shield: '<path d="M12 3l7.5 3v5.5c0 4.6-3.2 8.2-7.5 9.5-4.3-1.3-7.5-4.9-7.5-9.5V6z"/>',
    share: '<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.2 10.8l7.6-3.6M8.2 13.2l7.6 3.6"/>',
    sync: '<path d="M20 11a8 8 0 0 0-14.3-4.3L4 9M4 13a8 8 0 0 0 14.3 4.3L20 15"/><path d="M4 4v5h5M20 20v-5h-5"/>',
    play: '<path d="M7 5l12 7-12 7z"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    print: '<path d="M7 9V4h10v5M7 17H5a1 1 0 0 1-1-1v-5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v5a1 1 0 0 1-1 1h-2"/><rect x="7" y="14" width="10" height="6"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    up: '<path d="M12 19V5M6 11l6-6 6 6"/>',
    down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
    flat: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    chev: '<path d="M6 9l6 6 6-6"/>',
    ext: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    star: '<path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.8-5.2-2.8-5.2 2.8 1-5.8-4.3-4.1 5.9-.8z"/>',
    tag: '<path d="M3 12V4h8l9 9-8 8z"/><circle cx="7.5" cy="8.5" r="1.3"/>',
    trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
    folder: '<path d="M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/>',
    send: '<path d="M4 12l16-8-6 16-3-7z"/>',
  };
  const icon = (name, cls) => raw(`<svg class="${cls || ""}" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${P[name] || P.grid}</svg>`);

  /* =========================================================
     State
     ========================================================= */
  const MODULES = [
    { id: "home", label: "Home", icon: "home" },
    { id: "search", label: "Search", icon: "search" },
    { id: "contacts", label: "Contacts", icon: "users" },
    { id: "analytics", label: "Analytics", icon: "chart" },
    { id: "runbook", label: "Runbook", icon: "book" },
    { id: "workspace", label: "Workspace", icon: "grid" },
  ];
  const state = {
    demo: false, ready: false, open: false, pinned: store.get("pinned", false), module: store.get("module", "home"),
    me: null, health: null, actions: null, summary: null, flags: null, signedOut: false,
    stream: { mode: "connecting", es: null, poll: null, demoTimer: null },
    search: { text: "", guide: null, answers: {}, scope: "all", result: null, busy: false },
    contacts: { tab: "all", q: "", rows: [], selected: new Set(), last: null, loading: false },
    analytics: { flagStatus: "open", flagLevel: "" },
    runbook: { q: "", entries: null, adding: false },
    workspace: { users: null, files: null, q: "", user: "", externalOnly: false },
  };

  /* =========================================================
     API
     ========================================================= */
  class ApiError extends Error { constructor(msg, status, code) { super(msg); this.status = status; this.code = code; } }

  async function api(method, path, body, opts) {
    opts = opts || {};
    if (state.demo) {
      const res = await window.NTXPDemo.handle(method, path, body);
      if (res.status >= 400) {
        const e = new ApiError((res.data && res.data.error) || "Request failed", res.status, res.data && res.data.code);
        if (!opts.quiet) toast(e.message, "error");
        throw e;
      }
      return opts.raw ? res.text : res.data;
    }
    const init = { method, credentials: "same-origin", headers: { Accept: opts.raw ? "text/csv" : "application/json" } };
    if (body instanceof FormData) init.body = body;
    else if (body !== undefined) { init.body = JSON.stringify(body); init.headers["Content-Type"] = "application/json"; }
    let r;
    try { r = await fetch(path, init); }
    catch (e) {
      const err = new ApiError("Cannot reach the NTXP Admin server. Check your connection.", 0, "network");
      if (!opts.quiet) toast(err.message, "error");
      throw err;
    }
    if (r.status === 401 || r.status === 403) {
      if (!opts.quiet) showSignin(r.status);
      throw new ApiError("Not signed in", r.status, "auth");
    }
    if (!r.ok) {
      let msg = "Request failed (" + r.status + ")", code = "http_" + r.status;
      try { const j = await r.json(); if (j && j.error) { msg = j.error; code = j.code || code; } } catch (e) { /* non-JSON error */ }
      const err = new ApiError(msg, r.status, code);
      if (!opts.quiet) toast(msg, "error");
      throw err;
    }
    if (opts.raw) return r.text();
    const ct = r.headers.get("content-type") || "";
    return ct.includes("json") ? r.json() : r.text();
  }
  const GET = (p, o) => api("GET", p, undefined, o);
  const POST = (p, b, o) => api("POST", p, b === undefined ? {} : b, o);
  const PATCH = (p, b, o) => api("PATCH", p, b, o);

  /* =========================================================
     Toasts and dialogs
     ========================================================= */
  function toast(msg, kind) {
    const el = frag(html`<div class="toast ${kind || ""}"><span>${msg}</span></div>`);
    $("#toasts").appendChild(el);
    setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .3s"; setTimeout(() => el.remove(), 320); }, kind === "error" ? 6000 : 4000);
  }

  let dialogResolve = null; let dialogReturn = null;
  function showDialog(o) {
    const layer = $("#dialog-layer");
    if (dialogResolve) closeDialog(null);
    dialogReturn = document.activeElement;
    const btns = (o.actions || [{ label: "OK", value: true, cls: "btn-primary" }]);
    mount(layer, html`<div class="dialog ${o.wide ? "wide" : ""}" role="alertdialog" aria-modal="true" aria-labelledby="dlg-title">
      ${o.kicker ? html`<span class="kicker">${o.kicker}</span>` : ""}
      <h2 id="dlg-title">${o.title}</h2>
      <div class="dlg-body">${o.body || ""}</div>
      <div class="dialog-foot">${btns.map((b, i) => html`<button type="button" class="btn ${b.cls || ""}" data-i="${i}">${b.label}</button>`)}</div>
    </div>`);
    layer.hidden = false;
    const el = $(".dialog", layer);
    const p = new Promise((resolve) => { dialogResolve = resolve; });
    $$(".dialog-foot .btn", el).forEach((b) => b.addEventListener("click", () => {
      const a = btns[+b.dataset.i];
      if (a.validate && !a.validate(el)) return;
      closeDialog({ value: a.value, el });
    }));
    setTimeout(() => { const f = $("[autofocus]", el) || $(".dialog-foot .btn:last-child", el); if (f) f.focus(); }, 30);
    return { el, promise: p };
  }
  function closeDialog(result) {
    const layer = $("#dialog-layer");
    const r = dialogResolve; dialogResolve = null;
    layer.hidden = true;
    const el = $(".dialog", layer);
    if (r) r(result || { value: null, el });
    setTimeout(() => { if (layer.hidden) layer.innerHTML = ""; }, 0);
    if (dialogReturn && document.contains(dialogReturn)) dialogReturn.focus();
  }

  /* =========================================================
     Shell: launcher, panel, rail, top bar
     ========================================================= */
  const consoleEl = () => $("#console");

  function openConsole() {
    if (state.open) return;
    state.open = true;
    $("#scrim").hidden = false; consoleEl().hidden = false;
    $("#launcher").setAttribute("aria-expanded", "true");
    applyPinned();
    if (!state.ready) boot(); else go(state.module, true);
    setTimeout(() => { const b = $(`.rail-btn[aria-current="page"]`); (b || $("#close-btn")).focus(); }, 40);
  }
  function closeConsole() {
    if (!state.open) return;
    state.open = false;
    consoleEl().hidden = true; $("#scrim").hidden = true;
    closeDrawer(true); closeHealth();
    $("#launcher").setAttribute("aria-expanded", "false");
    $("#launcher").focus();
  }
  function applyPinned() {
    consoleEl().classList.toggle("pinned", !!state.pinned);
    $("#pin-btn").setAttribute("aria-pressed", String(!!state.pinned));
    $("#pin-btn").setAttribute("aria-label", state.pinned ? "Restore pop-up size" : "Pin to full page");
    $("#scrim").style.display = state.pinned ? "none" : "";
  }

  function renderRail() {
    const redflags = (state.flags || []).filter((f) => f.status === "open" && (f.severity === "redflag" || f.level === 3)).length;
    mount($("#rail"), html`${MODULES.map((m) => html`<button type="button" class="rail-btn" data-mod="${m.id}" ${m.id === state.module ? raw('aria-current="page"') : ""} aria-label="${m.label}">
        ${icon(m.icon)}<span class="lbl">${m.label}</span>${m.id === "analytics" && redflags ? html`<span class="count" aria-label="${redflags} red flags">${redflags}</span>` : ""}
      </button>`)}
      <div class="rail-foot">NTXP LLC<br>101 South Locust St Ste 605<br>Denton, TX 76201</div>`);
  }

  function go(mod, force) {
    if (!MODULES.some((m) => m.id === mod)) mod = "home";
    if (mod === state.module && !force && $("#main").dataset.mod === mod) return;
    state.module = mod; store.set("module", mod);
    renderRail();
    const main = $("#main");
    main.dataset.mod = mod; main.scrollTop = 0;
    if (state.signedOut) return showSignin(403);
    ({ home: renderHome, search: renderSearch, contacts: renderContacts, analytics: renderAnalytics, runbook: renderRunbook, workspace: renderWorkspace })[mod]();
  }

  function renderMe() {
    const m = state.me;
    if (!m) { mount($("#me"), ""); return; }
    const known = { "alison@ntxpllc.com": "Owner · Designated signatory", "trevor@ntxpllc.com": "Operations contact" };
    mount($("#me"), html`<span class="avatar" aria-hidden="true">${initials(m.name)}</span>
      <span class="me-text"><b>${m.name}</b><span>${known[String(m.email).toLowerCase()] || cap(m.role)}</span></span>
      <span class="sr-only">Signed in as ${m.name}, ${m.email}</span>`);
  }

  function setStatus() {
    const dot = $("#status-dot"), lbl = $("#status-label");
    const h = state.health;
    const errs = h ? Object.values(h.sources || {}).filter((v) => v === "error").length : 0;
    let cls = "", text = "Connecting";
    if (state.signedOut) { cls = "err"; text = "Signed out"; }
    else if (state.stream.mode === "live") { cls = errs ? "warn" : "live"; text = state.demo ? "Demo · live" : "Live"; }
    else if (state.stream.mode === "polling") { cls = "warn"; text = state.demo ? "Demo · polling" : "Polling 30 s"; }
    else if (h) { cls = errs ? "warn" : "live"; text = state.demo ? "Demo" : "Online"; }
    dot.className = "dot " + cls; lbl.textContent = text;
    $("#status-btn").setAttribute("aria-label", "Source health: " + text + (errs ? ", " + errs + " source error" + (errs > 1 ? "s" : "") : ""));
  }

  function renderHealth() {
    const h = state.health || { sources: {} };
    const entries = Object.entries(h.sources || {});
    const label = { gmail: "Gmail", drive: "Drive", calendar: "Calendar", contacts: "Contacts", directory: "Directory", reports: "Admin reports", jobtread: "JobTread", plaud: "Plaud", quo: "Quo phone", council: "Model Council", sheets_db: "Admin DB sheet" };
    mount($("#health-pop"), html`<h3 class="kicker">Source health</h3>
      ${state.demo ? html`<p class="muted" style="margin:0 0 10px;font-size:12px">Demo mode — synthetic data. Changes stay in this tab.</p>` : ""}
      <ul class="health-list">${entries.map(([k, v]) => html`<li><span>${label[k] || k}</span><span class="pill ${slug(v)}">${v}</span></li>`)}</ul>
      <p class="muted" style="margin:10px 0 0;font-size:12px">Analytics stream: ${state.stream.mode === "live" ? "live" : state.stream.mode === "polling" ? "polling every 30 s" : "connecting"}</p>`);
  }
  function toggleHealth() {
    const pop = $("#health-pop"); const btn = $("#status-btn");
    if (pop.hidden) { renderHealth(); pop.hidden = false; btn.setAttribute("aria-expanded", "true"); }
    else closeHealth();
  }
  function closeHealth() { $("#health-pop").hidden = true; $("#status-btn").setAttribute("aria-expanded", "false"); }

  function showSignin(status) {
    state.signedOut = true; setStatus();
    mount($("#main"), html`<div class="signin"><div class="glass">
      <span class="kicker kicker-gold">NTXP 2.1</span>
      <h2>Sign in with your NTXP Google account</h2>
      <p class="ink2">${status === 403 ? "This console is limited to the NTXP owners. Sign in with an owner account to continue." : "Your session has ended. Sign in again to continue."}</p>
      <p><a class="btn btn-primary" href="/oauth2/sign_in?rd=%2F">Sign in with Google</a></p>
    </div></div>`);
  }

  /* =========================================================
     Boot
     ========================================================= */
  async function detectDemo() {
    const forced = /[?&]demo\b/.test(location.search) || /(^#|[#&])demo\b/.test(location.hash);
    if (forced || !window.fetch) return true;
    try {
      const r = await fetch("/api/health", { credentials: "same-origin", headers: { Accept: "application/json" } });
      if (r.status === 401 || r.status === 403) { state.signedOut = true; return false; }
      if (!r.ok) return true;
      const j = await r.json();
      state.health = j;
      return !!j.demo;
    } catch (e) { return true; }
  }

  let bootPromise = null;
  function boot() {
    if (bootPromise) return bootPromise;
    mount($("#main"), html`<div class="glass pad"><div class="skeleton" style="width:40%"></div><div class="skeleton" style="width:70%;margin-top:12px"></div></div>`);
    bootPromise = (async () => {
      state.demo = await detectDemo();
      state.ready = true;
      if (state.signedOut) { renderRail(); showSignin(403); return; }
      const [me, health] = await Promise.all([GET("/api/me", { quiet: true }).catch(() => null), state.health && !state.demo ? state.health : GET("/api/health", { quiet: true }).catch(() => null)]);
      if (state.signedOut) return;
      state.me = me; state.health = health;
      renderMe(); setStatus();
      loadFlags().then(() => { renderRail(); updateBadge(); }).catch(() => {});
      startStream();
      if (state.open) go(state.module, true);
    })();
    return bootPromise;
  }

  async function loadSummary(force) {
    if (state.summary && !force) return state.summary;
    state.summary = await GET("/api/analytics/summary");
    return state.summary;
  }
  async function loadFlags() {
    const qs = new URLSearchParams({ status: state.analytics.flagStatus });
    if (state.analytics.flagLevel) qs.set("level", state.analytics.flagLevel);
    const r = await GET("/api/flags?" + qs.toString());
    state.flags = r.flags || [];
    return state.flags;
  }
  function updateBadge() {
    const n = (state.flags || []).filter((f) => f.status === "open" && (f.severity === "redflag" || f.level === 3)).length;
    const b = $("#launcher-badge");
    b.hidden = !n; b.textContent = n;
    $("#launcher").setAttribute("aria-label", "Open NTXP Admin console" + (n ? ", " + n + " open red flag" + (n > 1 ? "s" : "") : ""));
  }

  /* =========================================================
     Module: Home
     ========================================================= */
  async function renderHome() {
    const main = $("#main");
    mount(main, html`<div class="mod-head"><div><span class="kicker kicker-gold">Owner actions</span><h2>Good ${greeting()}, ${state.me ? state.me.name.split(" ")[0] : "owner"}</h2>
      <p>Ten things the owners do most, one click each. Today's numbers come from the analytics engine.</p></div></div>
      ${state.demo ? html`<div class="demo-banner">${icon("flag")}<span>Demo mode — synthetic NTXP records. Every action works and changes stay in this browser tab.</span></div>` : ""}
      <div class="today" id="today">${[0, 1, 2].map(() => html`<div class="today-item"><div class="skeleton" style="width:100%"></div></div>`)}</div>
      <div class="actions-grid" id="actions-grid"></div>`);
    try {
      if (!state.actions) state.actions = await GET("/api/actions");
    } catch (e) { state.actions = []; }
    if (state.module !== "home") return;
    mount($("#actions-grid"), html`${(state.actions || []).slice(0, 10).map((a) => html`<button type="button" class="glass action-card hoverline" data-mod="${a.module}" data-action="${a.id}">
        <span class="ic">${icon(a.icon)}</span><b>${a.title}</b><span class="blurb">${a.blurb}</span><span class="go">Open ${moduleLabel(a.module)} →</span>
      </button>`)}`);
    if (!state.actions.length) mount($("#actions-grid"), html`<div class="empty">No owner actions available.</div>`);
    try {
      const [sum] = await Promise.all([loadSummary(), state.flags ? state.flags : loadFlags()]);
      if (state.module !== "home") return;
      const tile = (id) => (sum.tiles || []).find((t) => t.id === id || t.report_id === id);
      const red = (state.flags || []).filter((f) => f.status === "open" && (f.severity === "redflag" || f.level === 3)).length;
      const ue = tile("unanswered_email"), bq = tile("open_billing_questions");
      mount($("#today"), html`
        <button type="button" class="today-item ${red ? "alert" : ""}" data-mod="analytics" data-scroll="flags"><span class="big">${red}</span><span class="lbl"><span class="kicker">Today</span><b>Open red flags</b></span></button>
        <button type="button" class="today-item" data-report="${ue ? ue.report_id : "unanswered_email"}"><span class="big">${ue ? ue.display : "—"}</span><span class="lbl"><span class="kicker">Today</span><b>Unanswered client emails</b></span></button>
        <button type="button" class="today-item" data-report="${bq ? bq.report_id : "open_billing_questions"}"><span class="big">${bq ? bq.display : "—"}</span><span class="lbl"><span class="kicker">Today</span><b>Open billing questions</b></span></button>`);
    } catch (e) {
      mount($("#today"), html`<div class="today-item"><span class="lbl"><b>Today's numbers are unavailable</b><span class="muted">The analytics engine did not answer.</span></span></div>`);
    }
  }
  const greeting = () => { const h = new Date().getHours(); return h < 12 ? "morning" : h < 17 ? "afternoon" : "evening"; };
  const moduleLabel = (id) => (MODULES.find((m) => m.id === id) || { label: cap(id) }).label;

  /* =========================================================
     Module: Search
     ========================================================= */
  const SEARCH_EXAMPLES = ["Jalen's emails about the roof drain RFI", "How often are clients waiting on billing replies?", "Everything open on Cedar Hollow Library"];

  function renderSearch() {
    const S = state.search;
    mount($("#main"), html`<div class="mod-head"><div><span class="kicker">Guided semantic search</span><h2>Search</h2>
      <p>All NTXP mailboxes and Drive. Say it in plain words; I'll ask a couple of questions to narrow it.</p></div></div>
      <form class="glass search-compose" id="search-form">
        <label class="sr-only" for="search-text">Describe what you're looking for</label>
        <textarea class="input" id="search-text" placeholder="Describe what you're looking for — a specific message, a trend, a project, or a person">${S.text}</textarea>
        <div class="compose-foot">
          <div class="example-chips">${SEARCH_EXAMPLES.map((x) => html`<button type="button" class="chip" data-example="${x}">${x}</button>`)}</div>
          <button type="submit" class="btn btn-primary" style="margin-left:auto">${icon("send")} Continue</button>
        </div>
      </form>
      <div id="guide-area"></div>
      <div id="results-area"></div>`);
    if (S.guide) renderGuide();
    if (S.result) renderResults();
  }

  async function runGuide(text) {
    const S = state.search;
    S.text = text; S.answers = {}; S.result = null;
    mount($("#guide-area"), html`<div class="restated"><span class="kicker">Understanding</span><div class="skeleton" style="width:60%"></div></div>`);
    mount($("#results-area"), "");
    try {
      S.guide = await POST("/api/search/guide", { text });
      renderGuide();
    } catch (e) { mount($("#guide-area"), ""); }
  }

  function renderGuide() {
    const S = state.search, g = S.guide, d = g.draft || {};
    const list = (a) => (a || []).join(", ");
    mount($("#guide-area"), html`<div class="restated"><span class="kicker">I understood · ${g.intent}</span><p>${g.restated}</p></div>
      <div class="guide-grid">
        <div class="glass pad" aria-label="Clarifying questions">
          <span class="kicker">A few quick questions</span>
          ${(g.questions || []).map((q) => html`<div class="q-block" role="group" aria-labelledby="q-${slug(q.id)}">
              <div class="q" id="q-${slug(q.id)}">${q.question}<small>${q.multi ? "Pick any" : "Pick one"}</small></div>
              <div class="chips">${(q.options || []).map((o) => html`<button type="button" class="chip" data-q="${q.id}" data-multi="${q.multi ? 1 : 0}" data-opt="${o}" aria-pressed="${isAnswered(q.id, o) ? "true" : "false"}">${o}</button>`)}</div>
            </div>`)}
        </div>
        <form class="glass draft" id="draft-form" aria-label="Search draft">
          <span class="kicker">Draft · edit anything</span>
          <label class="field"><span>People</span><input class="input" name="people" value="${list(d.people)}" placeholder="Names, comma separated"></label>
          <label class="field"><span>Mailboxes</span><input class="input" name="users" value="${list(d.users)}" placeholder="All domain users"></label>
          <div class="row2"><label class="field"><span>From</span><input class="input" name="from" value="${d.from || ""}"></label>
            <label class="field"><span>To</span><input class="input" name="to" value="${d.to || ""}"></label></div>
          <div class="row2"><label class="field"><span>Date from</span><input class="input" type="date" name="date_from" value="${d.date_from || ""}"></label>
            <label class="field"><span>Date to</span><input class="input" type="date" name="date_to" value="${d.date_to || ""}"></label></div>
          <label class="field"><span>Keywords</span><input class="input" name="keywords" value="${list(d.keywords)}"></label>
          <label class="field"><span>Project</span><input class="input" name="project" value="${d.project || ""}"></label>
          <label class="toggle"><input type="checkbox" name="has_attachment" ${d.has_attachment ? raw("checked") : ""}> Has attachment</label>
        </form>
      </div>
      <div class="run-row">
        <div class="seg" role="group" aria-label="Scope">${["all", "gmail", "drive"].map((s) => html`<button type="button" data-scope="${s}" aria-pressed="${S.scope === s}">${{ all: "Mail + Drive", gmail: "Mail", drive: "Drive" }[s]}</button>`)}</div>
        <button type="button" class="btn btn-primary" id="run-search">${icon("search")} Run search</button>
        ${g.jev ? jevBadge(g.jev) : ""}
      </div>`);
  }
  function isAnswered(qid, opt) {
    const a = state.search.answers[qid];
    return Array.isArray(a) ? a.includes(opt) : a === opt;
  }
  function readDraft() {
    const f = $("#draft-form"); const base = Object.assign({}, state.search.guide.draft || {});
    if (!f) return base;
    const split = (v) => String(v || "").split(",").map((s) => s.trim()).filter(Boolean);
    base.people = split(f.people.value); base.users = split(f.users.value);
    base.from = f.from.value.trim(); base.to = f.to.value.trim();
    base.date_from = f.date_from.value; base.date_to = f.date_to.value;
    base.keywords = split(f.keywords.value); base.project = f.project.value.trim();
    base.has_attachment = f.has_attachment.checked;
    base.labels = base.labels || [];
    return base;
  }
  async function runSearch() {
    const S = state.search;
    if (S.busy) return;
    const draft = readDraft(); S.guide.draft = draft; S.busy = true;
    const btn = $("#run-search"); if (btn) btn.disabled = true;
    mount($("#results-area"), html`<h3 class="section">Results</h3><div class="results">${[0, 1, 2].map(() => html`<div class="glass result"><div><div class="skeleton" style="width:40%"></div><div class="skeleton" style="width:85%;margin-top:10px"></div></div></div>`)}</div>`);
    try {
      S.result = await POST("/api/search/run", { draft, answers: S.answers, scope: S.scope, limit: 25 });
      renderResults();
    } catch (e) { mount($("#results-area"), ""); }
    finally { S.busy = false; if ($("#run-search")) $("#run-search").disabled = false; }
  }
  function jevBadge(j) {
    return html`<span class="jev" title="Jev routing: tier, executor and cost">Tier <b>${j.tier}</b> · ${j.executor || "—"} · <b>${money(j.cost)}</b></span>`;
  }
  function renderResults() {
    const r = state.search.result; if (!r) return;
    const t = r.trend, pj = r.project, res = r.results || [];
    const maxB = t ? Math.max(1, ...t.buckets.map((b) => b.count)) : 1;
    const maxP = t ? Math.max(1, ...t.by_person.map((b) => b.count)) : 1;
    mount($("#results-area"), html`
      <h3 class="section">Results <span class="kicker">${res.length} match${res.length === 1 ? "" : "es"}</span><span style="margin-left:auto">${r.jev ? jevBadge(r.jev) : ""}</span></h3>
      ${t ? html`<div class="trend-grid">
          <div class="glass pad"><span class="kicker">Trend over time</span>
            <div class="vbars" role="img" aria-label="Trend: ${t.buckets.map((b) => b.period + " " + b.count).join(", ")}">${t.buckets.map((b) => html`<div class="vbar"><b>${b.count}</b><i style="height:${Math.round((b.count / maxB) * 100)}%"></i><span>${b.period}</span></div>`)}</div>
            <p class="summary-text">${t.summary}</p></div>
          <div class="glass pad"><span class="kicker">By person</span><div class="hbars" style="margin-top:12px">${t.by_person.map((p) => html`<div class="hbar" style="grid-template-columns:110px minmax(0,1fr) 34px"><span>${p.person}</span><span class="track"><i style="width:${Math.round((p.count / maxP) * 100)}%"></i></span><span class="v">${p.count}</span></div>`)}</div></div>
        </div>` : ""}
      ${pj ? html`<div class="glass pad" style="margin-bottom:16px"><span class="kicker">Project summary</span>
          <h3 style="margin:6px 0 8px;font:600 18px var(--f-display)">${pj.name}</h3><p class="ink2" style="margin:0 0 12px">${pj.summary}</p>
          <div class="flag-cols"><div><h5>People</h5><ul>${(pj.people || []).map((p) => html`<li>${p}</li>`)}</ul></div>
          <div><h5>Open items</h5><ul>${(pj.open_items || []).map((p) => html`<li>${p}</li>`)}</ul></div></div></div>` : ""}
      <div class="results">${res.length ? res.map((m) => html`<article class="glass result hoverline">
          <div><div class="meta"><span class="pill plain">${m.source === "drive" ? "Drive" : "Gmail"}</span><span>From <b>${m.from}</b></span>${m.to ? html`<span>To <b>${m.to}</b></span>` : ""}<span>Mailbox <b>${m.user}</b></span></div>
          <h4>${m.subject}</h4><p>${m.snippet}</p></div>
          <div class="side"><span class="mono muted" style="font-size:12px">${when(m.date)}</span>
            <span class="score-wrap" title="Relevance ${pct(m.score)}"><span class="score" aria-hidden="true"><i style="width:${Math.round((m.score || 0) * 100)}%"></i></span><span class="score-lbl">${pct(m.score)} match</span></span>
            <a class="btn btn-sm" href="${safeUrl(m.link)}" target="_blank" rel="noopener noreferrer">${icon("ext")} Open</a></div>
        </article>`) : html`<div class="glass empty">No matches. Loosen the keywords or widen the date range.</div>`}</div>`);
  }

  /* =========================================================
     Module: Shared Contacts
     ========================================================= */
  const CCOLS = [
    { key: "name", label: "Name", cls: "w-name" },
    { key: "emails", label: "Email", cls: "w-email", list: true },
    { key: "phones", label: "Phone", cls: "w-phone", list: true },
    { key: "org", label: "Organization", cls: "w-org" },
    { key: "title", label: "Title", cls: "w-title" },
    { key: "labels", label: "Labels", cls: "w-labels", list: true },
    { key: "address", label: "Address", cls: "w-addr" },
    { key: "notes", label: "Notes", cls: "w-notes" },
  ];
  const cellText = (c, col) => (col.list ? (c[col.key] || []).join(", ") : c[col.key] || "");

  function renderContacts() {
    const C = state.contacts;
    mount($("#main"), html`<div class="mod-head"><div><span class="kicker">IPDM shared address book</span><h2>Shared Contacts</h2>
      <p>Edit cells directly — changes save on Enter or when you leave the cell. Tab moves across, arrows move rows, Esc reverts.</p></div>
      <div class="mod-actions">
        <button type="button" class="btn" id="c-import">${icon("upload")} Import</button>
        <button type="button" class="btn" id="c-export">${icon("download")} Export</button>
        <button type="button" class="btn" id="c-sync">${icon("sync")} Sync now</button>
      </div></div>
      <div class="contacts-tools">
        <div class="tabs" role="tablist" aria-label="Contact source">${[["all", "All"], ["workspace", "Workspace"], ["directory", "Directory"], ["shared", "Shared (IPDM)"]].map(([k, l]) => html`<button type="button" role="tab" data-tab="${k}" aria-selected="${C.tab === k}">${l}</button>`)}</div>
        <label class="search-inline">${icon("search")}<span class="sr-only">Filter contacts</span><input class="input" type="search" id="c-q" placeholder="Filter by name, email, org, label…" value="${C.q}"></label>
      </div>
      <div id="bulkbar-slot"></div>
      <div class="table-wrap contacts-wrap"><table class="grid sheet" aria-label="Contacts" aria-rowcount="0">
        <thead><tr><th class="sel"><input type="checkbox" class="cbx" id="c-all" aria-label="Select all visible contacts"></th><th class="star-h" title="Shared to IPDM">★</th>
          ${CCOLS.map((c) => html`<th class="${c.cls}">${c.label}</th>`)}<th>Source</th><th>Owner</th><th>Updated</th></tr></thead>
        <tbody id="c-body"><tr><td colspan="13" class="ro" style="padding:16px"><div class="skeleton"></div></td></tr></tbody></table></div>
      <div class="grid-foot"><span id="c-count"></span><span><kbd>Tab</kbd> next cell · <kbd>Enter</kbd> save · <kbd>Esc</kbd> revert · <kbd>Shift</kbd>-click range select</span></div>`);
    loadContacts();
  }

  let contactsReq = 0;
  async function loadContacts() {
    const C = state.contacts; const my = ++contactsReq;
    const qs = new URLSearchParams({ source: C.tab, limit: "500" });
    if (C.q) qs.set("q", C.q);
    try {
      const r = await GET("/api/contacts?" + qs.toString());
      if (my !== contactsReq || state.module !== "contacts") return;
      C.rows = r.contacts || [];
      const ids = new Set(C.rows.map((c) => c.id));
      C.selected.forEach((id) => { if (!ids.has(id)) C.selected.delete(id); });
      C.last = null;
      drawContactRows();
    } catch (e) {
      if (my === contactsReq && $("#c-body")) mount($("#c-body"), html`<tr><td colspan="13" class="ro" style="padding:16px">Could not load contacts.</td></tr>`);
    }
  }

  function drawContactRows() {
    const C = state.contacts; const tb = $("#c-body"); if (!tb) return;
    tb.textContent = "";
    if (!C.rows.length) { mount(tb, html`<tr><td colspan="13"><div class="empty">No contacts match.</div></td></tr>`); }
    C.rows.forEach((c, i) => tb.appendChild(contactRow(c, i)));
    $(".sheet").setAttribute("aria-rowcount", String(C.rows.length));
    $("#c-count").textContent = C.rows.length + " contact" + (C.rows.length === 1 ? "" : "s");
    syncSelectionUI();
  }

  function contactRow(c, i) {
    const tr = document.createElement("tr");
    tr.dataset.id = c.id; tr.dataset.idx = i;
    const sel = document.createElement("td"); sel.className = "sel";
    const cb = document.createElement("input"); cb.type = "checkbox"; cb.className = "cbx row-cb";
    cb.setAttribute("aria-label", "Select " + (c.name || c.id)); cb.checked = state.contacts.selected.has(c.id);
    sel.appendChild(cb); tr.appendChild(sel);
    const star = document.createElement("td"); star.className = "ro star-cell"; tr.appendChild(star); paintStar(star, c);
    CCOLS.forEach((col) => {
      const td = document.createElement("td"); td.className = col.cls;
      const inp = document.createElement("input");
      inp.className = "cell"; inp.type = "text"; inp.value = cellText(c, col); inp.dataset.orig = inp.value; inp.dataset.col = col.key;
      inp.setAttribute("aria-label", col.label + " for " + (c.name || c.id)); inp.spellcheck = false; inp.autocomplete = "off";
      td.appendChild(inp); tr.appendChild(td);
    });
    [["source", cap(c.source)], ["owner_user", c.owner_user], ["updated", when(c.updated)]].forEach(([k, v]) => {
      const td = document.createElement("td"); td.className = "ro"; td.dataset.k = k; td.textContent = v || "—"; tr.appendChild(td);
    });
    if (state.contacts.selected.has(c.id)) tr.classList.add("selected");
    return tr;
  }
  function paintStar(td, c) {
    mount(td, c.shared ? html`<span class="pill star" title="In the IPDM shared address book" aria-label="Shared">★</span>` : html`<span class="muted" aria-label="Not shared">—</span>`);
  }

  function syncSelectionUI() {
    const C = state.contacts; const n = C.selected.size;
    $$("#c-body tr[data-id]").forEach((tr) => {
      const on = C.selected.has(tr.dataset.id);
      tr.classList.toggle("selected", on); const cb = $(".row-cb", tr); if (cb) cb.checked = on;
    });
    const all = $("#c-all");
    if (all) { all.checked = n > 0 && n === C.rows.length; all.indeterminate = n > 0 && n < C.rows.length; }
    const slot = $("#bulkbar-slot"); if (!slot) return;
    if (!n) { slot.textContent = ""; return; }
    mount(slot, html`<div class="bulkbar" role="toolbar" aria-label="Bulk actions"><span class="count">${n} selected</span>
      <button type="button" class="btn btn-sm" data-bulk="share">${icon("star")} Share to IPDM</button>
      <button type="button" class="btn btn-sm" data-bulk="unshare">Unshare</button>
      <button type="button" class="btn btn-sm" data-bulk="label">${icon("tag")} Add label</button>
      <button type="button" class="btn btn-sm" data-bulk="export">${icon("download")} Export selected</button>
      <button type="button" class="btn btn-sm btn-danger" data-bulk="delete">${icon("trash")} Delete</button>
      <button type="button" class="btn btn-sm btn-ghost" data-bulk="clear" style="margin-left:auto">Clear</button></div>`);
  }

  async function commitCell(inp) {
    const val = inp.value.trim();
    if (val === inp.dataset.orig || inp.dataset.busy === "1") { inp.classList.remove("dirty"); return; }
    const tr = inp.closest("tr"); const td = inp.closest("td");
    const C = state.contacts; const idx = +tr.dataset.idx; const c = C.rows[idx];
    const col = CCOLS.find((x) => x.key === inp.dataset.col);
    const value = col.list ? val.split(",").map((s) => s.trim()).filter(Boolean) : val;
    inp.dataset.busy = "1"; td.dataset.state = "saving";
    try {
      const updated = await PATCH("/api/contacts/" + encodeURIComponent(c.id), { [col.key]: value });
      C.rows[idx] = Object.assign({}, c, updated || {});
      const fresh = cellText(C.rows[idx], col);
      inp.dataset.orig = fresh;
      if (document.activeElement !== inp) inp.value = fresh;
      inp.classList.remove("dirty");
      td.dataset.state = "saved";
      paintStar($(".star-cell", tr), C.rows[idx]);
      const up = $('td[data-k="updated"]', tr); if (up) up.textContent = when(C.rows[idx].updated);
      setTimeout(() => { if (td.dataset.state === "saved") delete td.dataset.state; }, 1600);
    } catch (e) {
      td.dataset.state = "error";
      td.title = e.message + " — press Esc to revert";
    } finally { inp.dataset.busy = ""; }
  }

  function contactCells() { return $$("#c-body input.cell"); }
  function focusCell(inp) { if (!inp) return; inp.focus(); inp.select(); markActiveRow(inp); }
  function markActiveRow(inp) {
    $$("#c-body tr.active").forEach((r) => r.classList.remove("active"));
    const tr = inp.closest("tr"); if (tr) tr.classList.add("active");
  }

  function onCellKey(e) {
    const inp = e.target; if (!inp.classList.contains("cell")) return;
    const cells = contactCells(); const i = cells.indexOf(inp);
    const sameColIn = (tr) => tr && $(`input.cell[data-col="${inp.dataset.col}"]`, tr);
    if (e.key === "Tab") {
      e.preventDefault(); e.stopPropagation();
      const next = cells[i + (e.shiftKey ? -1 : 1)];
      if (next) focusCell(next); else commitCell(inp);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const next = sameColIn(inp.closest("tr").nextElementSibling);
      if (next) focusCell(next); else commitCell(inp);
    } else if (e.key === "Escape") {
      e.preventDefault(); e.stopPropagation();
      inp.value = inp.dataset.orig; inp.classList.remove("dirty");
      const td = inp.closest("td"); delete td.dataset.state; td.removeAttribute("title");
      inp.select();
    } else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !e.altKey && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      const tr = inp.closest("tr");
      const next = sameColIn(e.key === "ArrowDown" ? tr.nextElementSibling : tr.previousElementSibling);
      if (next) focusCell(next);
    }
  }

  async function bulkAction(kind) {
    const C = state.contacts; const ids = Array.from(C.selected);
    if (!ids.length) return;
    if (kind === "clear") { C.selected.clear(); syncSelectionUI(); return; }
    if (kind === "export") return exportContacts(ids);
    let label;
    if (kind === "label") {
      const d = showDialog({ kicker: "Bulk label", title: `Add a label to ${ids.length} contact${ids.length > 1 ? "s" : ""}`,
        body: html`<label class="field"><span>Label</span><input class="input" id="bulk-label" autofocus placeholder="e.g. Subcontractor, 2417 North Prairie" list="label-suggest">
          <datalist id="label-suggest">${["★ NTXP Shared", "Client", "Subcontractor", "Supplier", "Architect", "Inspector"].map((l) => html`<option value="${l}">`)}</datalist></label>`,
        actions: [{ label: "Cancel", value: false, cls: "btn-ghost" }, { label: "Add label", value: true, cls: "btn-primary", validate: (el) => !!$("#bulk-label", el).value.trim() }] });
      const ip = $("#bulk-label", d.el); ip.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $(".dialog-foot .btn-primary", d.el).click(); } });
      const res = await d.promise; if (!res || !res.value) return;
      label = $("#bulk-label", res.el).value.trim();
    }
    try {
      const r = await POST("/api/contacts/bulk", { ids, action: kind, label });
      if (r.needs_approval) {
        showDialog({ kicker: "Tier 3 · owner approval required", title: "Nothing was deleted",
          body: html`<div class="tier">${r.summary}</div><p>Deletes are staged for approval inside Claude and bound to this exact list of ${ids.length} contact${ids.length > 1 ? "s" : ""}.</p>`,
          actions: [{ label: "Understood", value: true, cls: "btn-primary" }] });
        return;
      }
      const verb = { share: "Shared", unshare: "Unshared", label: "Labeled", unlabel: "Unlabeled" }[kind] || "Updated";
      toast(`${verb} ${r.done} contact${r.done === 1 ? "" : "s"}${r.failed && r.failed.length ? ` · ${r.failed.length} failed: ${r.failed.map((f) => f.error).join("; ")}` : ""}`, r.failed && r.failed.length ? "error" : "ok");
      loadContacts();
    } catch (e) { /* toast shown */ }
  }

  async function exportContacts(ids) {
    const qs = new URLSearchParams({ format: "google_csv" });
    if (ids && ids.length) qs.set("ids", ids.join(",")); else qs.set("source", state.contacts.tab === "all" ? "shared" : state.contacts.tab);
    try {
      const csv = await GET("/api/contacts/export?" + qs.toString(), { raw: true });
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = `ntxp-contacts-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      toast(`Exported ${ids && ids.length ? ids.length + " selected" : "the " + (qs.get("source") || "") + " list"} as Google CSV`, "ok");
    } catch (e) { /* toast shown */ }
  }

  async function syncContacts() {
    const b = $("#c-sync"); if (b) b.disabled = true;
    try {
      const r = await POST("/api/contacts/sync");
      toast(`Sync complete — pulled ${r.pulled}, added ${r.shared_added} to shared, removed ${r.shared_removed}`, "ok");
      loadContacts();
    } catch (e) { /* toast shown */ } finally { if (b) b.disabled = false; }
  }

  function openImport() {
    const d = showDialog({ wide: true, kicker: "Import contacts", title: "Bring in a vCard or CSV",
      body: html`<div class="form-grid" style="margin-bottom:12px">
          <label class="field"><span>Format</span><select class="input" id="imp-format">
            <option value="auto">Detect automatically</option><option value="vcf">vCard (.vcf)</option><option value="google_csv">Google CSV</option><option value="outlook_csv">Outlook CSV</option><option value="csv">Generic CSV</option></select></label>
          <label class="field"><span>Import into</span><select class="input" id="imp-target"><option value="shared">Shared (IPDM)</option><option value="workspace">My Workspace contacts</option></select></label>
        </div>
        <div class="dropzone" id="imp-drop" tabindex="0" role="button" aria-label="Choose a .vcf or .csv file, or drop it here">
          ${icon("upload")}<b>Drop a .vcf or .csv file here</b><span class="muted">or <u>choose a file</u> — Google, Outlook or generic CSV</span>
          <input type="file" id="imp-file" accept=".vcf,.csv,text/vcard,text/csv" hidden>
        </div>
        <div id="imp-preview" style="margin-top:14px"></div>`,
      actions: [{ label: "Cancel", value: false, cls: "btn-ghost" }, { label: "Import", value: "commit", cls: "btn-primary", validate: () => !!imp.file && imp.count > 0 }] });
    const imp = { file: null, count: 0 };
    const commitBtn = $(".dialog-foot .btn-primary", d.el); commitBtn.disabled = true;
    const drop = $("#imp-drop", d.el), fileIn = $("#imp-file", d.el);
    const pick = (f) => {
      if (!f) return;
      if (!/\.(vcf|csv)$/i.test(f.name)) { toast("Choose a .vcf or .csv file", "error"); return; }
      imp.file = f; preview();
    };
    drop.addEventListener("click", () => fileIn.click());
    drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileIn.click(); } });
    fileIn.addEventListener("change", () => pick(fileIn.files[0]));
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => pick(e.dataTransfer.files[0]));
    $("#imp-format", d.el).addEventListener("change", () => imp.file && preview());
    $("#imp-target", d.el).addEventListener("change", () => imp.file && preview());

    const send = (commit) => {
      const fd = new FormData(); fd.append("file", imp.file);
      const qs = new URLSearchParams({ format: $("#imp-format", d.el).value, target: $("#imp-target", d.el).value, commit: String(commit) });
      return POST("/api/contacts/import?" + qs.toString(), fd);
    };
    async function preview() {
      const box = $("#imp-preview", d.el);
      mount(box, html`<div class="skeleton"></div>`);
      try {
        const r = await send(false);
        const dupNames = new Set((r.duplicates || []).map((x) => x.incoming));
        const rows = r.preview || [];
        imp.count = rows.filter((c) => !dupNames.has(c.name || (c.emails || [])[0])).length;
        mount(box, html`<div class="updated-line" style="margin-bottom:8px"><span class="pill ok">${({ vcf: "vCard", google_csv: "Google CSV", outlook_csv: "Outlook CSV", csv: "Generic CSV" })[r.format] || r.format} detected</span>
            <span>${rows.length} found</span><span>${(r.duplicates || []).length} duplicate${(r.duplicates || []).length === 1 ? "" : "s"} will be skipped</span><span class="muted">${imp.file.name}</span></div>
          <div class="table-wrap" style="max-height:280px"><table class="grid"><thead><tr><th>Status</th><th>Name</th><th>Email</th><th>Phone</th><th>Organization</th><th>Title</th></tr></thead>
          <tbody>${rows.map((c) => { const dup = dupNames.has(c.name || (c.emails || [])[0]); return html`<tr><td>${dup ? html`<span class="pill watch">Duplicate</span>` : html`<span class="pill good">New</span>`}</td><td>${c.name}</td><td>${(c.emails || []).join(", ")}</td><td>${(c.phones || []).join(", ")}</td><td>${c.org}</td><td>${c.title}</td></tr>`; })}</tbody></table></div>`);
        commitBtn.disabled = imp.count === 0;
        commitBtn.textContent = imp.count ? `Import ${imp.count} contact${imp.count === 1 ? "" : "s"}` : "Nothing new to import";
      } catch (e) { mount(box, html`<p class="muted">Preview failed. Check the file format and try again.</p>`); commitBtn.disabled = true; }
    }
    d.promise.then(async (res) => {
      if (!res || res.value !== "commit") return;
      try {
        const r = await send(true);
        toast(`Imported ${r.created} contact${r.created === 1 ? "" : "s"}${r.skipped ? `, skipped ${r.skipped} duplicate${r.skipped === 1 ? "" : "s"}` : ""}`, "ok");
        loadContacts();
      } catch (e) { /* toast shown */ }
    });
  }

  /* =========================================================
     Charts (SVG)
     ========================================================= */
  const SLICE_COLORS = ["#4F7FAF", "#7FA6C9", "#2E527A", "#AEBBCB", "#5E6F8A", "#91B4D6"];
  const polar = (cx, cy, r, deg) => [cx + r * Math.cos((deg * Math.PI) / 180), cy + r * Math.sin((deg * Math.PI) / 180)];
  const arcPath = (cx, cy, r, a0, a1) => {
    const [x0, y0] = polar(cx, cy, r, a0), [x1, y1] = polar(cx, cy, r, a1);
    return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  };
  function tileScale(t) {
    if (t.unit === "%" || t.unit === "/100") return 100;
    const m = Math.max(Number(t.target || 0) * 2, Number(t.value || 0) * 1.25, 1);
    const pow = Math.pow(10, Math.floor(Math.log10(m)));
    return Math.ceil(m / (pow / 2)) * (pow / 2);
  }
  const unitSuffix = (u) => (u === "%" ? "%" : u === "h" ? "h" : u || "");

  function heroNum(t, size) {
    return html`<span><span class="hero" data-count="${t.value}" style="${size ? "font-size:" + size : ""}">${fmt(t.value, decimalsOf(t.value))}</span>${t.unit ? html`<span class="hero-unit">${t.unit}</span>` : ""}</span>`;
  }

  function gaugeViz(t, from) {
    const max = tileScale(t); const id = "gg-" + slug(t.id);
    const A0 = 150, A1 = 390, cx = 110, cy = 104, r = 84;
    const f = (v) => Math.max(0, Math.min(1, Number(v) / max));
    const tAng = A0 + (A1 - A0) * f(t.target);
    const [tx0, ty0] = polar(cx, cy, r - 13, tAng), [tx1, ty1] = polar(cx, cy, r + 13, tAng);
    const [mx, my] = polar(cx, cy, r, A0), [Mx, My] = polar(cx, cy, r, A1);
    return html`<div class="gwrap" style="position:relative;width:220px;height:156px">
      <svg viewBox="0 0 220 156" width="220" height="156" role="img" aria-label="${t.label}: ${t.display}${unitSuffix(t.unit)}, target ${t.target}${unitSuffix(t.unit)}">
        <defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#2E527A"/><stop offset=".55" stop-color="#7FA6C9"/><stop offset="1" stop-color="#F7F8FA"/></linearGradient></defs>
        <path d="${arcPath(cx, cy, r, A0, A1)}" fill="none" stroke="rgba(216,221,228,.08)" stroke-width="13" stroke-linecap="round"/>
        <path class="gauge-arc" data-to="${(100 - f(t.value) * 100).toFixed(2)}" d="${arcPath(cx, cy, r, A0, A1)}" fill="none" stroke="url(#${id})" stroke-width="13" stroke-linecap="round" pathLength="100" stroke-dasharray="100 200" stroke-dashoffset="${(100 - f(from) * 100).toFixed(2)}"/>
        <line x1="${tx0.toFixed(1)}" y1="${ty0.toFixed(1)}" x2="${tx1.toFixed(1)}" y2="${ty1.toFixed(1)}" stroke="#F7F8FA" stroke-width="2" stroke-linecap="round"/>
        <text x="${mx.toFixed(1)}" y="${(my + 18).toFixed(1)}" text-anchor="middle" fill="#72849C" font-family="JetBrains Mono, monospace" font-size="10">0</text>
        <text x="${Mx.toFixed(1)}" y="${(My + 18).toFixed(1)}" text-anchor="middle" fill="#72849C" font-family="JetBrains Mono, monospace" font-size="10">${max}</text>
      </svg>
      <div class="viz-center" style="top:62px">${heroNum(t)}<small>target ${t.target}${unitSuffix(t.unit)}</small></div></div>`;
  }

  function ringViz(t, from) {
    const id = "rg-" + slug(t.id); const max = tileScale(t);
    const f = (v) => Math.max(0, Math.min(1, Number(v) / max));
    const r = 62, C = 2 * Math.PI * r;
    const [tx0, ty0] = polar(80, 80, r - 11, -90 + 360 * f(t.target)), [tx1, ty1] = polar(80, 80, r + 11, -90 + 360 * f(t.target));
    const bd = (t.breakdown || []).slice(0, 3);
    return html`<div style="display:flex;flex-direction:column;align-items:center;gap:8px;width:100%">
      <div style="position:relative;width:160px;height:160px">
      <svg viewBox="0 0 160 160" width="160" height="160" role="img" aria-label="${t.label}: ${t.display}${unitSuffix(t.unit)}, target ${t.target}${unitSuffix(t.unit)}">
        <defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#F7F8FA"/><stop offset=".5" stop-color="#7FA6C9"/><stop offset="1" stop-color="#2E527A"/></linearGradient></defs>
        <circle cx="80" cy="80" r="${r}" fill="none" stroke="rgba(216,221,228,.08)" stroke-width="12"/>
        <circle class="ring-arc" data-to="${(C * (1 - f(t.value))).toFixed(2)}" cx="80" cy="80" r="${r}" fill="none" stroke="url(#${id})" stroke-width="12" stroke-linecap="round" stroke-dasharray="${C.toFixed(2)}" stroke-dashoffset="${(C * (1 - f(from))).toFixed(2)}" transform="rotate(-90 80 80)"/>
        <line x1="${tx0.toFixed(1)}" y1="${ty0.toFixed(1)}" x2="${tx1.toFixed(1)}" y2="${ty1.toFixed(1)}" stroke="#F7F8FA" stroke-width="2" stroke-linecap="round"/>
      </svg>
      <div class="viz-center" style="top:50%;transform:translateY(-54%)">${heroNum(t)}<small>target ${t.target}${unitSuffix(t.unit)}</small></div></div>
      ${bd.length ? html`<ul class="legend" style="grid-template-columns:repeat(${bd.length},auto);gap:2px 10px;justify-content:center">${bd.map((b) => html`<li style="padding:0"><span>${b.label}</span><span class="v">${b.value}</span></li>`)}</ul>` : ""}
    </div>`;
  }

  function pieViz(t) {
    const items = (t.breakdown || []).filter((b) => b.value > 0);
    const total = items.reduce((a, b) => a + Number(b.value), 0) || 1;
    const cx = 75, cy = 75, R = 66, r0 = 42;
    let a = -90;
    const slices = items.map((b, i) => {
      const sweep = (Number(b.value) / total) * 360; const a0 = a, a1 = a + sweep; a = a1;
      const mid = (a0 + a1) / 2; const [dx, dy] = polar(0, 0, 9, mid);
      let d;
      if (sweep >= 359.99) d = `M${cx} ${cy - R} A${R} ${R} 0 1 1 ${cx - 0.01} ${cy - R} L${cx - 0.01} ${cy - r0} A${r0} ${r0} 0 1 0 ${cx} ${cy - r0} Z`;
      else {
        const [x0, y0] = polar(cx, cy, R, a0), [x1, y1] = polar(cx, cy, R, a1), [x2, y2] = polar(cx, cy, r0, a1), [x3, y3] = polar(cx, cy, r0, a0);
        const L = sweep > 180 ? 1 : 0;
        d = `M${x0.toFixed(2)} ${y0.toFixed(2)} A${R} ${R} 0 ${L} 1 ${x1.toFixed(2)} ${y1.toFixed(2)} L${x2.toFixed(2)} ${y2.toFixed(2)} A${r0} ${r0} 0 ${L} 0 ${x3.toFixed(2)} ${y3.toFixed(2)} Z`;
      }
      return html`<path class="slice" data-i="${i}" data-dx="${dx.toFixed(2)}" data-dy="${dy.toFixed(2)}" d="${d}" fill="${SLICE_COLORS[i % SLICE_COLORS.length]}" stroke="#0B1D33" stroke-width="1.5" tabindex="0" role="img" aria-label="${b.label}: ${b.value} (${Math.round((b.value / total) * 100)}%)"></path>`;
    });
    return html`<div class="pie-wrap"><div class="pie-box">
        <svg viewBox="-12 -12 174 174" width="150" height="150">${slices}</svg>
        <div class="viz-center">${heroNum({ value: total, unit: "" })}<small>total</small></div></div>
      <ul class="legend">${items.map((b, i) => html`<li data-i="${i}"><i style="background:${SLICE_COLORS[i % SLICE_COLORS.length]}"></i><span>${b.label}</span><span class="v">${b.value}</span></li>`)}</ul></div>`;
  }

  function barViz(t) {
    const items = t.breakdown || [];
    const max = t.unit === "%" ? 100 : Math.max(1, ...items.map((b) => Number(b.value)));
    return html`<div class="bar-hero">${heroNum(t)}<span class="muted mono" style="font-size:11px;margin-left:8px">target ${t.target}${unitSuffix(t.unit)}</span></div>
      <div class="hbars" role="list">${items.map((b) => html`<div class="hbar" role="listitem"><span title="${b.label}">${b.label}</span><span class="track"><i data-w="${((Number(b.value) / max) * 100).toFixed(1)}" style="width:0"></i></span><span class="v">${b.value}${t.unit === "%" ? "%" : ""}</span></div>`)}</div>`;
  }

  function trendHtml(t) {
    const v = Number(t.trend || 0);
    const dir = v > 0 ? "up" : v < 0 ? "down" : "flat";
    return html`<span class="trend" aria-label="Trend ${v > 0 ? "up" : v < 0 ? "down" : "flat"} ${Math.abs(v)}">${icon(dir)}${v > 0 ? "+" : ""}${fmt(v, decimalsOf(v))}${unitSuffix(t.unit) === "%" ? " pts" : unitSuffix(t.unit) ? " " + unitSuffix(t.unit) : ""}</span>`;
  }
  const statusWord = (s) => ({ good: "Good", watch: "Watch", bad: "Bad" })[s] || cap(s);

  function tileEl(t, prev) {
    const from = prev ? prev.value : 0;
    const viz = t.kind === "gauge" ? gaugeViz(t, from) : t.kind === "ring" ? ringViz(t, from) : t.kind === "pie" ? pieViz(t) : barViz(t);
    const el = frag(html`<div class="glass tile hoverline" role="button" tabindex="0" data-tile="${t.id}" data-report="${t.report_id || t.id}" aria-label="${t.label}, ${t.display}${unitSuffix(t.unit)}, status ${statusWord(t.status)}. Open report.">
      <div class="tile-head"><span class="kicker">${t.label}</span><span class="pill ${slug(t.status)}">${statusWord(t.status)}</span></div>
      <div class="viz ${t.kind}${t.kind === "bar" ? " bar-viz" : ""}">${viz}</div>
      <div class="tile-foot">${trendHtml(t)}<span class="kicker">Report →</span></div></div>`);
    const fromVal = prev ? Number(prev.value) : 0;
    $$("[data-count]", el).forEach((n) => {
      const to = Number(n.dataset.count); const isTotal = t.kind === "pie";
      const start = isTotal ? (prev ? (prev.breakdown || []).reduce((a, b) => a + Number(b.value), 0) : 0) : fromVal;
      n.textContent = fmt(start, decimalsOf(to));
      requestAnimationFrame(() => animateNumber(n, start, to, decimalsOf(to)));
    });
    requestAnimationFrame(() => requestAnimationFrame(() => {
      $$(".gauge-arc, .ring-arc", el).forEach((p) => p.setAttribute("stroke-dashoffset", p.dataset.to));
      $$(".hbar i[data-w]", el).forEach((b) => { b.style.width = b.dataset.w + "%"; });
    }));
    wirePie(el);
    return el;
  }

  function wirePie(el) {
    const slices = $$(".slice", el); if (!slices.length) return;
    const legend = $$(".legend li[data-i]", el);
    const set = (i) => {
      slices.forEach((s) => {
        const on = s.dataset.i === String(i);
        s.classList.toggle("exploded", on);
        s.style.transform = on ? `translate(${s.dataset.dx}px, ${s.dataset.dy}px)` : "";
      });
      legend.forEach((l) => l.classList.toggle("on", l.dataset.i === String(i)));
    };
    slices.forEach((s) => {
      s.addEventListener("mouseenter", () => set(s.dataset.i));
      s.addEventListener("focus", () => set(s.dataset.i));
      s.addEventListener("mouseleave", () => set(null));
      s.addEventListener("blur", () => set(null));
    });
    legend.forEach((l) => { l.addEventListener("mouseenter", () => set(l.dataset.i)); l.addEventListener("mouseleave", () => set(null)); });
  }

  /* =========================================================
     Module: Employee Analytics
     ========================================================= */
  async function renderAnalytics() {
    mount($("#main"), html`<div class="mod-head"><div><span class="kicker">Employee analytics</span><h2>Team health</h2>
      <p>Signals from Gmail, JobTread, Calendar, Drive, Quo and Plaud. Click a tile for its evidence report.</p>
      <div class="updated-line" id="an-updated" style="margin-top:8px"></div></div>
      <div class="mod-actions"><button type="button" class="btn btn-primary" id="an-run">${icon("play")} Run analysis now</button></div></div>
      <div class="tiles" id="tiles">${Array.from({ length: 6 }, () => html`<div class="glass tile"><div class="skeleton" style="width:50%"></div><div class="skeleton" style="height:140px;margin-top:14px"></div></div>`)}</div>
      <h3 class="section">People <span class="kicker">vs. own baseline</span></h3>
      <div class="table-wrap" id="people"></div>
      <h3 class="section" id="flags-head">Flags <span class="kicker">cross-checked · council-reviewed</span></h3>
      <div class="contacts-tools">
        <div class="tabs" role="tablist" aria-label="Flag status">${[["open", "Open"], ["all", "All"]].map(([k, l]) => html`<button type="button" role="tab" data-fstatus="${k}" aria-selected="${state.analytics.flagStatus === k}">${l}</button>`)}</div>
        <label class="field" style="flex-direction:row;align-items:center;gap:8px"><span>Level</span><select class="input" id="f-level" style="width:auto">
          ${[["", "Any level"], ["1", "L1 · note"], ["2", "L2 · email"], ["3", "L3 · text"]].map(([v, l]) => html`<option value="${v}" ${state.analytics.flagLevel === v ? raw("selected") : ""}>${l}</option>`)}</select></label>
      </div>
      <div class="flags" id="flags"></div>`);
    try {
      const s = await loadSummary(true);
      if (state.module !== "analytics") return;
      drawTiles(s); drawPeople(s); drawUpdated();
    } catch (e) { mount($("#tiles"), html`<div class="glass empty">Analytics summary unavailable.</div>`); }
    try { await loadFlags(); if (state.module === "analytics") drawFlags(); renderRail(); updateBadge(); }
    catch (e) { mount($("#flags"), html`<div class="glass empty">Flags unavailable.</div>`); }
  }

  function drawUpdated() {
    const s = state.summary; const el = $("#an-updated"); if (!el || !s) return;
    const m = state.stream.mode;
    mount(el, html`<span class="dot ${m === "live" ? "live" : m === "polling" ? "warn" : ""}"></span><span>${m === "live" ? "Live" : m === "polling" ? "Polling every 30 s" : "Connecting"}</span><span>Updated ${when(s.updated, true)} · ${ago(s.updated)}</span>`);
  }

  function drawTiles(s) {
    const wrap = $("#tiles"); if (!wrap) return;
    wrap.textContent = "";
    (s.tiles || []).forEach((t) => wrap.appendChild(tileEl(t, null)));
    if (!(s.tiles || []).length) mount(wrap, html`<div class="glass empty">No tiles yet.</div>`);
  }

  function drawPeople(s) {
    const rows = s.people || [];
    const lvl = (n) => (n ? html`<span class="pill lvl lvl-${n}">L${n} ${["", "note", "email", "text"][n] || ""}</span>` : html`<span class="muted">—</span>`);
    mount($("#people"), html`<table class="grid"><thead><tr><th>Person</th><th class="num">Response h</th><th class="num">Unanswered</th><th class="num">vs. baseline</th><th class="num">Open flags</th><th>Top level</th></tr></thead>
      <tbody>${rows.map((p) => {
        const d = Number(p.baseline_dev || 0); const w = Math.min(100, Math.abs(d) * 100);
        return html`<tr><td><div class="person"><b>${p.name}</b><span>${p.role}</span></div></td>
          <td class="num">${fmt(p.response_hrs, 1)}</td><td class="num">${p.unanswered}</td>
          <td><div class="dev-cell"><span class="mono" style="font-size:12px;color:${d > 0.25 ? "var(--red-ink)" : "var(--ink-2)"}">${d > 0 ? "+" : ""}${Math.round(d * 100)}%</span>
            <span class="dev" role="img" aria-label="${Math.round(d * 100)}% vs baseline"><span class="neg">${d < 0 ? html`<i style="width:${w}%"></i>` : ""}</span><span class="pos">${d > 0 ? html`<i style="width:${w}%"></i>` : ""}</span></span></div></td>
          <td class="num">${p.open_flags}</td><td>${lvl(p.top_level)}</td></tr>`;
      })}</tbody></table>`);
  }

  const LEVEL_WORD = { 1: "L1 · note", 2: "L2 · email", 3: "L3 · text" };
  function flagCard(f) {
    const person = (state.summary && (state.summary.people || []).find((p) => p.email === f.person)) || null;
    const cc = f.crosscheck || {};
    const internal = /@ntxpllc\.com$/i.test(f.person || "");
    return html`<article class="glass flag sev-${slug(f.severity)}" data-flag="${f.id}">
      <div class="flag-top"><span class="pill lvl lvl-${f.level}">${LEVEL_WORD[f.level] || "L" + f.level}</span>
        <span class="pill ${slug(f.urgency)}">${f.urgency}</span><span class="pill ${slug(f.severity)}">${f.severity === "redflag" ? "red flag" : f.severity}</span>
        <span class="pill plain">${f.channel}</span><span class="pill plain">${f.status}</span><span class="id">${f.id} · ${when(f.created, true)}</span></div>
      <h4>${f.summary}</h4>
      <div class="who">${person ? person.name + " · " + person.role : f.person} · KPI <span class="mono">${f.kpi}</span></div>
      <div class="metrics">
        <div class="metric"><span class="kicker">Confidence</span><span class="val">${pct(f.confidence)}</span><div class="meter"><i style="width:${Math.round((f.confidence || 0) * 100)}%"></i></div></div>
        ${internal ? html`<div class="metric"><span class="kicker">Volatility (internal only)</span><span class="val">${pct(f.volatility)}</span><div class="meter"><i style="width:${Math.round((f.volatility || 0) * 100)}%;background:var(--ink-3)"></i></div></div>` : ""}
        <div class="metric"><span class="kicker">Council agreement</span><span class="val">${f.council ? pct(f.council.agreement) : "—"}</span><div class="meter"><i style="width:${f.council ? Math.round(f.council.agreement * 100) : 0}%"></i></div></div>
      </div>
      <div class="flag-cols">
        <div><h5>Evidence</h5><ul>${(f.evidence || []).map((e) => html`<li class="ev"><code>${e.source}</code> ${e.ref} — ${e.note}</li>`)}</ul></div>
        <div><h5>Cross-check · <span class="pill ${cc.status === "confirmed" ? "bad" : cc.status === "explained" ? "good" : "watch"}" style="vertical-align:middle">${cc.status || "pending"}</span></h5>
          <div class="ev" style="margin-bottom:4px">Checked: ${(cc.sources_checked || []).join(", ") || "—"}</div>
          ${(cc.explanations || []).length ? html`<ul>${cc.explanations.map((x) => html`<li>${x}</li>`)}</ul>` : html`<div class="ev muted">No explanation found yet.</div>`}</div>
        ${f.council ? html`<div><h5>Council conclusion</h5><div class="council"><span class="mono muted" style="font-size:11px">${f.council.council_id} · ${pct(f.council.agreement)} agree</span><br>${f.council.conclusion}</div></div>` : ""}
        <div><h5>Escalation history</h5><ul class="timeline">${(f.escalations || []).map((e) => html`<li><span class="t">${when(e.at, true)}</span><span>L${e.level} · ${({ daily_note: "daily note", email: "email", sms: "text" })[e.channel] || e.channel} → ${(e.to || []).join(", ")}</span></li>`)}</ul></div>
      </div>
      <div class="flag-act">
        <label class="sr-only" for="note-${slug(f.id)}">Note for ${f.id}</label>
        <input class="input" id="note-${slug(f.id)}" placeholder="Optional note">
        ${["ack", "dismiss", "escalate", "resolve"].map((a) => html`<button type="button" class="btn btn-sm ${a === "escalate" ? "btn-danger" : ""}" data-flag-act="${a}" ${(f.status === "resolved" || f.status === "dismissed") && a !== "escalate" ? raw("disabled") : ""} ${a === "escalate" && f.level >= 3 ? raw("disabled") : ""}>${({ ack: "Ack", dismiss: "Dismiss", escalate: "Escalate", resolve: "Resolve" })[a]}</button>`)}
      </div></article>`;
  }
  function drawFlags() {
    const list = state.flags || [];
    mount($("#flags"), list.length ? html`${list.map(flagCard)}` : html`<div class="glass empty">No flags in this view.</div>`);
  }
  async function flagAction(btn) {
    const card = btn.closest("[data-flag]"); const id = card.dataset.flag;
    const note = $(".flag-act .input", card).value.trim();
    $$("button", card).forEach((b) => { b.disabled = true; });
    try {
      const f = await POST("/api/flags/" + encodeURIComponent(id) + "/action", { action: btn.dataset.flagAct, note });
      const i = state.flags.findIndex((x) => x.id === id);
      if (i >= 0) state.flags[i] = f;
      const el = frag(flagCard(f)); card.replaceWith(el);
      toast(`${id}: ${({ ack: "acknowledged", dismiss: "dismissed", escalate: "escalated to L" + f.level, resolve: "resolved" })[btn.dataset.flagAct]}`, "ok");
      renderRail(); updateBadge();
    } catch (e) { $$("button", card).forEach((b) => { b.disabled = false; }); }
  }
  async function runAnalysis() {
    const b = $("#an-run"); if (b) { b.disabled = true; b.lastChild.textContent = " Running…"; }
    try {
      const r = await POST("/api/analytics/run");
      toast(`Analysis complete — ${r.flags_created} new flag${r.flags_created === 1 ? "" : "s"}, ${r.flags_escalated} escalated${r.jev ? " · " + money(r.jev.cost) : ""}`, "ok");
      if (state.module === "analytics") renderAnalytics();
    } catch (e) { /* toast shown */ } finally { if (b && document.contains(b)) { b.disabled = false; b.lastChild.textContent = " Run analysis now"; } }
  }

  /* ---------- Live stream ---------- */
  function onTile(t) {
    if (!t || !t.id || !state.summary) return;
    const tiles = state.summary.tiles || []; const i = tiles.findIndex((x) => x.id === t.id);
    const prev = i >= 0 ? tiles[i] : null;
    if (i >= 0) tiles[i] = t; else tiles.push(t);
    state.summary.updated = new Date().toISOString();
    const old = $(`#tiles [data-tile="${CSS.escape(t.id)}"]`);
    if (old) { const el = tileEl(t, prev); const hadFocus = old.contains(document.activeElement); old.replaceWith(el); if (hadFocus) el.focus(); }
    else if ($("#tiles") && state.module === "analytics") $("#tiles").appendChild(tileEl(t, null));
    drawUpdated();
  }
  function startStream() {
    const S = state.stream;
    if (state.demo) {
      S.mode = "live"; setStatus();
      clearInterval(S.demoTimer);
      S.demoTimer = setInterval(() => { if (state.summary) onTile(window.NTXPDemo.tick()); }, 9000);
      return;
    }
    if (!("EventSource" in window)) return startPolling();
    try {
      const es = new EventSource("/api/analytics/stream", { withCredentials: true });
      S.es = es;
      es.addEventListener("open", () => { S.mode = "live"; setStatus(); drawUpdated(); });
      es.addEventListener("tile", (ev) => { try { onTile(JSON.parse(ev.data)); } catch (e) { /* malformed event */ } });
      es.addEventListener("error", () => { if (es.readyState === 2 || S.mode !== "live") { es.close(); S.es = null; startPolling(); } });
    } catch (e) { startPolling(); }
  }
  function startPolling() {
    const S = state.stream; if (S.poll) return;
    S.mode = "polling"; setStatus(); drawUpdated();
    S.poll = setInterval(async () => {
      try {
        const prevTiles = state.summary ? state.summary.tiles : [];
        const s = await GET("/api/analytics/summary", { quiet: true });
        const before = new Map((prevTiles || []).map((t) => [t.id, JSON.stringify(t)]));
        state.summary = Object.assign({}, s, { tiles: prevTiles && prevTiles.length ? prevTiles : s.tiles });
        (s.tiles || []).forEach((t) => { if (before.get(t.id) !== JSON.stringify(t)) onTile(t); });
        state.summary.updated = s.updated;
        if (state.module === "analytics") { drawPeople(state.summary); drawUpdated(); }
      } catch (e) { /* next poll */ }
    }, 30000);
  }

  /* ---------- Report drawer ---------- */
  let drawerReturn = null;
  async function openReport(id) {
    const d = $("#drawer");
    drawerReturn = document.activeElement;
    d.hidden = false;
    mount(d, html`<div class="drawer-head"><div><span class="kicker">Report</span><h2 id="drawer-title">Loading…</h2></div>
      <div class="actions"><button type="button" class="icon-btn" data-close-drawer aria-label="Close report">${icon("x")}</button></div></div>
      <div class="bounding-line"></div><div class="drawer-body"><div class="skeleton" style="width:60%"></div><div class="skeleton" style="width:90%;margin-top:12px"></div></div>`);
    $("[data-close-drawer]", d).focus();
    try {
      const r = await GET("/api/analytics/report/" + encodeURIComponent(id));
      if (d.hidden) return;
      mount(d, html`<div class="drawer-head"><div style="flex:1;min-width:0"><span class="kicker">Report · ${r.id}</span><h2 id="drawer-title">${r.title}</h2>
          <div class="report-meta"><span>Period <b class="mono">${(r.period || {}).from} → ${(r.period || {}).to}</b></span><span>Generated ${when(r.generated, true)}</span><span>Sources: ${(r.sources || []).join(", ")}</span></div></div>
        <div class="actions"><button type="button" class="btn btn-sm" data-print-report>${icon("print")} Print</button><button type="button" class="icon-btn" data-close-drawer aria-label="Close report">${icon("x")}</button></div></div>
        <div class="bounding-line"></div>
        <div class="drawer-body">
          <p class="print-only" style="text-align:center;margin:0 0 12pt;font-size:9pt">NTXP LLC · 101 South Locust St Ste 605, Denton, TX 76201 · 469-248-7431 · Internal — owner use only</p>
          ${(r.sections || []).map((s) => html`<section class="report-sec"><h3>${s.heading}</h3>
            <ul>${(s.findings || []).map((x) => html`<li>${x}</li>`)}</ul>
            ${(s.evidence || []).length ? html`<div class="table-wrap"><table class="grid evidence"><thead><tr><th>Source</th><th>Reference</th><th>Note</th></tr></thead>
              <tbody>${s.evidence.map((e) => html`<tr><td><span class="pill plain">${e.source}</span></td><td>${e.ref}</td><td class="ink2">${e.note}</td></tr>`)}</tbody></table></div>` : ""}
          </section>`)}
          <section class="report-sec"><h3>Conclusions</h3>${(r.conclusions || []).map((c) => html`<div class="conclusion"><div>${c.text}${c.council_id ? html`<div class="muted mono" style="font-size:11px;margin-top:4px">Council ${c.council_id}</div>` : ""}</div>
            <div class="conf"><b>${pct(c.confidence)}</b><span class="kicker">confidence</span><div class="meter"><i style="width:${Math.round((c.confidence || 0) * 100)}%"></i></div></div></div>`)}</section>
          ${r.jev && r.jev.tier != null ? html`<p style="margin-top:18px">${jevBadge(r.jev)}</p>` : ""}
        </div>`);
      $("[data-close-drawer]", d).focus();
    } catch (e) {
      mount($(".drawer-body", d), html`<div class="empty">Report unavailable.</div>`);
    }
  }
  function closeDrawer(silent) {
    const d = $("#drawer"); if (d.hidden) return;
    d.hidden = true; d.innerHTML = "";
    if (!silent && drawerReturn && document.contains(drawerReturn)) drawerReturn.focus();
  }

  /* =========================================================
     Module: Runbook
     ========================================================= */
  function renderRunbook() {
    const R = state.runbook;
    mount($("#main"), html`<div class="mod-head"><div><span class="kicker">For humans when a workflow is stuck</span><h2>Runbook</h2>
      <p>Symptom, likely cause, the steps that fix it, and who to call when they don't.</p></div>
      <div class="mod-actions"><button type="button" class="btn btn-primary" id="rb-add">${icon("plus")} Add entry</button></div></div>
      <div class="contacts-tools"><label class="search-inline" style="max-width:480px">${icon("search")}<span class="sr-only">Search runbook</span><input class="input" type="search" id="rb-q" placeholder="Search symptoms, workflows, steps…" value="${R.q}"></label></div>
      <div id="rb-form-slot"></div>
      <div class="rb-list" id="rb-list"><div class="glass pad"><div class="skeleton"></div></div></div>`);
    if (R.adding) drawRunbookForm();
    loadRunbook();
  }
  let rbReq = 0;
  async function loadRunbook() {
    const my = ++rbReq; const R = state.runbook;
    try {
      const r = await GET("/api/runbook" + (R.q ? "?q=" + encodeURIComponent(R.q) : ""));
      if (my !== rbReq || state.module !== "runbook") return;
      R.entries = r.entries || []; drawRunbook();
    } catch (e) { mount($("#rb-list"), html`<div class="glass empty">Runbook unavailable.</div>`); }
  }
  function drawRunbook() {
    const list = state.runbook.entries || [];
    mount($("#rb-list"), list.length ? html`${list.map((e) => html`<details class="glass rb hoverline">
        <summary><div><span class="kicker">${e.workflow} · ${e.id}</span><h4>${e.symptom}</h4></div>
          <span class="side"><span class="pill ${e.tier >= 3 ? "bad" : e.tier === 2 ? "watch" : "plain"}">Tier ${e.tier}</span>${icon("chev", "chev")}</span></summary>
        <div class="rb-body">
          <dl class="kv"><dt>Likely cause</dt><dd>${e.likely_cause}</dd><dt>Escalate to</dt><dd>${e.escalate_to}</dd><dt>Updated</dt><dd>${when(e.updated)}</dd></dl>
          <div><span class="kicker" style="display:block;margin-bottom:8px">Steps</span><ol>${(e.steps || []).map((s) => html`<li><span>${s}</span></li>`)}</ol></div>
        </div></details>`)}` : html`<div class="glass empty">No runbook entries match.</div>`);
  }
  function drawRunbookForm() {
    mount($("#rb-form-slot"), html`<form class="glass pad" id="rb-form" style="margin-bottom:14px" aria-label="New runbook entry">
      <span class="kicker">New entry</span>
      <div class="form-grid" style="margin-top:12px">
        <label class="field"><span>Workflow</span><input class="input" name="workflow" required placeholder="e.g. Pay application"></label>
        <label class="field"><span>Escalate to</span><input class="input" name="escalate_to" required placeholder="Person or role"></label>
        <label class="field full"><span>Symptom</span><input class="input" name="symptom" required placeholder="What the person sees"></label>
        <label class="field full"><span>Likely cause</span><input class="input" name="likely_cause" required></label>
        <label class="field full"><span>Steps (one per line)</span><textarea class="input" name="steps" rows="4" required></textarea></label>
        <label class="field"><span>Tier</span><select class="input" name="tier"><option value="0">Tier 0 · automatic</option><option value="1" selected>Tier 1 · routine</option><option value="2">Tier 2 · review</option><option value="3">Tier 3 · owner approval</option></select></label>
      </div>
      <div class="dialog-foot"><button type="button" class="btn btn-ghost" id="rb-cancel">Cancel</button><button type="submit" class="btn btn-primary">Save entry</button></div></form>`);
    $("#rb-form [name=workflow]").focus();
  }
  async function saveRunbook(form) {
    const body = {
      workflow: form.workflow.value.trim(), symptom: form.symptom.value.trim(), likely_cause: form.likely_cause.value.trim(),
      steps: form.steps.value.split(/\n+/).map((s) => s.replace(/^\s*\d+[.)]\s*/, "").trim()).filter(Boolean),
      escalate_to: form.escalate_to.value.trim(), tier: +form.tier.value,
    };
    try {
      await POST("/api/runbook", body);
      toast("Runbook entry added", "ok");
      state.runbook.adding = false; $("#rb-form-slot").textContent = "";
      loadRunbook();
    } catch (e) { /* toast shown */ }
  }

  /* =========================================================
     Module: Workspace
     ========================================================= */
  function renderWorkspace() {
    const W = state.workspace;
    mount($("#main"), html`<div class="mod-head"><div><span class="kicker">Google Workspace control</span><h2>Workspace</h2>
      <p>Account actions are Tier 3: each is staged, summarized and applied only after an owner approves it here.</p></div></div>
      <h3 class="section" style="margin-top:0">Users</h3>
      <div class="table-wrap" id="users"><div class="pad"><div class="skeleton"></div></div></div>
      <h3 class="section">Drive search <span class="kicker">org-wide</span></h3>
      <form class="contacts-tools" id="drive-form" role="search">
        <label class="search-inline">${icon("search")}<span class="sr-only">Search Drive</span><input class="input" type="search" name="q" placeholder="File name or keyword" value="${W.q}"></label>
        <label class="sr-only" for="drive-user">Owner</label><select class="input" id="drive-user" name="user" style="width:auto;max-width:240px"><option value="">All users</option></select>
        <label class="toggle"><input type="checkbox" name="ext" ${W.externalOnly ? raw("checked") : ""}> Only externally shared</label>
        <button type="submit" class="btn">Search</button>
      </form>
      <div class="table-wrap" id="drive"></div>`);
    loadUsers(); searchDrive();
  }
  async function loadUsers() {
    try {
      const r = await GET("/api/users");
      state.workspace.users = r.users || [];
      if (state.module !== "workspace") return;
      drawUsers();
      const sel = $("#drive-user");
      if (sel) mount(sel, html`<option value="">All users</option>${state.workspace.users.map((u) => html`<option value="${u.email}" ${state.workspace.user === u.email ? raw("selected") : ""}>${u.name}</option>`)}`);
    } catch (e) { mount($("#users"), html`<div class="empty">Users unavailable.</div>`); }
  }
  function drawUsers() {
    const users = state.workspace.users || [];
    mount($("#users"), html`<table class="grid"><thead><tr><th>User</th><th>Org unit</th><th>Last sign-in</th><th>Status</th><th style="text-align:right">Actions</th></tr></thead>
      <tbody>${users.map((u) => html`<tr><td><div class="person"><b>${u.name}${u.is_admin ? html` <span class="pill plain" style="margin-left:4px">Admin</span>` : ""}</b><span>${u.email}</span></div></td>
        <td class="mono" style="font-size:12px">${u.org_unit}</td><td class="mono" style="font-size:12px">${when(u.last_login, true)}</td>
        <td>${u.suspended ? html`<span class="pill bad">Suspended</span>` : html`<span class="pill good">Active</span>`}</td>
        <td><div class="user-acts">
          ${u.suspended ? html`<button type="button" class="btn btn-sm" data-uact="unsuspend" data-email="${u.email}">Unsuspend</button>` : html`<button type="button" class="btn btn-sm btn-danger" data-uact="suspend" data-email="${u.email}">Suspend</button>`}
          <button type="button" class="btn btn-sm" data-uact="reset_signin" data-email="${u.email}">Reset sign-in</button>
          <button type="button" class="btn btn-sm" data-uact="transfer_drive" data-email="${u.email}">Transfer Drive</button>
        </div></td></tr>`)}</tbody></table>`);
  }
  async function userAction(action, email) {
    const users = state.workspace.users || [];
    const u = users.find((x) => x.email === email) || { name: email };
    let to;
    if (action === "transfer_drive") {
      const d = showDialog({ kicker: "Transfer Drive", title: `Move ${u.name}'s Drive files to…`,
        body: html`<label class="field"><span>New owner</span><select class="input" id="xfer-to" autofocus>${users.filter((x) => x.email !== email && !x.suspended).map((x) => html`<option value="${x.email}">${x.name} — ${x.email}</option>`)}</select></label>`,
        actions: [{ label: "Cancel", value: false, cls: "btn-ghost" }, { label: "Stage transfer", value: true, cls: "btn-primary" }] });
      const res = await d.promise; if (!res || !res.value) return;
      to = $("#xfer-to", res.el).value;
    }
    try {
      const r = await POST("/api/users/" + encodeURIComponent(email) + "/action", to ? { action, to } : { action });
      if (!r.needs_approval) { toast("Done", "ok"); loadUsers(); return; }
      const d = showDialog({ kicker: "Tier 3 · owner approval", title: "Approve this change?",
        body: html`<div class="tier">${r.summary}</div><p class="mono muted" style="font-size:12px">Change ${r.change_id} · staged by ${state.me ? state.me.name : "owner"} · nothing has happened yet</p>`,
        actions: [{ label: "Cancel", value: false, cls: "btn-ghost" }, { label: "Approve", value: true, cls: "btn-danger" }] });
      const res = await d.promise;
      if (!res || !res.value) { toast("Change " + r.change_id + " left unapproved — nothing was applied"); return; }
      await POST("/api/approve/" + encodeURIComponent(r.change_id));
      toast("Approved and applied: " + r.change_id, "ok");
      loadUsers();
    } catch (e) { /* toast shown */ }
  }
  let driveReq = 0;
  async function searchDrive() {
    const W = state.workspace; const my = ++driveReq;
    const qs = new URLSearchParams(); if (W.q) qs.set("q", W.q); if (W.user) qs.set("user", W.user);
    mount($("#drive"), html`<div class="pad"><div class="skeleton"></div></div>`);
    try {
      const r = await GET("/api/drive/search" + (qs.toString() ? "?" + qs : ""));
      if (my !== driveReq || state.module !== "workspace") return;
      let files = r.files || [];
      if (W.externalOnly) files = files.filter((f) => f.shared_externally);
      const ext = files.filter((f) => f.shared_externally).length;
      const kind = (m) => (/folder/.test(m) ? "Folder" : /spreadsheet|sheet|excel/.test(m) ? "Sheet" : /document|word/.test(m) ? "Doc" : /pdf/.test(m) ? "PDF" : "File");
      mount($("#drive"), files.length ? html`<table class="grid"><thead><tr><th>Name</th><th>Owner</th><th>Type</th><th>Modified</th><th>Sharing</th></tr></thead>
        <tbody>${files.map((f) => html`<tr><td><a href="${safeUrl(f.link)}" target="_blank" rel="noopener noreferrer" style="display:inline-flex;gap:8px;align-items:center;color:var(--ink);text-decoration:none">${icon(/folder/.test(f.mime) ? "folder" : "file")}<span>${f.name}</span></a></td>
          <td class="ink2">${f.owner}</td><td>${kind(f.mime)}</td><td class="mono" style="font-size:12px">${when(f.modified)}</td>
          <td>${f.shared_externally ? html`<span class="pill bad">External</span>` : html`<span class="pill good">Internal</span>`}</td></tr>`)}</tbody></table>
        <div class="grid-foot" style="padding:8px 12px">${files.length} file${files.length === 1 ? "" : "s"} · ${ext} shared outside ntxpllc.com</div>` : html`<div class="empty">No files match.</div>`);
    } catch (e) { mount($("#drive"), html`<div class="empty">Drive search unavailable.</div>`); }
  }

  /* =========================================================
     Events
     ========================================================= */
  const debouncedContacts = debounce(loadContacts, 260);
  const debouncedRunbook = debounce(loadRunbook, 260);

  function focusables(root) {
    return $$('a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])', root)
      .filter((el) => el.offsetParent !== null || el === document.activeElement);
  }
  function topLayer() {
    if (!$("#dialog-layer").hidden) return $("#dialog-layer");
    if (!$("#drawer").hidden) return $("#drawer");
    return consoleEl();
  }

  function wire() {
    $("#launcher").addEventListener("click", openConsole);
    $("#close-btn").addEventListener("click", closeConsole);
    $("#scrim").addEventListener("click", closeConsole);
    $("#pin-btn").addEventListener("click", () => { state.pinned = !state.pinned; store.set("pinned", state.pinned); applyPinned(); });
    $("#status-btn").addEventListener("click", (e) => { e.stopPropagation(); toggleHealth(); });
    document.addEventListener("click", (e) => { if (!$("#health-pop").hidden && !e.target.closest(".health-wrap")) closeHealth(); });

    $("#rail").addEventListener("click", (e) => { const b = e.target.closest(".rail-btn"); if (b) go(b.dataset.mod); });
    $("#rail").addEventListener("keydown", (e) => {
      if (!["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"].includes(e.key)) return;
      const btns = $$(".rail-btn"); const i = btns.indexOf(document.activeElement); if (i < 0) return;
      e.preventDefault(); const n = btns[(i + (e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : -1) + btns.length) % btns.length]; n.focus();
    });

    $("#global-search").addEventListener("submit", (e) => {
      e.preventDefault(); const q = $("#global-q").value.trim(); if (!q) return;
      $("#global-q").value = ""; state.search.text = q; go("search", true); $("#search-text").value = q; runGuide(q);
    });

    const main = $("#main");
    main.addEventListener("click", (e) => {
      const t = e.target;
      let b;
      if ((b = t.closest("[data-report]")) && !t.closest(".slice")) { openReport(b.dataset.report); return; }
      if ((b = t.closest(".slice"))) { const tile = b.closest("[data-report]"); if (tile) openReport(tile.dataset.report); return; }
      if ((b = t.closest(".action-card, .today-item[data-mod]"))) {
        go(b.dataset.mod);
        if (b.dataset.action === "import_contacts") setTimeout(openImport, 50);
        if (b.dataset.action === "external_files") { state.workspace.externalOnly = true; go("workspace", true); }
        if (b.dataset.action === "red_flags" || b.dataset.scroll === "flags") setTimeout(() => { const h = $("#flags-head"); if (h) h.scrollIntoView({ block: "start" }); }, 400);
        if (b.dataset.action === "find_message") setTimeout(() => $("#search-text") && $("#search-text").focus(), 30);
        return;
      }
      if ((b = t.closest("[data-example]"))) { $("#search-text").value = b.dataset.example; runGuide(b.dataset.example); return; }
      if ((b = t.closest(".chip[data-q]"))) {
        const A = state.search.answers; const q = b.dataset.q; const opt = b.dataset.opt;
        if (b.dataset.multi === "1") {
          const cur = new Set(A[q] || []); cur.has(opt) ? cur.delete(opt) : cur.add(opt); A[q] = Array.from(cur);
          b.setAttribute("aria-pressed", String(cur.has(opt)));
        } else {
          A[q] = A[q] === opt ? undefined : opt; if (A[q] === undefined) delete A[q];
          $$(`.chip[data-q="${CSS.escape(q)}"]`).forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.opt === A[q])));
        }
        return;
      }
      if ((b = t.closest("[data-scope]"))) { state.search.scope = b.dataset.scope; $$("[data-scope]").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); return; }
      if (t.closest("#run-search")) { runSearch(); return; }
      if ((b = t.closest("[data-tab]"))) { state.contacts.tab = b.dataset.tab; state.contacts.selected.clear(); $$("[data-tab]").forEach((x) => x.setAttribute("aria-selected", String(x === b))); loadContacts(); return; }
      if ((b = t.closest("[data-bulk]"))) { bulkAction(b.dataset.bulk); return; }
      if (t.closest("#c-import")) { openImport(); return; }
      if (t.closest("#c-export")) { exportContacts(null); return; }
      if (t.closest("#c-sync")) { syncContacts(); return; }
      if ((b = t.closest(".row-cb"))) {
        const C = state.contacts; const tr = b.closest("tr"); const idx = +tr.dataset.idx;
        if (e.shiftKey && C.last != null) {
          const [a, z] = [Math.min(C.last, idx), Math.max(C.last, idx)];
          for (let k = a; k <= z; k++) { if (b.checked) C.selected.add(C.rows[k].id); else C.selected.delete(C.rows[k].id); }
        } else if (b.checked) C.selected.add(tr.dataset.id); else C.selected.delete(tr.dataset.id);
        C.last = idx; syncSelectionUI(); return;
      }
      if (t.id === "c-all") {
        const C = state.contacts;
        if (t.checked) C.rows.forEach((r) => C.selected.add(r.id)); else C.selected.clear();
        syncSelectionUI(); return;
      }
      if (t.closest("#an-run")) { runAnalysis(); return; }
      if ((b = t.closest("[data-fstatus]"))) {
        state.analytics.flagStatus = b.dataset.fstatus; $$("[data-fstatus]").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
        loadFlags().then(drawFlags).catch(() => {}); return;
      }
      if ((b = t.closest("[data-flag-act]"))) { flagAction(b); return; }
      if (t.closest("#rb-add")) { state.runbook.adding = !state.runbook.adding; if (state.runbook.adding) drawRunbookForm(); else $("#rb-form-slot").textContent = ""; return; }
      if (t.closest("#rb-cancel")) { state.runbook.adding = false; $("#rb-form-slot").textContent = ""; return; }
      if ((b = t.closest("[data-uact]"))) { userAction(b.dataset.uact, b.dataset.email); return; }
    });
    main.addEventListener("keydown", (e) => {
      if (e.target.classList && e.target.classList.contains("cell")) return onCellKey(e);
      const tile = e.target.closest && e.target.closest(".tile[role=button]");
      if (tile && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openReport(tile.dataset.report); }
      if (e.target.id === "search-text" && e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); $("#search-form").requestSubmit(); }
    });
    main.addEventListener("input", (e) => {
      const t = e.target;
      if (t.classList.contains("cell")) { t.classList.toggle("dirty", t.value !== t.dataset.orig); return; }
      if (t.id === "c-q") { state.contacts.q = t.value.trim(); debouncedContacts(); return; }
      if (t.id === "rb-q") { state.runbook.q = t.value.trim(); debouncedRunbook(); return; }
      if (t.id === "search-text") state.search.text = t.value;
    });
    main.addEventListener("focusin", (e) => { if (e.target.classList && e.target.classList.contains("cell")) markActiveRow(e.target); });
    main.addEventListener("focusout", (e) => { if (e.target.classList && e.target.classList.contains("cell")) commitCell(e.target); });
    main.addEventListener("change", (e) => {
      if (e.target.id === "f-level") { state.analytics.flagLevel = e.target.value; loadFlags().then(drawFlags).catch(() => {}); }
      if (e.target.closest("#drive-form") && (e.target.name === "user" || e.target.name === "ext")) $("#drive-form").requestSubmit();
    });
    main.addEventListener("submit", (e) => {
      e.preventDefault();
      if (e.target.id === "search-form") { const v = $("#search-text").value.trim(); if (v) runGuide(v); else $("#search-text").focus(); }
      if (e.target.id === "rb-form") saveRunbook(e.target);
      if (e.target.id === "drive-form") {
        const f = e.target; const W = state.workspace;
        W.q = f.q.value.trim(); W.user = f.user.value; W.externalOnly = f.ext.checked; searchDrive();
      }
    });

    $("#drawer").addEventListener("click", (e) => {
      if (e.target.closest("[data-close-drawer]")) closeDrawer();
      if (e.target.closest("[data-print-report]")) {
        document.body.classList.add("print-report");
        const done = () => { document.body.classList.remove("print-report"); window.removeEventListener("afterprint", done); };
        window.addEventListener("afterprint", done);
        window.print();
        setTimeout(done, 1500);
      }
    });

    consoleEl().addEventListener("keydown", (e) => {
      if (e.key !== "Tab" || e.defaultPrevented) return;
      const items = focusables(topLayer()); if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && (document.activeElement === first || !topLayer().contains(document.activeElement))) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (document.activeElement === last || !topLayer().contains(document.activeElement))) { e.preventDefault(); first.focus(); }
    });

    let gAt = 0;
    document.addEventListener("keydown", (e) => {
      const typing = e.target.closest && e.target.closest("input, textarea, select, [contenteditable]");
      if (e.key === "Escape") {
        if (!$("#dialog-layer").hidden) { e.preventDefault(); closeDialog(null); return; }
        if (!$("#health-pop").hidden) { closeHealth(); $("#status-btn").focus(); return; }
        if (!$("#drawer").hidden) { closeDrawer(); return; }
        if (state.open) { closeConsole(); return; }
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "g") { gAt = Date.now(); return; }
      if (e.key === "a" && Date.now() - gAt < 1200) { gAt = 0; e.preventDefault(); if (state.open) closeConsole(); else openConsole(); return; }
      if (e.key === "/" && state.open) { e.preventDefault(); $("#global-q").focus(); }
    });
  }

  /* =========================================================
     Start
     ========================================================= */
  wire();
  renderRail();
  applyPinned();
  if (/[#&?]open\b/.test(location.hash + location.search)) openConsole();
  else boot().then(updateBadge).catch(() => {});
})();
