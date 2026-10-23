#!/usr/bin/env python3
"""
NTXP Form Filler page rendering and final PDF export (contract: ARCHITECTURE.md).

- render_pages(): pypdfium2 page images (PNG, 2x) for the GUI live view.
- page_sizes(): page widths/heights in PDF points.
- export_pdf(): draws every field value / mark / highlight onto the pages with
  reportlab and merges with pypdf. AcroForm widgets are flattened into the page
  (their blank appearance is kept, the value is drawn, the widget is removed).
- Formatting helpers shared with the GUI server: format_currency, format_phone,
  format_date, initials_of.

Default text style: Arial-metric 11 pt, black, regular. Helvetica is used unless an
Arial or Liberation Sans TTF exists on the system, in which case it is embedded.
Nothing from the review (confidence, issues) is ever drawn on the PDF.
"""

import base64
import glob
import io
import os
import re
from datetime import datetime
from pathlib import Path

DEFAULT_FONT_SIZE = 11
DEFAULT_COLOR = "#000000"
DEFAULT_HIGHLIGHT = "#FFEB3B"

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_currency(value):
    """Accounting format: $1,234.00; negatives ($1,234.00). Junk is stripped.

    Returns "" when no number can be read.
    """
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    negative = "-" in s or (s.startswith("(") and s.endswith(")")) or ("(" in s and ")" in s)
    cleaned = re.sub(r"[^0-9.]", "", s)
    if cleaned.count(".") > 1:
        head, _, tail = cleaned.rpartition(".")
        cleaned = head.replace(".", "") + "." + tail
    if not re.search(r"\d", cleaned):
        return ""
    try:
        amount = round(float(cleaned), 2)
    except ValueError:
        return ""
    text = "${:,.2f}".format(abs(amount))
    return "(" + text + ")" if negative and amount != 0 else text


def format_phone(value):
    """US phone (###) ###-####. Non-10-digit input is returned stripped, unchanged."""
    if value is None:
        return ""
    s = str(value).strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return "({}) {}-{}".format(digits[:3], digits[3:6], digits[6:])
    return s


def format_date(value):
    """Normalize to MM/DD/YYYY. Accepts YYYY-MM-DD, M/D/YYYY, M/D/YY, M-D-YYYY."""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m.%d.%Y", "%B %d, %Y",
                "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue
    return s


def initials_of(name):
    """'Alison Hopkins' -> 'AH'."""
    parts = [p for p in re.split(r"[\s\-]+", str(name or "").strip()) if p]
    return "".join(p[0].upper() for p in parts if p[0].isalpha())


def display_value(field):
    """The text drawn for a field (formatting applied by type)."""
    ftype = field.get("type", "text_word")
    value = field.get("value")
    if value in (None, ""):
        return ""
    if ftype == "currency":
        text = format_currency(value)
        # The form already prints "$" in front of the blank: do not print it twice.
        return text.replace("$", "", 1) if field.get("prefix") == "$" else text
    if ftype == "phone":
        return format_phone(value)
    if ftype == "date":
        return format_date(value)
    if ftype in ("checkmark", "x_mark"):
        return "on" if str(value).lower() in ("on", "yes", "true", "1", "x", "checked", "✓") else ""
    return str(value)


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

_FONT_CACHE = {}
FONT_SEARCH = [
    "/usr/share/fonts/**/Arial.ttf", "/usr/share/fonts/**/arial.ttf",
    "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/**/LiberationSans-Regular.ttf",
]


def text_font():
    """Register Arial / Liberation Sans if present; else Helvetica. Returns font name."""
    if "name" in _FONT_CACHE:
        return _FONT_CACHE["name"]
    name = "Helvetica"
    if os.environ.get("NFF_FORCE_HELVETICA") != "1":
        for pattern in FONT_SEARCH:
            hits = sorted(glob.glob(pattern, recursive=True))
            if not hits:
                continue
            try:
                from reportlab.pdfbase import pdfmetrics
                from reportlab.pdfbase.ttfonts import TTFont
                face = "Arial" if "arial" in hits[0].lower() else "LiberationSans"
                pdfmetrics.registerFont(TTFont(face, hits[0]))
                name = face
                break
            except Exception:
                continue
    _FONT_CACHE["name"] = name
    return name


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def page_sizes(pdf_path):
    from pypdf import PdfReader
    reader = PdfReader(str(pdf_path))
    out = []
    for p in reader.pages:
        box = p.mediabox
        out.append({"w": float(box.width), "h": float(box.height),
                    "ox": float(box.left), "oy": float(box.bottom)})
    return out


