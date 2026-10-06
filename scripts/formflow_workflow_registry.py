#!/usr/bin/env python3
"""
FormFlow Prewired Workflow Registry

Manages the mapping of known form types to their field-to-KB bindings,
save locations, and JEV tier assignments. Used by the skill to achieve
zero-inference-cost form filling for common form types.

Each workflow entry contains:
  - form_type: Canonical identifier
  - patterns: Regex patterns matching filename or form title
  - field_map: Maps form field labels → KB field_name entries
  - save_location: NTXP folder system location
  - jev_tier: JEV routing tier (0=regex, 1=cheap model, 2=full model)
  - category: Workflow category for grouping

Usage (as library):
    from formflow_workflow_registry import WorkflowRegistry
    registry = WorkflowRegistry()
    wf = registry.match("W-9 Tax Form.pdf")
    field_map = wf.field_map
    save_to = wf.save_location

Usage (CLI):
    python formflow_workflow_registry.py --match "W-9 Form.pdf"
    python formflow_workflow_registry.py --list
    python formflow_workflow_registry.py --list --category legal
    python formflow_workflow_registry.py --export
"""

import argparse
import json
import re
import sys

from formflow_signatures import SIGNATURE_FORM_TYPES


WORKFLOWS = {
    "w9": {
        "form_type": "w9",
        "name": "W-9 (Tax ID Request)",
        "category": "legal",
        "patterns": [r"(?i)(W-?9|Request\s+for\s+Taxpayer)"],
        "field_map": {
            "Name.*tax return": "business_name",
            "Business name.*disregarded": "dba_name",
            "Federal tax classification": "tax_classification",
            "Exempt payee code": "exempt_payee_code",
            "Address.*number.*street": "street_address",
            "City.*state.*ZIP": "city_state_zip",
            "Requester.*name": "requester_name",
            "Taxpayer Identification Number|TIN": "ein",
            "Social security number": "ssn",
            "Signature": "signer_name",
            "Date": "signature_date"
        },
        # IRS fw9.pdf (Rev. March 2024) AcroForm IDs; tooltips are absent, so map by ID.
        "acroform_map": {
            "f1_01[0]": "business_name",
            "f1_02[0]": "dba_name",
            "c1_1[*]": "tax_classification_box",
            "f1_03[0]": "llc_tax_class_code",
            "f1_04[0]": "tax_classification_other",
            "f1_05[0]": "exempt_payee_code",
            "f1_06[0]": "fatca_code",
            "f1_07[0]": "street_address",
            "f1_08[0]": "city_state_zip",
            "f1_09[0]": "requester_name_address",
            "f1_10[0]": "account_numbers",
            "f1_11[0]": "ssn_part1",
            "f1_12[0]": "ssn_part2",
            "f1_13[0]": "ssn_part3",
            "f1_14[0]": "ein_part1",
            "f1_15[0]": "ein_part2",
        },
        "tax_classification_states": {
            "individual": "/1", "c_corp": "/2", "s_corp": "/3",
            "partnership": "/4", "trust_estate": "/5", "llc": "/6", "other": "/7",
        },
        "signature_placements": [
            {"page": 1, "kind": "signature", "x": 150, "y": 196, "width": 220},
            {"page": 1, "kind": "date", "x": 410, "y": 196},
        ],
        "save_location": "!Company Documents",
        "jev_tier": 0,
        "is_confidential": True
    },
    "w4": {
        "form_type": "w4",
        "name": "W-4 (Employee Withholding)",
        "category": "legal",
        "patterns": [r"(?i)(W-?4|Employee.s?\s+Withholding)"],
        "field_map": {
            "First name.*middle initial": "first_name",
            "Last name": "last_name",
            "Social security": "ssn",
            "Address": "street_address",
            "City.*town.*state.*ZIP": "city_state_zip",
            "Filing status": "filing_status",
            "Multiple jobs": "multiple_jobs"
        },
        "save_location": "Employee folder",
        "jev_tier": 0,
        "is_confidential": True
    },
    "i9": {
        "form_type": "i9",
        "name": "I-9 (Employment Eligibility)",
        "category": "legal",
        "patterns": [r"(?i)(I-?9|Employment\s+Eligibility)"],
        "field_map": {
            "Last Name": "last_name",
            "First Name": "first_name",
            "Middle Initial": "middle_initial",
            "Other Last Names": "other_last_names",
            "Address": "street_address",
            "Apt": "apt_suite",
            "City.*Town": "city",
            "State": "state",
            "ZIP": "zip_code",
            "Date of Birth": "dob",
            "Social Security": "ssn",
            "Email": "email",
            "Telephone": "phone",
            "Citizen": "citizenship"
        },
        "save_location": "Employee folder",
        "jev_tier": 0,
        "is_confidential": True
    },
    "nda": {
        "form_type": "nda",
        "name": "Non-Disclosure Agreement",
        "category": "legal",
        "patterns": [r"(?i)(NDA|Non-?Disclosure|Confidentiality\s+Agreement)"],
        "field_map": {
            "Disclosing Party|Party A": "company_name",
            "Receiving Party|Party B": "counterparty_name",
            "Effective Date": "effective_date",
            "Name.*Title.*Sign": "signer_name",
            "Title": "signer_title"
        },
        "save_location": "2.1",
        "jev_tier": 0,
        "is_confidential": False
    },
    "insurance_cert": {
        "form_type": "insurance_cert",
        "name": "Certificate of Insurance (ACORD 25)",
        "category": "legal",
        "patterns": [r"(?i)(Certificate\s+of\s+Insurance|ACORD\s*25|COI\b)"],
        "field_map": {
            "Named Insured|Insured": "company_name",
            "Producer": "insurance_agent",
            "General Liability.*Occurrence": "gl_occurrence_limit",
            "General Liability.*Aggregate": "gl_aggregate_limit",
            "Automobile.*Combined": "auto_combined_limit",
            "Umbrella.*Occurrence": "umbrella_limit",
            "Workers.*Compensation": "wc_statutory",
            "Policy Number": "policy_number",
            "Effective Date|Policy Eff": "policy_effective",
            "Expiration Date|Policy Exp": "policy_expiry"
        },
        "save_location": "2.7",
        "jev_tier": 0,
        "is_confidential": False
    },
    "lien_waiver": {
        "form_type": "lien_waiver",
        "name": "Lien Waiver / Release",
        "category": "legal",
        "patterns": [r"(?i)(Lien\s+Waiver|Waiver\s+of\s+Lien|Release\s+of\s+Lien)"],
        "field_map": {
            "Claimant|Contractor|Subcontractor": "company_name",
            "Owner": "project_owner",
            "Project": "project_name",
            "Amount|Through Amount": "waiver_amount",
            "Through Date": "waiver_through_date",
            "Signature": "signer_name",
            "Date": "signature_date"
        },
        "save_location": "2.8",
        "jev_tier": 0,
        "is_confidential": False
    },
    "hub_mbe": {
        "form_type": "hub_mbe",
        "name": "HUB/MBE/DBE Certification",
        "category": "legal",
        "patterns": [r"(?i)(HUB|MBE|DBE|SBE)\s*(Cert|Form|Application)"],
        "field_map": {
            "Company.*Name|Firm.*Name": "company_name",
            "Certification Type": "cert_type",
            "Certification Number|Cert.*No": "cert_number",
            "Expiration|Expiry": "cert_expiry",
            "Ethnicity|Race": "cert_ethnicity",
            "Owner.*Name": "owner_name"
        },
        "save_location": "13.1",
        "jev_tier": 0,
        "is_confidential": False
    },
    "sam_registration": {
        "form_type": "sam_registration",
        "name": "SAM.gov Registration",
        "category": "rfp",
        "patterns": [r"(?i)(SAM\s+Registration|sam\.gov|System\s+for\s+Award)"],
        "field_map": {
            "Legal Business Name": "company_name",
            "DUNS|UEI": "duns_number",
            "CAGE": "cage_code",
            "EIN|Tax.*ID": "ein",
            "NAICS": "naics_codes",
            "Physical Address": "street_address",
            "City": "city",
            "State": "state",
            "ZIP": "zip_code",
            "POC.*Name|Contact.*Name": "contact_name",
            "POC.*Email|Contact.*Email": "email",
            "POC.*Phone|Contact.*Phone": "phone"
        },
        "save_location": "!Company Documents",
        "jev_tier": 0,
        "is_confidential": False
    },
    "vendor_registration": {
        "form_type": "vendor_registration",
        "name": "Vendor Registration",
        "category": "account",
        "patterns": [r"(?i)(Vendor\s+Registration|Vendor\s+Application|Supplier\s+Reg)"],
        "field_map": {
            "Company.*Name|Vendor.*Name": "company_name",
            "Tax.*ID|EIN|FEIN": "ein",
            "Contact.*Name|Authorized.*Rep": "contact_name",
            "Phone|Telephone": "phone",
            "Email|E-?mail": "email",
            "Address": "street_address",
            "City": "city",
            "State": "state",
            "ZIP": "zip_code",
            "Insurance|COI": "has_insurance",
            "Bond": "bonding_capacity"
        },
        "save_location": "!Company Documents",
        "jev_tier": 0,
        "is_confidential": False
    },
    "bid_form": {
        "form_type": "bid_form",
        "name": "Bid / Proposal Form",
        "category": "rfp",
        "patterns": [r"(?i)(Bid\s+Form|Proposal\s+Form|Bid\s+Schedule)"],
        "field_map": {
            "Project.*Name|Project.*Title": "project_name",
            "Bidder|Contractor": "company_name",
            "Base Bid|Lump Sum|Total": "bid_amount",
            "Addend": "addenda_acknowledged",
            "Bond|Bid Bond": "bid_bond_info"
        },
        "save_location": "4.1",
        "jev_tier": 0,
        "is_confidential": True
    },
    "subcontractor_prequalification": {
        "form_type": "subcontractor_prequalification",
        "name": "Subcontractor Prequalification",
        "category": "rfp",
        "patterns": [r"(?i)(Pre-?[Qq]ualification|Subcontractor\s+Qual)"],
        "field_map": {
            "Company.*Name": "company_name",
            "Bonding.*Capacity|Bond.*Limit": "bonding_capacity",
            "Years.*Experience|Experience": "years_experience",
            "EMR|Experience\s+Modification": "emr_rate",
            "License.*Number": "license_number",
            "Contact": "contact_name",
            "Phone": "phone",
            "Email": "email"
        },
        "save_location": "4.3",
        "jev_tier": 0,
        "is_confidential": False
    },
    "credit_application": {
        "form_type": "credit_application",
        "name": "Credit Application",
        "category": "account",
        "patterns": [r"(?i)(Credit\s+Application|Credit\s+App)"],
        "field_map": {
            "Company.*Name|Applicant": "company_name",
            "DUNS": "duns_number",
            "Trade.*Reference": "trade_references",
            "Bank.*Name|Banking": "bank_name",
            "Account.*Number": "bank_account"
        },
        "save_location": "!Company Documents",
        "jev_tier": 0,
        "is_confidential": True
    },
    "business_license": {
        "form_type": "business_license",
        "name": "Business License Application",
        "category": "account",
        "patterns": [r"(?i)(Business\s+License|License\s+Application)"],
        "field_map": {
            "Business.*Name|Applicant": "company_name",
            "Address": "street_address",
            "License.*Type": "license_type",
            "Jurisdiction": "jurisdiction"
        },
        "save_location": "!Company Documents",
        "jev_tier": 0,
        "is_confidential": False
    },
    "daily_report": {
        "form_type": "daily_report",
        "name": "Daily Report / Field Report",
        "category": "construction",
        "patterns": [r"(?i)(Daily\s+Report|Daily\s+Log|Field\s+Report)"],
        "field_map": {
            "Project": "project_name",
            "Date": "report_date",
            "Weather": "weather",
            "Manpower|Workforce|Crew": "manpower_count",
            "Superintendent|Foreman": "superintendent_name"
        },
        "save_location": "10.2",
        "jev_tier": 0,
        "is_confidential": False
    },
    "safety_checklist": {
        "form_type": "safety_checklist",
        "name": "Safety Checklist / JHA",
        "category": "construction",
        "patterns": [r"(?i)(Safety\s+Checklist|Safety\s+Form|JHA|JSA)"],
        "field_map": {
            "Project": "project_name",
            "Date": "report_date",
            "Inspector|Supervisor": "inspector_name"
        },
        "save_location": "11",
        "jev_tier": 0,
        "is_confidential": False
    },
    "punch_list": {
        "form_type": "punch_list",
        "name": "Punch List",
        "category": "construction",
        "patterns": [r"(?i)(Punch\s*List|Deficiency\s+List)"],
        "field_map": {
            "Project": "project_name",
            "Location|Area": "punch_location",
            "Description|Item": "punch_description",
            "Responsible|Assigned": "responsible_party"
        },
        "save_location": "10.1",
        "jev_tier": 0,
        "is_confidential": False
    },
    "inspection_request": {
        "form_type": "inspection_request",
        "name": "Inspection Request",
        "category": "construction",
        "patterns": [r"(?i)(Inspection\s+Request|Request\s+for\s+Inspection)"],
        "field_map": {
            "Project": "project_name",
            "Type|Inspection.*Type": "inspection_type",
            "Date.*Requested|Requested.*Date": "requested_date",
            "Scope|Area": "inspection_scope"
        },
        "save_location": "11",
        "jev_tier": 0,
        "is_confidential": False
    }
}


