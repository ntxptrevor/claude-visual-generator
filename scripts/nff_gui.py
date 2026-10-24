#!/usr/bin/env python3
"""
NTXP Form Filler guided review GUI (contract: .claude/skills/ntxp-form-filler/ARCHITECTURE.md).

    python3 scripts/nff_gui.py --pdf blank.pdf [--form-type w9] [--kb-json kb.json]
        [--canonical-json c.json] [--port 8765] [--no-browser] [--resume SESSION_ID]

Creates NFF_HOME/sessions/<id>/, detects fields (AcroForm + visual), builds answers with
nff_workflow_registry.build_answers (Tier 1 enforced), classifies every field, renders the
pages with pypdfium2 and serves the review GUI + JSON API on 127.0.0.1 with a per-session
token. Prints machine-readable lines for the agent:

    NFF_GUI: <url>          NFF_EXPORT: <final pdf>          NFF_PROGRESS: <draft pdf>

Prices and signatures are never auto-filled. Signature / initials fields are exported only
after POST /api/signature/approve produced an approval bound (nff_signatures, SHA-256) to the
exact unsigned final document; any later edit voids it. Confidence is shown in the GUI only.
"""

import argparse
import base64
import hashlib
import hmac
import importlib
import json
import os
import re
import secrets
import shutil
import sys
import threading
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import nff_render as render  # noqa: E402
from nff_render import format_currency, format_date, format_phone, initials_of  # noqa: E402,F401

ASSETS = SCRIPTS.parent / ".claude" / "skills" / "ntxp-form-filler" / "assets" / "gui"
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/app.css": ("app.css", "text/css; charset=utf-8"),
          "/app.js": ("app.js", "application/javascript; charset=utf-8")}

FIELD_TYPES = ("text_word", "text_paragraph", "date", "person", "address", "phone", "email",
               "currency", "checkmark", "x_mark", "initials", "signature")
NEVER_AUTOFILL_TYPES = {"signature", "initials", "currency"}
NO_SAVE_TYPES = {"signature", "initials", "currency"}
SIGNED_TYPES = {"signature", "initials"}
MAX_BODY = 8 * 1024 * 1024
MAX_IMAGE = 2 * 1024 * 1024
DEFAULT_STYLE = {"color": "#000000", "size": 11, "font": "Arial", "weight": "regular"}
HIGHLIGHT_DEFAULT = {"color": "#FFEB3B", "opacity": 0.4, "width": 10}
SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
PRINT_LOCK = threading.Lock()


def emit(line):
    with PRINT_LOCK:
        print(line, flush=True)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nff_home():
    return Path(os.environ.get("NFF_HOME") or Path.home() / ".ntxp" / "nff").expanduser()


def optional(name):
    """Import a sibling module owned by another component; None when missing or broken."""
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def db_conn():
    db = optional("nff_db")
    if db is None:
        return None, None
    try:
        return db, db.connect()
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Classification (nff_jev.classify_field when importable, else local rules)
# ---------------------------------------------------------------------------

LOCAL_RULES = [
    ("date", r"\bdate\b|\bdated\b|\bd\.?o\.?b\b|expiration|expires|effective"),
    ("signature", r"signature|sign\s*here|^\s*signed\b|authorized\s+signer"),
    ("initials", r"\binitials?\b"),
    ("email", r"e-?mail"),
    ("phone", r"phone|telephone|\btel\b|\bfax\b|mobile|\bcell\b"),
    ("currency", r"amount|price|cost|\bfee\b|total|\$|\bbid\b|\bsum\b|dollar|payment"),
    ("address", r"address|street|mailing"),
    ("text_word", r"(company|business|firm|vendor|entity|legal|project)\s*name"),
    ("person", r"\bname\b|contact|owner|representative|officer|printed|print\b|\bby\b"),
    ("text_paragraph", r"description|comments?|\bnotes?\b|explain|remarks|scope"),
    ("checkmark", r"^\s*(yes|no|check|agree)\b"),
]
LOCAL_RULES = [(t, re.compile(p, re.I)) for t, p in LOCAL_RULES]


def local_classify(label, near="", rect=None):
    if rect:
        w, h = abs(rect[2] - rect[0]), abs(rect[3] - rect[1])
        if 0 < w <= 18 and 0 < h <= 18:
            return {"type": "checkmark", "confidence": 0.85, "referee": "local"}
    for ftype, rx in LOCAL_RULES:
        if rx.search(label or ""):
            if rect and ftype in ("text_word", "person") and abs(rect[3] - rect[1]) >= 40:
                return {"type": "text_paragraph", "confidence": 0.75, "referee": "local"}
            return {"type": ftype, "confidence": 0.8, "referee": "local"}
    if rect and abs(rect[3] - rect[1]) >= 40:
        return {"type": "text_paragraph", "confidence": 0.6, "referee": "local"}
    return {"type": "text_word", "confidence": 0.4, "referee": "local"}


def classify(label, near, rect, acro_kind=None, use_llm=False):
    if acro_kind == "checkbox":
        return {"type": "checkmark", "confidence": 0.99, "referee": "acroform"}
    if acro_kind == "signature":
        return {"type": "signature", "confidence": 0.99, "referee": "acroform"}
    jev = optional("nff_jev")
    if jev is not None and hasattr(jev, "classify_field"):
        try:
            try:
                r = jev.classify_field(label, near, rect, use_llm=use_llm)
            except TypeError:
                r = jev.classify_field(label, near, rect)
            if isinstance(r, dict) and r.get("type") in FIELD_TYPES:
                return {"type": r["type"], "confidence": float(r.get("confidence") or 0),
                        "referee": "jev:" + str(r.get("referee", "rules"))}
        except Exception:
            pass
    return local_classify(label, near, rect)


# ---------------------------------------------------------------------------
# Field detection
# ---------------------------------------------------------------------------


def _page_words(pdf_path):
    try:
        import pdfplumber
    except ImportError:
        return {}
    out = {}
    with pdfplumber.open(str(pdf_path)) as pdf:
        for n, page in enumerate(pdf.pages, 1):
            try:
                out[n] = {"words": page.extract_words(keep_blank_chars=False),
                          "w": float(page.width), "h": float(page.height)}
            except Exception:
                out[n] = {"words": [], "w": float(page.width), "h": float(page.height)}
    return out


def _label_near(words, ph, rect, side="left"):
    """(label, near_text) from the words on the field's line."""
    top, bottom = ph - rect[3], ph - rect[1]
    line = [w for w in words if (w["top"] + w["bottom"]) / 2 >= top - 3
            and (w["top"] + w["bottom"]) / 2 <= bottom + 3]
    line.sort(key=lambda w: w["x0"])
    near = " ".join(w["text"] for w in line)
    run = []
    if side == "left":
        left = [w for w in line if w["x1"] <= rect[0] + 2]
        edge = rect[0]
        for w in reversed(left):
            if edge - w["x1"] > 14 and run:
                break
            if render_blank(w["text"]):
                break
            run.insert(0, w)
            edge = w["x0"]
            if len(run) >= 7:
                break
    else:
        right = [w for w in line if w["x0"] >= rect[2] - 2]
        edge = rect[2]
        for w in right:
            if w["x0"] - edge > 14 and run:
                break
            run.append(w)
            edge = w["x1"]
            if len(run) >= 7:
                break
    label = " ".join(w["text"] for w in run).strip().rstrip(":").strip()
    return label, near


