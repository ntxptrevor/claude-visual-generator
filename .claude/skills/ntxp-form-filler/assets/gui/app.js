/* NTXP Form Filler guided review GUI. Vanilla JS, no frameworks, no CDN.
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
    hlColor: "#FFEB3B", wasCompleted: false, exporting: false, sigCache: {}
  };

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
      document.title = "NTXP Form Filler | " + st.form_name;
      var sel = $("fieldType");
      clear(sel);
      st.field_types.forEach(function (t) { sel.appendChild(el("option", { value: t, text: TYPE_LABELS[t] || t })); });
      S.hlColor = (st.highlight_default && st.highlight_default.color) || "#FFEB3B";
      st.fields.forEach(function (f) { S.fields[f.id] = f; });
      buildPages(st.pages);
      st.highlights.forEach(drawHighlight);
      reorder();
      renderAllFields();
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
      wrap.appendChild(el("span", { cls: "page-label", text: "Page " + p.n }));
      wrap.appendChild(img); wrap.appendChild(svg); wrap.appendChild(layer);
      host.appendChild(wrap);
      var info = { n: p.n, w: p.w, h: p.h, ox: p.ox || 0, oy: p.oy || 0, el: wrap, svg: svg, layer: layer, img: img };
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
    commitOpenEditor(false).then(function () { focusField(i); });
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
    if (S.cur > 0) commitOpenEditor(false).then(function () { focusField(S.cur - 1); });
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
    return sendField(body, ed.field).catch(function (e) { toast("Not saved: " + e.message); });
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

    var inked = false, drawing = false, last = null;
    var pctx = pad.getContext("2d");
    pctx.lineWidth = 4; pctx.lineCap = "round"; pctx.lineJoin = "round"; pctx.strokeStyle = "#000";
    if (f.has_image && S.sigCache[f.id] && mode === "draw") {
      var im = new Image(); im.onload = function () { pctx.drawImage(im, 0, 0, pad.width, pad.height); inked = true; }; im.src = S.sigCache[f.id];
    }
    function pt(ev) { var r = pad.getBoundingClientRect(); return { x: (ev.clientX - r.left) * pad.width / r.width, y: (ev.clientY - r.top) * pad.height / r.height }; }
    pad.addEventListener("pointerdown", function (ev) { ev.preventDefault(); pad.setPointerCapture(ev.pointerId); drawing = true; last = pt(ev); });
    pad.addEventListener("pointermove", function (ev) {
      if (!drawing) return; var p = pt(ev);
      pctx.beginPath(); pctx.moveTo(last.x, last.y); pctx.lineTo(p.x, p.y); pctx.stroke(); last = p; inked = true;
    });
    pad.addEventListener("pointerup", function () { drawing = false; });
    clearBtn.addEventListener("click", function () { pctx.clearRect(0, 0, pad.width, pad.height); inked = false; });

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
      return inked ? { value: "", image: pad.toDataURL("image/png") } : { value: "", image: "" };
    };
    var startText = typed.value;
    ed.dirty = function () { return mode === "type" ? typed.value !== startText : inked; };
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
    announce("Save this answer to the NTXP Form Filler database? " + q.label + ": " + (q.old || "empty") + " changed to " + q.value);
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
    $("addField").setAttribute("aria-pressed", S.mode === "add" ? "true" : "false");
    $("highlighter").setAttribute("aria-pressed", S.mode === "highlight" ? "true" : "false");
    var hint = $("modeHint");
    if (S.mode === "add") { hint.textContent = "Drag a rectangle on the page to add a " + (TYPE_LABELS[$("fieldType").value] || "field") + ". Esc cancels."; hint.hidden = false; }
    else if (S.mode === "highlight") { hint.textContent = "Drag to highlight. Lines snap horizontal, vertical or 45°. Esc cancels."; hint.hidden = false; $("colorPicker").value = S.hlColor; }
    else { hint.hidden = true; }
    if (S.mode) { closeEditor(); S.reviewing = false; }
  }

  function pagePointerDown(ev, p) {
    if (!S.mode || ev.button > 0) {
      if (!S.mode && ev.target.tagName !== "line") { S.selHl = null; markSelectedHl(); }
      return;
    }
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
      ev.stopPropagation(); S.selHl = hl.id; S.selField = null; $("colorPicker").value = hl.color; markSelectedHl();
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
      $("propResult").textContent = "Applied " + r.applied.length + "; skipped " + r.skipped.length + "." +
        (r.sheet_rows_file ? " Sheet rows queued: " + r.sheet_rows_file : "");
      return loadProposals();
    }).catch(function (e) { $("propResult").textContent = "Error: " + e.message; });
  }

  // ------------------------------------------------------------------ wiring
  function globalKeys(ev) {
    if (ev.key === "Escape" && S.mode) { setMode(null); return; }
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
