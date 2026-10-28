#!/usr/bin/env python3
"""NTXP Form Fill live markup layer: vocabulary, NTXP markup rules, v3 import and PDF drawing.

Markups are stored like every other GUI overlay: absolute PDF user-space points with a
bottom-left origin (the page's media box). Callers that speak the ntxp-pdf-markups-and-redlines
v3 manifest (top-left origin, pdf_points / inches / normalized) are converted on the way in.

Visual rules follow ntxp-pdf-markups-and-redlines core/invariants.md:
  LOCK-01/02 redline red #FF0000 (legacy reds normalized), LOCK-05 text on red marks is red,
  LOCK-07 colored core opacity <= 0.80, LOCK-08 line-based marks carry a 0.30 halo at 3x width,
  LOCK-09 measured/evidence areas 0.30 fill / 0.80 perimeter, LOCK-10 bounding boxes bold and
  opaque, LOCK-12 revision clouds are one-sided outward scallops, LOCK-13 text is centered.
Stamps are attestations: they ride the same Tier 3 approval as signatures before a final export.
"""

import math
import re
import uuid
from datetime import datetime, timezone

REDLINE_RED = "#FF0000"
LEGACY_REDS = {"#D10000", "#CC0000", "#DC2626", "#F00", "RED"}
KINDS = ("cloud", "rectangle", "ellipse", "arrow", "line", "polyline", "ink", "text", "area", "stamp")
LINE_BASED = {"cloud", "arrow", "line", "polyline", "ink"}
RECT_KINDS = {"cloud", "rectangle", "ellipse", "text", "stamp"}
SEGMENT_KINDS = {"arrow", "line"}
POINT_KINDS = {"polyline", "ink", "area"}
STAMP_STATUSES = ("APPROVED", "APPROVED AS NOTED", "REVISE AND RESUBMIT", "REJECTED",
                  "FOR RECORD ONLY", "NOT REVIEWED", "VOID")
MAX_CORE_OPACITY = 0.80
HALO_OPACITY = 0.30
CLOUD_DEPTH = 5.0
CLOUD_SEGMENT = 28.0
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_POINTS = 4000

# ntxp-pdf-markups-and-redlines v3 kinds -> live kinds
V3_KINDS = {
    "cloud": "cloud", "revision_cloud": "cloud",
    "arrow": "arrow", "leader": "arrow",
    "line": "line", "dimension": "line",
    "polyline": "polyline", "route": "polyline",
    "bounding_box": "rectangle", "box": "rectangle", "rectangle": "rectangle", "rect": "rectangle",
    "ellipse": "ellipse", "circle": "ellipse",
    "highlight_polygon": "area", "area_measure": "area", "area": "area", "polygon": "area",
    "text": "text", "callout": "text", "note": "text", "label": "text",
    "stamp": "stamp",
    "ink": "ink", "freehand": "ink", "finger": "ink",
}


class MarkupError(ValueError):
    pass


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def color_of(value, default=REDLINE_RED):
    """LOCK-02: legacy reds normalize to the single redline red."""
    text = str(value or "").strip()
    if not text:
        return default
    if text.upper() in LEGACY_REDS:
        return REDLINE_RED
    if HEX.match(text):
        return text.upper()
    raise MarkupError(f"color must be #RRGGBB, got {text!r}")


def _num(v, what):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise MarkupError(f"{what} must be a number")
    if not math.isfinite(f):
        raise MarkupError(f"{what} must be finite")
    return f


def _pt(p, what):
    if not isinstance(p, (list, tuple)) or len(p) != 2:
        raise MarkupError(f"{what} must be [x, y]")
    return [_num(p[0], what), _num(p[1], what)]