def render_blank(text):
    return bool(re.match(r"^\$?[_.]{3,}$", text or ""))


def _widgets(pdf_path):
    from pypdf import PdfReader
    reader = PdfReader(str(pdf_path))
    out = []
    for pno, page in enumerate(reader.pages, 1):
        annots = page.get("/Annots")
        if not annots:
            continue
        for ref in annots.get_object():
            a = ref.get_object()
            if a.get("/Subtype") != "/Widget":
                continue
            parent = a.get("/Parent")
            parent = parent.get_object() if parent is not None else {}
            name = a.get("/T") or parent.get("/T")
            if not name or not a.get("/Rect"):
                continue
            ft = a.get("/FT") or parent.get("/FT")
            ff = int(a.get("/Ff", parent.get("/Ff", 0)) or 0)
            if ft == "/Btn" and ff & (1 << 16):  # push button
                continue
            r = [float(v) for v in a["/Rect"]]
            rect = [min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3])]
            on_states = []
            ap = a.get("/AP")
            if ap and ap.get_object().get("/N") is not None:
                normal = ap.get_object()["/N"].get_object()
                if hasattr(normal, "keys"):
                    on_states = [str(k) for k in normal.keys() if str(k) != "/Off"]
            value = a.get("/V", parent.get("/V", ""))
            out.append({"name": str(name), "page": pno, "rect": rect,
                        "kind": {"/Btn": "checkbox", "/Sig": "signature"}.get(ft, "text"),
                        "tooltip": str(a.get("/TU") or parent.get("/TU") or ""),
                        "required": bool(ff & 2), "on_states": on_states,
                        "value": str(value or "")})
    return out


def _flat_fields(pdf_path, pages_with_widgets, words_by_page):
    det = optional("nff_detect_fields")
    if det is None:
        return []
    try:
        found = det.detect_visual_fields(str(pdf_path))
    except Exception:
        return []
    out = []
    for f in found:
        page = int(f.get("page", 1))
        pos = f.get("position")
        if page in pages_with_widgets or not pos:
            continue
        info = words_by_page.get(page, {"words": [], "w": 612.0, "h": 792.0})
        ph, pw = info["h"], info["w"]
        x, y = float(pos["x1"]), float(pos["y1"])
        right, prefix = None, None
        for w in info["words"]:
            if abs((ph - w["bottom"] + 1) - y) > 2.5:
                continue
            if render_blank(w["text"]) and -8 <= x - w["x0"] <= 8:
                right = w["x1"]
                prefix = "$" if w["text"].startswith("$") else None
                break
        if right is None:
            nxt = [w["x0"] for w in info["words"]
                   if abs((ph - w["bottom"] + 1) - y) <= 2.5 and w["x0"] > x + 4]
            right = (min(nxt) - 6) if nxt else pw - 36
        right = max(right, x + 40)
        out.append({"name": f["field_name"], "label": f.get("field_name_raw") or f["field_name"],
                    "page": page, "rect": [round(x, 2), round(y - 2, 2), round(right, 2), round(y + 14, 2)],
                    "method": f.get("detection_method", "visual"), "prefix": prefix})
    return out


def detect_fields(pdf_path):
    """[{name, label, page, rect, origin, acro_kind?, ...}] for AcroForm + flat pages."""
    words = _page_words(pdf_path)
    det = optional("nff_detect_fields")
    acro_meta = {}
    if det is not None:
        try:
            for f in det.detect_acroform_fields(str(pdf_path)):
                acro_meta[f["field_name"].split(".")[-1]] = f
        except Exception:
            pass
    fields = []
    widget_pages = set()
    for w in _widgets(pdf_path):
        widget_pages.add(w["page"])
        info = words.get(w["page"], {"words": [], "h": 792.0})
        side = "right" if w["kind"] == "checkbox" else "left"
        label, near = _label_near(info["words"], info["h"], w["rect"], side)
        if not label and side == "right":
            label, near = _label_near(info["words"], info["h"], w["rect"], "left")
        label = w["tooltip"] or label or w["name"]
        meta = acro_meta.get(w["name"], {})
        fields.append({"name": w["name"], "label": label, "near": near, "page": w["page"],
                       "rect": [round(v, 2) for v in w["rect"]], "origin": "acroform",
                       "acro_kind": w["kind"], "on_states": w["on_states"],
                       "required": w["required"] or bool(meta.get("required")),
                       "initial_value": w["value"]})
    for f in _flat_fields(pdf_path, widget_pages, words):
        info = words.get(f["page"], {"words": [], "h": 792.0})
        _, near = _label_near(info["words"], info["h"], f["rect"], "left")
        f.update(origin="visual", near=near, required=False)
        fields.append(f)
    return fields


# ---------------------------------------------------------------------------
# Answers + field state
# ---------------------------------------------------------------------------

CHECK_YES = {"yes", "true", "on", "x", "1", "checked", "✓"}


def _checkbox_value(value, on_states):
    v = str(value or "")
    if v in on_states or v.lower() in CHECK_YES or (v.startswith("/") and v != "/Off" and not on_states):
        return "on"
    return ""


RETIRED_VALUES = ("405 S Elm St Ste 203", "405 S Elm St")


def resolve_canonical(rows, retired=RETIRED_VALUES):
    """Group canonical candidates per field and settle each with nff_canonical.determine().

    rows: canonical rows ({field_name, field_value, source_kind, source_title, source_ref,
    source_date, category, status}) or a plain {field: value} dict (already settled).
    Returns (values, held): values autofill; held = {field: decision} for conflicts, missing,
    stale or Tier 3 (confidential) answers, which must not autofill (shown as review).
    """
    if isinstance(rows, dict):
        return {k: v for k, v in rows.items() if v not in (None, "")}, {}
    can = optional("nff_canonical")
    groups, cats = {}, {}
    for r in rows or []:
        if str(r.get("status", "")).lower() in ("rejected", "retired", "superseded"):
            continue
        name = r.get("field_name")
        if not name or r.get("field_value") in (None, ""):
            continue
        groups.setdefault(name, []).append(
            {k: r.get(k) for k in ("field_value", "source_kind", "source_title", "source_ref", "source_date")})
        cats.setdefault(name, (r.get("category") or "other").lower())
    values, held = {}, {}
    for name, cands in groups.items():
        if can is None:
            distinct = {str(c["field_value"]).strip().lower() for c in cands}
            if len(distinct) == 1:
                values[name] = cands[0]["field_value"]
            else:
                held[name] = {"status": "conflict", "basis": "sources disagree - owner decides"}
            continue
        d = can.determine(name, cands, cats[name], retired)
        if d["status"] == "canonical" and d.get("jev_tier", 0) == 0 and d.get("value") not in (None, ""):
            values[name] = d["value"]
        else:
            held[name] = {"status": d["status"], "basis": d.get("basis", ""), "jev_tier": d.get("jev_tier")}
    return values, held