def render_pages(pdf_path, out_dir, scale=2.0):
    """Render every page to out_dir/page-<n>.png. Returns list of paths."""
    import pypdfium2 as pdfium
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    paths = []
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            bitmap = page.render(scale=scale)
            img = bitmap.to_pil()
            path = out_dir / f"page-{i + 1}.png"
            img.save(path, format="PNG", optimize=True)
            paths.append(path)
            page.close()
    finally:
        pdf.close()
    return paths


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _hex_rgb(color):
    c = str(color or DEFAULT_COLOR).lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", c):
        c = DEFAULT_COLOR.lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _wrap(text, font, size, width):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    lines = []
    for para in str(text).split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        line = words[0]
        for w in words[1:]:
            trial = line + " " + w
            if stringWidth(trial, font, size) <= width:
                line = trial
            else:
                lines.append(line)
                line = w
        lines.append(line)
    return lines


def _image_reader(field, image_dir):
    """Signature/initials image as a reportlab ImageReader, or None."""
    from reportlab.lib.utils import ImageReader
    if image_dir and field.get("image_file"):
        p = Path(image_dir) / Path(field["image_file"]).name
        if p.is_file():
            return ImageReader(str(p))
    data = field.get("image")
    if isinstance(data, str) and data.startswith("data:image/png;base64,"):
        return ImageReader(io.BytesIO(base64.b64decode(data.split(",", 1)[1])))
    return None


def _draw_field(c, field, font, image_dir, include_signatures):
    ftype = field.get("type", "text_word")
    x1, y1, x2, y2 = [float(v) for v in field["rect"]]
    w, h = max(x2 - x1, 1.0), max(y2 - y1, 1.0)
    style = field.get("style") or {}
    size = float(style.get("size") or DEFAULT_FONT_SIZE)
    r, g, b = _hex_rgb(style.get("color"))
    c.setFillColorRGB(r, g, b)
    c.setStrokeColorRGB(r, g, b)

    if ftype in ("signature", "initials"):
        if not include_signatures:
            return False
        img = _image_reader(field, image_dir)
        if img is not None:
            c.drawImage(img, x1, y1, width=w, height=h, mask="auto",
                        preserveAspectRatio=True, anchor="sw")
            return True
        text = str(field.get("value") or "").strip()
        if not text:
            return False
        c.setFont(font, size)
        c.drawString(x1 + 2, y1 + max(2.0, (h - size * 0.72) / 2), text)
        return True

    value = display_value(field)
    if not value:
        return False

    if ftype in ("checkmark", "x_mark"):
        side = min(w, h)
        cx, cy = x1 + w / 2, y1 + h / 2
        if ftype == "checkmark":
            # Vector check mark: no dependence on a Dingbats font being available.
            bx, by = cx - side / 2, cy - side / 2
            c.saveState()
            c.setLineWidth(max(1.0, side * 0.13))
            c.setLineCap(1)
            c.setLineJoin(1)
            path = c.beginPath()
            path.moveTo(bx + side * 0.18, by + side * 0.52)
            path.lineTo(bx + side * 0.42, by + side * 0.24)
            path.lineTo(bx + side * 0.84, by + side * 0.80)
            c.drawPath(path, stroke=1, fill=0)
            c.restoreState()
        else:
            msize = side * 0.95
            c.setFont(font, msize)
            c.drawCentredString(cx, cy - msize * 0.36, "X")
        return True

    c.setFont(font, size)
    multiline = ftype in ("text_paragraph", "address")
    line_h = size * 1.2
    if multiline and h >= line_h * 1.8:
        lines = _wrap(value, font, size, w - 4)
        y = y2 - size - 1
        for line in lines:
            if y < y1 - size * 0.25:
                break
            c.drawString(x1 + 2, y, line)
            y -= line_h
    else:
        text = ", ".join(p.strip() for p in value.split("\n") if p.strip()) if multiline else value
        c.drawString(x1 + 2, y1 + max(2.0, (h - size * 0.72) / 2), text)
    return True


def _draw_highlight(c, hl):
    r, g, b = _hex_rgb(hl.get("color") or DEFAULT_HIGHLIGHT)
    c.saveState()
    c.setStrokeColorRGB(r, g, b)
    c.setStrokeAlpha(float(hl.get("opacity", 0.4)))
    c.setLineWidth(float(hl.get("width", 10)))
    c.setLineCap(0)
    c.line(float(hl["x1"]), float(hl["y1"]), float(hl["x2"]), float(hl["y2"]))
    c.restoreState()