class Frame:
    """Converts caller coordinates into absolute bottom-left PDF points for one page."""

    def __init__(self, page, origin="top-left", unit="pdf_points"):
        self.ox, self.oy = float(page.get("ox", 0) or 0), float(page.get("oy", 0) or 0)
        self.w, self.h = float(page["w"]), float(page["h"])
        if origin not in ("top-left", "bottom-left"):
            raise MarkupError("origin must be top-left or bottom-left")
        if unit not in ("pdf_points", "inches", "normalized"):
            raise MarkupError("coordinate_mode must be pdf_points, inches or normalized")
        self.origin, self.unit = origin, unit

    def point(self, p, what="point"):
        x, y = _pt(p, what)
        if self.unit == "inches":
            x, y = x * 72.0, y * 72.0
        elif self.unit == "normalized":
            x, y = x * self.w, y * self.h
        if self.origin == "top-left":
            return [round(self.ox + x, 2), round(self.oy + self.h - y, 2)]
        return [round(x, 2), round(y, 2)]

    def rect(self, r, what="rect"):
        if not isinstance(r, (list, tuple)) or len(r) != 4:
            raise MarkupError(f"{what} must be [x0, y0, x1, y1]")
        a, b = self.point(r[:2], what), self.point(r[2:], what)
        return [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])]

    def clamp(self, x, y):
        return [min(max(x, self.ox), self.ox + self.w), min(max(y, self.oy), self.oy + self.h)]


def normalize(raw, pages, origin="top-left", unit="pdf_points", existing_id=None):
    """Validate a markup request and return the stored record (bottom-left PDF points)."""
    if not isinstance(raw, dict):
        raise MarkupError("markup must be an object")
    kind = str(raw.get("kind") or raw.get("type") or "").strip().lower()
    kind = V3_KINDS.get(kind, kind)
    if kind not in KINDS:
        raise MarkupError(f"unknown markup kind {kind!r}; use one of {', '.join(KINDS)}")
    try:
        page_no = int(raw.get("page"))
    except (TypeError, ValueError):
        raise MarkupError("page (1-based) is required")
    if not 1 <= page_no <= len(pages):
        raise MarkupError(f"page {page_no} is outside the document (1-{len(pages)})")
    page = pages[page_no - 1]
    fr = Frame(page, raw.get("origin") or origin, raw.get("coordinate_mode") or unit)
    geo = raw.get("geometry") if isinstance(raw.get("geometry"), dict) else {}

    def pick(key):
        return raw.get(key) if raw.get(key) is not None else geo.get(key)

    m = {"id": existing_id or _safe_id(raw.get("id")), "kind": kind, "page": page_no}
    if kind in RECT_KINDS or (kind == "area" and pick("rect") is not None and pick("points") is None):
        rect = pick("rect")
        if rect is None:
            raise MarkupError(f"{kind} needs rect [x0, y0, x1, y1]")
        r = fr.rect(rect)
        if r[2] - r[0] < 2 or r[3] - r[1] < 2:
            raise MarkupError("rect is too small (min 2 pt each side)")
        if kind == "area":
            m["points"] = [[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]]
        else:
            m["rect"] = [round(v, 2) for v in r]
    elif kind in SEGMENT_KINDS:
        if pick("start") is None or pick("end") is None:
            raise MarkupError(f"{kind} needs start [x, y] and end [x, y]")
        m["start"], m["end"] = fr.point(pick("start"), "start"), fr.point(pick("end"), "end")
        if math.hypot(m["end"][0] - m["start"][0], m["end"][1] - m["start"][1]) < 2:
            raise MarkupError(f"{kind} is too short")
    else:
        pts = pick("points")
        if not isinstance(pts, (list, tuple)) or len(pts) < (3 if kind == "area" else 2):
            raise MarkupError(f"{kind} needs at least {3 if kind == 'area' else 2} points")
        if len(pts) > MAX_POINTS:
            raise MarkupError(f"{kind} has too many points (max {MAX_POINTS})")
        m["points"] = [fr.point(p, "points") for p in pts]

    style = raw.get("style") if isinstance(raw.get("style"), dict) else {}
    color = color_of(raw.get("color") or style.get("color") or style.get("stroke_color"))
    default_width = {"cloud": 1.0, "rectangle": 2.5, "ink": 1.5, "stamp": 1.5, "text": 1.0}.get(kind, 2.0)
    width = _num(raw.get("width") or style.get("line_weight") or style.get("width") or default_width, "width")
    m["color"] = color
    m["width"] = round(min(max(width, 0.25), 24.0), 2)
    if kind == "rectangle":
        m["opacity"] = 1.0  # LOCK-10 bounding/evidence boxes are bold and opaque
    else:
        op = raw.get("opacity", style.get("opacity", MAX_CORE_OPACITY))
        m["opacity"] = round(min(max(_num(op, "opacity"), 0.05), MAX_CORE_OPACITY), 2)  # LOCK-07
    if kind in LINE_BASED:
        m["halo"] = raw.get("halo", True) is not False  # LOCK-08 (exception recorded via halo:false)
    if kind == "area":
        fo = raw.get("fill_opacity", style.get("fill_opacity", HALO_OPACITY))
        m["fill_opacity"] = round(min(max(_num(fo, "fill_opacity"), 0.05), HALO_OPACITY), 2)  # LOCK-09
    if kind == "cloud":
        m["cloud_depth"] = round(min(max(_num(raw.get("cloud_depth", CLOUD_DEPTH), "cloud_depth"), 1.0), 20.0), 2)
        seg = raw.get("cloud_segment_length", raw.get("cloud_segment", CLOUD_SEGMENT))  # stored key on updates
        m["cloud_segment"] = round(min(max(_num(seg, "cloud_segment_length"), 6.0), 120.0), 2)
    if raw.get("dashed") or str(raw.get("work_status", "")).lower() in ("demo", "demolition"):
        m["dashed"] = True  # LOCK-11 demolition linework is dotted

    text = str(raw.get("text") or raw.get("label") or "").strip()
    if kind == "text" and not text:
        raise MarkupError("text markup needs text")
    if kind == "stamp":
        status = str(raw.get("stamp_status") or raw.get("status") or raw.get("text") or "").strip().upper()
        if status not in STAMP_STATUSES:
            raise MarkupError(f"stamp status must be one of {', '.join(STAMP_STATUSES)}")
        m["stamp_status"] = status
        m["reviewer"] = str(raw.get("reviewer") or "").strip()[:80]
        m["company"] = str(raw.get("company") or "NTXP LLC").strip()[:80]
        m["stamp_date"] = str(raw.get("stamp_date") or raw.get("date") or "").strip()[:20]
        text = status
    if text:
        m["text"] = text[:500]
    for key in ("subject", "trade", "csi_division", "author", "status", "source_ref"):
        if key == "status" and kind == "stamp":
            continue  # a stamp's status lives in stamp_status
        val = raw.get(key)
        if val not in (None, ""):
            m[key] = str(val)[:160]
    if isinstance(raw.get("source"), dict):
        m["source"] = {k: str(v)[:80] for k, v in raw["source"].items() if k in ("sheet", "page", "revision")}
    m["updated_at"] = now_iso()
    return m


