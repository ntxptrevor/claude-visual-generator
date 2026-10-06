#!/usr/bin/env python3
"""
FormFlow JEV Decision Tree Router

Implements JEV's routing logic for FormFlow tasks. Routes every subtask
to the cheapest executor that produces a correct result.

JEV Tiers:
  - Tier 0: Deterministic (regex, pypdf, local fuzzy) — $0
  - Tier 1: Cheap model (DeepSeek, Haiku, Gemini Flash) — ~$0.001
  - Tier 2: Full model (Sonnet/Opus) or Council vote — ~$0.01

Usage (as library):
    from formflow_jev_router import JevRouter
    router = JevRouter()
    decision = router.route_classification("W-9 Tax Form.pdf")
    decision = router.route_extraction(has_acroform=True)
    decision = router.route_matching(confidence=92)
    decision = router.route_save_location(form_type="insurance_cert")

Usage (CLI):
    python formflow_jev_router.py --task classify --input "W-9 Form.pdf"
    python formflow_jev_router.py --task extract --acroform true
    python formflow_jev_router.py --task match --confidence 85
    python formflow_jev_router.py --task save --form-type lien_waiver
    python formflow_jev_router.py --cost-summary
"""

import argparse
import json
import re
import sys


FORM_TYPE_PATTERNS = {
    "w9": r"(?i)(W-?9|Request\s+for\s+Taxpayer)",
    "w4": r"(?i)(W-?4|Employee.s?\s+Withholding)",
    "i9": r"(?i)(I-?9|Employment\s+Eligibility)",
    "insurance_cert": r"(?i)(Certificate\s+of\s+Insurance|ACORD\s*25|COI\b)",
    "lien_waiver": r"(?i)(Lien\s+Waiver|Waiver\s+of\s+Lien|Release\s+of\s+Lien)",
    "hub_mbe": r"(?i)(HUB|MBE|DBE|SBE)\s*(Cert|Form|Application)",
    "sam_registration": r"(?i)(SAM\s+Registration|sam\.gov|System\s+for\s+Award)",
    "vendor_registration": r"(?i)(Vendor\s+Registration|Vendor\s+Application)",
    "bid_form": r"(?i)(Bid\s+Form|Proposal\s+Form|Bid\s+Schedule)",
    "nda": r"(?i)(NDA|Non-?Disclosure|Confidentiality\s+Agreement)",
    "daily_report": r"(?i)(Daily\s+Report|Daily\s+Log|Field\s+Report)",
    "subcontractor_prequalification": r"(?i)(Pre-?[Qq]ualification|Subcontractor\s+Qual)",
    "credit_application": r"(?i)(Credit\s+Application|Credit\s+App)",
    "business_license": r"(?i)(Business\s+License|License\s+Application)",
    "capability_statement": r"(?i)(Capability\s+Statement|Capabilities)",
    "safety_checklist": r"(?i)(Safety\s+Checklist|Safety\s+Form|JHA|JSA)",
    "punch_list": r"(?i)(Punch\s*List|Deficiency\s+List)",
    "inspection_request": r"(?i)(Inspection\s+Request|Request\s+for\s+Inspection)",
}

SAVE_LOCATION_MAP = {
    "w9": "!Company Documents",
    "w4": "Employee folder",
    "i9": "Employee folder",
    "insurance_cert": "2.7",
    "lien_waiver": "2.8",
    "hub_mbe": "13.1",
    "sam_registration": "!Company Documents",
    "vendor_registration": "!Company Documents",
    "bid_form": "4.1",
    "nda": "2.1",
    "daily_report": "10.2",
    "subcontractor_prequalification": "4.3",
    "credit_application": "!Company Documents",
    "business_license": "!Company Documents",
    "capability_statement": "!Active Bids",
    "safety_checklist": "11",
    "punch_list": "10.1",
    "inspection_request": "11",
}

CONFIDENTIAL_FORM_TYPES = {"w9", "w4", "i9", "credit_application", "nda"}

COST_TABLE = {
    "tier_0_regex": 0.0,
    "tier_0_pypdf2": 0.0,
    "tier_0_pdfplumber": 0.0,
    "tier_0_fuzzy_match": 0.0,
    "tier_0_reportlab": 0.0,
    "tier_1_deepseek": 0.001,
    "tier_1_haiku": 0.002,
    "tier_1_gemini_flash": 0.001,
    "tier_2_sonnet": 0.015,
    "tier_2_opus": 0.030,
    "tier_2_council_3vote": 0.006,
    "tier_2_council_run": 0.010,
}


