#!/usr/bin/env python3
"""
FormFlow Signature Appending System

Manages digital signature placement on filled PDF forms.
SECURITY: Only Trevor Hopkins (owner) and Alison Hopkins (owner) signatures
are authorized. Every signature application requires Tier 3 manual approval
within Claude before the document goes external.

Usage (as library):
    from formflow_signatures import SignatureManager
    mgr = SignatureManager()
    mgr.validate_signer("Trevor Hopkins")
    mgr.generate_approval_request(document_path, signer, fields)
    mgr.apply_signature(document_path, signer, approval_token)

Usage (CLI):
    python formflow_signatures.py --check "Trevor Hopkins"
    python formflow_signatures.py --list-signers
    python formflow_signatures.py --preview --document filled.pdf --signer "Trevor Hopkins"
"""

import argparse
import hashlib
import io
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path


AUTHORIZED_SIGNERS = {
    "trevor_hopkins": {
        "full_name": "Trevor Hopkins",
        "title": "Owner",
        "role": "owner",
        "email": "trevor@ntxpllc.com",
        "signature_fields": ["signature", "authorized_signature", "owner_signature",
                             "signer", "sign_here", "principal_signature"],
        "initials_fields": ["initials", "initial_here", "owner_initials"],
    },
    "alison_hopkins": {
        "full_name": "Alison Hopkins",
        "title": "Owner",
        "role": "owner",
        "email": "",
        "signature_fields": ["signature", "authorized_signature", "owner_signature",
                             "signer", "sign_here", "principal_signature",
                             "co_owner_signature", "secondary_signature"],
        "initials_fields": ["initials", "initial_here", "owner_initials"],
    },
}

GATE_TIER = 3

SIGNATURE_FORM_TYPES = {
    "w9", "w4", "i9", "nda", "lien_waiver", "bid_form",
    "credit_application", "vendor_registration", "sam_registration",
    "subcontractor_prequalification", "insurance_cert",
}

SIGNATURE_FIELD_PATTERNS = [
    r"(?i)signature",
    r"(?i)sign\s*here",
    r"(?i)authorized\s*(representative|agent|signer)",
    r"(?i)print\s*name.*sign",
    r"(?i)owner.*sign",
    r"(?i)principal.*sign",
    r"(?i)officer.*sign",
    r"(?i)initials?",
]

DATE_FIELD_PATTERNS = [
    r"(?i)date\s*of\s*signature",
    r"(?i)sign.*date",
    r"(?i)dated?\s*$",
    r"(?i)execution\s*date",
]


def normalize_signer_key(name):
    return name.lower().strip().replace(" ", "_")


def validate_signer(name):
    key = normalize_signer_key(name)
    if key in AUTHORIZED_SIGNERS:
        return {
            "authorized": True,
            "signer": AUTHORIZED_SIGNERS[key],
            "key": key,
            "gate_tier": GATE_TIER,
            "gate_required": True,
            "message": f"{AUTHORIZED_SIGNERS[key]['full_name']} ({AUTHORIZED_SIGNERS[key]['title']}) is authorized to sign."
        }

    return {
        "authorized": False,
        "signer": None,
        "key": key,
        "gate_tier": None,
        "gate_required": None,
        "message": f"DENIED: '{name}' is not an authorized signer. "
                   f"Only {', '.join(s['full_name'] for s in AUTHORIZED_SIGNERS.values())} may sign.",
        "authorized_signers": [s["full_name"] for s in AUTHORIZED_SIGNERS.values()]
    }


def check_form_needs_signature(form_type):
    return {
        "form_type": form_type,
        "needs_signature": form_type in SIGNATURE_FORM_TYPES,
        "gate_tier": GATE_TIER if form_type in SIGNATURE_FORM_TYPES else None,
    }


