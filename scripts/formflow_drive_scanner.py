#!/usr/bin/env python3
"""
FormFlow Drive KB Prefill Scanner

Scans NTXP Google Drive for completed forms, applications, registrations,
licenses, RFP responses, and contracts to extract field values and seed
the FormFlow Knowledge Base.

Designed for JEV-optimized scanning:
  - Tier 0: Regex on filename/metadata ($0)
  - Tier 1: Simple text extraction (DeepSeek/Haiku, ~$0.001)
  - Tier 2: Complex document parsing (Sonnet, ~$0.01)

Usage (as library):
    from formflow_drive_scanner import DriveScanner
    scanner = DriveScanner()
    results = scanner.classify_file("W-9 NTXP LLC.pdf")
    fields = scanner.extract_from_text(text_content, form_type)

Usage (CLI):
    python formflow_drive_scanner.py --classify "W-9 NTXP LLC.pdf"
    python formflow_drive_scanner.py --scan-plan
    python formflow_drive_scanner.py --extract-text "raw text" --form-type w9
"""

import argparse
import json
import re
import sys


SCAN_LOCATIONS = [
    {
        "path": "!Company Documents",
        "description": "Registrations, licenses, insurance certs, tax forms",
        "expected_types": ["w9", "vendor_registration", "sam_registration",
                          "business_license", "insurance_cert"],
        "priority": 1
    },
    {
        "path": "!Active Bids",
        "description": "RFP responses, bid forms, capability statements",
        "expected_types": ["bid_form", "capability_statement",
                          "subcontractor_prequalification"],
        "priority": 2
    },
    {
        "path": "!Active Projects/*/2.1",
        "description": "Contracts, NTP letters",
        "expected_types": ["nda", "contract"],
        "priority": 3
    },
    {
        "path": "!Active Projects/*/2.7",
        "description": "Insurance certificates",
        "expected_types": ["insurance_cert"],
        "priority": 3
    },
    {
        "path": "!Active Projects/*/2.8",
        "description": "Lien waivers",
        "expected_types": ["lien_waiver"],
        "priority": 3
    },
    {
        "path": "!Active Projects/*/13",
        "description": "HUB/MBE certifications",
        "expected_types": ["hub_mbe"],
        "priority": 3
    }
]

FILENAME_CLASSIFIERS = [
    {
        "pattern": r"(?i)(W-?9|Request\s+for\s+Taxpayer)",
        "form_type": "w9",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(W-?4|Employee.s?\s+Withholding)",
        "form_type": "w4",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(I-?9|Employment\s+Eligibility)",
        "form_type": "i9",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(Certificate\s+of\s+Insurance|ACORD\s*25|COI\b)",
        "form_type": "insurance_cert",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(Lien\s+Waiver|Waiver\s+of\s+Lien|Release\s+of\s+Lien)",
        "form_type": "lien_waiver",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(HUB|MBE|DBE|SBE)\s*(Cert|Form|Application)",
        "form_type": "hub_mbe",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(SAM\s+Registration|sam\.gov|System\s+for\s+Award)",
        "form_type": "sam_registration",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(Vendor\s+Registration|Vendor\s+Application|Supplier\s+Reg)",
        "form_type": "vendor_registration",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(Bid\s+Form|Proposal\s+Form|Bid\s+Schedule)",
        "form_type": "bid_form",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(Pre-?[Qq]ualification|Subcontractor\s+Qual)",
        "form_type": "subcontractor_prequalification",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(Daily\s+Report|Daily\s+Log|Field\s+Report)",
        "form_type": "daily_report",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(NDA|Non-?Disclosure|Confidentiality\s+Agreement)",
        "form_type": "nda",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(Credit\s+Application|Credit\s+App)",
        "form_type": "credit_application",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(Business\s+License|License\s+Application)",
        "form_type": "business_license",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(Capability\s+Statement|Capabilities)",
        "form_type": "capability_statement",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(Safety\s+Checklist|Safety\s+Form|JHA|JSA)",
        "form_type": "safety_checklist",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(Punch\s*List|Deficiency\s+List)",
        "form_type": "punch_list",
        "jev_tier": 0
    },
    {
        "pattern": r"(?i)(Inspection\s+Request|Request\s+for\s+Inspection)",
        "form_type": "inspection_request",
        "jev_tier": 0
    }
]

