/* NTXP Form Fill guided review GUI. Vanilla JS, no frameworks, no CDN.
 * Every value from the server is inserted with textContent / attributes only (never innerHTML).
 */
(function () {
  "use strict";

  var TOKEN = new URLSearchParams(location.search).get("token") || "";
  var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var TYPE_LABELS = {
    text_word: "Text (one line)", text_paragraph: "Paragraph", date: "Date", person: "Person",
    address: "Address", phone: "Phone", email: "Email", currency: "Currency", checkmark: "Check mark ✓",
    x_mark: "X mark", initials: "Initials", signature: "Signature"
  };
  var STATE_LABELS = { auto: "AUTO", review: "REVIEW", manual: "MANUAL", user: "ADDED" };
  var FONT_STACK = 'Arial, "Liberation Sans", Helvetica, sans-serif';
  var SCRIPT_FONT = '"Segoe Script", "Brush Script MT", "Lucida Handwriting", "URW Chancery L", "Z003", cursive';

  var S = {
    st: null, pages: [], fields: {}, order: [], cur: -1, reviewing: false, mode: null,
    selField: null, selHl: null, editor: null, saveQueue: [], saveShown: null,
    hlColor: "#FFEB3B", wasCompleted: false, exporting: false, sigCache: {},
    markups: [], selMk: null, mkColor: "#FF0000", rev: 0, es: null
  };
  var SVGNS = "http://www.w3.org/2000/svg";
  var LINE_BASED = { cloud: 1, arrow: 1, line: 1, polyline: 1, ink: 1 };
  var RECT_KINDS = { cloud: 1, rectangle: 1, ellipse: 1, text: 1, stamp: 1, area: 1 };

  // ------------------------------------------------------------------ helpers
  function $(id) { return document.getElementById(id); }
  function el(tag, attrs) {
    var e = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === "text") e.textContent = String(v);
        else if (k === "cls") e.className = v;
        else if (k.slice(0, 2) === "on" && typeof v === "function") e.addEventListener(k.slice(2), v);
        else e.setAttribute(k, v === true ? "" : String(v));
      });
    }
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c === null || c === undefined) continue;
      e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return e;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function withToken(url) { return url + (url.indexOf("?") >= 0 ? "&" : "?") + "token=" + encodeURIComponent(TOKEN); }

  function api(method, path, body) {
    var opts = { method: method, headers: { "X-NFF-Token": TOKEN }, cache: "no-store" };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return { ok: false, error: "bad response" }; }).then(function (j) {
        if (!r.ok) { var err = new Error(j.error || ("HTTP " + r.status)); err.data = j; err.status = r.status; throw err; }
        return j;
      });
    });
  }

  var toastTimer = null;
  function toast(msg, ms) {
    var t = $("toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove("show"); }, ms || 3500);
  }
  function announce(msg) { $("srLive").textContent = ""; setTimeout(function () { $("srLive").textContent = msg; }, 30); }

  // Formatting (mirrors scripts/nff_render.py)
  function formatCurrency(v) {
    var s = String(v == null ? "" : v).trim();
    if (!s) return "";
    var neg = s.indexOf("-") >= 0 || (s.indexOf("(") >= 0 && s.indexOf(")") >= 0);
    var c = s.replace(/[^0-9.]/g, "");
    var parts = c.split(".");
    if (parts.length > 2) { var tail = parts.pop(); c = parts.join("") + "." + tail; }
    if (!/\d/.test(c)) return "";
    var n = Math.round(parseFloat(c) * 100) / 100;
    if (isNaN(n)) return "";
    var txt = "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return neg && n !== 0 ? "(" + txt + ")" : txt;
  }
  function formatPhone(v) {
    var d = String(v || "").replace(/\D/g, "");
    if (d.length === 11 && d[0] === "1") d = d.slice(1);
    d = d.slice(0, 10);
    if (!d) return "";
    if (d.length < 4) return "(" + d;
    if (d.length < 7) return "(" + d.slice(0, 3) + ") " + d.slice(3);
    return "(" + d.slice(0, 3) + ") " + d.slice(3, 6) + "-" + d.slice(6);
  }
  function isoToUs(iso) { var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || ""); return m ? m[2] + "/" + m[3] + "/" + m[1] : ""; }
  function usToIso(us) { var m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(us || ""); return m ? m[3] + "-" + m[1] + "-" + m[2] : ""; }
  function validEmail(v) { return /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$/.test(v); }
  function isOn(v) { return /^(on|yes|true|1|x|checked|✓)$/i.test(String(v || "")); }
  function signerInitials() {
    var name = (S.st && S.st.default_signer) || "Alison Hopkins";
    return name.split(/[\s-]+/).filter(Boolean).map(function (p) { return p[0].toUpperCase(); }).join("");
  }

  // ------------------------------------------------------------------ geometry
  function pageInfo(n) { return S.pages[n - 1]; }
  function scaleOf(n) { var p = pageInfo(n); return p.el.clientWidth / p.w; }
  function pdfToBox(f) {
    var p = pageInfo(f.page), s = scaleOf(f.page), r = f.rect;
    return { left: (r[0] - p.ox) * s, top: (p.oy + p.h - r[3]) * s, width: (r[2] - r[0]) * s, height: (r[3] - r[1]) * s };
  }
  function screenToPdf(n, px, py) {
    var p = pageInfo(n), s = scaleOf(n);
    return { x: p.ox + px / s, y: p.oy + p.h - py / s };
  }
  function snap(x1, y1, x2, y2) {
    var dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy);
    if (!len) return [x1, y1, x2, y2];
    var raw = Math.atan2(dy, dx), step = Math.PI / 4, ang = Math.round(raw / step) * step;
    var proj = len * Math.abs(Math.cos(raw - ang));
    return [x1, y1, x1 + proj * Math.cos(ang), y1 + proj * Math.sin(ang)];
  }

  // ------------------------------------------------------------------ build
  function load() {
    return api("GET", "/api/session").then(function (st) {
      S.st = st;
      $("formName").textContent = st.form_name + (st.form_type ? " (" + st.form_type + ")" : "");
      document.title = "NTXP Form Fill | " + st.form_name;
      var sel = $("fieldType");
      clear(sel);
      st.field_types.forEach(function (t) { sel.appendChild(el("option", { value: t, text: TYPE_LABELS[t] || t })); });
      S.hlColor = (st.highlight_default && st.highlight_default.color) || "#FFEB3B";
      st.fields.forEach(function (f) { S.fields[f.id] = f; });
      buildPages(st.pages);
      st.highlights.forEach(drawHighlight);
      fillSelect($("markupKind"), st.markup_kinds || []);
      fillSelect($("stampStatus"), st.stamp_statuses || []);
      S.markups = st.markups || [];
      S.rev = st.rev || 0;
      renderMarkups();
      reorder();
      renderAllFields();
      startLive();
      updateProgress();
      if (st.review) showReview(st.review, true);
      if (st.flags && st.flags.last_export) showExport(st.flags.last_export);
      S.wasCompleted = st.progress.completed;
      if (S.wasCompleted) $("completedFlag").hidden = false;
      if (st.notes && st.notes.length) toast("Owner must confirm: " + st.notes.join(" "), 8000);
    }).catch(function (e) {
      $("formName").textContent = "Could not load session";
      toast("Error: " + e.message, 10000);
    });
  }

  function buildPages(pages) {
    var host = $("pages");
    clear(host);
    S.pages = [];
    pages.forEach(function (p) {
      var wrap = el("section", { cls: "page", "data-page": p.n, "aria-label": "Page " + p.n + " of " + pages.length });
      var img = el("img", { cls: "page-img", alt: "Page " + p.n + " of the form", src: withToken(p.img), draggable: "false" });
      var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "hl-layer");
      svg.setAttribute("aria-hidden", "true");
      var layer = el("div", { cls: "layer" });
      // Markups live in PDF user space (bottom-left origin), so a resize never redraws them.
      var ox = p.ox || 0, oy = p.oy || 0;
      var mk = document.createElementNS(SVGNS, "svg");
      mk.setAttribute("class", "mk-layer");
      mk.setAttribute("viewBox", ox + " " + oy + " " + p.w + " " + p.h);
      mk.setAttribute("preserveAspectRatio", "none");
      mk.setAttribute("aria-hidden", "true");
      var mkRoot = document.createElementNS(SVGNS, "g");
      mkRoot.setAttribute("transform", "translate(0 " + (2 * oy + p.h) + ") scale(1 -1)");
      mk.appendChild(mkRoot);
      wrap.appendChild(el("span", { cls: "page-label", text: "Page " + p.n }));
      wrap.appendChild(img); wrap.appendChild(svg); wrap.appendChild(mk); wrap.appendChild(layer);
      host.appendChild(wrap);
      var info = { n: p.n, w: p.w, h: p.h, ox: ox, oy: oy, el: wrap, svg: svg, layer: layer, img: img, mk: mkRoot };
      S.pages.push(info);
      sizePage(info);
      wrap.addEventListener("pointerdown", function (ev) { pagePointerDown(ev, info); });
      img.addEventListener("load", function () { layoutAll(); });
    });
  }

  function sizePage(p) {
    var avail = $("viewer").clientWidth - 40;
    var w = Math.max(320, Math.min(avail, 1100));
    p.el.style.width = w + "px";
    p.el.style.height = (w * p.h / p.w) + "px";
    p.svg.setAttribute("viewBox", "0 0 " + w + " " + (w * p.h / p.w));
  }

  function reorder() {
    S.order = Object.keys(S.fields).map(function (k) { return S.fields[k]; }).sort(function (a, b) {
      if (a.page !== b.page) return a.page - b.page;
      var dy = Math.round(b.rect[3] / 4) - Math.round(a.rect[3] / 4);
      return dy !== 0 ? dy : a.rect[0] - b.rect[0];
    });
  }

  function fieldStateText(f) {
    var st = { auto: "auto-filled", review: "needs review", manual: "manual entry", user: "added by you" }[f.state] || f.state;
    return st + (f.approved ? ", approved" : "");
  }

  function renderField(f) {
    var p = pageInfo(f.page);
    var node = document.getElementById("fld-" + f.id);
    if (!node) {
      node = el("button", { type: "button", cls: "field", id: "fld-" + f.id, "data-id": f.id });
      node.addEventListener("click", function (ev) { ev.stopPropagation(); openField(f.id, false); });
      node.addEventListener("pointerdown", function (ev) { ev.stopPropagation(); });
      p.layer.appendChild(node);
    }
    var multi = f.type === "text_paragraph" || f.type === "address";
    var mark = f.type === "checkmark" || f.type === "x_mark";
    node.className = "field st-" + f.state + (f.approved ? " approved" : "") + (multi ? " multi" : "") + (mark ? " mark" : "") +
      (S.cur >= 0 && S.order[S.cur] && S.order[S.cur].id === f.id ? " current" : "");
    var b = pdfToBox(f), s = scaleOf(f.page);
    node.style.left = b.left + "px"; node.style.top = b.top + "px";
    node.style.width = b.width + "px"; node.style.height = b.height + "px";
    var size = (f.style && f.style.size) || 11;
    node.style.fontSize = Math.max(6, size * s) + "px";
    node.style.color = (f.style && f.style.color) || "#000000";
    clear(node);
    var shown = displayValue(f);
    if ((f.type === "signature" || f.type === "initials") && (S.sigCache[f.id] || f.has_image)) {
      node.appendChild(el("img", { cls: "sig", alt: "", src: S.sigCache[f.id] || withToken("/api/field-image/" + f.id + ".png?v=" + Date.now()) }));
    } else if (mark) {
      if (isOn(f.value)) { node.style.fontSize = Math.max(8, b.height * 0.8) + "px"; node.appendChild(el("span", { cls: "val", text: f.type === "x_mark" ? "X" : "✓" })); }
    } else {
      node.appendChild(el("span", { cls: "val", text: multi && b.height < size * s * 2.2 ? shown.replace(/\n+/g, ", ") : shown }));
    }
    node.setAttribute("aria-label", f.label + ", " + (TYPE_LABELS[f.type] || f.type) + ", " + fieldStateText(f) +
      ", value: " + (mark ? (isOn(f.value) ? "checked" : "not checked") : (shown || "empty")));
  }
  function displayValue(f) {
    var v = f.value == null ? "" : String(f.value);
    if (f.type === "currency") { var c = formatCurrency(v); return f.prefix === "$" ? c.replace("$", "") : c; }
    return v;
  }
  function renderAllFields() { S.order.forEach(renderField); }
  function syncBars() {
    var tb = document.querySelector(".toolbar");
    if (tb) document.documentElement.style.setProperty("--toolbar-h", tb.offsetHeight + "px");
  }
  function layoutAll() {
    syncBars();
    S.pages.forEach(sizePage);
    renderAllFields();
    S.pages.forEach(function (p) { while (p.svg.firstChild) p.svg.removeChild(p.svg.firstChild); });
    (S.st ? S.st.highlights : []).forEach(drawHighlight);
    if (S.editor) positionEditor();
  }

  // ------------------------------------------------------------------ progress / pages
  function updateProgress() {
    var total = S.order.length, done = S.order.filter(function (f) { return f.approved; }).length;
    var pct = total ? Math.round(100 * done / total) : 0;
    $("progressBar").style.width = pct + "%";
    $("progress").setAttribute("aria-valuenow", String(pct));
    $("progress").setAttribute("aria-valuetext", done + " of " + total + " fields approved");
    $("progressText").textContent = done + " of " + total + " fields approved (" + pct + "%)";
    updatePageIndicator();
    var completed = total > 0 && done === total;
    $("completedFlag").hidden = !completed;
    if (completed && !S.wasCompleted) { S.wasCompleted = true; onCompleted(); }
    if (!completed) S.wasCompleted = false;
  }
  function currentPage() {
    if (S.reviewing && S.cur >= 0 && S.order[S.cur]) return S.order[S.cur].page;
    var v = $("viewer"), mid = v.scrollTop + v.clientHeight / 2, best = 1;
    S.pages.forEach(function (p) { if (p.el.offsetTop <= mid) best = p.n; });
    return best;
  }
  function updatePageIndicator() {
    var n = currentPage();
    $("pageIndicator").textContent = "Page " + n + " of " + S.pages.length;
    $("lastPage").disabled = n <= 1;
    $("nextPage").textContent = n >= S.pages.length ? "NEXT PAGE (finish)" : "NEXT PAGE";
  }
  function scrollToPage(n) {
    var p = pageInfo(n);
    if (!p) return;
    $("viewer").scrollTo({ top: Math.max(0, p.el.offsetTop - 30), behavior: REDUCED ? "auto" : "smooth" });
  }
  function applyFields(list) { list.forEach(function (f) { S.fields[f.id] = f; }); }

  function approvePage(n) {
    return api("POST", "/api/page/approve", { page: n }).then(function () {
      S.order.forEach(function (f) { if (f.page === n) f.approved = true; });
      pageInfo(n).el.classList.remove("reopened");
      renderAllFields(); updateProgress();
    });
  }
  function reopenPage(n) {
    return api("POST", "/api/page/reopen", { page: n }).then(function () {
      S.order.forEach(function (f) { if (f.page === n) f.approved = false; });
      pageInfo(n).el.classList.add("reopened");
      renderAllFields(); updateProgress();
    });
  }
  function firstIndexOnPage(n) { for (var i = 0; i < S.order.length; i++) if (S.order[i].page === n) return i; return -1; }

  function nextPage() {
    var n = currentPage();
    commitOpenEditor(false).then(function () { return approvePage(n); }).then(function () {
      announce("Page " + n + " approved");
      if (n < S.pages.length) {
        closeEditor();
        var i = firstIndexOnPage(n + 1);
        if (S.reviewing && i >= 0) focusField(i); else { S.cur = -1; scrollToPage(n + 1); setTimeout(updatePageIndicator, 400); }
      } else {
        closeEditor(); S.reviewing = false; toast("Last page approved.");
      }
    }).catch(function (e) { toast("Error: " + e.message); });
  }
  function lastPage() {
    var n = currentPage();
    if (n <= 1) return;
    commitOpenEditor(false).then(function () { return approvePage(n); }).then(function () {
      return reopenPage(n - 1);
    }).then(function () {
      announce("Page " + (n - 1) + " re-opened for review");
      toast("Page " + (n - 1) + " re-opened for review");
      S.reviewing = true;
      var i = firstIndexOnPage(n - 1);
      if (i >= 0) focusField(i); else scrollToPage(n - 1);
    }).catch(function (e) { toast("Error: " + e.message); });
  }

  // ------------------------------------------------------------------ guided review
  function startReview() {
    setMode(null);
    if (!S.order.length) { toast("No fields detected. Use Add field to mark them."); return; }
    S.reviewing = true;
    var i = S.order.findIndex(function (f) { return !f.approved; });
    focusField(i < 0 ? 0 : i);
    announce("Guided review started. Enter or Space accepts and moves on, Shift+Enter goes back, Escape stops.");
  }
  function stopReview() {
    S.reviewing = false;
    closeEditor();
    S.cur = -1; renderAllFields();
    announce("Review stopped");
  }
  function focusField(i) {
    if (i < 0 || i >= S.order.length) return;
    var prev = S.cur;
    S.cur = i;
    if (prev >= 0 && S.order[prev]) renderField(S.order[prev]);
    var f = S.order[i];
    renderField(f);
    var node = document.getElementById("fld-" + f.id);
    node.scrollIntoView({ block: "center", inline: "nearest", behavior: REDUCED ? "auto" : "smooth" });
    openEditor(f);
    updatePageIndicator();
  }
  function openField(id, fromReview) {
    var i = S.order.findIndex(function (f) { return f.id === id; });
    if (i < 0) return;
    commitOpenEditor(false).then(function () { focusField(i); }, function () {});
  }
  function acceptAndNext() {
    if (!S.editor) return;
    var ed = S.editor;
    var v = ed.read();
    if (v.error) { ed.showError(v.error); return; }
    var body = { id: ed.field.id, value: v.value, approve: true };
    if (v.image !== undefined) { if (v.image) body.image = v.image; else body.clear_image = true; }
    sendField(body, ed.field).then(function () {
      var nextI = S.cur + 1;
      if (nextI < S.order.length) { focusField(nextI); return; }
      var firstOpen = S.order.findIndex(function (f) { return !f.approved; });
      if (firstOpen >= 0) { focusField(firstOpen); toast("Some fields are still open."); }
      else { closeEditor(); S.reviewing = false; S.cur = -1; renderAllFields(); }
    }).catch(function (e) { ed.showError(e.message); });
  }
  function goPrevious() {
    if (S.cur > 0) commitOpenEditor(false).then(function () { focusField(S.cur - 1); }, function () {});
  }

  function sendField(body, f) {
    return api("POST", "/api/field", body).then(function (res) {
      S.fields[res.field.id] = res.field;
      if (body.image) S.sigCache[res.field.id] = body.image;
      if (body.clear_image) delete S.sigCache[res.field.id];
      reorder(); renderField(res.field); updateProgress();
      if (res.ask_save) queueSave(res.field);
      if (S.st.signature_approval && !res.signature_approved) {
        S.st.signature_approval = null;
        toast("Change voided the signature approval; approve again before export.", 6000);
      }
      return res;
    });
  }
  // Save edits silently (without approving) when the user leaves an editor.
  function commitOpenEditor(approve) {
    if (!S.editor) return Promise.resolve();
    var ed = S.editor, v = ed.read();
    if (v.error || !ed.dirty()) return Promise.resolve();
    var body = { id: ed.field.id, value: v.value };
    if (approve) body.approve = true;
    if (v.image !== undefined) { if (v.image) body.image = v.image; else body.clear_image = true; }
    return sendField(body, ed.field).catch(function (e) { toast("Not saved: " + e.message); throw e; });
  }

  // ------------------------------------------------------------------ editors
  function closeEditor() {
    if (S.editor) { S.editor.node.remove(); S.editor = null; }
  }
  function positionEditor() {
    var ed = S.editor; if (!ed) return;
    var f = ed.field, b = pdfToBox(f), p = pageInfo(f.page);
    var pw = p.el.clientWidth, ph = p.el.clientHeight, eh = ed.node.offsetHeight || 220, ew = ed.node.offsetWidth || 360;
    var top = b.top + b.height + 8;
    if (top + eh > ph + 120 && b.top - eh - 8 > 0) top = b.top - eh - 8;
    var left = Math.min(Math.max(0, b.left), Math.max(0, pw - ew));
    ed.node.style.top = top + "px"; ed.node.style.left = left + "px";
  }

  function openEditor(f) {
    closeEditor();
    S.selField = f.id; S.selHl = null; markSelectedHl();
    $("colorPicker").value = (f.style && f.style.color) || "#000000";
    $("fontSize").value = (f.style && f.style.size) || 11;
    var p = pageInfo(f.page);
    var node = el("div", { cls: "editor", role: "dialog", "aria-label": "Edit " + f.label, tabindex: "-1" });
    var badge = el("span", { cls: "badge st-" + f.state, text: STATE_LABELS[f.state] || f.state });
    node.appendChild(el("h2", null, badge, f.label));
    var meta = (TYPE_LABELS[f.type] || f.type);
    if (f.source) meta += " · source: " + f.source;
    if (f.confidence) meta += " · " + Math.round(f.confidence * 100) + "%";
    if (f.reason) meta += " · " + f.reason;
    if (f.auto_value && f.value !== f.auto_value) meta += " · auto value: " + f.auto_value;
    node.appendChild(el("p", { cls: "meta", text: meta }));
    var err = el("p", { cls: "err", role: "alert" });
    var ed = { field: f, node: node, initial: f.value, showError: function (m) { err.textContent = m; } };
    var body = buildInput(f, ed);
    node.appendChild(body);
    node.appendChild(err);
    var row = el("div", { cls: "row" },
      el("button", { type: "button", cls: "btn primary", text: "Accept ✓", onclick: function () { acceptAndNext(); } }),
      el("button", { type: "button", cls: "btn", text: "Previous", onclick: function () { goPrevious(); } }),
      el("button", { type: "button", cls: "btn", text: "Stop", onclick: function () { stopReview(); } }));
    if (f.origin === "user") {
      row.appendChild(el("button", { type: "button", cls: "btn", text: "Remove field", onclick: function () { removeField(f); } }));
    }
    node.appendChild(row);
    node.appendChild(el("p", { cls: "hint", text: "Enter or Space = accept & next · Shift+Enter = previous · Esc = stop" +
      ((f.type === "text_paragraph" || f.type === "address") ? " · Alt+Enter = new line" : "") }));
    node.addEventListener("keydown", editorKeys, true);
    node.addEventListener("pointerdown", function (ev) { ev.stopPropagation(); });
    node.addEventListener("click", function (ev) { ev.stopPropagation(); });
    p.layer.appendChild(node);
    S.editor = ed;
    positionEditor();
    setTimeout(function () { (ed.focusTarget || node).focus({ preventScroll: true }); }, REDUCED ? 0 : 60);
  }

  function editorKeys(ev) {
    var t = ev.target, tag = t.tagName;
    var typing = (tag === "INPUT" && !/^(checkbox|radio|button|color)$/.test(t.type)) || tag === "TEXTAREA";
    if (ev.key === "Escape") { ev.preventDefault(); stopReview(); return; }
    if (ev.key === "Enter" && ev.shiftKey) { ev.preventDefault(); goPrevious(); return; }
    if (ev.key === "Enter" && ev.altKey && tag === "TEXTAREA") {
      ev.preventDefault();
      var s = t.selectionStart, e = t.selectionEnd;
      t.value = t.value.slice(0, s) + "\n" + t.value.slice(e);
      t.selectionStart = t.selectionEnd = s + 1;
      return;
    }
    if (ev.key === "Enter") {
      if (tag === "BUTTON" && !t.classList.contains("toggle") && t.textContent.indexOf("Accept") < 0) return; // let other buttons work
      ev.preventDefault(); acceptAndNext(); return;
    }
    if (ev.key === " " && !typing && tag !== "BUTTON" && tag !== "SELECT" && tag !== "CANVAS") {
      ev.preventDefault(); acceptAndNext();
    }
  }

  function buildInput(f, ed) {
    var wrap = el("div");
    var id = "inp-" + f.id;
    var t = f.type;
    var input;
    function textInput(type, extra) {
      input = el("input", Object.assign({ type: type, id: id, "aria-label": f.label, autocomplete: "off" }, extra || {}));
      input.value = f.value || "";
      wrap.appendChild(input);
      ed.focusTarget = input;
      ed.read = function () { return { value: input.value }; };
      ed.dirty = function () { return input.value !== (f.value || ""); };
    }
    if (t === "text_paragraph" || t === "address") {
      input = el("textarea", { id: id, "aria-label": f.label, rows: t === "address" ? 3 : 4 });
      input.value = f.value || "";
      wrap.appendChild(input);
      ed.focusTarget = input;
      ed.read = function () { return { value: input.value }; };
      ed.dirty = function () { return input.value !== (f.value || ""); };
    } else if (t === "date") {
      input = el("input", { type: "date", id: id, "aria-label": f.label + " (date)" });
      input.value = usToIso(f.value);
      wrap.appendChild(input);
      wrap.appendChild(el("p", { cls: "hint", text: "Exported as MM/DD/YYYY" }));
      ed.focusTarget = input;
      ed.read = function () { return { value: isoToUs(input.value) }; };
      ed.dirty = function () { return isoToUs(input.value) !== (f.value || ""); };
    } else if (t === "phone") {
      textInput("tel", { inputmode: "tel", placeholder: "(###) ###-####" });
      input.addEventListener("input", function () { input.value = formatPhone(input.value); });
      ed.read = function () {
        var d = input.value.replace(/\D/g, "");
        if (d && d.length !== 10 && !(d.length === 11 && d[0] === "1")) return { error: "Enter a 10-digit US phone number." };
        return { value: formatPhone(input.value) };
      };
    } else if (t === "email") {
      textInput("email", { inputmode: "email", spellcheck: "false" });
      var check = function () {
        var bad = input.value.trim() && !validEmail(input.value.trim());
        input.setAttribute("aria-invalid", bad ? "true" : "false");
        return bad;
      };
      input.addEventListener("input", function () { check(); ed.showError(""); });
      ed.read = function () { return check() ? { error: "Enter a valid email address (name@example.com)." } : { value: input.value.trim() }; };
    } else if (t === "currency") {
      textInput("text", { inputmode: "decimal", placeholder: "$0.00" });
      input.value = formatCurrency(f.value);
      input.addEventListener("blur", function () { input.value = formatCurrency(input.value); });
      wrap.appendChild(el("p", { cls: "gate-note", text: "Prices are never auto-filled. Enter the amount; it is shown as $1,234.00 (negatives as ($1,234.00))." }));
      ed.read = function () { return { value: formatCurrency(input.value) }; };
      ed.dirty = function () { return formatCurrency(input.value) !== formatCurrency(f.value); };
    } else if (t === "checkmark" || t === "x_mark") {
      var on = isOn(f.value);
      var btn = el("button", { type: "button", cls: "toggle", "aria-pressed": on ? "true" : "false",
        "aria-label": (t === "x_mark" ? "X mark" : "Check mark") + " for " + f.label, text: on ? (t === "x_mark" ? "X" : "✓") : "" });
      btn.addEventListener("click", function () {
        on = !on; btn.setAttribute("aria-pressed", on ? "true" : "false"); btn.textContent = on ? (t === "x_mark" ? "X" : "✓") : "";
      });
      wrap.appendChild(el("div", { cls: "row" }, btn, el("span", { text: "Click (or Tab + Space) to toggle; T toggles too." })));
      ed.node && ed.node.addEventListener("keydown", function (ev) { if (ev.key === "t" || ev.key === "T") { ev.preventDefault(); btn.click(); } });
      ed.focusTarget = null; // focus the editor so Space accepts
      ed.read = function () { return { value: on ? "on" : "" }; };
      ed.dirty = function () { return on !== isOn(f.value); };
    } else if (t === "initials") {
      textInput("text", { maxlength: "6", "aria-describedby": "gate-" + f.id });
      if (!input.value) input.value = signerInitials();
      input.addEventListener("input", function () { input.value = input.value.toUpperCase(); });
      wrap.appendChild(el("p", { cls: "gate-note", id: "gate-" + f.id, text: "Initials default to the signer (" + signerInitials() + ") and export only after Tier 3 signature approval." }));
      ed.read = function () { return { value: input.value.trim().toUpperCase() }; };
      ed.dirty = function () { return input.value.trim().toUpperCase() !== (f.value || ""); };
    } else if (t === "signature") {
      buildSignature(f, ed, wrap);
    } else {
      textInput("text", t === "person" ? { autocomplete: "off" } : null);
    }
    return wrap;
  }

  function buildSignature(f, ed, wrap) {
    var mode = f.has_image && !f.value ? "draw" : "type";
    var tabs = el("div", { cls: "tabs", role: "tablist", "aria-label": "Signature method" });
    var tType = el("button", { type: "button", cls: "btn small", role: "tab", text: "Type" });
    var tDraw = el("button", { type: "button", cls: "btn small", role: "tab", text: "Draw" });
    tabs.appendChild(tType); tabs.appendChild(tDraw);
    var typed = el("input", { type: "text", "aria-label": "Type the signer's full name", placeholder: (S.st.default_signer || "Alison Hopkins") });
    typed.value = f.value || "";
    var preview = el("canvas", { cls: "sig-preview", width: "600", height: "140", "aria-hidden": "true" });
    var typePane = el("div", null, typed, preview);
    var pad = el("canvas", { cls: "sig-pad", width: "640", height: "220", "aria-label": "Draw signature with mouse, pen or finger" });
    var clearBtn = el("button", { type: "button", cls: "btn small", text: "Clear drawing" });
    var drawPane = el("div", null, pad, el("div", { cls: "row" }, clearBtn));
    wrap.appendChild(tabs); wrap.appendChild(typePane); wrap.appendChild(drawPane);
    wrap.appendChild(el("p", { cls: "gate-note", text: "Never auto-filled. Default signer: " + (S.st.default_signer || "Alison Hopkins") +
      ". Exported only after Tier 3 approval bound to the final document hash (Trevor Hopkins needs a stated circumstance)." }));

    var inked = false, drawing = false, last = null, cleared = false;
    var pctx = pad.getContext("2d");
    pctx.lineWidth = 4; pctx.lineCap = "round"; pctx.lineJoin = "round"; pctx.strokeStyle = "#000";
    var storedOnly = !!f.has_image && !S.sigCache[f.id];  // drawn earlier, before this page session
    if (f.has_image && mode === "draw") {
      var im = new Image();
      im.onload = function () { pctx.drawImage(im, 0, 0, pad.width, pad.height); };
      im.src = S.sigCache[f.id] || withToken("/api/field-image/" + f.id + ".png?v=" + Date.now());
    }
    function pt(ev) { var r = pad.getBoundingClientRect(); return { x: (ev.clientX - r.left) * pad.width / r.width, y: (ev.clientY - r.top) * pad.height / r.height }; }
    pad.addEventListener("pointerdown", function (ev) { ev.preventDefault(); pad.setPointerCapture(ev.pointerId); drawing = true; last = pt(ev); });
    pad.addEventListener("pointermove", function (ev) {
      if (!drawing) return; var p = pt(ev);
      pctx.beginPath(); pctx.moveTo(last.x, last.y); pctx.lineTo(p.x, p.y); pctx.stroke(); last = p; inked = true; cleared = false;
    });
    pad.addEventListener("pointerup", function () { drawing = false; });
    clearBtn.addEventListener("click", function () { pctx.clearRect(0, 0, pad.width, pad.height); inked = false; cleared = true; });

    function renderTyped(canvas, text) {
      var c = canvas.getContext("2d");
      c.clearRect(0, 0, canvas.width, canvas.height);
      if (!text) return;
      var size = canvas.height * 0.62;
      c.font = "italic " + size + "px " + SCRIPT_FONT;
      while (c.measureText(text).width > canvas.width * 0.94 && size > 10) { size -= 2; c.font = "italic " + size + "px " + SCRIPT_FONT; }
      c.fillStyle = "#000"; c.textBaseline = "middle";
      c.fillText(text, canvas.width * 0.03, canvas.height * 0.55);
    }
    typed.addEventListener("input", function () { renderTyped(preview, typed.value.trim()); });
    renderTyped(preview, typed.value.trim());

    function setMode(m) {
      mode = m;
      tType.setAttribute("aria-selected", m === "type" ? "true" : "false");
      tDraw.setAttribute("aria-selected", m === "draw" ? "true" : "false");
      typePane.hidden = m !== "type"; drawPane.hidden = m !== "draw";
      ed.focusTarget = m === "type" ? typed : pad;
    }
    tType.addEventListener("click", function () { setMode("type"); typed.focus(); });
    tDraw.addEventListener("click", function () { setMode("draw"); pad.focus(); });
    pad.setAttribute("tabindex", "0");
    setMode(mode);

    ed.read = function () {
      if (mode === "type") {
        var text = typed.value.trim();
        if (!text) return { value: "", image: "" };
        var b = f.rect, ratio = Math.max(0.12, Math.min(0.6, (b[3] - b[1]) / (b[2] - b[0])));
        var off = document.createElement("canvas"); off.width = 900; off.height = Math.round(900 * ratio);
        renderTyped(off, text);
        return { value: text, image: off.toDataURL("image/png") };
      }
      if (inked) return { value: "", image: pad.toDataURL("image/png") };
      // Untouched stored drawing: undefined means "send nothing", so the image is kept.
      return storedOnly && !cleared ? { value: "", image: undefined } : { value: "", image: "" };
    };
    var startText = typed.value;
    ed.dirty = function () { return mode === "type" ? typed.value !== startText : (inked || cleared); };
  }

  function removeField(f) {
    api("POST", "/api/field/delete", { id: f.id }).then(function () {
      closeEditor();
      var n = document.getElementById("fld-" + f.id); if (n) n.remove();
      delete S.fields[f.id]; reorder(); S.cur = -1; updateProgress();
    }).catch(function (e) { toast("Error: " + e.message); });
  }

  // ------------------------------------------------------------------ save card
  function queueSave(f) {
    S.saveQueue = S.saveQueue.filter(function (q) { return q.id !== f.id; });
    S.saveQueue.push({ id: f.id, label: f.label, old: f.pending_save ? f.pending_save.old : f.auto_value, value: f.value });
    if (!S.saveShown) showNextSave();
  }
  function showNextSave() {
    var q = S.saveQueue.shift();
    if (!q) { S.saveShown = null; $("saveCard").hidden = true; return; }
    S.saveShown = q;
    $("saveCardLabel").textContent = q.label;
    $("saveCardOld").textContent = q.old ? q.old : "(empty)";
    $("saveCardNew").textContent = q.value;
    $("saveCard").hidden = false;
    announce("Save this answer to the NTXP Form Fill database? " + q.label + ": " + (q.old || "empty") + " changed to " + q.value);
  }
  function decideSave(decision) {
    var q = S.saveShown; if (!q) return;
    api("POST", "/api/field/save-decision", { id: q.id, decision: decision }).then(function (r) {
      toast(decision === "saved" ? "Saved: recorded in " + r.recorded_in + " and queued for the Sheet." : "Ignored this time.");
    }).catch(function (e) { toast("Error: " + e.message); }).then(showNextSave);
  }

  // ------------------------------------------------------------------ tools
  function setMode(m) {
    S.mode = S.mode === m ? null : m;
    document.body.classList.toggle("mode-add", S.mode === "add");
    document.body.classList.toggle("mode-highlight", S.mode === "highlight");
    document.body.classList.toggle("mode-markup", S.mode === "markup");
    $("markupTool").setAttribute("aria-pressed", S.mode === "markup" ? "true" : "false");
    $("addField").setAttribute("aria-pressed", S.mode === "add" ? "true" : "false");
    $("highlighter").setAttribute("aria-pressed", S.mode === "highlight" ? "true" : "false");
    var hint = $("modeHint");
    if (S.mode === "add") { hint.textContent = "Drag a rectangle on the page to add a " + (TYPE_LABELS[$("fieldType").value] || "field") + ". Esc cancels."; hint.hidden = false; }
    else if (S.mode === "highlight") { hint.textContent = "Drag to highlight. Lines snap horizontal, vertical or 45°. Esc cancels."; hint.hidden = false; $("colorPicker").value = S.hlColor; }
    else if (S.mode === "markup") { hint.textContent = markupHint(); hint.hidden = false; $("colorPicker").value = S.mkColor; }
    else { hint.hidden = true; }
    if (S.mode) { closeEditor(); S.reviewing = false; }
  }

  function pagePointerDown(ev, p) {
    if (!S.mode || ev.button > 0) {
      if (!S.mode && ev.target.tagName !== "line") { S.selHl = null; markSelectedHl(); selectMarkup(null); }
      return;
    }
    if (S.mode === "markup") { return markupPointerDown(ev, p); }
    ev.preventDefault();
    var rect = p.el.getBoundingClientRect();
    var x0 = ev.clientX - rect.left, y0 = ev.clientY - rect.top;
    p.el.setPointerCapture(ev.pointerId);
    var temp;
    if (S.mode === "add") {
      temp = el("div", { cls: "rubber" }); p.layer.appendChild(temp);
    } else {
      temp = document.createElementNS("http://www.w3.org/2000/svg", "line");
      temp.setAttribute("stroke", S.hlColor); temp.setAttribute("stroke-opacity", "0.4");
      temp.setAttribute("stroke-width", String(10 * scaleOf(p.n))); temp.setAttribute("stroke-linecap", "butt");
      p.svg.appendChild(temp);
    }
    var x1 = x0, y1 = y0;
    function move(e) {
      x1 = Math.max(0, Math.min(rect.width, e.clientX - rect.left)); y1 = Math.max(0, Math.min(rect.height, e.clientY - rect.top));
      if (S.mode === "add") {
        temp.style.left = Math.min(x0, x1) + "px"; temp.style.top = Math.min(y0, y1) + "px";
        temp.style.width = Math.abs(x1 - x0) + "px"; temp.style.height = Math.abs(y1 - y0) + "px";
      } else {
        var sn = snap(x0, y0, x1, y1);
        temp.setAttribute("x1", sn[0]); temp.setAttribute("y1", sn[1]); temp.setAttribute("x2", sn[2]); temp.setAttribute("y2", sn[3]);
      }
    }
    function up() {
      p.el.removeEventListener("pointermove", move); p.el.removeEventListener("pointerup", up);
      temp.remove();
      var a = screenToPdf(p.n, x0, y0);
      if (S.mode === "add") {
        var b = screenToPdf(p.n, x1, y1);
        if (Math.abs(x1 - x0) < 6 || Math.abs(y1 - y0) < 6) { toast("Drag a larger rectangle."); return; }
        api("POST", "/api/field/add", { page: p.n, rect: [a.x, a.y, b.x, b.y], type: $("fieldType").value }).then(function (r) {
          S.fields[r.field.id] = r.field; reorder(); renderField(r.field); updateProgress();
          setMode("add"); // leave add mode
          announce("Field added on page " + p.n);
          openField(r.field.id);
        }).catch(function (e) { toast("Error: " + e.message); });
      } else {
        var sn = snap(x0, y0, x1, y1);
        if (Math.hypot(sn[2] - sn[0], sn[3] - sn[1]) < 6) return;
        var e2 = screenToPdf(p.n, sn[2], sn[3]);
        api("POST", "/api/highlight", { page: p.n, x1: a.x, y1: a.y, x2: e2.x, y2: e2.y, color: S.hlColor }).then(function (r) {
          S.st.highlights.push(r.highlight); drawHighlight(r.highlight);
        }).catch(function (e) { toast("Error: " + e.message); });
      }
    }
    p.el.addEventListener("pointermove", move); p.el.addEventListener("pointerup", up);
  }

  function drawHighlight(hl) {
    var p = pageInfo(hl.page); if (!p) return;
    var s = scaleOf(hl.page);
    var line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", (hl.x1 - p.ox) * s); line.setAttribute("y1", (p.oy + p.h - hl.y1) * s);
    line.setAttribute("x2", (hl.x2 - p.ox) * s); line.setAttribute("y2", (p.oy + p.h - hl.y2) * s);
    line.setAttribute("stroke", hl.color); line.setAttribute("stroke-opacity", String(hl.opacity || 0.4));
    line.setAttribute("stroke-width", String((hl.width || 10) * s)); line.setAttribute("stroke-linecap", "butt");
    line.setAttribute("data-id", hl.id); line.setAttribute("class", "hl" + (S.selHl === hl.id ? " selected" : ""));
    line.addEventListener("pointerdown", function (ev) {
      if (S.mode) return;
      ev.stopPropagation(); selectMarkup(null); S.selHl = hl.id; S.selField = null; $("colorPicker").value = hl.color; markSelectedHl();
      toast("Highlight selected: change its color, or press Delete to remove it.");
    });
    p.svg.appendChild(line);
  }
  function markSelectedHl() {
    S.pages.forEach(function (p) {
      Array.prototype.forEach.call(p.svg.querySelectorAll("line"), function (l) {
        l.setAttribute("class", "hl" + (l.getAttribute("data-id") === S.selHl ? " selected" : ""));
      });
    });
  }
  function onColor() {
    if (S.mode === "markup" || S.selMk) {
      S.mkColor = $("colorPicker").value.toUpperCase();
      if (S.selMk) {
        api("POST", "/api/markup/update", { id: S.selMk, color: S.mkColor }).catch(function (e) { toast("Error: " + e.message); });
      }
      return;
    }
    var c = $("colorPicker").value.toUpperCase();
    if (S.selHl) {
      api("POST", "/api/highlight/update", { id: S.selHl, color: c }).then(function (r) {
        S.st.highlights.forEach(function (h) { if (h.id === r.highlight.id) h.color = r.highlight.color; });
        layoutAll();
      }).catch(function (e) { toast("Error: " + e.message); });
    } else if (S.mode === "highlight" || !S.selField) {
      S.hlColor = c;
    } else if (S.selField) {
      api("POST", "/api/field", { id: S.selField, style: { color: c } }).then(function (r) { S.fields[r.field.id] = r.field; reorder(); renderField(r.field); });
    }
  }
  function onSize() {
    var v = parseFloat($("fontSize").value);
    if (!S.selField || isNaN(v)) return;
    api("POST", "/api/field", { id: S.selField, style: { size: v } }).then(function (r) { S.fields[r.field.id] = r.field; reorder(); renderField(r.field); if (S.editor) positionEditor(); })
      .catch(function (e) { toast("Error: " + e.message); });
  }

  // ------------------------------------------------------------------ completion / review / export
  function onCompleted() {
    closeEditor(); S.reviewing = false; S.cur = -1; renderAllFields();
    S.pages.forEach(function (p) { p.el.classList.remove("reopened"); });
    $("completedFlag").hidden = false;
    announce("Completed. Every field is approved. Running the review.");
    runReview(true);
  }
  function runReview(autoExport) {
    return api("POST", "/api/review", {}).then(function (rv) {
      showReview(rv, false);
      if (autoExport && rv.can_export) exportFinal();
      return rv;
    }).catch(function (e) { toast("Review failed: " + e.message); });
  }
  function showReview(rv, quiet) {
    var wasOpen = !$("reviewPanel").hidden;
    document.body.classList.add("panel-open");
    $("reviewPanel").hidden = false;
    if (!wasOpen) layoutAll();
    var c = rv.confidence || {};
    $("confidence").textContent = c.text || "Confidence unavailable";
    var dr = $("confidenceDrivers"); clear(dr);
    (c.drivers || []).forEach(function (d) { dr.appendChild(el("li", { text: d })); });
    var ul = $("issues"); clear(ul);
    var issues = rv.issues || [];
    if (!issues.length) ul.appendChild(el("li", { cls: "none", text: "No issues found." }));
    issues.forEach(function (i) {
      ul.appendChild(el("li", { cls: i.blocking ? "blocking" : "", text: (i.blocking ? "Blocking: " : (i.advisory ? "Advisory: " : "Check: ")) + i.message }));
    });
    $("sigGate").hidden = !rv.needs_signature_approval;
    $("exportFinal").disabled = !rv.can_export;
    if (!quiet) announce((c.text || "") + ". " + (rv.blocking ? rv.blocking + " blocking issue(s)." : "No blocking issues."));
  }
  function exportFinal() {
    if (S.exporting) return;
    S.exporting = true;
    api("POST", "/api/export", { final: true }).then(function (r) {
      showExport(r);
      toast("Final PDF exported: " + r.path, 6000);
    }).catch(function (e) {
      if (e.data && e.data.review) showReview(e.data.review, false);
      toast("Export blocked: " + e.message, 6000);
    }).then(function () { S.exporting = false; });
  }
  function showExport(r) {
    $("exportResult").hidden = false;
    $("exportPath").textContent = r.path;
    var a = $("exportLink");
    a.href = withToken("/api/download/" + encodeURIComponent(r.file));
    a.setAttribute("download", r.file);
  }

  function stopAndDownload() {
    commitOpenEditor(false).then(function () { return api("POST", "/api/stop", {}); }).then(function (r) {
      var a = el("a", { href: withToken("/api/download/" + encodeURIComponent(r.file)), download: r.file });
      document.body.appendChild(a); a.click(); a.remove();
      toast("Progress saved: " + r.path, 6000);
    }).catch(function (e) { toast("Error: " + e.message); });
  }

  // Signature approval dialog
  function openSigDialog() {
    var d = $("sigDialog"), sel = $("sigSigner");
    clear(sel);
    (S.st.signers || []).forEach(function (s) { sel.appendChild(el("option", { value: s.name, text: s.name + " (" + s.title + ")" })); });
    sel.value = S.st.default_signer || "Alison Hopkins";
    $("sigCircumstance").value = ""; $("sigConfirm").checked = false; $("sigError").textContent = "";
    $("sigSummary").hidden = true;
    syncCirc();
    d.showModal();
  }
  function syncCirc() {
    var s = (S.st.signers || []).find(function (x) { return x.name === $("sigSigner").value; });
    $("sigCircRow").hidden = !(s && s.requires_circumstance);
  }
  function approveSignature() {
    var signer = $("sigSigner").value, circ = $("sigCircumstance").value.trim();
    var s = (S.st.signers || []).find(function (x) { return x.name === signer; });
    if (s && s.requires_circumstance && !circ) { $("sigError").textContent = signer + " signs only when circumstances require: state the circumstance, or choose " + S.st.default_signer + "."; return; }
    if (!$("sigConfirm").checked) { $("sigError").textContent = "Check the approval box to confirm."; return; }
    api("POST", "/api/signature/approve", { signer: signer, circumstance: circ || null, confirm: true }).then(function (r) {
      S.st.signature_approval = r.approval;
      $("sigSummary").textContent = r.summary; $("sigSummary").hidden = false;
      $("sigDialog").close();
      toast("Signature approved (" + r.approval.request_id + "), bound to SHA-256 " + r.approval.document_sha256.slice(0, 12) + "…", 6000);
      return runReview(true);
    }).catch(function (e) { $("sigError").textContent = e.message; });
  }

  // Drive scan / proposals
  function scanDrive() {
    var d = $("proposalsDialog");
    $("scanMessage").textContent = "Scanning…"; $("propResult").textContent = "";
    clear($("proposalList"));
    d.showModal();
    api("POST", "/api/scan", {}).then(function (r) {
      $("scanMessage").textContent = r.ok ? ("Scanned " + r.documents + " documents; " + r.new_proposals + " new proposals.") : r.message;
    }).catch(function (e) { $("scanMessage").textContent = "Scan failed: " + e.message; })
      .then(loadProposals);
  }
  function loadProposals() {
    return api("GET", "/api/proposals").then(function (r) {
      var ul = $("proposalList"); clear(ul);
      if (!r.proposals.length) { ul.appendChild(el("li", { text: "No pending proposals." })); return; }
      r.proposals.forEach(function (p, i) {
        var cid = "prop-" + i;
        var cb = el("input", { type: "checkbox", id: cid, "data-id": p.id });
        var lab = el("label", { "for": cid },
          el("span", { cls: "pf", text: p.field_name }), ": ",
          el("span", { cls: "pcur", text: p.current_value || "(none)" }), " → ",
          el("span", { cls: "pnew", text: p.proposed_value }),
          p.tier3 ? el("span", { cls: "t3", text: "Tier 3" }) : null,
          el("span", { cls: "psrc", text: "Source: " + (p.source || "unknown") + (p.kind ? " · " + p.kind : "") }));
        ul.appendChild(el("li", null, cb, lab));
      });
    }).catch(function (e) { $("propResult").textContent = "Could not load proposals: " + e.message; });
  }
  function applyProposals() {
    var ids = Array.prototype.map.call($("proposalList").querySelectorAll("input[type=checkbox]:checked"), function (c) { return c.getAttribute("data-id"); });
    if (!ids.length) { $("propResult").textContent = "Check at least one line to apply."; return; }
    api("POST", "/api/proposals/apply", { ids: ids }).then(function (r) {
      var sh = r.sheet || {}, msg = "Approved " + r.applied.length + "; skipped " + r.skipped.length + ".";
      if (sh.status === "appended_live") msg += " Written to the Sheet: " + sh.row_count + " row(s).";
      else if (sh.status === "queued_for_agent") msg += " " + sh.row_count + " Sheet row(s) queued for Claude to append (" + sh.queue_file + ").";
      else if (sh.status === "not_queued") msg += " Sheet rows NOT queued: " + (sh.error || "");
      (r.skipped || []).forEach(function (k) { msg += " Skipped " + k.id + ": " + k.reason + "."; });
      $("propResult").textContent = msg;
      return loadProposals();
    }).catch(function (e) { $("propResult").textContent = "Error: " + e.message; });
  }

  // ------------------------------------------------------------------ wiring
  // ------------------------------------------------------------------ live view (server-sent events)
  // Every saved change bumps the session revision; the server pushes it and this window
  // re-reads the session and patches only what changed (fields, highlights, markups, flags).
  function startLive() {
    if (!window.EventSource || S.es) return;
    var badge = $("liveBadge");
    var es = new EventSource(withToken("/api/events?since=" + S.rev));
    S.es = es;
    es.addEventListener("open", function () { badge.classList.remove("off"); badge.textContent = "LIVE"; });
    es.addEventListener("error", function () { badge.classList.add("off"); badge.textContent = "RECONNECTING"; });
    es.addEventListener("change", function (ev) {
      var d = {}; try { d = JSON.parse(ev.data); } catch (e) { return; }
      if (d.rev > S.rev) refresh();
    });
  }
  var refreshing = null, refreshAgain = false;
  function refresh() {
    if (refreshing) { refreshAgain = true; return refreshing; }
    refreshing = api("GET", "/api/session").then(function (st) {
      if ((st.rev || 0) <= S.rev) return;
      S.rev = st.rev;
      var editing = S.editor && S.editor.field ? S.editor.field.id : null, seen = {}, changed = 0;
      st.fields.forEach(function (f) {
        seen[f.id] = 1;
        if (f.id === editing) return;  // never clobber what the user is typing
        var old = S.fields[f.id];
        if (!old || JSON.stringify(old) !== JSON.stringify(f)) { S.fields[f.id] = f; changed++; if (old && pageInfo(f.page)) renderField(f); }
      });
      Object.keys(S.fields).forEach(function (id) {
        if (!seen[id] && id !== editing) { var n = document.getElementById("fld-" + id); if (n) n.remove(); delete S.fields[id]; changed++; }
      });
      reorder();
      S.order.forEach(function (f) { if (!document.getElementById("fld-" + f.id)) renderField(f); });
      if (JSON.stringify(S.st.highlights) !== JSON.stringify(st.highlights)) {
        S.st.highlights = st.highlights;
        S.pages.forEach(function (p) { while (p.svg.firstChild) p.svg.removeChild(p.svg.firstChild); });
        st.highlights.forEach(drawHighlight); changed++;
      }
      if (JSON.stringify(S.markups) !== JSON.stringify(st.markups || [])) { S.markups = st.markups || []; renderMarkups(); changed++; }
      ["review", "flags", "signature_approval", "progress", "confidence"].forEach(function (k) { S.st[k] = st[k]; });
      updateProgress();
      var badge = $("liveBadge");
      badge.classList.remove("pulse"); void badge.offsetWidth; badge.classList.add("pulse");
      if (changed) announce("Document updated");
    }).catch(function () { /* the next event retries */ }).then(function () {
      refreshing = null;
      if (refreshAgain) { refreshAgain = false; refresh(); }
    });
    return refreshing;
  }

  // ------------------------------------------------------------------ markups
  function fillSelect(sel, items) {
    clear(sel);
    items.forEach(function (t) { sel.appendChild(el("option", { value: t, text: t.replace(/_/g, " ") })); });
  }
  function markupHint() {
    var k = $("markupKind").value;
    if (k === "arrow" || k === "line") return "Drag from the tail to the point of the " + k + ". Esc cancels.";
    if (k === "ink" || k === "polyline") return "Draw freehand; release to finish. Esc cancels.";
    if (k === "text") return "Type the note in the Markup text box, then drag its box. Esc cancels.";
    if (k === "stamp") return "Pick the stamp status, then drag where the stamp goes. Stamps need Tier 3 approval before final export.";
    return "Drag to place the " + k + ". Esc cancels.";
  }
  function svg(tag, attrs) {
    var n = document.createElementNS(SVGNS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }
  function cloudD(r, depth, seg) {
    var x0 = r[0], y0 = r[1], x1 = r[2], y1 = r[3], cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    var c = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], d = "M " + x0 + " " + y0;
    for (var i = 0; i < 4; i++) {
      var a = c[i], b = c[(i + 1) % 4], len = Math.hypot(b[0] - a[0], b[1] - a[1]);
      var n = Math.max(1, Math.round(len / seg)), dx = (b[0] - a[0]) / len, dy = (b[1] - a[1]) / len;
      var nx = dy, ny = -dx, mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
      if ((mx - cx) * nx + (my - cy) * ny < 0) { nx = -nx; ny = -ny; }
      for (var k = 0; k < n; k++) {
        var px = a[0] + (b[0] - a[0]) * k / n, py = a[1] + (b[1] - a[1]) * k / n;
        var qx = a[0] + (b[0] - a[0]) * (k + 1) / n, qy = a[1] + (b[1] - a[1]) * (k + 1) / n;
        d += " Q " + ((px + qx) / 2 + nx * 2 * depth) + " " + ((py + qy) / 2 + ny * 2 * depth) + " " + qx + " " + qy;
      }
    }
    return d + " Z";
  }
  function wrapLines(text, width, size) {
    var max = Math.max(1, Math.floor(width / (size * 0.56))), out = [];
    String(text || "").split("\n").forEach(function (para) {
      var line = "";
      para.split(/\s+/).forEach(function (w) {
        if (!w) return;
        var t = line ? line + " " + w : w;
        if (t.length > max && line) { out.push(line); line = w; } else line = t;
      });
      out.push(line);
    });
    return out;
  }
  function textBlock(g, text, r, color, size) {
    // counter-flip so text reads upright inside the y-up markup layer (LOCK-13 centered)
    var w = r[2] - r[0] - 6, h = r[3] - r[1] - 4, lines;
    size = size || 11;
    while (true) { lines = wrapLines(text, w, size); if (lines.length * size * 1.2 <= h || size <= 5) break; size -= 0.5; }
    var t = svg("g", { transform: "translate(" + ((r[0] + r[2]) / 2) + " " + ((r[1] + r[3]) / 2) + ") scale(1 -1)" });
    var top = -(lines.length * size * 1.2) / 2 + size * 0.95;
    lines.forEach(function (ln, i) {
      var tx = svg("text", { x: 0, y: top + i * size * 1.2, "text-anchor": "middle", "font-size": size, fill: color });
      tx.textContent = ln; t.appendChild(tx);
    });
    g.appendChild(t);
  }
  function lineAttrs(m, width, opacity) {
    var a = { fill: "none", stroke: m.color, "stroke-width": width, "stroke-opacity": opacity, "stroke-linejoin": "round", "stroke-linecap": "round" };
    if (m.dashed) a["stroke-dasharray"] = "2 3";
    return a;
  }
  function shapeFor(m, attrs) {
    var k = m.kind, r = m.rect;
    if (k === "cloud") return svg("path", Object.assign({ d: cloudD(r, m.cloud_depth || 5, m.cloud_segment || 28) }, attrs));
    if (k === "rectangle" || k === "text" || k === "stamp") return svg("rect", Object.assign({ x: r[0], y: r[1], width: r[2] - r[0], height: r[3] - r[1] }, attrs));
    if (k === "ellipse") return svg("ellipse", Object.assign({ cx: (r[0] + r[2]) / 2, cy: (r[1] + r[3]) / 2, rx: (r[2] - r[0]) / 2, ry: (r[3] - r[1]) / 2 }, attrs));
    if (k === "arrow" || k === "line") return svg("line", Object.assign({ x1: m.start[0], y1: m.start[1], x2: m.end[0], y2: m.end[1] }, attrs));
    var pts = (m.points || []).map(function (p) { return p[0] + "," + p[1]; }).join(" ");
    return svg(k === "area" ? "polygon" : "polyline", Object.assign({ points: pts }, attrs));
  }
  function drawMarkup(m) {
    var p = pageInfo(m.page); if (!p) return;
    var g = svg("g", { "class": "mk" + (S.selMk === m.id ? " selected" : ""), "data-id": m.id });
    var w = m.width || 2, op = m.opacity == null ? 0.8 : m.opacity;
    if (LINE_BASED[m.kind] && m.halo !== false) g.appendChild(shapeFor(m, lineAttrs(m, w * 3, 0.3)));  // LOCK-08 halo
    if (m.kind === "area") {
      g.appendChild(shapeFor(m, { fill: m.color, "fill-opacity": m.fill_opacity || 0.3, stroke: "none" }));
      g.appendChild(shapeFor(m, lineAttrs(m, w, op)));
    } else if (m.kind === "text") {
      g.appendChild(shapeFor(m, { fill: "#FFFFFF", "fill-opacity": 0.5, stroke: m.color, "stroke-width": w, "stroke-opacity": op }));
      textBlock(g, m.text, m.rect, m.color, 11);
    } else if (m.kind === "stamp") {
      var r = m.rect, h = r[3] - r[1];
      g.appendChild(shapeFor(m, { fill: "none", stroke: m.color, "stroke-width": w, "stroke-opacity": 0.8 }));
      g.appendChild(svg("rect", { x: r[0] + 3, y: r[1] + 3, width: r[2] - r[0] - 6, height: h - 6, fill: "none", stroke: m.color, "stroke-width": 0.75, "stroke-opacity": 0.8 }));
      textBlock(g, m.company || "NTXP LLC", [r[0], r[3] - h * 0.30, r[2], r[3] - 3], m.color, 9);
      textBlock(g, m.stamp_status || m.text, [r[0] + 3, r[1] + h * 0.34, r[2] - 3, r[3] - h * 0.30], m.color, 14);
      var foot = [m.reviewer, m.stamp_date].filter(Boolean).join(" | ");
      if (foot) textBlock(g, foot, [r[0] + 3, r[1] + 3, r[2] - 3, r[1] + h * 0.34], m.color, 8);
    } else {
      g.appendChild(shapeFor(m, lineAttrs(m, w, m.kind === "rectangle" ? 1 : op)));
      if (m.kind === "arrow") {
        var a = Math.atan2(m.end[1] - m.start[1], m.end[0] - m.start[0]), sz = 3 * w + 6, e = m.end;
        var pts = [e, [e[0] - sz * Math.cos(a - 0.45), e[1] - sz * Math.sin(a - 0.45)], [e[0] - sz * Math.cos(a + 0.45), e[1] - sz * Math.sin(a + 0.45)]];
        g.appendChild(svg("polygon", { points: pts.map(function (q) { return q[0] + "," + q[1]; }).join(" "), fill: m.color, "fill-opacity": op }));
      }
      if (m.text && (m.kind === "arrow" || m.kind === "line")) textBlock(g, m.text, [m.start[0] - 60, m.start[1] + 4, m.start[0] + 60, m.start[1] + 26], m.color, 10);
      if (m.text && m.rect) {  // label tag centered above clouds, boxes and ellipses (LOCK-05 red text on red marks)
        var cx = (m.rect[0] + m.rect[2]) / 2, top = m.rect[3] + (m.kind === "cloud" ? 2 * (m.cloud_depth || 5) : 0);
        textBlock(g, m.text, [cx - 110, top + 3, cx + 110, top + 27], m.color, 11);
      }
    }
    g.addEventListener("pointerdown", function (ev) {
      if (S.mode) return;
      ev.stopPropagation(); S.selHl = null; markSelectedHl(); selectMarkup(m.id);
      $("colorPicker").value = m.color;
      toast((m.kind === "stamp" ? "Stamp" : "Markup") + " selected: change its color, or press Delete to remove it.");
    });
    p.mk.appendChild(g);
  }
  function renderMarkups() {
    S.pages.forEach(function (p) { while (p.mk.firstChild) p.mk.removeChild(p.mk.firstChild); });
    S.markups.forEach(drawMarkup);
  }
  function selectMarkup(id) {
    S.selMk = id;
    S.pages.forEach(function (p) {
      Array.prototype.forEach.call(p.mk.querySelectorAll("g.mk"), function (g) {
        g.setAttribute("class", "mk" + (g.getAttribute("data-id") === id ? " selected" : ""));
      });
    });
  }
  function todayUs() { var d = new Date(); return ("0" + (d.getMonth() + 1)).slice(-2) + "/" + ("0" + d.getDate()).slice(-2) + "/" + d.getFullYear(); }
  function markupPointerDown(ev, p) {
    ev.preventDefault();
    var kind = $("markupKind").value, rect = p.el.getBoundingClientRect();
    if (kind === "text" && !$("markupText").value.trim()) { toast("Type the note in the Markup text box first."); $("markupText").focus(); return; }
    var x0 = ev.clientX - rect.left, y0 = ev.clientY - rect.top, pts = [[x0, y0]], x1 = x0, y1 = y0, temp;
    p.el.setPointerCapture(ev.pointerId);
    if (RECT_KINDS[kind]) { temp = el("div", { cls: "rubber" }); p.layer.appendChild(temp); }
    else if (kind === "arrow" || kind === "line") { temp = svg("line", { stroke: S.mkColor, "stroke-width": 2 }); p.svg.appendChild(temp); }
    else { temp = svg("polyline", { stroke: S.mkColor, "stroke-width": 2, fill: "none" }); p.svg.appendChild(temp); }
    function move(e) {
      x1 = Math.max(0, Math.min(rect.width, e.clientX - rect.left)); y1 = Math.max(0, Math.min(rect.height, e.clientY - rect.top));
      if (RECT_KINDS[kind]) {
        temp.style.left = Math.min(x0, x1) + "px"; temp.style.top = Math.min(y0, y1) + "px";
        temp.style.width = Math.abs(x1 - x0) + "px"; temp.style.height = Math.abs(y1 - y0) + "px";
      } else if (kind === "arrow" || kind === "line") {
        temp.setAttribute("x1", x0); temp.setAttribute("y1", y0); temp.setAttribute("x2", x1); temp.setAttribute("y2", y1);
      } else {
        pts.push([x1, y1]); temp.setAttribute("points", pts.map(function (q) { return q[0] + "," + q[1]; }).join(" "));
      }
    }
    function up() {
      p.el.removeEventListener("pointermove", move); p.el.removeEventListener("pointerup", up);
      temp.remove();
      var body = { kind: kind, page: p.n, origin: "bottom-left", color: S.mkColor, author: S.st.default_signer || "" };
      var a = screenToPdf(p.n, x0, y0), b = screenToPdf(p.n, x1, y1);
      if (RECT_KINDS[kind]) {
        if (Math.abs(x1 - x0) < 6 || Math.abs(y1 - y0) < 6) { toast("Drag a larger box."); return; }
        body.rect = [a.x, a.y, b.x, b.y];
      } else if (kind === "arrow" || kind === "line") {
        if (Math.hypot(x1 - x0, y1 - y0) < 6) return;
        body.start = [a.x, a.y]; body.end = [b.x, b.y];
      } else {
        if (pts.length < 3) return;
        body.points = pts.map(function (q) { var r2 = screenToPdf(p.n, q[0], q[1]); return [r2.x, r2.y]; });
      }
      var txt = $("markupText").value.trim();
      if (txt) body.text = txt;
      if (kind === "stamp") { body.status = $("stampStatus").value; body.reviewer = S.st.default_signer || ""; body.stamp_date = todayUs(); }
      api("POST", "/api/markup", body).then(function (r) {
        if (!S.markups.some(function (m) { return m.id === r.markup.id; })) { S.markups.push(r.markup); drawMarkup(r.markup); }
        announce((kind === "stamp" ? "Stamp " : "Markup ") + "added on page " + p.n);
      }).catch(function (e) { toast("Error: " + e.message); });
    }
    p.el.addEventListener("pointermove", move); p.el.addEventListener("pointerup", up);
  }

  function globalKeys(ev) {
    if (ev.key === "Escape" && S.mode) { setMode(null); return; }
    if ((ev.key === "Delete" || ev.key === "Backspace") && S.selMk && !S.editor &&
        ["INPUT", "SELECT", "TEXTAREA"].indexOf(document.activeElement.tagName) < 0) {
      var mid = S.selMk;
      api("POST", "/api/markup/delete", { id: mid }).then(function (r) {
        S.markups = S.markups.filter(function (m) { return m.id !== mid; }); S.selMk = null; renderMarkups();
        announce("Markup deleted");
      }).catch(function (e) { toast("Error: " + e.message); });
      return;
    }
    if (ev.key === "Escape" && S.reviewing) { stopReview(); return; }
    if ((ev.key === "Delete" || ev.key === "Backspace") && S.selHl && !S.editor && document.activeElement.tagName !== "INPUT") {
      var id = S.selHl;
      api("POST", "/api/highlight/delete", { id: id }).then(function () {
        S.st.highlights = S.st.highlights.filter(function (h) { return h.id !== id; }); S.selHl = null; layoutAll();
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (!TOKEN) { $("formName").textContent = "Missing session token in the URL"; return; }
    $("startReview").addEventListener("click", startReview);
    $("addField").addEventListener("click", function () { setMode("add"); });
    $("highlighter").addEventListener("click", function () { setMode("highlight"); });
    $("markupTool").addEventListener("click", function () { setMode("markup"); });
    $("markupKind").addEventListener("change", function () {
      $("stampWrap").hidden = $("markupKind").value !== "stamp";
      if (S.mode === "markup") $("modeHint").textContent = markupHint();
    });
    $("fieldType").addEventListener("change", function () { if (S.mode === "add") { S.mode = null; setMode("add"); } });
    $("colorPicker").addEventListener("change", onColor);
    $("fontSize").addEventListener("change", onSize);
    $("scanDrive").addEventListener("click", scanDrive);
    $("stopDownload").addEventListener("click", stopAndDownload);
    $("nextPage").addEventListener("click", nextPage);
    $("lastPage").addEventListener("click", lastPage);
    $("saveYes").addEventListener("click", function () { decideSave("saved"); });
    $("saveNo").addEventListener("click", function () { decideSave("ignored"); });
    $("rerunReview").addEventListener("click", function () { runReview(false); });
    $("exportFinal").addEventListener("click", exportFinal);
    $("closePanel").addEventListener("click", function () { $("reviewPanel").hidden = true; document.body.classList.remove("panel-open"); layoutAll(); });
    $("openSigDialog").addEventListener("click", openSigDialog);
    $("sigSigner").addEventListener("change", syncCirc);
    $("sigCancel").addEventListener("click", function () { $("sigDialog").close(); });
    $("sigApprove").addEventListener("click", approveSignature);
    $("propClose").addEventListener("click", function () { $("proposalsDialog").close(); });
    $("propApply").addEventListener("click", applyProposals);
    document.addEventListener("keydown", globalKeys);
    syncBars();
    $("viewer").addEventListener("scroll", function () { if (!S.reviewing) updatePageIndicator(); }, { passive: true });
    var rt = null;
    window.addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(layoutAll, 120); });
    load();
  });
})();