def detect_signature_fields(form_fields):
    """Identify which form fields are signature or date-of-signature fields."""
    import re

    sig_fields = []
    date_fields = []

    for field in form_fields:
        field_name = field.get("name", "") or field.get("label", "")

        for pattern in SIGNATURE_FIELD_PATTERNS:
            if re.search(pattern, field_name):
                sig_fields.append({
                    "field_name": field_name,
                    "field_type": field.get("type", "text"),
                    "page": field.get("page", 1),
                    "position": field.get("position", None),
                })
                break

        for pattern in DATE_FIELD_PATTERNS:
            if re.search(pattern, field_name):
                date_fields.append({
                    "field_name": field_name,
                    "field_type": "date",
                    "page": field.get("page", 1),
                    "position": field.get("position", None),
                })
                break

    return {
        "signature_fields": sig_fields,
        "date_fields": date_fields,
        "total_signature_fields": len(sig_fields),
        "total_date_fields": len(date_fields),
    }


def document_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generate_approval_request(document_name, form_type, signer_name,
                              signature_fields, save_location=None,
                              document_path=None):
    """Generate a Tier 3 approval request for signature application.

    This ALWAYS requires manual approval within Claude. No exceptions.
    The approval request includes full context for the reviewer. When
    document_path is given, the request is bound to that file's SHA-256.
    """
    validation = validate_signer(signer_name)
    if not validation["authorized"]:
        return {
            "status": "denied",
            "error": validation["message"],
            "approval_request": None,
        }

    signer = validation["signer"]
    request_id = f"sig-{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    approval_request = {
        "request_id": request_id,
        "gate_tier": GATE_TIER,
        "gate_action": "explain_and_wait",
        "timestamp": now,
        "document": {
            "name": document_name,
            "form_type": form_type,
            "save_location": save_location,
            "sha256": document_digest(document_path) if document_path else None,
        },
        "signer": {
            "name": signer["full_name"],
            "title": signer["title"],
            "role": signer["role"],
        },
        "signature_placements": [
            {
                "field": f["field_name"],
                "page": f.get("page", 1),
                "action": "apply_signature",
            }
            for f in signature_fields
        ],
        "summary": (
            f"SIGNATURE APPROVAL REQUIRED (Tier 3 — Hard Stop)\n\n"
            f"Document: {document_name}\n"
            f"Form Type: {form_type}\n"
            f"Signer: {signer['full_name']} ({signer['title']})\n"
            f"Fields to sign: {len(signature_fields)}\n"
            f"Save to: {save_location or 'TBD'}\n\n"
            f"This document will be stamped with {signer['full_name']}'s "
            f"signature and may be sent externally. This action is "
            f"IRREVERSIBLE once the document leaves NTXP.\n\n"
            f"Do you approve applying {signer['full_name']}'s signature "
            f"to this document?"
        ),
        "approval_options": [
            {"key": "approve", "label": "Approve — Apply signature and proceed"},
            {"key": "reject", "label": "Reject — Do not sign this document"},
            {"key": "edit", "label": "Edit — Review fields before signing"},
        ],
        "warnings": [
            "This is a Tier 3 gate. Manual approval is ALWAYS required.",
            "Once signed and sent, this document represents NTXP LLC legally.",
            "Verify all filled fields are correct before approving.",
        ],
    }

    return {
        "status": "pending_approval",
        "request_id": request_id,
        "approval_request": approval_request,
    }


def build_signature_data(signer_name, include_date=True):
    """Build the data dict for signature field filling.

    Returns field values to be passed to formflow_fill_pdf.py.
    Does NOT apply them — that requires approval first.
    """
    validation = validate_signer(signer_name)
    if not validation["authorized"]:
        return None

    signer = validation["signer"]
    now = datetime.utcnow()

    data = {
        "signer_name": signer["full_name"],
        "signer_title": signer["title"],
        "company_name": "NTXP LLC",
    }

    if include_date:
        data["signature_date"] = now.strftime("%m/%d/%Y")
        data["date"] = now.strftime("%m/%d/%Y")

    return data


