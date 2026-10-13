#!/usr/bin/env python3
"""
FormFlow Google Sheets KB Database Operations

Replaces Supabase with a URL-accessible Google Sheet as the knowledge base.
All CRUD operations go through Google Sheets MCP tools.

Usage (as library, called by the skill):
    from formflow_sheets_db import SheetsKB
    kb = SheetsKB(sheet_id)
    kb.get_field("full_name")
    kb.set_field("full_name", "Trevor", category="personal", confidence=100)
    kb.search_fields("name")
    kb.log_session({...})
    kb.log_learning({...})

Usage (CLI for setup/debug):
    python formflow_sheets_db.py --action setup
    python formflow_sheets_db.py --action export --output kb_export.json
    python formflow_sheets_db.py --action stats
"""

import argparse
import json
import sys
import uuid
from datetime import datetime


KB_HEADERS = [
    "id", "category", "field_name", "field_value", "field_type",
    "confidence", "source", "alternates", "correction_count",
    "last_corrected", "correction_reason", "created_at", "updated_at"
]

SESSIONS_HEADERS = [
    "session_id", "form_name", "form_type", "fields_total", "fields_auto",
    "fields_corrected", "confidence_avg", "model_used", "cost",
    "duration_sec", "source_path", "output_path", "timestamp"
]

LEARNING_HEADERS = [
    "id", "event_type", "field_name", "detail",
    "action_taken", "model_used", "timestamp"
]

WORKFLOWS_HEADERS = [
    "workflow_id", "form_type", "form_pattern", "field_map_json",
    "save_location", "jev_tier", "created_at"
]

VALID_CATEGORIES = [
    "personal", "contact", "address", "employment", "education",
    "financial", "medical", "legal", "business", "construction", "other"
]

VALID_FIELD_TYPES = [
    "text", "date", "email", "phone", "zip", "ssn", "ein",
    "number", "currency", "checkbox", "select"
]

VALID_SOURCES = [
    "wizard", "drive_scan", "manual", "form_fill", "ingestion", "learning_loop"
]


def generate_id():
    return str(uuid.uuid4())[:12]


def now_iso():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def build_kb_row(field_name, field_value, category="other", field_type="text",
                 confidence=80, source="manual", alternates="", correction_count=0):
    if category not in VALID_CATEGORIES:
        category = "other"
    if field_type not in VALID_FIELD_TYPES:
        field_type = "text"
    if source not in VALID_SOURCES:
        source = "manual"

    now = now_iso()
    return [
        generate_id(), category, field_name, str(field_value), field_type,
        str(int(confidence)), source, alternates, str(int(correction_count)),
        "", "", now, now
    ]


def build_session_row(form_name, form_type, fields_total, fields_auto,
                      fields_corrected, confidence_avg, model_used="regex",
                      cost=0.0, duration_sec=0, source_path="", output_path=""):
    return [
        generate_id(), form_name, form_type, str(fields_total), str(fields_auto),
        str(fields_corrected), str(round(confidence_avg, 1)), model_used,
        str(round(cost, 4)), str(int(duration_sec)), source_path, output_path,
        now_iso()
    ]


def build_learning_row(event_type, field_name, detail, action_taken="", model_used=""):
    return [
        generate_id(), event_type, field_name, detail,
        action_taken, model_used, now_iso()
    ]


def build_workflow_row(form_type, form_pattern, field_map, save_location, jev_tier=0):
    return [
        generate_id(), form_type, form_pattern, json.dumps(field_map),
        save_location, str(jev_tier), now_iso()
    ]