def _safe_id(value):
    text = str(value or "").strip()
    return text if SAFE_ID.match(text) else "m" + uuid.uuid4().hex[:10]


def import_manifest(manifest, pages):
    """Load an ntxp-pdf-markups-and-redlines manifest (v2/v3 envelope or a bare list).

    Returns (markups, skipped) where skipped = [{"id", "reason"}].
    """
    if isinstance(manifest, list):
        items, unit = manifest, "pdf_points"
    elif isinstance(manifest, dict):
        items = manifest.get("markups") or manifest.get("items") or []
        unit = str(manifest.get("coordinate_mode") or "pdf_points")
    else:
        raise MarkupError("manifest must be an object or a list")
    if not isinstance(items, list):
        raise MarkupError("manifest markups must be a list")
    out, skipped, seen = [], [], set()
    for raw in items:
        try:
            m = normalize(raw, pages, origin="top-left", unit=unit)
        except MarkupError as e:
            skipped.append({"id": str((raw or {}).get("id", "")) if isinstance(raw, dict) else "", "reason": str(e)})
            continue
        if m["id"] in seen:
            m["id"] = _safe_id(None)
        seen.add(m["id"])
        out.append(m)
    return out, skipped


# ------------------------------------------------------------------ geometry
def cloud_points(rect, depth=CLOUD_DEPTH, segment=CLOUD_SEGMENT):
    """One-sided outward revision cloud (LOCK-12): [(p0, control, p1), ...] quadratic scallops."""
    x0, y0, x1, y1 = rect
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    arcs = []
    for i in range(4):
        (ax, ay), (bx, by) = corners[i], corners[(i + 1) % 4]
        length = math.hypot(bx - ax, by - ay)
        n = max(1, int(round(length / segment)))
        dx, dy = (bx - ax) / length, (by - ay) / length
        nx, ny = dy, -dx
        mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
        if (mx - cx) * nx + (my - cy) * ny < 0:
            nx, ny = -nx, -ny
        for k in range(n):
            px, py = ax + (bx - ax) * k / n, ay + (by - ay) * k / n
            qx, qy = ax + (bx - ax) * (k + 1) / n, ay + (by - ay) * (k + 1) / n
            ctrl = ((px + qx) / 2.0 + nx * 2 * depth, (py + qy) / 2.0 + ny * 2 * depth)
            arcs.append(((px, py), ctrl, (qx, qy)))
    return arcs