def generate_signature_report(request_id, signer_name, document_name,
                              fields_signed, approved_by="Claude session",
                              approval_timestamp=None):
    """Generate an audit record of a signature application."""
    validation = validate_signer(signer_name)
    if not validation["authorized"]:
        return None

    signer = validation["signer"]
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "request_id": request_id,
        "event": "signature_applied",
        "timestamp": approval_timestamp or now,
        "document": document_name,
        "signer": {
            "name": signer["full_name"],
            "title": signer["title"],
            "role": signer["role"],
        },
        "fields_signed": fields_signed,
        "approved_by": approved_by,
        "gate_tier": GATE_TIER,
        "audit_note": (
            f"Signature of {signer['full_name']} applied to {document_name}. "
            f"Tier 3 manual approval obtained. "
            f"{len(fields_signed)} field(s) signed."
        ),
    }


class SignatureNotApproved(Exception):
    pass


def verify_approval(approval, document_path, signer_name):
    """Raise unless approval is an explicit, matching Tier 3 approval for this exact file."""
    validation = validate_signer(signer_name)
    if not validation["authorized"]:
        raise SignatureNotApproved(validation["message"])
    if not approval or approval.get("decision") != "approve":
        raise SignatureNotApproved("No explicit approval recorded. Tier 3 gate is still closed.")
    if approval.get("signer") != validation["signer"]["full_name"]:
        raise SignatureNotApproved("Approval was granted for a different signer.")
    if not approval.get("request_id") or not approval.get("approved_by"):
        raise SignatureNotApproved("Approval record is missing request_id or approved_by.")
    if approval.get("document_sha256") != document_digest(document_path):
        raise SignatureNotApproved(
            "Document changed after approval (SHA-256 mismatch). Re-approval required.")
    return validation["signer"]


def apply_signature(document_path, output_path, signer_name, placements, approval,
                    signature_image=None):
    """Stamp an approved owner signature onto a PDF.

    placements: [{"page": 1, "kind": "signature"|"date"|"name"|"title",
                  "x": float, "y": float, "width": float}] in PDF points.
    Without signature_image, an electronic "/s/ Full Name" signature is drawn.
    """
    signer = verify_approval(approval, document_path, signer_name)

    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas

    reader = PdfReader(str(document_path))
    writer = PdfWriter(clone_from=reader)
    today = datetime.now().strftime("%m/%d/%Y")

    by_page = {}
    for pl in placements:
        by_page.setdefault(int(pl.get("page", 1)), []).append(pl)

    stamped = []
    for page_no, items in by_page.items():
        page = writer.pages[page_no - 1]
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(w, h))
        for pl in items:
            kind = pl.get("kind", "signature")
            x, y = float(pl["x"]), float(pl["y"])
            if kind == "signature" and signature_image:
                c.drawImage(signature_image, x, y, width=float(pl.get("width", 150)),
                            height=float(pl.get("height", 24)), mask="auto",
                            preserveAspectRatio=True)
            elif kind == "signature":
                c.setFont("Times-Italic", 13)
                c.drawString(x, y, f"/s/ {signer['full_name']}")
            else:
                text = {"date": today, "name": signer["full_name"],
                        "title": signer["title"]}.get(kind, "")
                c.setFont("Helvetica", 10)
                c.drawString(x, y, text)
            stamped.append({"page": page_no, "kind": kind})
        c.save()
        buf.seek(0)
        page.merge_page(PdfReader(buf).pages[0])

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)

    record = generate_signature_report(
        approval["request_id"], signer_name, Path(document_path).name, stamped,
        approved_by=approval["approved_by"],
        approval_timestamp=approval.get("approved_at"))
    record["output_sha256"] = document_digest(output_path)
    record["source_sha256"] = approval["document_sha256"]
    return record


def get_signature_workflow_config():
    """Return configuration for integrating signatures into form fill workflow."""
    return {
        "gate_tier": GATE_TIER,
        "gate_action": "explain_and_wait",
        "authorized_signers": {
            k: {"name": v["full_name"], "title": v["title"], "role": v["role"]}
            for k, v in AUTHORIZED_SIGNERS.items()
        },
        "form_types_requiring_signature": sorted(SIGNATURE_FORM_TYPES),
        "rules": [
            "Signatures ALWAYS require Tier 3 manual approval — no exceptions.",
            "Only Trevor Hopkins (owner) and Alison Hopkins (owner) may sign.",
            "Approval must occur within Claude before document goes external.",
            "Every signature application generates an audit record.",
            "Rejected signature requests are logged but no signature is applied.",
            "The signer's name, title, and date are auto-filled from the registry.",
        ],
        "integration_point": "After Phase 3 Step 3-6 (Generate filled PDF), "
                             "before saving to Drive.",
        "workflow_insert": {
            "step": "3-6b",
            "name": "Signature Application (if required)",
            "description": (
                "If the form type requires a signature, detect signature fields, "
                "generate Tier 3 approval request, wait for manual approval, "
                "apply signature data, regenerate PDF, then proceed to save."
            ),
        },
    }