def build_fields(pdf_path, form_type=None, kb=None, canonical=None, use_llm=False, held=None):
    """Detect, answer (Tier 1 enforced) and classify. Returns (fields, form_type, manual_notes).

    held: {kb_field: decision} canonical answers that need the owner (conflict, missing,
    stale, Tier 3). Those fields are never autofilled; they are shown in the review state.
    """
    import nff_workflow_registry as reg
    held = held or {}
    detected = detect_fields(pdf_path)
    if not form_type:
        wf = reg.match_workflow(Path(pdf_path).name)
        form_type = wf["form_type"] if wf else None
    labels = [{"field_name": d["name"], "field_name_raw": d["label"], "page": d["page"]}
              for d in detected]
    try:
        result = reg.build_answers(form_type, kb or {}, labels, canonical)
    except (KeyError, ValueError):
        result = reg.build_label_answers(form_type, labels, kb or {}, canonical)
    answers = {}
    for a in result.get("answers", []):
        answers.setdefault(a["field_name"], a)
    manual = {m.get("field_name"): m for m in result.get("manual", []) if m.get("field_name")}
    notes = [m["reason"] for m in result.get("manual", []) if not m.get("field_name")]

    fields = []
    for n, d in enumerate(detected, 1):
        c = classify(d["label"], d.get("near", ""), d["rect"], d.get("acro_kind"), use_llm)
        ftype = c["type"]
        ans = answers.get(d["name"])
        value, source, conf, reason, kb_field = "", None, 0.0, "", None
        if ans is not None:
            kb_field, source = ans.get("kb_field"), ans.get("source")
            if ans.get("clear"):
                value, conf, reason = "", 0.99, "Tier 1: leave blank"
            else:
                value = str(ans.get("field_value", ""))
                conf = {"tier1": 0.99, "canonical": 0.97, "derived": 0.96}.get(
                    source, float(ans.get("confidence", 95)) / 100.0)
        elif d["name"] in manual:
            m = manual[d["name"]]
            kb_field, reason = m.get("kb_field"), m.get("reason", "")
        if ftype in NEVER_AUTOFILL_TYPES and value:
            value, source, conf = "", None, 0.0
            reason = ("price or money commitment - owner enters it" if ftype == "currency"
                      else "signature - Tier 3 signature step only")
        hold = held.get(kb_field) if kb_field else None
        if hold and source != "tier1":
            value, source, conf = "", "canonical_" + str(hold.get("status")), 0.0
            reason = f"canonical answer {hold.get('status')}: {hold.get('basis', '')} - owner reviews"
        initial = str(d.get("initial_value") or "")
        if not value and not (ans is not None and ans.get("clear")) and initial and ftype != "signature":
            # The PDF already carries this value: keep it so flattening never drops it.
            value = initial if d.get("acro_kind") != "checkbox" else _checkbox_value(initial, d.get("on_states", []))
            if value:
                source, conf = "pdf_existing", 0.9
                reason = "value already in the PDF - review it"
        if d.get("acro_kind") == "checkbox":
            value = _checkbox_value(value, d.get("on_states", []))
        elif ftype == "phone":
            value = format_phone(value)
        elif ftype == "date":
            value = format_date(value)
        if hold and source != "tier1" and source != "pdf_existing":
            state = "review"
        elif source == "pdf_existing":
            state = "review"
        elif ans is not None and (value or ans.get("clear")):
            state = "auto" if conf >= 0.95 else "review"
        else:
            state = "manual"
            if not reason:
                reason = "no KB match"
        fields.append({
            "id": f"f{n}", "name": d["name"], "label": d["label"], "page": d["page"],
            "rect": d["rect"], "type": ftype, "type_confidence": round(c["confidence"], 2),
            "type_referee": c.get("referee"), "value": value, "auto_value": value,
            "source": source, "kb_field": kb_field, "confidence": round(conf, 2),
            "state": state, "approved": False, "reason": reason, "origin": d["origin"],
            "acro_kind": d.get("acro_kind"), "required": bool(d.get("required")),
            "on_state": (d.get("on_states") or [""])[0] if d.get("acro_kind") == "checkbox" else None,
            "prefix": d.get("prefix"),
            "style": dict(DEFAULT_STYLE), "user_entered": False, "image_file": None,
        })
    # Fixed-position answers (e.g. CIQ overlay_map) with no detected field.
    known = {f["name"] for f in fields}
    for a in result.get("answers", []):
        if a["field_name"] in known or not a.get("position") or a.get("clear"):
            continue
        x, y = float(a["position"]["x1"]), float(a["position"]["y1"])
        n = len(fields) + 1
        fields.append({
            "id": f"f{n}", "name": a["field_name"], "label": a["field_name"].replace("_", " ").title(),
            "page": int(a.get("page", 1)), "rect": [x, y - 2, x + 260, y + 14], "type": "text_word",
            "type_confidence": 0.9, "type_referee": "workflow", "value": str(a.get("field_value", "")),
            "auto_value": str(a.get("field_value", "")), "source": a.get("source"),
            "kb_field": a.get("kb_field"), "confidence": 0.99 if a.get("source") == "tier1" else 0.95,
            "state": "auto", "approved": False, "reason": "", "origin": "workflow", "acro_kind": None,
            "required": False, "style": dict(DEFAULT_STYLE), "user_entered": False, "image_file": None,
        })
    fields.sort(key=lambda f: (f["page"], -round(f["rect"][3] / 4), f["rect"][0]))
    return fields, form_type, notes


def normalize_value(ftype, value):
    if value is None:
        return ""
    v = str(value)
    if ftype == "currency":
        return format_currency(v)
    if ftype == "phone":
        return format_phone(v)
    if ftype == "date":
        return format_date(v)
    if ftype in ("checkmark", "x_mark"):
        return "on" if v.strip().lower() in CHECK_YES else ""
    if ftype == "initials":
        return v.strip().upper()[:6]
    if ftype in ("text_paragraph", "address"):
        return v.replace("\r\n", "\n").strip()
    return v.strip()


def snap_line(x1, y1, x2, y2):
    """Snap a stroke to horizontal, vertical or 45 degrees, keeping its start point."""
    import math
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return x1, y1, x2, y2
    raw = math.atan2(dy, dx)
    angle = round(raw / (math.pi / 4)) * (math.pi / 4)
    proj = length * abs(math.cos(raw - angle))
    nx, ny = x1 + proj * math.cos(angle), y1 + proj * math.sin(angle)
    return round(x1, 2), round(y1, 2), round(nx, 2), round(ny, 2)


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


def _safe_stem(name):
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem).strip("._-")
    return (s or "form")[:60]