def match_workflow(filename_or_title):
    """Match a filename or form title to a prewired workflow.

    Returns the workflow dict if matched, None otherwise.
    """
    for wf_id, wf in WORKFLOWS.items():
        for pattern in wf["patterns"]:
            if re.search(pattern, filename_or_title):
                return wf
    return None


def get_workflow(form_type):
    """Get a workflow by its form_type identifier."""
    return WORKFLOWS.get(form_type)


def list_workflows(category=None):
    """List all workflows, optionally filtered by category."""
    results = []
    for wf_id, wf in WORKFLOWS.items():
        if category and wf.get("category") != category:
            continue
        results.append({
            "form_type": wf["form_type"],
            "name": wf["name"],
            "category": wf["category"],
            "field_count": len(wf["field_map"]),
            "save_location": wf["save_location"],
            "is_confidential": wf.get("is_confidential", False),
            "needs_signature": wf["form_type"] in SIGNATURE_FORM_TYPES
        })
    return results


def get_field_map(form_type):
    """Get the field-to-KB mapping for a given form type."""
    wf = WORKFLOWS.get(form_type)
    if wf:
        return wf["field_map"]
    return None


def map_form_field_to_kb(form_field_label, form_type=None):
    """Map a form field label to its KB field_name using the workflow's field map.

    If form_type is specified, checks only that workflow's map.
    Otherwise checks all workflows.
    Returns (kb_field_name, confidence) or (None, 0).
    """
    if form_type:
        wf = WORKFLOWS.get(form_type)
        if wf:
            for pattern, kb_field in wf["field_map"].items():
                if re.search(pattern, form_field_label, re.IGNORECASE):
                    return (kb_field, 95)

    for wf_id, wf in WORKFLOWS.items():
        for pattern, kb_field in wf["field_map"].items():
            if re.search(pattern, form_field_label, re.IGNORECASE):
                return (kb_field, 85 if form_type else 75)

    return (None, 0)