def route_classification(filename, content_snippet=None):
    """JEV Decision: Form Type Classification.

    Tries regex on filename first (Tier 0, $0).
    Falls back to content regex (Tier 0, $0).
    Falls back to model inference (Tier 1, ~$0.001).
    """
    for form_type, pattern in FORM_TYPE_PATTERNS.items():
        if re.search(pattern, filename):
            return {
                "task": "classification",
                "form_type": form_type,
                "tier": 0,
                "executor": "regex",
                "cost": COST_TABLE["tier_0_regex"],
                "confidence": 95,
                "method": "filename_regex",
                "is_confidential": form_type in CONFIDENTIAL_FORM_TYPES
            }

    if content_snippet:
        for form_type, pattern in FORM_TYPE_PATTERNS.items():
            if re.search(pattern, content_snippet[:500]):
                return {
                    "task": "classification",
                    "form_type": form_type,
                    "tier": 0,
                    "executor": "regex",
                    "cost": COST_TABLE["tier_0_regex"],
                    "confidence": 80,
                    "method": "content_regex",
                    "is_confidential": form_type in CONFIDENTIAL_FORM_TYPES
                }

    return {
        "task": "classification",
        "form_type": None,
        "tier": 1,
        "executor": "council_route",
        "cost": COST_TABLE["tier_1_deepseek"],
        "confidence": 0,
        "method": "model_inference",
        "router_args": {
            "task": f"Classify document: {filename}",
            "surface": "claude-code",
            "ambiguity": 2,
            "stakes": 1,
            "context_dep": 1,
            "voice": 0,
            "verifiable": 2,
        },
        "is_confidential": False
    }


def route_extraction(has_acroform=False, layout_complexity="simple"):
    """JEV Decision: Field Extraction.

    AcroForm present → pypdf only, $0.
    Simple text KV → regex + pdfplumber, $0.
    Complex tables → Tier 1, ~$0.002.
    Scanned/handwritten → Tier 2, ~$0.01.
    """
    if has_acroform:
        return {
            "task": "extraction",
            "tier": 0,
            "executor": "pypdf2",
            "cost": COST_TABLE["tier_0_pypdf2"],
            "method": "acroform_extraction"
        }

    if layout_complexity == "simple":
        return {
            "task": "extraction",
            "tier": 0,
            "executor": "pdfplumber_regex",
            "cost": COST_TABLE["tier_0_pdfplumber"],
            "method": "visual_regex_extraction"
        }

    if layout_complexity == "complex":
        return {
            "task": "extraction",
            "tier": 1,
            "executor": "council_route",
            "cost": COST_TABLE["tier_1_haiku"],
            "method": "model_visual_extraction",
            "router_args": {
                "task": "Extract form fields from complex PDF layout",
                "surface": "claude-code",
                "ambiguity": 2,
                "stakes": 1,
                "context_dep": 1,
                "voice": 0,
                "verifiable": 2,
            }
        }

    return {
        "task": "extraction",
        "tier": 2,
        "executor": "council_route",
        "cost": COST_TABLE["tier_2_sonnet"],
        "method": "ocr_model_extraction",
        "router_args": {
            "task": "OCR and extract fields from scanned/handwritten form",
            "surface": "claude-code",
            "ambiguity": 3,
            "stakes": 2,
            "context_dep": 1,
            "voice": 0,
            "verifiable": 1,
        }
    }


def route_matching(confidence, has_contradiction=False):
    """JEV Decision: KB Matching Confidence Gate.

    ≥95% → auto-fill, no gate.
    70-94% → auto-fill, Tier 1 gate (batch approve).
    <70% → present in GUI, Tier 2 gate.
    Contradiction → Tier 3 gate (change-gate protocol).
    """
    if has_contradiction:
        return {
            "task": "matching",
            "tier": 3,
            "gate_tier": 3,
            "executor": "change_gate",
            "cost": COST_TABLE["tier_0_regex"],
            "method": "contradiction_resolution",
            "gate_action": "explain_and_wait",
            "detail": "Value contradicts existing KB entry. Tier 3 gate required."
        }

    if confidence >= 95:
        return {
            "task": "matching",
            "tier": 0,
            "gate_tier": 0,
            "executor": "auto_fill",
            "cost": COST_TABLE["tier_0_fuzzy_match"],
            "method": "auto_fill_no_gate",
            "detail": f"High confidence ({confidence}%). Auto-fill without gate."
        }

    if confidence >= 70:
        return {
            "task": "matching",
            "tier": 1,
            "gate_tier": 1,
            "executor": "auto_fill_gated",
            "cost": COST_TABLE["tier_0_fuzzy_match"],
            "method": "auto_fill_batch_approve",
            "detail": f"Medium confidence ({confidence}%). Auto-fill with batch approval."
        }

    return {
        "task": "matching",
        "tier": 2,
        "gate_tier": 2,
        "executor": "gui_prompt",
        "cost": COST_TABLE["tier_0_fuzzy_match"],
        "method": "manual_gui_entry",
        "detail": f"Low confidence ({confidence}%). Present in GUI for manual entry."
    }