class Session:
    def __init__(self, sdir, state):
        self.dir = Path(sdir)
        self.state = state
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(24)

    # -- paths
    @property
    def home(self):
        return Path(self.state["nff_home"])

    @property
    def exports(self):
        p = self.home / "exports"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def source_pdf(self):
        return self.dir / "source.pdf"

    @classmethod
    def create(cls, pdf, form_type=None, kb=None, canonical=None, home=None, use_llm=False):
        home = Path(home) if home else nff_home()
        sid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        sdir = home / "sessions" / sid
        (sdir / "pages").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf, sdir / "source.pdf")
        if kb is None or canonical is None:
            db, conn = db_conn()
            if conn is not None:
                try:
                    if kb is None:
                        kb = db.kb_values(conn)
                    if canonical is None:
                        canonical = db.canonical_rows(conn)
                except Exception:
                    pass
                finally:
                    conn.close()
        canonical, held = resolve_canonical(canonical or {})
        fields, form_type, notes = build_fields(sdir / "source.pdf", form_type, kb or {}, canonical,
                                                use_llm, held=held)
        sizes = render.page_sizes(sdir / "source.pdf")
        render.render_pages(sdir / "source.pdf", sdir / "pages", scale=2.0)
        state = {
            "session_id": sid, "nff_home": str(home), "session_dir": str(sdir),
            "form_name": Path(pdf).name, "form_type": form_type, "created_at": now_iso(),
            "pages": [{"n": i + 1, **s} for i, s in enumerate(sizes)],
            "fields": fields, "highlights": [], "notes": notes,
            "canonical": canonical or {}, "canonical_held": held, "signature_approval": None, "review": None,
            "exports": [], "progress": [], "completed": False,
            "default_signer": _default_signer(),
        }
        s = cls(sdir, state)
        s.save()
        s.audit("session_created", fields=len(fields), form_type=form_type)
        return s

    @classmethod
    def load(cls, sid, home=None):
        home = Path(home) if home else nff_home()
        if not SAFE_FILE_RE.match(sid):
            raise ValueError("bad session id")
        sdir = home / "sessions" / sid
        state = json.loads((sdir / "state.json").read_text())
        return cls(sdir, state)

    def save(self):
        with self.lock:
            tmp = self.dir / "state.json.tmp"
            tmp.write_text(json.dumps(self.state, indent=2, default=str))
            os.replace(tmp, self.dir / "state.json")

    def audit(self, event, **kw):
        with open(self.dir / "audit.jsonl", "a") as fh:
            fh.write(json.dumps({"at": now_iso(), "event": event, **kw}, default=str) + "\n")

    # -- lookups
    def field(self, fid):
        for f in self.state["fields"]:
            if f["id"] == str(fid):
                return f
        return None

    def progress(self):
        fields = self.state["fields"]
        done = sum(1 for f in fields if f["approved"])
        return {"approved": done, "total": len(fields),
                "completed": bool(fields) and done == len(fields)}

    def digest(self):
        """Hash of everything that is drawn on the document."""
        items = []
        for f in self.state["fields"]:
            img = ""
            if f.get("image_file"):
                p = self.dir / f["image_file"]
                img = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ""
            items.append([f["id"], f["type"], f["value"], img, f["rect"], f.get("style")])
        items.append(self.state["highlights"])
        return hashlib.sha256(json.dumps(items, sort_keys=True, default=str).encode()).hexdigest()

    def touch(self):
        """Call after any change: voids a signature approval that no longer matches."""
        ap = self.state.get("signature_approval")
        if ap and ap.get("state_digest") != self.digest():
            self.audit("signature_approval_voided", request_id=ap.get("request_id"),
                       reason="document changed after approval")
            self.state["signature_approval"] = None
            self.state["approval_voided"] = True
        prog = self.progress()
        self.state["completed"] = prog["completed"]
        self.save()

    def public_state(self):
        st = self.state
        fields = []
        for f in st["fields"]:
            g = {k: v for k, v in f.items() if k not in ("image",)}
            g["has_image"] = bool(f.get("image_file"))
            fields.append(g)
        ap = st.get("signature_approval")
        return {
            "session_id": st["session_id"], "form_name": st["form_name"], "form_type": st["form_type"],
            "pages": [{**p, "img": f"/api/page/{p['n']}.png"} for p in st["pages"]],
            "fields": fields, "highlights": st["highlights"], "notes": st.get("notes", []),
            "field_types": list(FIELD_TYPES), "progress": self.progress(),
            "confidence": (st.get("review") or {}).get("confidence"),
            "review": st.get("review"),
            "flags": {"completed": self.progress()["completed"],
                      "exported": bool(st["exports"]),
                      "last_export": st["exports"][-1] if st["exports"] else None,
                      "signature_approved": bool(ap),
                      "approval_voided": bool(st.get("approval_voided")),
                      "nff_db": optional("nff_db") is not None,
                      "nff_jev": optional("nff_jev") is not None},
            "signature_approval": ({k: ap.get(k) for k in ("signer", "circumstance", "request_id",
                                                           "approved_at")} if ap else None),
            "default_signer": st.get("default_signer") or _default_signer(),
            "signers": _signers(),
            "default_style": DEFAULT_STYLE, "highlight_default": HIGHLIGHT_DEFAULT,
        }

    # -- export helpers
    def _drawable(self):
        return [dict(f) for f in self.state["fields"]]

    def write_pdf(self, out_path, include_signatures=False, src=None, only=None):
        fields = self._drawable()
        if only is not None:
            fields = [f for f in fields if f["type"] in only]
        return render.export_pdf(src or self.source_pdf, fields,
                                 [] if only is not None else self.state["highlights"],
                                 out_path, include_signatures=include_signatures, image_dir=self.dir)

    def signed_fields(self):
        return [f for f in self.state["fields"]
                if f["type"] in SIGNED_TYPES and (str(f.get("value") or "").strip() or f.get("image_file"))]


def _default_signer():
    sig = optional("nff_signatures")
    try:
        return sig.default_signer()
    except Exception:
        return "Alison Hopkins"


def _signers():
    sig = optional("nff_signatures")
    try:
        return [{"name": s["full_name"], "title": s["title"],
                 "requires_circumstance": s["requires_circumstance"],
                 "initials": initials_of(s["full_name"])} for s in sig.AUTHORIZED_SIGNERS.values()]
    except Exception:
        return [{"name": "Alison Hopkins", "title": "Owner", "requires_circumstance": False,
                 "initials": "AH"}]


# ---------------------------------------------------------------------------
# API actions (pure functions over a Session; the HTTP layer only routes)
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


def _save_image(s, f, data):
    if not data:
        return
    if not isinstance(data, str) or not data.startswith("data:image/png;base64,"):
        raise ApiError(400, "image must be a PNG data URL")
    raw = base64.b64decode(data.split(",", 1)[1], validate=False)
    if len(raw) > MAX_IMAGE or not raw.startswith(b"\x89PNG"):
        raise ApiError(400, "image too large or not a PNG")
    name = f"sig_{f['id']}.png"
    (s.dir / name).write_bytes(raw)
    f["image_file"] = name


def api_field(s, body):
    with s.lock:
        f = s.field(body.get("id"))
        if f is None:
            raise ApiError(404, "unknown field")
        old = f["value"]
        if "value" in body:
            f["value"] = normalize_value(f["type"], body.get("value"))
        if f["type"] in SIGNED_TYPES:
            if body.get("clear_image"):
                f["image_file"] = None
            if body.get("image"):
                _save_image(s, f, body["image"])
        style = body.get("style")
        if isinstance(style, dict):
            if "color" in style and re.fullmatch(r"#[0-9a-fA-F]{6}", str(style["color"])):
                f["style"]["color"] = style["color"].upper()
            if "size" in style:
                try:
                    f["style"]["size"] = max(4.0, min(48.0, float(style["size"])))
                except (TypeError, ValueError):
                    raise ApiError(400, "bad font size")
        if "type" in body and body["type"] in FIELD_TYPES and f["origin"] == "user":
            f["type"] = body["type"]
            f["value"] = normalize_value(f["type"], f["value"])
        if body.get("approve"):
            f["approved"] = True
        elif body.get("approve") is False:
            f["approved"] = False
        changed = f["value"] != old
        ask = (changed and f["value"] != f["auto_value"] and f["value"] != ""
               and f["type"] not in NO_SAVE_TYPES)
        if changed and f["value"] != f["auto_value"]:
            f["user_entered"] = True
        if ask:
            f["pending_save"] = {"old": f["auto_value"], "new": f["value"],
                                 "action": "manual_edit" if f["auto_value"] else "manual_entry"}
        s.touch()
        return {"ok": True, "field": f, "ask_save": ask, "progress": s.progress(),
                "signature_approved": bool(s.state.get("signature_approval"))}