PREWIRED_WORKFLOWS = [
    {
        "form_type": "w9",
        "form_pattern": "W-9|W9|Request for Taxpayer",
        "field_map": {
            "Name.*tax return": "business_name",
            "Business name": "dba_name",
            "Federal tax classification": "tax_classification",
            "Address": "address",
            "City.*state.*ZIP": "city_state_zip",
            "Taxpayer Identification Number": "ein",
            "Social security number": "ssn"
        },
        "save_location": "!Company Documents",
        "jev_tier": 0
    },
    {
        "form_type": "w4",
        "form_pattern": "W-4|W4|Employee.s Withholding",
        "field_map": {
            "First name": "first_name",
            "Last name": "last_name",
            "Social security": "ssn",
            "Address": "address",
            "Filing status": "filing_status"
        },
        "save_location": "Employee folder",
        "jev_tier": 0
    },
    {
        "form_type": "i9",
        "form_pattern": "I-9|I9|Employment Eligibility",
        "field_map": {
            "Last Name": "last_name",
            "First Name": "first_name",
            "Date of Birth": "dob",
            "Social Security": "ssn",
            "Address": "address",
            "Citizenship": "citizenship"
        },
        "save_location": "Employee folder",
        "jev_tier": 0
    },
    {
        "form_type": "insurance_cert",
        "form_pattern": "Certificate of Insurance|ACORD 25|COI",
        "field_map": {
            "Named Insured": "company_name",
            "Policy Number": "policy_number",
            "Producer": "insurance_agent",
            "General Liability": "gl_limit",
            "Auto Liability": "auto_limit"
        },
        "save_location": "2.7",
        "jev_tier": 0
    },
    {
        "form_type": "lien_waiver",
        "form_pattern": "Lien Waiver|Waiver of Lien|Release of Lien",
        "field_map": {
            "Claimant": "company_name",
            "Project": "project_name",
            "Amount": "waiver_amount",
            "Through Date": "waiver_through_date"
        },
        "save_location": "2.8",
        "jev_tier": 0
    },
    {
        "form_type": "hub_mbe",
        "form_pattern": "HUB|MBE|DBE|SBE|Certification|Disadvantaged",
        "field_map": {
            "Company": "company_name",
            "Certification Type": "cert_type",
            "Certification Number": "cert_number",
            "Expiration": "cert_expiry"
        },
        "save_location": "13.1",
        "jev_tier": 0
    },
    {
        "form_type": "sam_registration",
        "form_pattern": "SAM|System for Award Management|sam\\.gov",
        "field_map": {
            "Legal Business Name": "company_name",
            "DUNS": "duns_number",
            "CAGE": "cage_code",
            "EIN": "ein",
            "NAICS": "naics_codes"
        },
        "save_location": "!Company Documents",
        "jev_tier": 0
    },
    {
        "form_type": "vendor_registration",
        "form_pattern": "Vendor Registration|Vendor Application|Supplier Registration",
        "field_map": {
            "Company Name": "company_name",
            "Tax ID": "ein",
            "Contact": "contact_name",
            "Phone": "phone",
            "Email": "email",
            "Insurance": "has_insurance"
        },
        "save_location": "!Company Documents",
        "jev_tier": 0
    },
    {
        "form_type": "bid_form",
        "form_pattern": "Bid Form|Proposal Form|Bid Schedule",
        "field_map": {
            "Project": "project_name",
            "Bidder": "company_name",
            "Base Bid": "bid_amount",
            "Addenda": "addenda_acknowledged"
        },
        "save_location": "4.1",
        "jev_tier": 0
    },
    {
        "form_type": "subcontractor_prequalification",
        "form_pattern": "Prequalification|Pre-Qualification|Subcontractor Qualification",
        "field_map": {
            "Company Name": "company_name",
            "Bonding Capacity": "bonding_capacity",
            "Years Experience": "years_experience",
            "EMR": "emr_rate"
        },
        "save_location": "4.3",
        "jev_tier": 0
    },
    {
        "form_type": "daily_report",
        "form_pattern": "Daily Report|Daily Log|Field Report",
        "field_map": {
            "Project": "project_name",
            "Date": "report_date",
            "Weather": "weather",
            "Manpower": "manpower_count"
        },
        "save_location": "10.2",
        "jev_tier": 0
    },
    {
        "form_type": "nda",
        "form_pattern": "Non-Disclosure|NDA|Confidentiality Agreement",
        "field_map": {
            "Party": "company_name",
            "Signer": "signer_name",
            "Title": "signer_title",
            "Date": "effective_date"
        },
        "save_location": "2.1",
        "jev_tier": 0
    }
]


def get_setup_tab_data():
    """Returns dict of tab_name -> [headers, ...prewired_rows]."""
    tabs = {
        "KB": [KB_HEADERS],
        "Sessions": [SESSIONS_HEADERS],
        "Learning": [LEARNING_HEADERS],
        "Workflows": [WORKFLOWS_HEADERS]
    }

    for wf in PREWIRED_WORKFLOWS:
        tabs["Workflows"].append(build_workflow_row(
            wf["form_type"], wf["form_pattern"], wf["field_map"],
            wf["save_location"], wf["jev_tier"]
        ))

    return tabs