def _flatten_widgets(writer, page):
    """Merge blank widget appearances into the page content, then remove the widgets."""
    from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                               NameObject)
    annots = page.get("/Annots")
    if not annots:
        return 0
    annots = annots.get_object()
    keep, ops, merged = ArrayObject(), [], 0
    resources = page.get("/Resources")
    resources = resources.get_object() if resources is not None else DictionaryObject()
    xobjs = resources.get("/XObject")
    xobjs = xobjs.get_object() if xobjs is not None else DictionaryObject()
    for ref in annots:
        a = ref.get_object()
        if a.get("/Subtype") != "/Widget":
            keep.append(ref)
            continue
        merged += 1
        parent = a.get("/Parent")
        parent = parent.get_object() if parent is not None else {}
        ft = a.get("/FT") or parent.get("/FT")
        ap = a.get("/AP")
        if not ap:
            continue
        normal = ap.get_object().get("/N")
        if normal is None:
            continue
        normal_ref = normal
        normal = normal.get_object()
        stream_ref = None
        if ft == "/Btn":
            if hasattr(normal, "keys") and "/Off" in normal:
                stream_ref = normal.raw_get("/Off")
            elif hasattr(normal, "get_data"):
                stream_ref = normal_ref
        else:
            value = a.get("/V", parent.get("/V", ""))
            if hasattr(normal, "get_data") and not str(value or "").strip():
                stream_ref = normal_ref
        if stream_ref is None:
            continue
        stream = stream_ref.get_object()
        if not hasattr(stream, "get_data"):
            continue
        rect = [float(v) for v in a.get("/Rect")]
        rx1, ry1 = min(rect[0], rect[2]), min(rect[1], rect[3])
        rw, rh = abs(rect[2] - rect[0]), abs(rect[3] - rect[1])
        bbox = [float(v) for v in stream.get("/BBox", [0, 0, rw, rh])]
        bw, bh = (bbox[2] - bbox[0]) or rw or 1, (bbox[3] - bbox[1]) or rh or 1
        sx, sy = rw / bw, rh / bh
        name = f"/NFFap{len(ops)}"
        if not hasattr(stream_ref, "idnum"):
            stream_ref = writer._add_object(stream)
        xobjs[NameObject(name)] = stream_ref
        ops.append(f"q {sx:.4f} 0 0 {sy:.4f} {rx1 - bbox[0] * sx:.4f} "
                   f"{ry1 - bbox[1] * sy:.4f} cm {name} Do Q")
    if ops:
        resources[NameObject("/XObject")] = xobjs
        page[NameObject("/Resources")] = resources
        contents = page.get("/Contents")
        arr = ArrayObject()
        pre, post = DecodedStreamObject(), DecodedStreamObject()
        pre.set_data(b"q\n")
        post.set_data(("\nQ\n" + "\n".join(ops) + "\n").encode("latin-1"))
        arr.append(writer._add_object(pre))
        if contents is not None:
            cobj = contents.get_object()
            if isinstance(cobj, ArrayObject):
                arr.extend(cobj)
            else:
                arr.append(contents if hasattr(contents, "idnum") else writer._add_object(cobj))
        arr.append(writer._add_object(post))
        page[NameObject("/Contents")] = arr
    if keep:
        page[NameObject("/Annots")] = keep
    elif "/Annots" in page:
        del page["/Annots"]
    return merged


def export_pdf(src_pdf, fields, highlights, out_path, include_signatures=False,
               image_dir=None):
    """Draw every field value and highlight onto src_pdf and write out_path.

    fields: GUI state fields (rect in PDF points, type, value, style).
    include_signatures: only True after a verified Tier 3 approval.
    Returns {"path", "drawn", "font"}.
    """
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject
    from reportlab.pdfgen import canvas

    font = text_font()
    reader = PdfReader(str(src_pdf))
    writer = PdfWriter(clone_from=reader)

    by_page = {}
    for f in fields or []:
        if f.get("rect"):
            by_page.setdefault(int(f.get("page", 1)), {"f": [], "h": []})["f"].append(f)
    for hl in highlights or []:
        by_page.setdefault(int(hl.get("page", 1)), {"f": [], "h": []})["h"].append(hl)

    drawn = 0
    for idx, page in enumerate(writer.pages, start=1):
        _flatten_widgets(writer, page)
        items = by_page.get(idx)
        if not items:
            continue
        box = page.mediabox
        # Overlay content uses the page's own user space (rects are absolute PDF
        # coordinates), so it lines up even when the media box is offset.
        pw, ph = float(box.right), float(box.top)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(pw, ph), invariant=1)
        for hl in items["h"]:
            _draw_highlight(c, hl)
        for f in items["f"]:
            if _draw_field(c, f, font, image_dir, include_signatures):
                drawn += 1
        c.save()
        buf.seek(0)
        page.merge_page(PdfReader(buf).pages[0])

    root = writer._root_object
    if "/AcroForm" in root:
        del root[NameObject("/AcroForm")]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as fh:
        writer.write(fh)
    return {"path": str(out_path), "drawn": drawn, "font": font}