def _queue_sheet_change(s, row):
    q = s.home / "sheet_push_queue.jsonl"
    q.parent.mkdir(parents=True, exist_ok=True)
    with open(q, "a") as fh:
        fh.write(json.dumps(row) + "\n")
    return q


def api_save_decision(s, body):
    decision = body.get("decision")
    if decision not in ("saved", "ignored"):
        raise ApiError(400, "decision must be saved or ignored")
    with s.lock:
        f = s.field(body.get("id"))
        if f is None:
            raise ApiError(404, "unknown field")
        pend = f.get("pending_save") or {"old": f["auto_value"], "new": f["value"],
                                         "action": "manual_edit" if f["auto_value"] else "manual_entry"}
        row = {"logged_at": now_iso(), "field_name": f.get("kb_field") or f["name"],
               "form_field_title": f["label"], "form_name": s.state["form_name"],
               "old_value": pend["old"], "new_value": pend["new"], "action": pend["action"],
               "decision": decision, "user": os.environ.get("NFF_USER", ""),
               "session_id": s.state["session_id"], "notes": "NFF GUI manual edit"}
        where = "change_log.jsonl"
        db, conn = db_conn()
        if conn is not None:
            try:
                db.record_change(conn, **row)
                where = "nff_db.change_log"
            except Exception:
                conn = None
            finally:
                try:
                    db and conn and conn.close()
                except Exception:
                    pass
        if where == "change_log.jsonl":
            with open(s.dir / "change_log.jsonl", "a") as fh:
                fh.write(json.dumps(row) + "\n")
        queued = None
        if decision == "saved":
            queued = str(_queue_sheet_change(s, row))
        f.pop("pending_save", None)
        f.setdefault("decisions", []).append({"decision": decision, "at": row["logged_at"]})
        s.save()
        s.audit("save_decision", field=f["id"], decision=decision, recorded_in=where)
        return {"ok": True, "decision": decision, "recorded_in": where, "sheet_queue": queued}


def api_field_add(s, body):
    try:
        page = int(body.get("page"))
        rect = [float(v) for v in body.get("rect")]
    except (TypeError, ValueError):
        raise ApiError(400, "page and rect [x1,y1,x2,y2] required")
    if not 1 <= page <= len(s.state["pages"]) or len(rect) != 4:
        raise ApiError(400, "bad page or rect")
    ftype = body.get("type") if body.get("type") in FIELD_TYPES else "text_word"
    rect = [min(rect[0], rect[2]), min(rect[1], rect[3]), max(rect[0], rect[2]), max(rect[1], rect[3])]
    if rect[2] - rect[0] < 4 or rect[3] - rect[1] < 4:
        raise ApiError(400, "rectangle too small")
    with s.lock:
        n = 1 + max([int(f["id"][1:]) for f in s.state["fields"] if f["id"][1:].isdigit()] or [0])
        label = str(body.get("label") or "").strip()[:80] or f"Added {ftype.replace('_', ' ')}"
        f = {"id": f"f{n}", "name": f"user_field_{n}", "label": label, "page": page,
             "rect": [round(v, 2) for v in rect], "type": ftype, "type_confidence": 1.0,
             "type_referee": "user", "value": "", "auto_value": "", "source": "user",
             "kb_field": None, "confidence": 0.0, "state": "user", "approved": False,
             "reason": "added by user (missed field)", "origin": "user", "acro_kind": None,
             "required": False, "style": dict(DEFAULT_STYLE), "user_entered": True, "image_file": None}
        s.state["fields"].append(f)
        s.touch()
        s.audit("field_added", field=f["id"], page=page, type=ftype)
        return {"ok": True, "field": f, "progress": s.progress()}


def api_field_delete(s, body):
    with s.lock:
        f = s.field(body.get("id"))
        if f is None or f["origin"] != "user":
            raise ApiError(400, "only user-added fields can be removed")
        s.state["fields"].remove(f)
        s.touch()
        return {"ok": True, "progress": s.progress()}


def api_highlight(s, body):
    try:
        page = int(body.get("page"))
        x1, y1, x2, y2 = (float(body[k]) for k in ("x1", "y1", "x2", "y2"))
    except (TypeError, ValueError, KeyError):
        raise ApiError(400, "page, x1, y1, x2, y2 required")
    if not 1 <= page <= len(s.state["pages"]):
        raise ApiError(400, "bad page")
    color = str(body.get("color") or HIGHLIGHT_DEFAULT["color"])
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        color = HIGHLIGHT_DEFAULT["color"]
    x1, y1, x2, y2 = snap_line(x1, y1, x2, y2)
    with s.lock:
        hl = {"id": "h" + uuid.uuid4().hex[:8], "page": page, "x1": x1, "y1": y1, "x2": x2, "y2": y2,
              "color": color.upper(), "opacity": HIGHLIGHT_DEFAULT["opacity"],
              "width": max(2.0, min(30.0, float(body.get("width") or HIGHLIGHT_DEFAULT["width"])))}
        s.state["highlights"].append(hl)
        s.touch()
        return {"ok": True, "highlight": hl}


def api_highlight_update(s, body, delete=False):
    with s.lock:
        hl = next((h for h in s.state["highlights"] if h["id"] == body.get("id")), None)
        if hl is None:
            raise ApiError(404, "unknown highlight")
        if delete:
            s.state["highlights"].remove(hl)
        elif re.fullmatch(r"#[0-9a-fA-F]{6}", str(body.get("color", ""))):
            hl["color"] = body["color"].upper()
        s.touch()
        return {"ok": True, "highlight": None if delete else hl}


def api_page(s, body, approve=True):
    try:
        page = int(body.get("page"))
    except (TypeError, ValueError):
        raise ApiError(400, "page required")
    if not 1 <= page <= len(s.state["pages"]):
        raise ApiError(400, "bad page")
    with s.lock:
        n = 0
        for f in s.state["fields"]:
            if f["page"] == page:
                f["approved"] = approve
                n += 1
        s.touch()
        s.audit("page_approved" if approve else "page_reopened", page=page, fields=n)
        return {"ok": True, "page": page, "fields": n, "progress": s.progress()}


def _review_fields(s):
    ap = s.state.get("signature_approval") or {}
    out = []
    for f in s.state["fields"]:
        g = {"id": f["id"], "field_name": f["name"], "kb_field": f.get("kb_field") or f["name"],
             "name": f["name"], "label": f["label"], "type": f["type"], "value": f["value"],
             "required": f.get("required", False), "user_entered": f.get("user_entered", False),
             "source": "user" if f.get("user_entered") else (f.get("source") or "manual")}
        if f["type"] in ("checkmark", "x_mark") and f.get("acro_kind") == "checkbox":
            g["value"] = (f.get("on_state") or "on") if f["value"] else ""
        if f["type"] == "signature" and f.get("image_file"):
            g["value"] = ap.get("signer") or "[drawn signature]"
        if f["type"] == "initials" and f.get("image_file") and not f["value"]:
            g["value"] = "[drawn initials]"
        out.append(g)
    return out