CONTENT_EXTRACTORS = {
    "company_info": [
        (r"(?i)(?:Company|Business|Legal)\s*(?:Name|Entity)\s*[:\-]?\s*(.+?)(?:\n|$)", "company_name"),
        (r"(?i)(?:DBA|Trade\s+Name|Doing\s+Business)\s*[:\-]?\s*(.+?)(?:\n|$)", "dba_name"),
        (r"(?i)(?:EIN|Tax\s*(?:ID|Identification))\s*[:\-]?\s*(\d{2}-?\d{7})", "ein"),
        (r"(?i)(?:DUNS)\s*[:\-#]?\s*(\d{9})", "duns_number"),
        (r"(?i)(?:CAGE)\s*[:\-#]?\s*([A-Z0-9]{5})", "cage_code"),
        (r"(?i)(?:NAICS)\s*[:\-#]?\s*([\d,\s]+)", "naics_codes"),
    ],
    "personal_info": [
        (r"(?i)(?:Full\s+Name|Name)\s*[:\-]?\s*([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", "full_name"),
        (r"(?i)(?:First\s+Name)\s*[:\-]?\s*([A-Z][a-z]+)", "first_name"),
        (r"(?i)(?:Last\s+Name)\s*[:\-]?\s*([A-Z][a-z]+)", "last_name"),
        (r"(?i)(?:SSN|Social\s+Security)\s*[:\-]?\s*(\d{3}-?\d{2}-?\d{4})", "ssn"),
        (r"(?i)(?:Date\s+of\s+Birth|DOB|Birth\s*Date)\s*[:\-]?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", "dob"),
    ],
    "contact_info": [
        (r"(?i)(?:Email|E-?mail)\s*[:\-]?\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", "email"),
        (r"(?i)(?:Phone|Tel|Telephone)\s*[:\-]?\s*(\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4})", "phone"),
        (r"(?i)(?:Fax)\s*[:\-]?\s*(\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4})", "fax"),
    ],
    "address_info": [
        (r"(?i)(?:Address|Street)\s*[:\-]?\s*(\d+\s+[A-Za-z\s]+(?:St|Ave|Blvd|Dr|Rd|Ln|Way|Ct|Pkwy|Hwy)[.\s])", "street_address"),
        (r"(?i)(?:City)\s*[:\-]?\s*([A-Za-z\s]+?)(?:\s*,|\s+[A-Z]{2}|\n|$)", "city"),
        (r"(?i)(?:State)\s*[:\-]?\s*([A-Z]{2})", "state"),
        (r"(?i)(?:ZIP|Zip\s*Code|Postal)\s*[:\-]?\s*(\d{5}(?:-\d{4})?)", "zip_code"),
    ],
    "insurance_info": [
        (r"(?i)(?:Policy\s*(?:Number|#|No))\s*[:\-]?\s*([A-Z0-9\-]+)", "policy_number"),
        (r"(?i)(?:Agent|Producer|Broker)\s*[:\-]?\s*(.+?)(?:\n|$)", "insurance_agent"),
        (r"(?i)(?:General\s+Liability|GL)\s*[:\$]?\s*([\d,]+)", "gl_limit"),
        (r"(?i)(?:Expir|Exp)\s*[:\-]?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", "insurance_expiry"),
    ],
    "certification_info": [
        (r"(?i)(?:Cert(?:ification)?\s*(?:Number|#|No))\s*[:\-]?\s*([A-Z0-9\-]+)", "cert_number"),
        (r"(?i)(?:Cert(?:ification)?\s*Type)\s*[:\-]?\s*(.+?)(?:\n|$)", "cert_type"),
        (r"(?i)(?:Expir|Valid\s+(?:Through|Until))\s*[:\-]?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", "cert_expiry"),
    ]
}

FORM_TYPE_TO_EXTRACTORS = {
    "w9": ["company_info", "personal_info", "address_info"],
    "w4": ["personal_info", "address_info"],
    "i9": ["personal_info", "address_info"],
    "insurance_cert": ["company_info", "insurance_info", "contact_info"],
    "lien_waiver": ["company_info"],
    "hub_mbe": ["company_info", "certification_info"],
    "sam_registration": ["company_info", "contact_info", "address_info"],
    "vendor_registration": ["company_info", "contact_info", "address_info"],
    "bid_form": ["company_info"],
    "subcontractor_prequalification": ["company_info", "contact_info"],
    "nda": ["company_info", "personal_info"],
    "credit_application": ["company_info", "contact_info", "address_info"],
    "business_license": ["company_info", "address_info"],
    "capability_statement": ["company_info", "contact_info"],
    "daily_report": [],
    "safety_checklist": [],
    "punch_list": [],
    "inspection_request": [],
}


def classify_file(filename):
    """Classify a file by its name using regex (JEV Tier 0, $0).

    Returns: {"form_type": str, "jev_tier": int, "confidence": int} or None
    """
    for classifier in FILENAME_CLASSIFIERS:
        if re.search(classifier["pattern"], filename):
            return {
                "form_type": classifier["form_type"],
                "jev_tier": classifier["jev_tier"],
                "confidence": 95,
                "method": "filename_regex"
            }
    return None


def classify_content(text, max_chars=500):
    """Classify a document by its first N characters of content (JEV Tier 0).

    Falls back when filename classification fails. Still regex-based, $0.
    """
    snippet = text[:max_chars]
    for classifier in FILENAME_CLASSIFIERS:
        if re.search(classifier["pattern"], snippet):
            return {
                "form_type": classifier["form_type"],
                "jev_tier": 0,
                "confidence": 80,
                "method": "content_regex"
            }
    return None


