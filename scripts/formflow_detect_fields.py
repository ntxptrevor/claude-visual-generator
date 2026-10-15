#!/usr/bin/env python3
"""
FormFlow Field Detector — Detects form fields in PDF documents using
AcroForm extraction and visual pattern recognition.

Usage:
    python scripts/formflow_detect_fields.py \
        --form form.pdf \
        --output-json fields.json
"""

import argparse
import json
import re
import sys
from pathlib import Path


def detect_acroform_fields(file_path):
    try:
        from pypdf import PdfReader
    except ImportError:
        print("WARNING: pypdf not installed. Skipping AcroForm detection.")
        return []

    fields = []
    try:
        reader = PdfReader(file_path)
        form_fields = reader.get_fields()
        if not form_fields:
            return fields

        for name, field_obj in form_fields.items():
            field_type_code = field_obj.get("/FT", "")
            field_type_map = {
                "/Tx": "text",
                "/Btn": "checkbox",
                "/Ch": "dropdown",
                "/Sig": "signature",
            }
            field_type = field_type_map.get(str(field_type_code), "text")

            value = field_obj.get("/V", "")
            if hasattr(value, "get_object"):
                value = str(value.get_object())
            value = str(value).strip() if value else ""

            default_value = field_obj.get("/DV", "")
            if hasattr(default_value, "get_object"):
                default_value = str(default_value.get_object())
            default_value = str(default_value).strip() if default_value else ""

            rect = field_obj.get("/Rect")
            position = None
            if rect:
                try:
                    coords = [float(x) for x in rect]
                    position = {
                        "x1": coords[0], "y1": coords[1],
                        "x2": coords[2], "y2": coords[3],
                    }
                except (ValueError, TypeError):
                    pass

            max_len = field_obj.get("/MaxLen")
            options = None
            if field_type == "dropdown":
                opt = field_obj.get("/Opt")
                if opt:
                    options = [str(o) for o in opt]

            fields.append({
                "field_name": name,
                "field_type": field_type,
                "current_value": value,
                "default_value": default_value,
                "position": position,
                "max_length": int(max_len) if max_len else None,
                "options": options,
                "required": bool(field_obj.get("/Ff", 0) & 2),
                "detection_method": "acroform",
            })
    except Exception as e:
        print(f"WARNING: AcroForm detection error: {e}")

    return fields


BLANK_RE = re.compile(r"^\$?[_.]{3,}$")
LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 .,'/&()#-]{1,58}$")
MAX_LABEL_WORDS = 7
MIN_GAP = 18


def _lines(words, tolerance=3):
    rows = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if rows and abs(rows[-1][0]["top"] - w["top"]) <= tolerance:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w["x0"]) for r in rows]


def _field(label, page_num, x, bottom, page_h, method):
    label = label.strip().rstrip(":").strip()
    if not LABEL_RE.match(label) or len(label.split()) > MAX_LABEL_WORDS:
        return None
    return {
        "field_name": re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_"),
        "field_name_raw": label,
        "field_type": "text",
        "current_value": "",
        "page": page_num,
        "position": {"x1": round(x, 1), "y1": round(page_h - bottom + 1, 1)},
        "detection_method": method,
    }


def _blank_fields_on_page(page, page_num):
    """Find 'Label: ____', 'Label ____' and 'Label:' + empty gap, with the blank's position.

    position is in PDF points from the bottom-left, where the value should start.
    """
    page_h = float(page.height)
    found = []
    for row in _lines(page.extract_words(keep_blank_chars=False)):
        label_words = []
        for i, w in enumerate(row):
            text = w["text"]
            nxt = row[i + 1] if i + 1 < len(row) else None
            if BLANK_RE.match(text):
                if label_words:
                    x = w["x0"] + (6 if text.startswith("$") else 0)
                    f = _field(" ".join(l["text"] for l in label_words), page_num, x,
                               w["bottom"], page_h, "visual_underline")
                    if f:
                        found.append(f)
                label_words = []
                continue
            label_words.append(w)
            if not text.endswith(":"):
                continue
            if nxt is not None and BLANK_RE.match(nxt["text"]):
                continue
            gap = (nxt["x0"] - w["x1"]) if nxt is not None else page.width - w["x1"]
            if gap >= MIN_GAP:
                f = _field(" ".join(l["text"] for l in label_words), page_num, w["x1"] + 4,
                           w["bottom"], page_h, "visual_label_colon")
                if f:
                    found.append(f)
            label_words = []
    return found


def detect_visual_fields(file_path):
    try:
        import pdfplumber
    except ImportError:
        print("WARNING: pdfplumber not installed. Skipping visual detection.")
        return []

    fields = []
    seen_names = set()

    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            for f in _blank_fields_on_page(page, page_num):
                if f["field_name"] not in seen_names:
                    seen_names.add(f["field_name"])
                    fields.append(f)

            text = page.extract_text() or ""
            for line in (ln.strip() for ln in text.split("\n")):
                if not line:
                    continue
                checkbox = re.findall(
                    r"[\[\(\{]\s*[\]\)\}]\s*([A-Za-z][A-Za-z\s]{2,30})",
                    line
                )
                for cb_label in checkbox:
                    norm = re.sub(r"\s+", "_", cb_label.strip()).lower()
                    if norm not in seen_names:
                        seen_names.add(norm)
                        fields.append({
                            "field_name": norm,
                            "field_name_raw": cb_label.strip(),
                            "field_type": "checkbox",
                            "current_value": "",
                            "page": page_num,
                            "detection_method": "visual_checkbox",
                        })

    return fields


def merge_fields(acroform_fields, visual_fields):
    merged = list(acroform_fields)
    acro_names = {f["field_name"].lower() for f in acroform_fields}

    for vf in visual_fields:
        if vf["field_name"].lower() not in acro_names:
            merged.append(vf)

    return merged


def main():
    parser = argparse.ArgumentParser(description="FormFlow Field Detector")
    parser.add_argument("--form", required=True, help="Path to PDF form")
    parser.add_argument("--output-json", required=True, help="Output JSON file")
    args = parser.parse_args()

    form_path = Path(args.form)
    if not form_path.exists():
        print(f"ERROR: File not found: {form_path}")
        sys.exit(1)

    if form_path.suffix.lower() != ".pdf":
        print(f"ERROR: Only PDF forms supported, got: {form_path.suffix}")
        sys.exit(1)

    print(f"Detecting form fields in {form_path.name}...")

    acro_fields = detect_acroform_fields(str(form_path))
    print(f"  AcroForm fields: {len(acro_fields)}")

    # JEV Tier 0: an AcroForm already defines every fillable field, so skip visual parsing.
    visual_fields = [] if acro_fields else detect_visual_fields(str(form_path))
    print(f"  Visual fields: {len(visual_fields)}")

    all_fields = merge_fields(acro_fields, visual_fields)
    print(f"  Total unique fields: {len(all_fields)}")

    type_counts = {}
    for f in all_fields:
        ft = f.get("field_type", "text")
        type_counts[ft] = type_counts.get(ft, 0) + 1

    output = {
        "source_form": str(form_path),
        "field_count": len(all_fields),
        "field_types": type_counts,
        "fields": all_fields,
    }

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Output saved to {output_path}")
    print(f"\nField types: {type_counts}")


if __name__ == "__main__":
    main()