def _local_review(s):
    checks = []
    rx = {"date": (r"^\d{2}/\d{2}/\d{4}$", "date must be MM/DD/YYYY"),
          "phone": (r"^\(\d{3}\) \d{3}-\d{4}$|^\d{3}-\d{3}-\d{4}$", "phone must be (###) ###-####"),
          "email": (r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$", "invalid email address"),
          "currency": (r"^\(?\$\d{1,3}(,\d{3})*\.\d{2}\)?$", "currency must look like $1,234.00")}
    for f in s.state["fields"]:
        v = str(f["value"] or "").strip()
        if f.get("required") and not v:
            checks.append({"id": f"required.{f['id']}", "passed": False, "blocking": True,
                           "message": f"Required field '{f['label']}' is blank"})
        if v and f["type"] in rx and not re.match(rx[f["type"]][0], v):
            checks.append({"id": f"format.{f['id']}", "passed": False, "blocking": False,
                           "message": f"{f['label']}: {rx[f['type']][1]}"})
    return {"checks": checks, "issues": [c["message"] for c in checks],
            "confidence": None, "engine": "local"}


def api_review(s, body=None):
    with s.lock:
        jev = optional("nff_jev")
        ap = s.state.get("signature_approval")
        result = None
        if jev is not None and hasattr(jev, "review"):
            st = {"session_id": s.state["session_id"], "session_dir": str(s.dir),
                  "form_type": s.state["form_type"], "fields": _review_fields(s),
                  "signature_approval": ap, "approvals": [ap] if ap else [],
                  "canonical": s.state.get("canonical") or {},
                  "signer": ap.get("signer") if ap else None,
                  "document_path": ap.get("document_path") if ap else None}
            _, conn = db_conn()
            try:
                result = jev.review(st, conn)
                result["engine"] = "nff_jev"
            except Exception as e:
                result = _local_review(s)
                result["engine_error"] = f"nff_jev.review failed: {type(e).__name__}: {e}"
            finally:
                if conn is not None:
                    conn.close()
        else:
            result = _local_review(s)
        checks = result.get("checks") or []
        # Signature gate is ours too: never trust a missing approval.
        if s.signed_fields() and not ap:
            checks.append({"id": "signature.gate", "passed": False, "blocking": True,
                           "message": "Signature/initials need Tier 3 approval (Approve signature) "
                                      "before export"})
        issues = [{"message": c.get("message", c.get("id", "")), "blocking": bool(c.get("blocking")),
                   "advisory": bool(c.get("advisory"))}
                  for c in checks if not c.get("passed")]
        conf = result.get("confidence")
        if isinstance(conf, dict) and conf.get("score") is not None:
            sc, lo, hi = (round(100 * float(conf.get(k, 0))) for k in ("score", "low", "high"))
            confidence = {"available": True, "score": sc, "low": lo, "high": hi,
                          "text": f"Confidence {sc}% ({lo}–{hi}%)",
                          "drivers": conf.get("drivers", [])[:6]}
        else:
            confidence = {"available": False, "text": "Confidence unavailable (JEV layer not installed)"}
        blocking = [i for i in issues if i["blocking"]]
        prog = s.progress()
        review = {"at": now_iso(), "engine": result.get("engine"), "issues": issues,
                  "blocking": len(blocking), "confidence": confidence,
                  "completed": prog["completed"],
                  "can_export": prog["completed"] and not blocking,
                  "needs_signature_approval": bool(s.signed_fields()) and not ap,
                  "engine_error": result.get("engine_error"),
                  "advisories": result.get("advisories", [])}
        s.state["review"] = review
        s.save()
        s.audit("review", blocking=len(blocking), engine=review["engine"],
                confidence=confidence.get("text"))
        return review


def api_signature_approve(s, body):
    sig = optional("nff_signatures")
    if sig is None:
        raise ApiError(500, "nff_signatures unavailable")
    signer = str(body.get("signer") or sig.default_signer()).strip()
    circumstance = str(body.get("circumstance") or "").strip() or None
    if body.get("confirm") is not True:
        raise ApiError(400, "explicit confirmation required (confirm: true)")
    with s.lock:
        signed = s.signed_fields()
        if not signed:
            raise ApiError(400, "no signature or initials value to approve")
        v = sig.validate_signer(signer)
        if not v["authorized"]:
            s.audit("signature_rejected", signer=signer, reason="not authorized")
            raise ApiError(403, v["message"])
        full = v["signer"]["full_name"]
        for f in signed:
            if f["type"] == "signature" and not f.get("image_file"):
                typed = re.sub(r"\s+", " ", str(f["value"]).strip().lower())
                if typed not in (full.lower(), "/s/ " + full.lower()):
                    raise ApiError(400, f"Typed signature '{f['value']}' does not match signer {full}")
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        unsigned = s.dir / f"unsigned_final_{ts}.pdf"
        s.write_pdf(unsigned, include_signatures=False)
        req = sig.generate_approval_request(
            s.state["form_name"], s.state.get("form_type") or "general", full,
            [{"field_name": f["label"], "page": f["page"]} for f in signed],
            document_path=str(unsigned), circumstance=circumstance)
        if req.get("status") != "pending_approval":
            s.audit("signature_rejected", signer=full, reason=req.get("status"))
            raise ApiError(400, req.get("error") or "approval refused", status_code=req.get("status"))
        ar = req["approval_request"]
        approval = {"decision": "approve", "request_id": req["request_id"], "signer": full,
                    "circumstance": circumstance,
                    "approved_by": f"owner via NFF GUI (session {s.state['session_id']})",
                    "approved_at": now_iso(), "document_sha256": ar["document"]["sha256"],
                    "document_path": str(unsigned), "state_digest": s.digest(),
                    "fields": [f["id"] for f in signed]}
        sig.verify_approval(approval, str(unsigned), full)  # sanity: the gate accepts it
        s.state["signature_approval"] = approval
        s.state["approval_voided"] = False
        (s.dir / f"approval_{req['request_id']}.json").write_text(json.dumps(
            {"request": req, "approval": approval}, indent=2))
        s.save()
        s.audit("signature_approved", request_id=req["request_id"], signer=full,
                circumstance=circumstance, sha256=approval["document_sha256"])
        return {"ok": True, "status": "approved", "summary": ar["summary"],
                "approval": {k: approval[k] for k in ("request_id", "signer", "circumstance",
                                                      "approved_at", "document_sha256")}}


def _record_outcomes(s):
    db, conn = db_conn()
    if conn is None:
        return
    try:
        for f in s.state["fields"]:
            if f.get("kb_field") and f.get("auto_value"):
                db.record_outcome(conn, f["kb_field"], f.get("source") or "kb",
                                  f["value"] == f["auto_value"])
    except Exception:
        pass
    finally:
        conn.close()


def api_export(s, body):
    final = bool(body.get("final", True))
    if not final:
        return api_stop(s, body, download=True)
    with s.lock:
        if not s.progress()["completed"]:
            raise ApiError(409, "every field must be approved before the final export")
        review = api_review(s)
        if review["blocking"]:
            raise ApiError(409, "review has blocking issues", review=review)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"{_safe_stem(s.state['form_name'])}_completed_{ts}.pdf"
        out = s.exports / name
        signed = s.signed_fields()
        if signed:
            sig = optional("nff_signatures")
            ap = s.state.get("signature_approval")
            if not ap or ap.get("state_digest") != s.digest():
                raise ApiError(409, "signature approval missing or void; approve again")
            try:
                sig.verify_approval(ap, ap["document_path"], ap["signer"])
            except Exception as e:
                raise ApiError(409, f"signature gate closed: {e}")
            s.write_pdf(out, include_signatures=True, src=ap["document_path"], only=SIGNED_TYPES)
            record = sig.generate_signature_report(
                ap["request_id"], ap["signer"], name,
                [{"page": f["page"], "field": f["label"]} for f in signed],
                approved_by=ap["approved_by"], approval_timestamp=ap["approved_at"])
            if record:
                record["output_sha256"] = sig.document_digest(out)
                record["source_sha256"] = ap["document_sha256"]
                (s.dir / f"signature_record_{ap['request_id']}.json").write_text(json.dumps(record, indent=2))
            s.audit("signature_applied", request_id=ap["request_id"], output=str(out))
        else:
            s.write_pdf(out, include_signatures=False)
        entry = {"path": str(out), "file": name, "at": now_iso(), "final": True}
        s.state["exports"].append(entry)
        s.save()
        _record_outcomes(s)
        s.audit("exported", path=str(out))
    emit(f"NFF_EXPORT: {out}")
    return {"ok": True, **entry, "download": f"/api/download/{name}", "review": review}


def api_stop(s, body=None, download=True):
    with s.lock:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        stem = _safe_stem(s.state["form_name"])
        name = f"{stem}_DRAFT-progress_{ts}.pdf"
        out = s.exports / name
        s.write_pdf(out, include_signatures=False)
        s.save()
        state_copy = s.exports / f"{stem}_DRAFT-progress_{ts}.json"
        public = s.public_state()
        public["session_dir"] = str(s.dir)
        state_copy.write_text(json.dumps(public, indent=2, default=str))
        entry = {"path": str(out), "file": name, "state_path": str(state_copy), "at": now_iso()}
        s.state["progress"].append(entry)
        s.save()
        s.audit("progress_saved", path=str(out))
    emit(f"NFF_PROGRESS: {out}")
    return {"ok": True, **entry, "download": f"/api/download/{name}"}


SCAN_HELP = ("Drive scan needs live Google credentials, which this machine does not have. "
             "Ask Claude to run the scan with the Google Drive connector (it builds a manifest and "
             "runs nff_scan.py --from-manifest); then press Scan Drive again to see the proposals.")


def api_scan(s, body=None):
    scan = optional("nff_scan")
    db, conn = db_conn()
    if scan is None or conn is None:
        return {"ok": False, "status": "unavailable",
                "message": "Drive scan module is not installed. " + SCAN_HELP}
    try:
        days = int(scan.setting(conn, "scan_recent_days", 30))
        try:
            items = scan.collect_live(
                conn, days,
                scan.setting(conn, "company_docs_folder_id", scan.DEFAULT_COMPANY_FOLDER),
                scan.setting(conn, "closed_bids_folder_id", scan.DEFAULT_BIDS_FOLDER))
        except Exception as e:
            pending = len(db.list_proposals(conn, "pending"))
            return {"ok": False, "status": "no_credentials", "detail": str(e)[:200],
                    "message": SCAN_HELP, "pending": pending}
        new = scan.build_proposals(conn, items, days)
        added = db.add_proposals(conn, new)
        return {"ok": True, "status": "scanned", "documents": len(items), "new_proposals": added,
                "pending": len(db.list_proposals(conn, "pending"))}
    finally:
        conn.close()


def _fallback_proposals_file(s):
    return s.home / "proposals" / "pending.json"


def api_proposals(s):
    scan = optional("nff_scan")
    db, conn = db_conn()
    rows = []
    if conn is not None:
        try:
            for p in db.list_proposals(conn, "pending"):
                masked = scan is not None
                rows.append({"id": p["proposal_id"], "field_name": p["field_name"],
                             "current_value": scan.shown(p, "cur") if masked else p["current_value"],
                             "proposed_value": scan.shown(p, "new") if masked else p["proposed_value"],
                             "source": p.get("source_title") or p.get("source_ref") or "",
                             "category": p.get("category"),
                             "kind": scan.kind_of(p) if scan else "",
                             "tier3": bool(scan.is_tier3(p)) if scan else False})
        finally:
            conn.close()
    else:
        f = _fallback_proposals_file(s)
        if f.is_file():
            for p in json.loads(f.read_text()):
                if p.get("status", "pending") == "pending":
                    rows.append({"id": p.get("proposal_id"), "field_name": p.get("field_name"),
                                 "current_value": p.get("current_value", ""),
                                 "proposed_value": p.get("proposed_value", ""),
                                 "source": p.get("source_title", ""), "category": p.get("category"),
                                 "kind": "", "tier3": False})
    return {"ok": True, "proposals": rows}


def queue_sheet_append(s, scan, out):
    """Write approved proposal rows to the Sheet, or queue them for the agent. Never claims
    a Sheet write that did not happen."""
    masked = scan.mask_apply_output(out) if hasattr(scan, "mask_apply_output") else out
    rows = {"Canonical": masked["canonical"]["rows"], "KB": masked["kb"]["rows"]}
    count = len(rows["Canonical"]) + len(rows["KB"])
    result = {"status": "nothing_to_write", "rows": rows, "row_count": count,
              "change_log": "nff_db.change_log (action=approved_proposal, pending push)"}
    if not count:
        return result
    try:
        scan.append_live(out)
        result.update(status="appended_live", written=True)
        return result
    except Exception as e:  # no live credentials: queue for the Sheets connector
        result["live_error"] = str(e)[:200]
    qfile = s.home / "sheet_append_queue.jsonl"
    try:
        qfile.parent.mkdir(parents=True, exist_ok=True)
        with open(qfile, "a") as fh:
            fh.write(json.dumps({"queued_at": now_iso(), "session_id": s.state["session_id"],
                                 "canonical": out["canonical"], "kb": out["kb"],
                                 "applied": out["applied"]}) + "\n")
    except OSError as e:
        result.update(status="not_queued", written=False, error=f"could not queue rows: {e}")
        return result
    result.update(status="queued_for_agent", written=False, queue_file=str(qfile))
    emit(f"NFF_SHEET_APPEND: {qfile}")
    return result


def api_proposals_apply(s, body):
    ids = body.get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ApiError(400, "ids must be a list of proposal ids")
    if not ids:
        return {"ok": True, "applied": [], "skipped": []}
    scan = optional("nff_scan")
    db, conn = db_conn()
    if conn is not None and scan is not None:
        # Same code path as `nff_scan.py --apply`: the Canonical/KB rows go to the Sheet live
        # when credentials exist, else into the agent append queue; only then is each proposal
        # marked approved with a change_log row (action=approved_proposal, pushed_to_sheet=0).
        sheet = {"status": "nothing_to_write", "row_count": 0}

        def write_first(o):
            # Runs before anything is marked approved: if the rows can be neither written nor
            # queued, the proposals stay pending and the user can retry.
            sheet.update(queue_sheet_append(s, scan, o))
            if sheet["status"] == "not_queued":
                raise ApiError(500, sheet.get("error", "could not write or queue Sheet rows"))

        try:
            out = scan.apply_proposals(conn, ids, approve_tier3=False, user=os.environ.get("NFF_USER", ""),
                                       writer=write_first)
        finally:
            conn.close()
        s.audit("proposals_applied", applied=out["applied"], skipped=len(out["skipped"]),
                sheet=sheet["status"])
        return {"ok": True, "approved": out["applied"], "applied": out["applied"],
                "skipped": out["skipped"], "sheet": sheet}
    f = _fallback_proposals_file(s)
    if not f.is_file():
        raise ApiError(404, "no proposals")
    props = json.loads(f.read_text())
    applied = []
    for p in props:
        if p.get("proposal_id") in ids and p.get("status", "pending") == "pending":
            p["status"] = "approved"
            applied.append(p["proposal_id"])
            _queue_sheet_change(s, {"logged_at": now_iso(), "field_name": p.get("field_name"),
                                    "form_field_title": "", "form_name": "", "old_value": p.get("current_value", ""),
                                    "new_value": p.get("proposed_value", ""), "action": "approved_proposal",
                                    "decision": "saved", "user": os.environ.get("NFF_USER", ""),
                                    "session_id": s.state["session_id"], "notes": "GUI proposals checklist"})
    f.write_text(json.dumps(props, indent=2))
    return {"ok": True, "applied": applied, "skipped": [i for i in ids if i not in applied]}


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


class Handler(BaseHTTPRequestHandler):
    server_version = "NFFGUI/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep stdout clean for NFF_* lines
        if os.environ.get("NFF_GUI_DEBUG"):
            sys.stderr.write("nff_gui: " + (fmt % args) + "\n")

    @property
    def session(self):
        return self.server.session

    # -- responses
    def _headers(self, status, ctype, length, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _json(self, status, obj):
        data = json.dumps(obj, default=str).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(data))
        self.wfile.write(data)

    def _file(self, path, ctype, download_name=None):
        data = Path(path).read_bytes()
        extra = {"Content-Disposition": f'attachment; filename="{download_name}"'} if download_name else None
        self._headers(200, ctype, len(data), extra)
        self.wfile.write(data)

    def _error(self, status, message, **extra):
        self._json(status, {"ok": False, "error": message, **extra})

    # -- checks
    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0].strip("[]").lower()
        return host in ("127.0.0.1", "localhost", "::1")

    def _token_ok(self, query):
        given = self.headers.get("X-NFF-Token") or (query.get("token") or [""])[0]
        return bool(given) and hmac.compare_digest(given.encode(), self.session.token.encode())

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "bad Content-Length")
        if n > MAX_BODY:
            raise ApiError(413, "request too large")
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if n and ctype != "application/json":
            raise ApiError(415, "Content-Type must be application/json")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "invalid JSON")
        if not isinstance(body, dict):
            raise ApiError(400, "JSON object required")
        return body

    def _route(self, method):
        url = urlparse(self.path)
        path, query = unquote(url.path), parse_qs(url.query)
        if not self._host_ok():
            return self._error(403, "bad host")
        if method == "GET" and path in STATIC:
            name, ctype = STATIC[path]
            return self._file(ASSETS / name, ctype)
        if not path.startswith("/api/"):
            return self._error(404, "not found")
        if not self._token_ok(query):
            return self._error(401, "token required")
        if "\x00" in path or ".." in path.split("/") or "\\" in path:
            return self._error(400, "bad path")
        s = self.session
        try:
            if method == "GET":
                return self._get(s, path)
            body = self._body()
            routes = {
                "/api/field": lambda: api_field(s, body),
                "/api/field/save-decision": lambda: api_save_decision(s, body),
                "/api/field/add": lambda: api_field_add(s, body),
                "/api/field/delete": lambda: api_field_delete(s, body),
                "/api/highlight": lambda: api_highlight(s, body),
                "/api/highlight/update": lambda: api_highlight_update(s, body),
                "/api/highlight/delete": lambda: api_highlight_update(s, body, delete=True),
                "/api/page/approve": lambda: api_page(s, body, True),
                "/api/page/reopen": lambda: api_page(s, body, False),
                "/api/review": lambda: api_review(s, body),
                "/api/signature/approve": lambda: api_signature_approve(s, body),
                "/api/export": lambda: api_export(s, body),
                "/api/stop": lambda: api_stop(s, body),
                "/api/scan": lambda: api_scan(s, body),
                "/api/proposals/apply": lambda: api_proposals_apply(s, body),
            }
            fn = routes.get(path)
            if fn is None:
                return self._error(404, "unknown endpoint")
            return self._json(200, fn())
        except ApiError as e:
            return self._error(e.status, e.message, **e.extra)
        except Exception as e:  # noqa: BLE001
            return self._error(500, f"{type(e).__name__}: {e}")

    def _get(self, s, path):
        if path == "/api/session":
            return self._json(200, s.public_state())
        if path == "/api/proposals":
            return self._json(200, api_proposals(s))
        m = re.fullmatch(r"/api/page/(\d{1,4})\.png", path)
        if m:
            n = int(m.group(1))
            p = s.dir / "pages" / f"page-{n}.png"
            if not 1 <= n <= len(s.state["pages"]) or not p.is_file():
                return self._error(404, "no such page")
            return self._file(p, "image/png")
        m = re.fullmatch(r"/api/field-image/(f\d{1,5})\.png", path)
        if m:
            f = s.field(m.group(1))
            if not f or not f.get("image_file"):
                return self._error(404, "no image")
            return self._file(s.dir / f["image_file"], "image/png")
        m = re.fullmatch(r"/api/download/([^/]+)", path)
        if m:
            p = safe_download_path(s, m.group(1))
            if p is None:
                return self._error(404, "not found")
            ctype = "application/pdf" if p.suffix == ".pdf" else "application/json"
            return self._file(p, ctype, download_name=p.name)
        return self._error(404, "unknown endpoint")

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")


