#!/usr/bin/env python3
"""
FormFlow Document Parser — Extracts key-value pairs from PDF, Excel, and
Word documents to populate the Knowledge Base.

Usage:
    python scripts/formflow_parse_document.py \
        --file document.pdf \
        --output-json extracted.json

Supported formats: PDF (.pdf), Excel (.xlsx/.xls), Word (.docx)
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


FIELD_PATTERNS = {
    "personal": [
        r"(?i)(first|last|middle|full)\s*name",
        r"(?i)date\s*of\s*birth|dob|birth\s*date",
        r"(?i)gender|sex",
        r"(?i)ssn|social\s*security",
        r"(?i)nationality|citizenship",
        r"(?i)marital\s*status",
    ],
    "contact": [
        r"(?i)e[-]?mail",
        r"(?i)phone|tel|mobile|cell|fax",
        r"(?i)website|url",
    ],
    "address": [
        r"(?i)address|street|city|state|zip|postal|country|apt|suite",
    ],
    "employment": [
        r"(?i)employer|company|job\s*title|position|occupation|work",
        r"(?i)department|supervisor|manager",
        r"(?i)hire\s*date|start\s*date|employment",
        r"(?i)salary|wage|compensation",
    ],
    "education": [
        r"(?i)school|university|college|degree|diploma|gpa|major",
        r"(?i)graduation|certificate|qualification",
    ],
    "financial": [
        r"(?i)bank|account|routing|income|tax|ein|revenue",
    ],
    "medical": [
        r"(?i)medical|health|insurance|policy|allergies|medication",
        r"(?i)doctor|physician|emergency\s*contact",
    ],
    "legal": [
        r"(?i)license|permit|registration|court|case\s*number",
    ],
    "business": [
        r"(?i)business\s*name|company\s*name|dba|trade\s*name",
        r"(?i)incorporation|registered\s*agent|ein|tax\s*id",
    ],
}

FIELD_TYPE_PATTERNS = {
    "date": r"(?i)date|dob|birth|graduation|hire|start|end|expir",
    "email": r"(?i)e[-]?mail",
    "phone": r"(?i)phone|tel|mobile|cell|fax",
    "zip": r"(?i)zip|postal",
    "ssn": r"(?i)ssn|social\s*security",
}


def categorize_field(field_name):
    for category, patterns in FIELD_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, field_name):
                return category
    return "other"


def detect_field_type(field_name):
    for ftype, pattern in FIELD_TYPE_PATTERNS.items():
        if re.search(pattern, field_name):
            return ftype
    return "text"


def normalize_field_name(raw_name):
    name = re.sub(r"[^a-zA-Z0-9\s]", "", raw_name).strip()
    name = re.sub(r"\s+", "_", name).lower()
    return name


def parse_pdf(file_path):
    try:
        import pdfplumber
    except ImportError:
        print("ERROR: pdfplumber not installed. Run: pip install pdfplumber")
        sys.exit(1)

    entries = []
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        if reader.get_fields():
            for field_name, field_obj in reader.get_fields().items():
                value = field_obj.get("/V", "")
                if hasattr(value, "get_object"):
                    value = str(value.get_object())
                value = str(value) if value else ""
                entries.append({
                    "field_name": normalize_field_name(field_name),
                    "field_name_raw": field_name,
                    "field_value": value.strip(),
                    "category": categorize_field(field_name),
                    "field_type": detect_field_type(field_name),
                    "source_method": "acroform",
                })
    except Exception:
        pass

    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            lines = text.split("\n")
            for line in lines:
                kv_match = re.match(r"^([^:]{3,50}):\s*(.+)$", line.strip())
                if kv_match:
                    key, val = kv_match.group(1).strip(), kv_match.group(2).strip()
                    norm_key = normalize_field_name(key)
                    if norm_key and not any(e["field_name"] == norm_key for e in entries):
                        entries.append({
                            "field_name": norm_key,
                            "field_name_raw": key,
                            "field_value": val,
                            "category": categorize_field(key),
                            "field_type": detect_field_type(key),
                            "source_method": "text_extraction",
                            "page": page_num,
                        })

            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                for row in table:
                    if not row or len(row) < 2:
                        continue
                    key_cell = str(row[0] or "").strip()
                    val_cell = str(row[1] or "").strip()
                    if 3 <= len(key_cell) <= 60 and val_cell:
                        norm_key = normalize_field_name(key_cell)
                        if norm_key and not any(e["field_name"] == norm_key for e in entries):
                            entries.append({
                                "field_name": norm_key,
                                "field_name_raw": key_cell,
                                "field_value": val_cell,
                                "category": categorize_field(key_cell),
                                "field_type": detect_field_type(key_cell),
                                "source_method": "table_extraction",
                                "page": page_num,
                            })

    return entries


def parse_excel(file_path):
    try:
        from openpyxl import load_workbook
    except ImportError:
        print("ERROR: openpyxl not installed. Run: pip install openpyxl")
        sys.exit(1)

    entries = []
    wb = load_workbook(file_path, data_only=True)

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue

        header_row = rows[0]
        if len(rows) >= 2:
            for row in rows[1:]:
                for col_idx, cell_val in enumerate(row):
                    if col_idx < len(header_row) and header_row[col_idx]:
                        key = str(header_row[col_idx]).strip()
                        val = str(cell_val).strip() if cell_val else ""
                        norm_key = normalize_field_name(key)
                        if norm_key and val:
                            entries.append({
                                "field_name": norm_key,
                                "field_name_raw": key,
                                "field_value": val,
                                "category": categorize_field(key),
                                "field_type": detect_field_type(key),
                                "source_method": "excel_header",
                                "sheet": sheet_name,
                            })

        for row in rows:
            if row and len(row) >= 2:
                key_cell = str(row[0] or "").strip()
                val_cell = str(row[1] or "").strip()
                if 3 <= len(key_cell) <= 60 and val_cell:
                    norm_key = normalize_field_name(key_cell)
                    if norm_key and not any(e["field_name"] == norm_key for e in entries):
                        entries.append({
                            "field_name": norm_key,
                            "field_name_raw": key_cell,
                            "field_value": val_cell,
                            "category": categorize_field(key_cell),
                            "field_type": detect_field_type(key_cell),
                            "source_method": "excel_kv",
                            "sheet": sheet_name,
                        })

    return entries


def parse_word(file_path):
    try:
        from docx import Document
    except ImportError:
        print("ERROR: python-docx not installed. Run: pip install python-docx")
        sys.exit(1)

    entries = []
    doc = Document(file_path)

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        kv_match = re.match(r"^([^:]{3,50}):\s*(.+)$", text)
        if kv_match:
            key, val = kv_match.group(1).strip(), kv_match.group(2).strip()
            norm_key = normalize_field_name(key)
            if norm_key:
                entries.append({
                    "field_name": norm_key,
                    "field_name_raw": key,
                    "field_value": val,
                    "category": categorize_field(key),
                    "field_type": detect_field_type(key),
                    "source_method": "docx_paragraph",
                })

    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if len(cells) >= 2:
                key, val = cells[0], cells[1]
                if 3 <= len(key) <= 60 and val:
                    norm_key = normalize_field_name(key)
                    if norm_key and not any(e["field_name"] == norm_key for e in entries):
                        entries.append({
                            "field_name": norm_key,
                            "field_name_raw": key,
                            "field_value": val,
                            "category": categorize_field(key),
                            "field_type": detect_field_type(key),
                            "source_method": "docx_table",
                        })

    return entries


PARSERS = {
    ".pdf": parse_pdf,
    ".xlsx": parse_excel,
    ".xls": parse_excel,
    ".docx": parse_word,
}


def main():
    parser = argparse.ArgumentParser(description="FormFlow Document Parser")
    parser.add_argument("--file", required=True, help="Path to document file")
    parser.add_argument("--output-json", required=True, help="Output JSON file path")
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"ERROR: File not found: {file_path}")
        sys.exit(1)

    ext = file_path.suffix.lower()
    if ext not in PARSERS:
        print(f"ERROR: Unsupported file type: {ext}")
        print(f"Supported: {', '.join(PARSERS.keys())}")
        sys.exit(1)

    print(f"Parsing {file_path.name} ({ext})...")
    entries = PARSERS[ext](str(file_path))
    print(f"Extracted {len(entries)} field entries.")

    output = {
        "source_file": str(file_path),
        "file_type": ext,
        "entry_count": len(entries),
        "entries": entries,
    }

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Output saved to {output_path}")

    categories = {}
    for e in entries:
        cat = e.get("category", "other")
        categories[cat] = categories.get(cat, 0) + 1
    print("\nEntries by category:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    main()
