"""
Document Form Filler - Smart Knowledge Base & Form Filling Tool

A web application that:
1. Builds a knowledge base from uploaded documents (PDF, Excel, Word)
2. Detects form fields in uploaded PDF forms
3. Auto-fills forms using the knowledge base
4. Flags contradictions and allows inline editing
"""

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import pdfplumber
from docx import Document as DocxDocument
from flask import Flask, jsonify, redirect, render_template, request, send_file, url_for
from openpyxl import load_workbook
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import NameObject, TextStringObject

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB max
app.secret_key = os.urandom(24)

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
KB_FILE = BASE_DIR / "knowledge_base.json"

UPLOAD_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------

class KnowledgeBase:
    """Persistent, evolving knowledge base stored as JSON."""

    # Standard categories for organizing knowledge
    CATEGORIES = {
        "personal": "Personal Information",
        "contact": "Contact Details",
        "address": "Address Information",
        "employment": "Employment & Work",
        "education": "Education & Training",
        "financial": "Financial Information",
        "medical": "Medical & Health",
        "legal": "Legal & Compliance",
        "business": "Business Information",
        "other": "Other",
    }

    # Field patterns for categorization
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

    def __init__(self):
        self.entries = {}
        self.history = []
        self.load()

    def load(self):
        if KB_FILE.exists():
            data = json.loads(KB_FILE.read_text())
            self.entries = data.get("entries", {})
            self.history = data.get("history", [])

    def save(self):
        KB_FILE.write_text(json.dumps({
            "entries": self.entries,
            "history": self.history,
        }, indent=2, default=str))

    def categorize_field(self, field_name):
        for category, patterns in self.FIELD_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, field_name):
                    return category
        return "other"

    def set_entry(self, key, value, source="manual", confidence=1.0):
        key_lower = key.strip().lower()
        category = self.categorize_field(key)
        now = datetime.now().isoformat()

        conflict = None
        if key_lower in self.entries:
            existing = self.entries[key_lower]
            if existing["value"] != value and existing["value"]:
                conflict = {
                    "field": key,
                    "old_value": existing["value"],
                    "new_value": value,
                    "old_source": existing.get("source", "unknown"),
                    "new_source": source,
                }

        self.entries[key_lower] = {
            "key": key.strip(),
            "value": value,
            "category": category,
            "source": source,
            "confidence": confidence,
            "updated_at": now,
        }

        self.history.append({
            "action": "set",
            "key": key_lower,
            "value": value,
            "source": source,
            "timestamp": now,
        })

        self.save()
        return conflict

    def get_entry(self, key):
        return self.entries.get(key.strip().lower())

    def find_match(self, field_name):
        """Fuzzy-match a form field name to a KB entry."""
        field_lower = field_name.strip().lower()

        # Direct match
        if field_lower in self.entries:
            return self.entries[field_lower]

        # Normalized match (remove special chars)
        normalized = re.sub(r"[^a-z0-9\s]", "", field_lower).strip()
        for key, entry in self.entries.items():
            key_norm = re.sub(r"[^a-z0-9\s]", "", key).strip()
            if key_norm == normalized:
                return entry

        # Partial / substring match
        best_match = None
        best_score = 0
        for key, entry in self.entries.items():
            # Check if key words appear in field name or vice versa
            key_words = set(re.sub(r"[^a-z0-9\s]", "", key).split())
            field_words = set(re.sub(r"[^a-z0-9\s]", "", field_lower).split())
            if not key_words or not field_words:
                continue
            overlap = key_words & field_words
            score = len(overlap) / max(len(key_words), len(field_words))
            if score > best_score and score >= 0.5:
                best_score = score
                best_match = entry

        return best_match

    def get_all(self):
        return self.entries

    def get_by_category(self):
        categorized = {}
        for key, entry in self.entries.items():
            cat = entry.get("category", "other")
            if cat not in categorized:
                categorized[cat] = []
            categorized[cat].append({"kb_key": key, **entry})
        return categorized

    def delete_entry(self, key):
        key_lower = key.strip().lower()
        if key_lower in self.entries:
            del self.entries[key_lower]
            self.save()
            return True
        return False

    def bulk_set(self, entries, source="upload"):
        """Set multiple entries, return list of conflicts."""
        conflicts = []
        for key, value in entries.items():
            if value and str(value).strip():
                conflict = self.set_entry(key, str(value).strip(), source=source)
                if conflict:
                    conflicts.append(conflict)
        return conflicts