def arrow_head(start, end, width):
    """Filled triangular head at `end`, sized from the stroke width."""
    size = 3.0 * width + 6.0
    ang = math.atan2(end[1] - start[1], end[0] - start[0])
    left = (end[0] - size * math.cos(ang - 0.45), end[1] - size * math.sin(ang - 0.45))
    right = (end[0] - size * math.cos(ang + 0.45), end[1] - size * math.sin(ang + 0.45))
    return [tuple(end), left, right]


def is_attestation(m):
    return m.get("kind") == "stamp"


# ------------------------------------------------------------------ PDF drawing (reportlab)
def _rgb(hexcolor):
    h = hexcolor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _path_for(c, m):
    p = c.beginPath()
    k = m["kind"]
    if k == "cloud":
        arcs = cloud_points(m["rect"], m.get("cloud_depth", CLOUD_DEPTH), m.get("cloud_segment", CLOUD_SEGMENT))
        p.moveTo(*arcs[0][0])
        for (a, q, b) in arcs:
            c1 = (a[0] + 2.0 / 3.0 * (q[0] - a[0]), a[1] + 2.0 / 3.0 * (q[1] - a[1]))
            c2 = (b[0] + 2.0 / 3.0 * (q[0] - b[0]), b[1] + 2.0 / 3.0 * (q[1] - b[1]))
            p.curveTo(c1[0], c1[1], c2[0], c2[1], b[0], b[1])
        p.close()
    elif k in SEGMENT_KINDS:
        p.moveTo(*m["start"])
        p.lineTo(*m["end"])
    elif k in ("polyline", "ink", "area"):
        pts = m["points"]
        p.moveTo(*pts[0])
        for pt in pts[1:]:
            p.lineTo(*pt)
        if k == "area":
            p.close()
    return p


def _stroke(c, m, path, width, alpha, color):
    r, g, b = _rgb(color)
    c.setStrokeColorRGB(r, g, b)
    c.setStrokeAlpha(alpha)
    c.setLineWidth(width)
    c.setLineJoin(1)
    c.setLineCap(1)
    c.setDash([2, 3] if m.get("dashed") else [])
    if path is None:
        x0, y0, x1, y1 = m["rect"]
        if m["kind"] == "ellipse":
            c.ellipse(x0, y0, x1, y1, stroke=1, fill=0)
        else:
            c.rect(x0, y0, x1 - x0, y1 - y0, stroke=1, fill=0)
    else:
        c.drawPath(path, stroke=1, fill=0)


def _wrap(text, font, size, width, string_width):
    lines = []
    for para in str(text).split("\n"):
        words, line = para.split(), ""
        for w in words:
            trial = (line + " " + w).strip()
            if string_width(trial, font, size) <= width or not line:
                line = trial
            else:
                lines.append(line)
                line = w
        lines.append(line)
    return lines