def safe_download_path(s, name):
    """Resolve a download name to a file inside the exports or session dir, else None."""
    if not SAFE_FILE_RE.match(name or "") or Path(name).suffix.lower() not in (".pdf", ".json"):
        return None
    for base in (s.exports, s.dir):
        base = base.resolve()
        p = (base / name).resolve()
        if p.parent == base and p.is_file():
            return p
    return None


def make_server(session, port=0):
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    httpd.session = session
    return httpd


def session_url(httpd):
    return f"http://127.0.0.1:{httpd.server_address[1]}/?token={httpd.session.token}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="NTXP Form Filler guided review GUI")
    ap.add_argument("--pdf", help="blank form PDF")
    ap.add_argument("--form-type", default=None)
    ap.add_argument("--kb-json", default=None, help="KB values {field_name: value}")
    ap.add_argument("--canonical-json", default=None, help="canonical answers {field_name: value}")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--resume", default=None, help="reopen an existing session id")
    ap.add_argument("--llm-classify", action="store_true",
                    help="let nff_jev use its local/Claude referee for ambiguous labels")
    a = ap.parse_args(argv)
    if a.resume:
        session = Session.load(a.resume)
    else:
        if not a.pdf or not Path(a.pdf).is_file():
            ap.error("--pdf FILE is required (or --resume SESSION_ID)")
        kb = json.loads(Path(a.kb_json).read_text()) if a.kb_json else None
        canonical = json.loads(Path(a.canonical_json).read_text()) if a.canonical_json else None
        session = Session.create(a.pdf, a.form_type, kb, canonical, use_llm=a.llm_classify)
    httpd = make_server(session, a.port)
    url = session_url(httpd)
    emit(f"NFF_SESSION: {session.dir}")
    emit(f"NFF_GUI: {url}")
    if not a.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