# Global KB instance
kb = KnowledgeBase()


# ---------------------------------------------------------------------------
# Document Parsers
# ---------------------------------------------------------------------------

def parse_pdf_for_kb(filepath):
    """Extract key-value pairs from a PDF for knowledge base."""
    entries = {}
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            # Look for "Label: Value" patterns
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Colon-separated
                if ":" in line:
                    parts = line.split(":", 1)
                    if len(parts) == 2 and len(parts[0].strip()) < 60:
                        key = parts[0].strip()
                        val = parts[1].strip()
                        if key and val:
                            entries[key] = val
                # Tab-separated (common in forms)
                elif "\t" in line:
                    parts = line.split("\t", 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip()
                        if key and val:
                            entries[key] = val

            # Also extract from tables
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row and len(row) >= 2:
                        key = str(row[0] or "").strip()
                        val = str(row[1] or "").strip()
                        if key and val and len(key) < 60:
                            entries[key] = val
    return entries


def parse_excel_for_kb(filepath):
    """Extract key-value pairs from an Excel file."""
    entries = {}
    wb = load_workbook(filepath, data_only=True)
    for ws in wb.worksheets:
        # Check if first row looks like headers
        headers = []
        for row_idx, row in enumerate(ws.iter_rows(values_only=True), 1):
            cells = [str(c).strip() if c is not None else "" for c in row]
            if row_idx == 1 and any(cells):
                headers = cells
                continue
            # Try key-value pairs (2-column layout)
            if len(cells) >= 2 and cells[0] and cells[1] and len(cells[0]) < 60:
                entries[cells[0]] = cells[1]
            # Try header-based extraction
            elif headers:
                for i, val in enumerate(cells):
                    if i < len(headers) and headers[i] and val:
                        composite_key = headers[i]
                        entries[composite_key] = val
    return entries


def parse_docx_for_kb(filepath):
    """Extract key-value pairs from a Word document."""
    entries = {}
    doc = DocxDocument(filepath)

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        if ":" in text:
            parts = text.split(":", 1)
            if len(parts) == 2 and len(parts[0].strip()) < 60:
                key = parts[0].strip()
                val = parts[1].strip()
                if key and val:
                    entries[key] = val

    # Extract from tables
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if len(cells) >= 2 and cells[0] and cells[1] and len(cells[0]) < 60:
                entries[cells[0]] = cells[1]
    return entries


# ---------------------------------------------------------------------------
# PDF Form Field Detection & Filling
# ---------------------------------------------------------------------------

def detect_form_fields(filepath):
    """Detect form fields in a PDF, returning field info with positions."""
    fields = []

    # Method 1: AcroForm fields (interactive PDF forms)
    reader = PdfReader(filepath)
    if reader.get_fields():
        for field_name, field_obj in reader.get_fields().items():
            field_type = field_obj.get("/FT", "")
            field_value = field_obj.get("/V", "")
            if hasattr(field_value, "get_object"):
                field_value = str(field_value)
            fields.append({
                "id": str(uuid.uuid4())[:8],
                "name": field_name,
                "type": str(field_type).replace("/", ""),
                "current_value": str(field_value) if field_value else "",
                "source": "acroform",
                "page": 0,
            })

    # Method 2: Visual field detection from text layout
    with pdfplumber.open(filepath) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            width = page.width
            height = page.height

            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue

                # Detect "Label: ___" or "Label: " patterns
                patterns = [
                    (r"^(.{3,50}):\s*_{2,}", "underline"),
                    (r"^(.{3,50}):\s*$", "empty_colon"),
                    (r"^(.{3,50})\s*\[\s*\]", "checkbox"),
                    (r"^(.{3,50}):\s*\(\s*\)", "radio"),
                ]
                for pattern, ftype in patterns:
                    match = re.match(pattern, line)
                    if match:
                        fname = match.group(1).strip()
                        # Avoid picking up sentences
                        if len(fname.split()) <= 6:
                            fields.append({
                                "id": str(uuid.uuid4())[:8],
                                "name": fname,
                                "type": ftype,
                                "current_value": "",
                                "source": "detected",
                                "page": page_idx,
                            })
                        break

                # Detect "Label .......... Value" patterns
                dot_match = re.match(r"^(.{3,50})\s*\.{3,}\s*(.*)$", line)
                if dot_match:
                    fname = dot_match.group(1).strip()
                    fval = dot_match.group(2).strip()
                    if len(fname.split()) <= 6:
                        fields.append({
                            "id": str(uuid.uuid4())[:8],
                            "name": fname,
                            "type": "dotted",
                            "current_value": fval,
                            "source": "detected",
                            "page": page_idx,
                        })

    # Deduplicate by name
    seen = set()
    unique_fields = []
    for f in fields:
        if f["name"] not in seen:
            seen.add(f["name"])
            unique_fields.append(f)

    return unique_fields


def get_pdf_page_count(filepath):
    reader = PdfReader(filepath)
    return len(reader.pages)


def render_pdf_page_as_text(filepath, page_num):
    """Get text representation of a PDF page for display."""
    with pdfplumber.open(filepath) as pdf:
        if page_num < len(pdf.pages):
            return pdf.pages[page_num].extract_text() or ""
    return ""


# ---------------------------------------------------------------------------
# Sanity Checks
# ---------------------------------------------------------------------------

def run_sanity_checks(fields_with_values):
    """Run sanity checks on filled form fields."""
    issues = []

    for field in fields_with_values:
        name = field.get("name", "").lower()
        value = field.get("filled_value", "")
        if not value:
            continue

        # Date format check
        if any(w in name for w in ["date", "dob", "birth"]):
            if not re.match(r"\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}", value):
                if not re.match(r"\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2}", value):
                    issues.append({
                        "field": field["name"],
                        "type": "format",
                        "message": f"'{value}' may not be a valid date format",
                        "severity": "warning",
                    })

        # Email check
        if any(w in name for w in ["email", "e-mail"]):
            if not re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
                issues.append({
                    "field": field["name"],
                    "type": "format",
                    "message": f"'{value}' may not be a valid email",
                    "severity": "warning",
                })

        # Phone check
        if any(w in name for w in ["phone", "tel", "mobile", "fax"]):
            digits = re.sub(r"\D", "", value)
            if len(digits) < 7 or len(digits) > 15:
                issues.append({
                    "field": field["name"],
                    "type": "format",
                    "message": f"'{value}' may not be a valid phone number",
                    "severity": "warning",
                })

        # ZIP code check
        if any(w in name for w in ["zip", "postal"]):
            if not re.match(r"^\d{5}(-\d{4})?$", value):
                issues.append({
                    "field": field["name"],
                    "type": "format",
                    "message": f"'{value}' may not be a valid ZIP code",
                    "severity": "warning",
                })

        # SSN check
        if any(w in name for w in ["ssn", "social security"]):
            cleaned = re.sub(r"[\s\-]", "", value)
            if not re.match(r"^\d{9}$", cleaned):
                issues.append({
                    "field": field["name"],
                    "type": "format",
                    "message": f"SSN should be 9 digits",
                    "severity": "error",
                })

        # Empty required-looking fields
        if not value.strip():
            issues.append({
                "field": field["name"],
                "type": "missing",
                "message": "Field is empty",
                "severity": "info",
            })

    return issues


def check_cross_field_consistency(fields_with_values):
    """Check for logical consistency across fields."""
    issues = []
    values = {f["name"].lower(): f.get("filled_value", "") for f in fields_with_values}

    # Check name consistency
    full_name = values.get("full name", "")
    first_name = values.get("first name", "")
    last_name = values.get("last name", "")
    if full_name and first_name and first_name not in full_name:
        issues.append({
            "field": "First Name / Full Name",
            "type": "consistency",
            "message": f"First name '{first_name}' not found in full name '{full_name}'",
            "severity": "error",
        })
    if full_name and last_name and last_name not in full_name:
        issues.append({
            "field": "Last Name / Full Name",
            "type": "consistency",
            "message": f"Last name '{last_name}' not found in full name '{full_name}'",
            "severity": "error",
        })

    return issues


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/kb", methods=["GET"])
def get_knowledge_base():
    return jsonify({
        "entries": kb.get_all(),
        "categorized": kb.get_by_category(),
        "categories": kb.CATEGORIES,
        "count": len(kb.entries),
    })


@app.route("/api/kb/entry", methods=["POST"])
def set_kb_entry():
    data = request.json
    key = data.get("key", "")
    value = data.get("value", "")
    source = data.get("source", "manual")

    if not key:
        return jsonify({"error": "Key is required"}), 400

    conflict = kb.set_entry(key, value, source=source)
    return jsonify({
        "success": True,
        "conflict": conflict,
        "entry": kb.get_entry(key),
    })


@app.route("/api/kb/entry/<key>", methods=["DELETE"])
def delete_kb_entry(key):
    if kb.delete_entry(key):
        return jsonify({"success": True})
    return jsonify({"error": "Entry not found"}), 404


@app.route("/api/kb/bulk", methods=["POST"])
def bulk_set_kb():
    data = request.json
    entries = data.get("entries", {})
    source = data.get("source", "wizard")
    conflicts = kb.bulk_set(entries, source=source)
    return jsonify({
        "success": True,
        "count": len(entries),
        "conflicts": conflicts,
    })


@app.route("/api/kb/upload", methods=["POST"])
def upload_to_kb():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in (".pdf", ".xlsx", ".xls", ".docx", ".doc"):
        return jsonify({"error": "Unsupported file type. Use PDF, Excel, or Word."}), 400

    filepath = UPLOAD_DIR / f"kb_{uuid.uuid4().hex[:8]}{ext}"
    file.save(str(filepath))

    try:
        if ext == ".pdf":
            entries = parse_pdf_for_kb(str(filepath))
        elif ext in (".xlsx", ".xls"):
            entries = parse_excel_for_kb(str(filepath))
        elif ext in (".docx", ".doc"):
            entries = parse_docx_for_kb(str(filepath))
        else:
            entries = {}

        conflicts = kb.bulk_set(entries, source=f"upload:{file.filename}")

        return jsonify({
            "success": True,
            "extracted": len(entries),
            "entries": entries,
            "conflicts": conflicts,
        })
    except Exception as e:
        return jsonify({"error": f"Failed to parse file: {str(e)}"}), 500
    finally:
        filepath.unlink(missing_ok=True)


@app.route("/api/form/upload", methods=["POST"])
def upload_form():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    ext = Path(file.filename).suffix.lower()
    if ext != ".pdf":
        return jsonify({"error": "Form must be a PDF file"}), 400

    form_id = uuid.uuid4().hex[:8]
    filepath = UPLOAD_DIR / f"form_{form_id}{ext}"
    file.save(str(filepath))

    try:
        fields = detect_form_fields(str(filepath))
        page_count = get_pdf_page_count(str(filepath))

        # Auto-match fields to KB
        for field in fields:
            match = kb.find_match(field["name"])
            if match:
                field["kb_match"] = match["key"]
                field["filled_value"] = match["value"]
                field["fill_source"] = "knowledge_base"
                field["confidence"] = match.get("confidence", 1.0)
            else:
                field["kb_match"] = None
                field["filled_value"] = field.get("current_value", "")
                field["fill_source"] = "none"
                field["confidence"] = 0

        # Get page text for rendering
        pages = []
        for i in range(page_count):
            text = render_pdf_page_as_text(str(filepath), i)
            pages.append({"page_num": i, "text": text})

        return jsonify({
            "success": True,
            "form_id": form_id,
            "filename": file.filename,
            "page_count": page_count,
            "fields": fields,
            "pages": pages,
        })
    except Exception as e:
        return jsonify({"error": f"Failed to process form: {str(e)}"}), 500


@app.route("/api/form/fill", methods=["POST"])
def save_form_fills():
    """Save filled values back to KB and run sanity checks."""
    data = request.json
    fields = data.get("fields", [])
    save_to_kb = data.get("save_to_kb", True)

    # Save manual entries to KB
    if save_to_kb:
        for field in fields:
            if field.get("filled_value") and field.get("fill_source") in ("manual", "edited"):
                kb.set_entry(
                    field["name"],
                    field["filled_value"],
                    source="form_fill",
                )

    # Run sanity checks
    field_issues = run_sanity_checks(fields)
    consistency_issues = check_cross_field_consistency(fields)

    return jsonify({
        "success": True,
        "issues": field_issues + consistency_issues,
        "kb_updated": save_to_kb,
    })


@app.route("/api/form/sanity-check", methods=["POST"])
def sanity_check():
    """Run sanity checks on a set of fields."""
    data = request.json
    fields = data.get("fields", [])
    page = data.get("page", None)

    if page is not None:
        fields = [f for f in fields if f.get("page") == page]

    field_issues = run_sanity_checks(fields)
    consistency_issues = check_cross_field_consistency(fields)

    return jsonify({
        "issues": field_issues + consistency_issues,
        "page": page,
        "checked_count": len(fields),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000, host="0.0.0.0")