def route_save_location(form_type, project_name=None):
    """JEV Decision: Where to Save Filled Form.

    Uses NTXP folder system mapping. Falls back to user prompt.
    """
    location = SAVE_LOCATION_MAP.get(form_type)

    if location:
        if project_name and location.startswith(("2.", "4.", "5.", "6", "7.",
                                                  "8.", "9", "10.", "11.", "12.", "13.")):
            full_path = f"!Active Projects/{project_name}/{location}"
        else:
            full_path = location

        return {
            "task": "save_location",
            "tier": 0,
            "executor": "folder_system_lookup",
            "cost": COST_TABLE["tier_0_regex"],
            "location": full_path,
            "folder_number": location,
            "method": "ntxp_folder_system",
            "gate_tier": 2,
            "detail": f"Save to {full_path} (NTXP folder {location})"
        }

    return {
        "task": "save_location",
        "tier": 1,
        "executor": "user_prompt",
        "cost": COST_TABLE["tier_0_regex"],
        "location": None,
        "method": "user_specified",
        "gate_tier": 2,
        "detail": f"No folder mapping for '{form_type}'. Will ask user."
    }


def route_sanity_check():
    """JEV Decision: Sanity checks are always Tier 0 (Python script, $0)."""
    return {
        "task": "sanity_check",
        "tier": 0,
        "executor": "python_script",
        "cost": COST_TABLE["tier_0_regex"],
        "method": "formflow_sanity_check.py"
    }


def route_report_generation():
    """JEV Decision: Report generation is always Tier 0 (reportlab, $0)."""
    return {
        "task": "report_generation",
        "tier": 0,
        "executor": "reportlab",
        "cost": COST_TABLE["tier_0_reportlab"],
        "method": "formflow_generate_report.py"
    }


def route_signature(signer_name=None):
    """JEV Decision: Signature application is ALWAYS Tier 3. No exceptions.

    Only Trevor Hopkins (owner) and Alison Hopkins (owner) are authorized.
    Manual approval within Claude is required before the document goes external.
    """
    authorized = {
        "trevor_hopkins": "Trevor Hopkins",
        "alison_hopkins": "Alison Hopkins",
    }

    if signer_name:
        key = signer_name.lower().strip().replace(" ", "_")
        if key not in authorized:
            return {
                "task": "signature",
                "tier": None,
                "executor": "denied",
                "cost": 0,
                "method": "unauthorized_signer",
                "gate_tier": None,
                "authorized": False,
                "detail": f"DENIED: '{signer_name}' is not authorized. "
                          f"Only {', '.join(authorized.values())} may sign."
            }

    return {
        "task": "signature",
        "tier": 3,
        "executor": "change_gate",
        "cost": COST_TABLE["tier_0_regex"],
        "method": "formflow_signatures.py",
        "gate_tier": 3,
        "gate_action": "explain_and_wait",
        "authorized": True,
        "detail": "Signature requires Tier 3 manual approval. Always."
    }


def route_learning_action(action_type, correction_count=0):
    """JEV Decision: Learning loop action routing."""
    if action_type == "flag_stale":
        return {
            "task": "learning",
            "tier": 0,
            "executor": "flag_only",
            "cost": COST_TABLE["tier_0_regex"],
            "method": "stale_field_flag"
        }

    if action_type in ("flag_for_review", "reclassify_type", "research_form_type"):
        return {
            "task": "learning",
            "tier": 1,
            "executor": "council_route",
            "cost": COST_TABLE["tier_1_deepseek"],
            "method": "cheap_model_research"
        }

    if action_type in ("council_consult", "resolve_contradiction"):
        return {
            "task": "learning",
            "tier": 2,
            "executor": "council_run",
            "cost": COST_TABLE["tier_2_council_run"],
            "method": "council_vote"
        }

    return {
        "task": "learning",
        "tier": 1,
        "executor": "council_route",
        "cost": COST_TABLE["tier_1_deepseek"],
        "method": "default_cheap_model"
    }