def list_signers():
    """Return the list of authorized signers for display."""
    return [
        {
            "name": s["full_name"],
            "title": s["title"],
            "role": s["role"],
            "email": s["email"],
            "gate_tier": GATE_TIER,
            "always_manual_approval": True,
        }
        for s in AUTHORIZED_SIGNERS.values()
    ]


def main():
    parser = argparse.ArgumentParser(description="FormFlow Signature Manager")
    parser.add_argument("--check", type=str, help="Check if a name is authorized to sign")
    parser.add_argument("--list-signers", action="store_true", help="List authorized signers")
    parser.add_argument("--preview", action="store_true",
                        help="Preview signature approval request")
    parser.add_argument("--document", type=str, help="Document name for preview")
    parser.add_argument("--signer", type=str, help="Signer name for preview")
    parser.add_argument("--form-type", type=str, default="general",
                        help="Form type for preview")
    parser.add_argument("--config", action="store_true",
                        help="Show signature workflow config")
    parser.add_argument("--request", action="store_true",
                        help="Create a hash-bound Tier 3 approval request for --document")
    parser.add_argument("--apply", action="store_true",
                        help="Stamp signature (requires --approval matching the document)")
    parser.add_argument("--output", type=str, help="Signed output PDF path")
    parser.add_argument("--placements", type=str, help="JSON file of placements")
    parser.add_argument("--approval", type=str, help="JSON approval record file")
    parser.add_argument("--signature-image", type=str, default=None)
    args = parser.parse_args()

    if args.request:
        placements = json.loads(Path(args.placements).read_text()) if args.placements else []
        fields = [{"field_name": p.get("kind", "signature"), "page": p.get("page", 1)}
                  for p in placements]
        result = generate_approval_request(
            Path(args.document).name, args.form_type, args.signer, fields,
            document_path=args.document)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["status"] == "pending_approval" else 2)

    if args.apply:
        try:
            record = apply_signature(
                args.document, args.output, args.signer,
                json.loads(Path(args.placements).read_text()),
                json.loads(Path(args.approval).read_text()) if args.approval else None,
                signature_image=args.signature_image)
        except SignatureNotApproved as e:
            print(f"BLOCKED: {e}", file=sys.stderr)
            sys.exit(3)
        print(json.dumps(record, indent=2))
        return

    if args.check:
        result = validate_signer(args.check)
        print(json.dumps(result, indent=2))

    elif args.list_signers:
        signers = list_signers()
        print("\nAuthorized Signers — FormFlow Signature System")
        print("=" * 55)
        for s in signers:
            print(f"\n  {s['name']:25s} | {s['title']}")
            print(f"  {'':25s} | Role: {s['role']}")
            print(f"  {'':25s} | Gate: Tier {s['gate_tier']} (ALWAYS manual)")
        print(f"\nTotal: {len(signers)} authorized signers")
        print("All signatures require Tier 3 manual approval. No exceptions.")

    elif args.preview:
        if not args.document or not args.signer:
            print("Error: --document and --signer required for preview", file=sys.stderr)
            sys.exit(1)

        sample_fields = [
            {"field_name": "Signature", "page": 1},
            {"field_name": "Date", "page": 1},
        ]
        result = generate_approval_request(
            args.document, args.form_type, args.signer,
            sample_fields, save_location="!Company Documents"
        )
        print(json.dumps(result, indent=2))

    elif args.config:
        config = get_signature_workflow_config()
        print(json.dumps(config, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