def fuzzy_match_field(query, kb_entries, threshold=60):
    """Simple fuzzy matching for field names against KB entries.

    Returns list of (entry, score) tuples sorted by score descending.
    """
    from difflib import SequenceMatcher

    query_lower = query.lower().strip()
    query_normalized = query_lower.replace(" ", "_").replace("-", "_")

    results = []
    for entry in kb_entries:
        field_name = entry.get("field_name", "").lower()

        if field_name == query_normalized:
            results.append((entry, 100))
            continue

        if query_normalized in field_name or field_name in query_normalized:
            results.append((entry, 90))
            continue

        ratio = SequenceMatcher(None, query_normalized, field_name).ratio()
        score = int(ratio * 100)
        if score >= threshold:
            results.append((entry, score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def parse_kb_rows(rows):
    """Parse raw sheet rows (list of lists) into list of dicts using KB_HEADERS."""
    if not rows or len(rows) < 2:
        return []

    headers = rows[0]
    entries = []
    for row in rows[1:]:
        entry = {}
        for i, header in enumerate(headers):
            entry[header] = row[i] if i < len(row) else ""
        entries.append(entry)
    return entries


def detect_contradictions(field_name, new_value, kb_entries):
    """Check if a new value contradicts an existing KB entry."""
    contradictions = []
    for entry in kb_entries:
        if entry.get("field_name") == field_name:
            existing = entry.get("field_value", "")
            if existing and existing.lower() != new_value.lower():
                contradictions.append({
                    "field_name": field_name,
                    "existing_value": existing,
                    "existing_confidence": int(entry.get("confidence", 0)),
                    "existing_source": entry.get("source", ""),
                    "new_value": new_value
                })
    return contradictions


def merge_alternates(existing_alternates, new_value):
    """Add a value to the pipe-delimited alternates list if not already present."""
    alts = [a.strip() for a in existing_alternates.split("|") if a.strip()]
    if new_value.strip() and new_value.strip() not in alts:
        alts.append(new_value.strip())
    return "|".join(alts)


def compute_kb_stats(kb_entries):
    """Compute stats from KB entries for reporting."""
    if not kb_entries:
        return {"total": 0, "by_category": {}, "by_source": {},
                "avg_confidence": 0, "high_correction_fields": []}

    by_category = {}
    by_source = {}
    confidences = []
    high_correction = []

    for entry in kb_entries:
        cat = entry.get("category", "other")
        src = entry.get("source", "unknown")
        conf = int(entry.get("confidence", 0))
        corrections = int(entry.get("correction_count", 0))

        by_category[cat] = by_category.get(cat, 0) + 1
        by_source[src] = by_source.get(src, 0) + 1
        confidences.append(conf)

        if corrections >= 3:
            high_correction.append({
                "field_name": entry.get("field_name"),
                "correction_count": corrections,
                "current_value": entry.get("field_value"),
                "confidence": conf
            })

    avg_conf = sum(confidences) / len(confidences) if confidences else 0

    return {
        "total": len(kb_entries),
        "by_category": by_category,
        "by_source": by_source,
        "avg_confidence": round(avg_conf, 1),
        "high_correction_fields": sorted(
            high_correction, key=lambda x: x["correction_count"], reverse=True
        )
    }


def compute_session_stats(session_rows):
    """Compute fill session stats for the learning loop."""
    if not session_rows:
        return {"total_sessions": 0, "avg_auto_rate": 0, "total_cost": 0,
                "by_form_type": {}, "low_auto_rate_types": []}

    by_type = {}
    costs = []
    auto_rates = []

    for row in session_rows:
        ft = row.get("form_type", "general")
        total = int(row.get("fields_total", 0)) or 1
        auto = int(row.get("fields_auto", 0))
        cost = float(row.get("cost", 0))

        rate = (auto / total) * 100
        auto_rates.append(rate)
        costs.append(cost)

        if ft not in by_type:
            by_type[ft] = {"count": 0, "auto_rates": []}
        by_type[ft]["count"] += 1
        by_type[ft]["auto_rates"].append(rate)

    low_auto = []
    for ft, data in by_type.items():
        avg_rate = sum(data["auto_rates"]) / len(data["auto_rates"])
        if avg_rate < 60 and data["count"] >= 2:
            low_auto.append({"form_type": ft, "avg_auto_rate": round(avg_rate, 1),
                             "session_count": data["count"]})

    return {
        "total_sessions": len(session_rows),
        "avg_auto_rate": round(sum(auto_rates) / len(auto_rates), 1) if auto_rates else 0,
        "total_cost": round(sum(costs), 4),
        "by_form_type": {k: v["count"] for k, v in by_type.items()},
        "low_auto_rate_types": low_auto
    }


def main():
    parser = argparse.ArgumentParser(description="FormFlow Google Sheets KB Operations")
    parser.add_argument("--action", choices=["setup", "export", "stats", "seed-workflows"],
                        required=True)
    parser.add_argument("--output", default=None, help="Output file for export")
    parser.add_argument("--kb-json", default=None, help="KB data as JSON (for import)")
    args = parser.parse_args()

    if args.action == "setup":
        tabs = get_setup_tab_data()
        print(json.dumps(tabs, indent=2))
        print(f"\nSetup data for {len(tabs)} tabs generated.")
        print("Use Google Sheets MCP tools to create the sheet and write headers.")

    elif args.action == "export":
        print("Export requires live Sheet access via MCP tools.")
        print("Use mcp__Google_Sheets__get_values to read KB tab, then save locally.")

    elif args.action == "stats":
        if args.kb_json:
            with open(args.kb_json) as f:
                data = json.load(f)
            stats = compute_kb_stats(data)
            print(json.dumps(stats, indent=2))
        else:
            print("Provide --kb-json with KB entries for offline stats.")

    elif args.action == "seed-workflows":
        workflows = []
        for wf in PREWIRED_WORKFLOWS:
            workflows.append(build_workflow_row(
                wf["form_type"], wf["form_pattern"], wf["field_map"],
                wf["save_location"], wf["jev_tier"]
            ))
        print(json.dumps(workflows, indent=2))
        print(f"\n{len(workflows)} prewired workflows ready to append.")


if __name__ == "__main__":
    main()