def estimate_fill_cost(field_count, has_acroform=True, known_form_type=True,
                       avg_confidence=90, contradictions=0):
    """Estimate total cost for a complete form fill operation."""
    cost = 0.0

    if known_form_type:
        cost += COST_TABLE["tier_0_regex"]
    else:
        cost += COST_TABLE["tier_1_deepseek"]

    if has_acroform:
        cost += COST_TABLE["tier_0_pypdf2"]
    else:
        cost += COST_TABLE["tier_1_haiku"]

    cost += COST_TABLE["tier_0_fuzzy_match"] * field_count

    if avg_confidence < 70:
        cost += COST_TABLE["tier_2_council_3vote"] * (field_count * 0.3)
    elif avg_confidence < 85:
        cost += COST_TABLE["tier_1_deepseek"] * (field_count * 0.1)

    cost += COST_TABLE["tier_2_council_run"] * contradictions

    cost += COST_TABLE["tier_0_regex"]

    cost += COST_TABLE["tier_0_reportlab"]

    return {
        "estimated_cost": round(cost, 4),
        "field_count": field_count,
        "assumptions": {
            "has_acroform": has_acroform,
            "known_form_type": known_form_type,
            "avg_confidence": avg_confidence,
            "contradictions": contradictions
        }
    }


def get_cost_summary():
    """Return a summary of JEV cost tiers for reporting."""
    return {
        "tier_0": {
            "description": "Deterministic (regex, pypdf, pdfplumber, fuzzy match, reportlab)",
            "cost": "$0",
            "tasks": [
                "Form type classification (known types)",
                "AcroForm field extraction",
                "Simple text field extraction",
                "KB fuzzy matching",
                "Sanity check validation",
                "Report generation",
                "Folder system lookup"
            ]
        },
        "tier_1": {
            "description": "Cheap model (DeepSeek, Haiku, Gemini Flash)",
            "cost": "$0.001-0.002 per call",
            "tasks": [
                "Unknown form type classification",
                "Complex table field extraction",
                "Low-confidence match resolution",
                "Learning loop research"
            ]
        },
        "tier_2": {
            "description": "Full model or Council vote",
            "cost": "$0.006-0.015 per call",
            "tasks": [
                "Scanned/handwritten OCR extraction",
                "Ambiguous field matching (3-model vote)",
                "Contradiction resolution (Council run)",
                "Field reclassification (Council consult)"
            ]
        },
        "typical_fill": estimate_fill_cost(15),
    }


def main():
    parser = argparse.ArgumentParser(description="FormFlow JEV Decision Tree Router")
    parser.add_argument("--task", choices=["classify", "extract", "match", "save", "signature"],
                        help="Task to route")
    parser.add_argument("--input", type=str, help="Input (filename for classify)")
    parser.add_argument("--acroform", type=str, default="false", help="Has AcroForm fields")
    parser.add_argument("--complexity", choices=["simple", "complex", "scanned"],
                        default="simple")
    parser.add_argument("--confidence", type=int, default=80, help="Match confidence 0-100")
    parser.add_argument("--contradiction", action="store_true", help="Has contradiction")
    parser.add_argument("--form-type", type=str, help="Form type for save routing")
    parser.add_argument("--project", type=str, default=None, help="Project name")
    parser.add_argument("--cost-summary", action="store_true", help="Show cost summary")
    parser.add_argument("--estimate", type=int, default=None,
                        help="Estimate fill cost for N fields")
    args = parser.parse_args()

    if args.cost_summary:
        summary = get_cost_summary()
        print(json.dumps(summary, indent=2))
        return

    if args.estimate:
        estimate = estimate_fill_cost(args.estimate)
        print(json.dumps(estimate, indent=2))
        return

    if args.task == "classify":
        if not args.input:
            print("Error: --input required for classify", file=sys.stderr)
            sys.exit(1)
        result = route_classification(args.input)
        print(json.dumps(result, indent=2))

    elif args.task == "extract":
        has_acro = args.acroform.lower() in ("true", "yes", "1")
        result = route_extraction(has_acroform=has_acro, layout_complexity=args.complexity)
        print(json.dumps(result, indent=2))

    elif args.task == "match":
        result = route_matching(args.confidence, has_contradiction=args.contradiction)
        print(json.dumps(result, indent=2))

    elif args.task == "save":
        if not args.form_type:
            print("Error: --form-type required for save", file=sys.stderr)
            sys.exit(1)
        result = route_save_location(args.form_type, project_name=args.project)
        print(json.dumps(result, indent=2))

    elif args.task == "signature":
        result = route_signature(args.input)
        print(json.dumps(result, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