def _centered_text(c, text, rect, color, font, size=11.0):
    """LOCK-13 centered, LOCK-15 shrink to fit rather than overflow."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    x0, y0, x1, y1 = rect
    w, h = x1 - x0 - 6, y1 - y0 - 4
    size = float(size)
    while True:
        lines = _wrap(text, font, size, w, stringWidth)
        if (len(lines) * size * 1.2 <= h and all(stringWidth(ln, font, size) <= w for ln in lines)) or size <= 5:
            break
        size -= 0.5
    r, g, b = _rgb(color)
    c.setFillColorRGB(r, g, b)
    c.setFillAlpha(1.0)
    c.setFont(font, size)
    total = len(lines) * size * 1.2
    y = (y0 + y1) / 2.0 + total / 2.0 - size
    for ln in lines:
        c.drawCentredString((x0 + x1) / 2.0, y, ln)
        y -= size * 1.2


def draw(c, m, bold_font="Helvetica-Bold"):
    """Draw one markup onto a reportlab canvas in PDF user space."""
    kind, color = m["kind"], m.get("color", REDLINE_RED)
    width, alpha = float(m.get("width", 2.0)), float(m.get("opacity", MAX_CORE_OPACITY))
    c.saveState()
    try:
        if kind == "area":
            r, g, b = _rgb(color)
            c.setFillColorRGB(r, g, b)
            c.setFillAlpha(float(m.get("fill_opacity", HALO_OPACITY)))
            c.drawPath(_path_for(c, m), stroke=0, fill=1)
            _stroke(c, m, _path_for(c, m), width, alpha, color)
        elif kind in ("rectangle", "ellipse"):
            _stroke(c, m, None, width, alpha, color)
        elif kind == "text":
            r, g, b = _rgb(color)
            c.setFillColorRGB(1, 1, 1)
            c.setFillAlpha(0.5)  # LOCK-10 RFI box interior white at 0.50
            x0, y0, x1, y1 = m["rect"]
            c.rect(x0, y0, x1 - x0, y1 - y0, stroke=0, fill=1)
            _stroke(c, dict(m, kind="rectangle"), None, width, alpha, color)
            _centered_text(c, m.get("text", ""), m["rect"], color, bold_font)
        elif kind == "stamp":
            _draw_stamp(c, m, bold_font)
        else:
            path = _path_for(c, m)
            if m.get("halo", True):
                _stroke(c, m, path, width * 3.0, HALO_OPACITY, color)  # LOCK-08 halo beneath the core
            _stroke(c, m, _path_for(c, m), width, alpha, color)
            if kind == "arrow":
                r, g, b = _rgb(color)
                c.setFillColorRGB(r, g, b)
                c.setFillAlpha(alpha)
                head = arrow_head(m["start"], m["end"], width)
                hp = c.beginPath()
                hp.moveTo(*head[0])
                hp.lineTo(*head[1])
                hp.lineTo(*head[2])
                hp.close()
                c.drawPath(hp, stroke=0, fill=1)
            if m.get("text") and kind in SEGMENT_KINDS:
                sx, sy = m["start"]
                box = [sx - 60, sy + 4, sx + 60, sy + 26]
                _centered_text(c, m["text"], box, color, bold_font, 10.0)
        if kind in ("cloud", "rectangle", "ellipse") and m.get("text"):
            _label_above(c, m, color, bold_font)
    finally:
        c.restoreState()


def _label_above(c, m, color, bold_font):
    """Label tag centered above a cloud, box or ellipse (LOCK-05: red text on red marks)."""
    x0, _, x1, y1 = m["rect"]
    top = y1 + (2 * m.get("cloud_depth", CLOUD_DEPTH) if m["kind"] == "cloud" else 0)
    cx = (x0 + x1) / 2.0
    _centered_text(c, m["text"], [cx - 110, top + 3, cx + 110, top + 27], color, bold_font, 11.0)


def _draw_stamp(c, m, bold_font):
    x0, y0, x1, y1 = m["rect"]
    color = m.get("color", REDLINE_RED)
    r, g, b = _rgb(color)
    c.setStrokeColorRGB(r, g, b)
    c.setStrokeAlpha(MAX_CORE_OPACITY)
    c.setLineWidth(float(m.get("width", 1.5)))
    c.rect(x0, y0, x1 - x0, y1 - y0, stroke=1, fill=0)
    inset = 3.0
    c.setLineWidth(0.75)
    c.rect(x0 + inset, y0 + inset, x1 - x0 - 2 * inset, y1 - y0 - 2 * inset, stroke=1, fill=0)
    h = y1 - y0
    head = [x0 + inset, y0 + h * 0.62, x1 - inset, y1 - inset]
    _centered_text(c, m.get("company", "NTXP LLC"), [x0, y1 - h * 0.30, x1, y1 - inset], color, bold_font, 9.0)
    _centered_text(c, m.get("stamp_status", ""), [head[0], y0 + h * 0.34, head[2], y1 - h * 0.30], color, bold_font, 14.0)
    foot = " | ".join(v for v in (m.get("reviewer"), m.get("stamp_date")) if v)
    if foot:
        _centered_text(c, foot, [x0 + inset, y0 + inset, x1 - inset, y0 + h * 0.34], color, bold_font, 8.0)
