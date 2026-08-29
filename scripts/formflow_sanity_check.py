#!/usr/bin/env python3
"""
FormFlow Sanity Check — Validates filled form fields for format correctness
and cross-field consistency.

Usage:
    python scripts/formflow_sanity_check.py \
        --filled filled_fields.json \
        --kb kb_snapshot.json \
        --output-json sanity_report.json
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


FORMAT_VALIDATORS = {
    "date": {
        "patterns": [
            r"^\d{1,2}/\d{1,2}/\d{4}$",
            r"^\d{4}-\d{2}-\d{2}$",
            r"^\d{1,2}-\d{1,2}-\d{4}$",
            r"^\w+ \d{1,2},? \d{4}$",
        ],
        "message": "Expected date format (MM/DD/YYYY, YYYY-MM-DD, etc.)",
    },
    "email": {
        "patterns": [r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"],
        "message": "Invalid email address format",
    },
    "phone": {
        "patterns": [
            r"^\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}$",
            r"^\+?1?[\s.\-]?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}$",
            r"^\d{10,11}$",
        ],
        "message": "Invalid phone number format",
    },
    "zip": {
        "patterns": [r"^\d{5}(-\d{4})?$"],
        "message": "Invalid ZIP code (expected 5 or 9 digits)",
    },
    "ssn": {
        "patterns": [r"^\d{3}-?\d{2}-?\d{4}$"],
        "message": "Invalid SSN format (expected XXX-XX-XXXX)",
    },
}


def validate_format(field_name, field_value, field_type):
    if not field_value or not field_value.strip():
        return None

    validator = FORMAT_VALIDATORS.get(field_type)
    if not validator:
        return None

    for pattern in validator["patterns"]:
        if re.match(pattern, field_value.strip()):
            return None

    return {
        "type": "format_error",
        "severity": "warning",
        "field": field_name,
        "value": field_value,
        "expected_type": field_type,
        "message": validator["message"],
    }


def check_required_fields(fields):
    issues = []
    for field in fields:
        if field.get("required") and not field.get("field_value", "").strip():
            issues.append({
                "type": "missing_required",
                "severity": "error",
                "field": field["field_name"],
                "message": f"Required field '{field.get('field_name_raw', field['field_name'])}' is empty",
            })
    return issues


def check_cross_field_consistency(fields):
    issues = []
    field_map = {f["field_name"]: f.get("field_value", "") for f in fields}

    first = field_map.get("first_name", "")
    last = field_map.get("last_name", "")
    full = field_map.get("full_name", "")
    if first and last and full:
        expected = f"{first} {last}"
        if full.lower() != expected.lower() and full.lower() != f"{last}, {first}".lower():
            issues.append({
                "type": "consistency_error",
                "severity": "warning",
                "field": "full_name",
                "value": full,
                "message": f"Full name '{full}' doesn't match first '{first}' + last '{last}'",
                "related_fields": ["first_name", "last_name"],
            })

    dob = field_map.get("date_of_birth", "") or field_map.get("dob", "")
    age = field_map.get("age", "")
    if dob and age:
        try:
            for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"]:
                try:
                    birth = datetime.strptime(dob, fmt)
                    break
                except ValueError:
                    continue
            else:
                birth = None

            if birth:
                today = datetime.now()
                calc_age = today.year - birth.year - (
                    (today.month, today.day) < (birth.month, birth.day)
                )
                if abs(calc_age - int(age)) > 1:
                    issues.append({
                        "type": "consistency_error",
                        "severity": "warning",
                        "field": "age",
                        "value": age,
                        "message": f"Age {age} doesn't match DOB {dob} (calculated: {calc_age})",
                        "related_fields": ["date_of_birth"],
                    })
        except (ValueError, TypeError):
            pass

    city = field_map.get("city", "")
    state = field_map.get("state", "")
    zip_code = field_map.get("zip_code", "") or field_map.get("zip", "")
    if city and not state and zip_code:
        issues.append({
            "type": "consistency_warning",
            "severity": "info",
            "field": "state",
            "message": f"City '{city}' and ZIP '{zip_code}' provided but state is missing",
            "related_fields": ["city", "zip_code"],
        })

    return issues


def check_kb_contradictions(fields, kb_entries):
    issues = []
    if not kb_entries:
        return issues

    kb_map = {}
    for entry in kb_entries:
        name = entry.get("field_name", "").lower()
        val = entry.get("field_value", "")
        if val:
            kb_map[name] = entry

    for field in fields:
        fname = field["field_name"].lower()
        fval = field.get("field_value", "").strip()
        if not fval:
            continue

        kb_entry = kb_map.get(fname)
        if kb_entry and kb_entry["field_value"].strip():
            kb_val = kb_entry["field_value"].strip()
            if fval.lower() != kb_val.lower():
                issues.append({
                    "type": "kb_contradiction",
                    "severity": "warning",
                    "field": field["field_name"],
                    "value": fval,
                    "kb_value": kb_val,
                    "kb_source": kb_entry.get("source", "unknown"),
                    "message": f"Value '{fval}' contradicts KB value '{kb_val}'",
                })

    return issues


def check_duplicates(fields):
    issues = []
    seen = {}
    for field in fields:
        val = field.get("field_value", "").strip()
        if not val or len(val) < 3:
            continue

        fname = field["field_name"]
        if val in seen and seen[val] != fname:
            issues.append({
                "type": "duplicate_value",
                "severity": "info",
                "field": fname,
                "value": val,
                "message": f"Same value '{val}' used in both '{seen[val]}' and '{fname}'",
                "related_fields": [seen[val]],
            })
        seen[val] = fname

    return issues


def run_sanity_checks(fields, kb_entries=None):
    all_issues = []

    for field in fields:
        fmt_issue = validate_format(
            field["field_name"],
            field.get("field_value", ""),
            field.get("field_type", "text"),
        )
        if fmt_issue:
            all_issues.append(fmt_issue)

    all_issues.extend(check_required_fields(fields))
    all_issues.extend(check_cross_field_consistency(fields))
    all_issues.extend(check_duplicates(fields))

    if kb_entries:
        all_issues.extend(check_kb_contradictions(fields, kb_entries))

    severity_order = {"error": 0, "warning": 1, "info": 2}
    all_issues.sort(key=lambda x: severity_order.get(x.get("severity", "info"), 3))

    return all_issues


def main():
    parser = argparse.ArgumentParser(description="FormFlow Sanity Check")
    parser.add_argument("--filled", required=True, help="Filled fields JSON")
    parser.add_argument("--kb", help="KB snapshot JSON (optional)")
    parser.add_argument("--output-json", required=True, help="Output report JSON")
    args = parser.parse_args()

    filled_path = Path(args.filled)
    if not filled_path.exists():
        print(f"ERROR: File not found: {filled_path}")
        sys.exit(1)

    with open(filled_path) as f:
        data = json.load(f)
    fields = data if isinstance(data, list) else data.get("fields", data.get("entries", []))

    kb_entries = None
    if args.kb:
        kb_path = Path(args.kb)
        if kb_path.exists():
            with open(kb_path) as f:
                kb_data = json.load(f)
            kb_entries = kb_data if isinstance(kb_data, list) else kb_data.get("entries", [])

    print(f"Running sanity checks on {len(fields)} fields...")
    issues = run_sanity_checks(fields, kb_entries)

    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")
    infos = sum(1 for i in issues if i["severity"] == "info")

    report = {
        "field_count": len(fields),
        "issue_count": len(issues),
        "errors": errors,
        "warnings": warnings,
        "info": infos,
        "passed": errors == 0,
        "issues": issues,
    }

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nSanity Check Results:")
    print(f"  Fields checked: {len(fields)}")
    print(f"  Errors:   {errors}")
    print(f"  Warnings: {warnings}")
    print(f"  Info:     {infos}")
    print(f"  Status:   {'PASSED' if errors == 0 else 'FAILED'}")
    print(f"\nReport saved to {output_path}")


if __name__ == "__main__":
    main()