def get_confidential_workflows():
    """Return list of workflow IDs that handle confidential content.

    Ledger (DeepSeek) and Mason (GLM) must never see these.
    """
    return [wf_id for wf_id, wf in WORKFLOWS.items()
            if wf.get("is_confidential", False)]


def export_for_sheets():
    """Export all workflows as rows for the Google Sheets Workflows tab."""
    import uuid
    from datetime import datetime

    rows = []
    for wf_id, wf in WORKFLOWS.items():
        rows.append([
            str(uuid.uuid4())[:12],
            wf["form_type"],
            "|".join(wf["patterns"]),
            json.dumps(wf["field_map"]),
            wf["save_location"],
            str(wf["jev_tier"]),
            datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        ])
    return rows


def get_categories():
    """Get all unique workflow categories."""
    return sorted(set(wf["category"] for wf in WORKFLOWS.values()))


def main():
    parser = argparse.ArgumentParser(description="FormFlow Workflow Registry")
    parser.add_argument("--match", type=str, help="Match a filename to a workflow")
    parser.add_argument("--list", action="store_true", help="List all workflows")
    parser.add_argument("--category", type=str, default=None,
                        help="Filter by category (legal, rfp, account, construction)")
    parser.add_argument("--export", action="store_true",
                        help="Export workflows for Google Sheets")
    parser.add_argument("--field-map", type=str, help="Show field map for a form type")
    parser.add_argument("--map-field", type=str,
                        help="Map a form field label to KB field name")
    parser.add_argument("--form-type", type=str, default=None,
                        help="Form type context for field mapping")
    args = parser.parse_args()

    if args.match:
        wf = match_workflow(args.match)
        if wf:
            print(json.dumps({
                "matched": True,
                "form_type": wf["form_type"],
                "name": wf["name"],
                "category": wf["category"],
                "save_location": wf["save_location"],
                "jev_tier": wf["jev_tier"],
                "is_confidential": wf.get("is_confidential", False),
                "needs_signature": wf["form_type"] in SIGNATURE_FORM_TYPES,
                "field_count": len(wf["field_map"])
            }, indent=2))
        else:
            print(json.dumps({"matched": False, "needs_model_inference": True}))

    elif args.list:
        workflows = list_workflows(category=args.category)
        if not workflows:
            print("No workflows found.")
        else:
            print(f"\nFormFlow Prewired Workflows"
                  f"{' (' + args.category + ')' if args.category else ''}")
            print("=" * 60)
            for wf in workflows:
                conf_marker = " [CONFIDENTIAL]" if wf["is_confidential"] else ""
                if wf["needs_signature"]:
                    conf_marker += " [SIGNATURE - TIER 3]"
                print(f"\n  {wf['form_type']:30s} | {wf['name']}{conf_marker}")
                print(f"  {'':30s} | Category: {wf['category']}")
                print(f"  {'':30s} | Fields: {wf['field_count']}")
                print(f"  {'':30s} | Save: {wf['save_location']}")
            print(f"\nTotal: {len(workflows)} workflows")

    elif args.export:
        rows = export_for_sheets()
        print(json.dumps(rows, indent=2))
        print(f"\n{len(rows)} workflow rows ready for Google Sheets.")

    elif args.field_map:
        fm = get_field_map(args.field_map)
        if fm:
            print(json.dumps(fm, indent=2))
        else:
            print(f"No field map for form type '{args.field_map}'")

    elif args.map_field:
        kb_field, confidence = map_form_field_to_kb(args.map_field,
                                                     form_type=args.form_type)
        print(json.dumps({
            "form_field": args.map_field,
            "kb_field": kb_field,
            "confidence": confidence,
            "form_type": args.form_type
        }, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
