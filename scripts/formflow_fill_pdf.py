#!/usr/bin/env python3
"""
FormFlow PDF Filler — Fills detected PDF form fields with KB answers
and produces a completed PDF output.

Usage:
    python scripts/formflow_fill_pdf.py \
        --form original_form.pdf \
        --answers filled_fields.json \
        --output output/filled_form.pdf
"""

import argparse
import json
import sys
from pathlib import Path


def fill_acroform(form_path, answers, output_path):
    try:
        from PyPDF2 import PdfReader, PdfWriter
        from PyPDF2.generic import NameObject, TextStringObject
    except ImportError:
        print("ERROR: PyPDF2 not installed. Run: pip install PyPDF2")
        sys.exit(1)

    reader = PdfReader(form_path)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)

    answer_map = {}
    for ans in answers:
        answer_map[ans["field_name"]] = ans.get("field_value", "")
        if "field_name_raw" in ans:
            answer_map[ans["field_name_raw"]] = ans.get("field_value", "")

    filled_count = 0
    skipped_count = 0

    if writer.get_fields():
        for page in writer.pages:
            annotations = page.get("/Annots")
            if not annotations:
                continue
            for annot in annotations:
                annot_obj = annot.get_object() if hasattr(annot, "get_object") else annot
                field_name = annot_obj.get("/T")
                if not field_name:
                    continue
                field_name_str = str(field_name)

                value = answer_map.get(field_name_str)
                if value is None:
                    norm = field_name_str.lower().replace(" ", "_")
                    value = answer_map.get(norm)

                if value is not None and value != "":
                    annot_obj.update({
                        NameObject("/V"): TextStringObject(value),
                        NameObject("/AS"): TextStringObject(value),
                    })
                    filled_count += 1
                else:
                    skipped_count += 1

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "wb") as f:
        writer.write(f)

    return filled_count, skipped_count


def fill_with_overlay(form_path, answers, output_path):
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas as rl_canvas
        from PyPDF2 import PdfReader, PdfWriter
    except ImportError:
        print("ERROR: reportlab and PyPDF2 required. Run: pip install reportlab PyPDF2")
        sys.exit(1)
    import io

    positioned_answers = [a for a in answers if a.get("position")]
    if not positioned_answers:
        return 0, len(answers)

    reader = PdfReader(form_path)
    writer = PdfWriter()

    pages_data = {}
    for ans in positioned_answers:
        page_num = ans.get("page", 1) - 1
        if page_num not in pages_data:
            pages_data[page_num] = []
        pages_data[page_num].append(ans)

    for page_idx in range(len(reader.pages)):
        page = reader.pages[page_idx]
        page_box = page.mediabox
        page_w = float(page_box.width)
        page_h = float(page_box.height)

        if page_idx in pages_data:
            packet = io.BytesIO()
            c = rl_canvas.Canvas(packet, pagesize=(page_w, page_h))
            c.setFont("Helvetica", 10)

            for ans in pages_data[page_idx]:
                pos = ans["position"]
                x = pos.get("x1", 0) + 2
                y = pos.get("y1", 0) + 2
                value = ans.get("field_value", "")
                if value:
                    c.drawString(x, y, value)

            c.save()
            packet.seek(0)

            overlay_reader = PdfReader(packet)
            page.merge_page(overlay_reader.pages[0])

        writer.add_page(page)

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "wb") as f:
        writer.write(f)

    return len(positioned_answers), len(answers) - len(positioned_answers)


def main():
    parser = argparse.ArgumentParser(description="FormFlow PDF Filler")
    parser.add_argument("--form", required=True, help="Original PDF form")
    parser.add_argument("--answers", required=True, help="JSON file with field answers")
    parser.add_argument("--output", required=True, help="Output filled PDF path")
    parser.add_argument("--method", choices=["acroform", "overlay", "auto"],
                        default="auto", help="Fill method")
    args = parser.parse_args()

    form_path = Path(args.form)
    if not form_path.exists():
        print(f"ERROR: Form not found: {form_path}")
        sys.exit(1)

    answers_path = Path(args.answers)
    if not answers_path.exists():
        print(f"ERROR: Answers file not found: {answers_path}")
        sys.exit(1)

    with open(answers_path) as f:
        data = json.load(f)

    answers = data if isinstance(data, list) else data.get("entries", data.get("fields", []))
    print(f"Filling {form_path.name} with {len(answers)} answers...")

    method = args.method
    if method == "auto":
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(form_path))
            has_acroform = bool(reader.get_fields())
        except Exception:
            has_acroform = False
        method = "acroform" if has_acroform else "overlay"

    print(f"Using method: {method}")

    if method == "acroform":
        filled, skipped = fill_acroform(str(form_path), answers, args.output)
    else:
        filled, skipped = fill_with_overlay(str(form_path), answers, args.output)

    print(f"\nResults:")
    print(f"  Filled: {filled} fields")
    print(f"  Skipped: {skipped} fields")
    print(f"  Output: {args.output}")

    result = {
        "form": str(form_path),
        "output": args.output,
        "method": method,
        "filled": filled,
        "skipped": skipped,
        "total": len(answers),
    }
    result_path = Path(args.output).with_suffix(".result.json")
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