def extract_fields_from_text(text, form_type=None):
    """Extract field values from document text using regex (JEV Tier 0, $0).

    If form_type is known, uses targeted extractors. Otherwise tries all.
    Returns list of {field_name, field_value, category, confidence, source}.
    """
    extractor_groups = []

    if form_type and form_type in FORM_TYPE_TO_EXTRACTORS:
        extractor_groups = FORM_TYPE_TO_EXTRACTORS[form_type]
    else:
        extractor_groups = list(CONTENT_EXTRACTORS.keys())

    results = []
    seen_fields = set()

    for group_name in extractor_groups:
        patterns = CONTENT_EXTRACTORS.get(group_name, [])
        category = _group_to_category(group_name)

        for pattern, field_name in patterns:
            if field_name in seen_fields:
                continue

            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip()
                if value and len(value) > 1:
                    seen_fields.add(field_name)
                    results.append({
                        "field_name": field_name,
                        "field_value": value,
                        "category": category,
                        "field_type": _infer_field_type(field_name, value),
                        "confidence": 75,
                        "source": "drive_scan"
                    })

    return results


def _group_to_category(group_name):
    mapping = {
        "company_info": "business",
        "personal_info": "personal",
        "contact_info": "contact",
        "address_info": "address",
        "insurance_info": "financial",
        "certification_info": "legal"
    }
    return mapping.get(group_name, "other")


def _infer_field_type(field_name, value):
    if field_name in ("ssn",):
        return "ssn"
    if field_name in ("ein",):
        return "ein"
    if field_name in ("email",):
        return "email"
    if field_name in ("phone", "fax"):
        return "phone"
    if field_name in ("zip_code",):
        return "zip"
    if field_name in ("dob", "insurance_expiry", "cert_expiry"):
        return "date"
    if field_name in ("gl_limit", "auto_limit", "bid_amount", "waiver_amount"):
        return "currency"
    if re.match(r"^\d+$", value):
        return "number"
    return "text"


def filter_scannable_files(file_list):
    """Filter a Drive file list to only scannable document types."""
    scannable_types = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.google-apps.document",
        "application/vnd.google-apps.spreadsheet",
    }
    scannable_extensions = {".pdf", ".docx", ".xlsx", ".doc", ".xls"}

    results = []
    for f in file_list:
        mime = f.get("mimeType", "")
        name = f.get("name", f.get("title", ""))
        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""

        if mime in scannable_types or ext in scannable_extensions:
            results.append(f)

    return results


def generate_scan_plan():
    """Generate the Drive scan plan showing locations, expected yields, and costs."""
    plan = {
        "locations": SCAN_LOCATIONS,
        "estimated_cost": "$0 (all Tier 0 regex)",
        "estimated_time": "30-120 seconds depending on Drive size",
        "strategy": [
            "1. List files via mcp__Google_Drive__search_files — no inference cost",
            "2. Filter by type: PDF, DOCX, XLSX only — regex on filename, $0",
            "3. Classify each filename through Tier 0 regex classifiers",
            "4. Read content of classified files via mcp__Google_Drive__read_file_content",
            "5. Extract fields using regex patterns — $0",
            "6. Only invoke model inference on files regex can't parse",
            "7. Deduplicate against existing KB before inserting",
            "8. Log every scan result to Learning tab"
        ],
        "classifier_count": len(FILENAME_CLASSIFIERS),
        "extractor_count": sum(len(v) for v in CONTENT_EXTRACTORS.values())
    }
    return plan


def main():
    parser = argparse.ArgumentParser(description="FormFlow Drive KB Prefill Scanner")
    parser.add_argument("--classify", type=str, help="Classify a filename")
    parser.add_argument("--scan-plan", action="store_true", help="Show scan plan")
    parser.add_argument("--extract-text", type=str, help="Extract fields from text")
    parser.add_argument("--form-type", type=str, default=None, help="Known form type")
    parser.add_argument("--output-json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.classify:
        result = classify_file(args.classify)
        if result:
            print(json.dumps(result, indent=2))
        else:
            print(json.dumps({"form_type": None, "jev_tier": 1,
                             "confidence": 0, "method": "needs_model_inference"}))

    elif args.scan_plan:
        plan = generate_scan_plan()
        if args.output_json:
            print(json.dumps(plan, indent=2))
        else:
            print("FormFlow Drive Scan Plan")
            print("=" * 50)
            for loc in plan["locations"]:
                print(f"\n  [{loc['priority']}] {loc['path']}")
                print(f"      {loc['description']}")
                print(f"      Expected: {', '.join(loc['expected_types'])}")
            print(f"\n  Cost: {plan['estimated_cost']}")
            print(f"  Classifiers: {plan['classifier_count']}")
            print(f"  Extractors: {plan['extractor_count']}")
            print(f"\n  Strategy:")
            for step in plan["strategy"]:
                print(f"    {step}")

    elif args.extract_text:
        text = args.extract_text
        if text == "-":
            text = sys.stdin.read()
        fields = extract_fields_from_text(text, form_type=args.form_type)
        print(json.dumps(fields, indent=2))
        print(f"\nExtracted {len(fields)} fields.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
