import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import formflow_fill_pdf as fill  # noqa: E402
import formflow_jev_router as jev  # noqa: E402
import formflow_signatures as sig  # noqa: E402
import formflow_workflow_registry as reg  # noqa: E402

STALE_KB = {
    "company_name": "NTXP Professional LLC",
    "street_address": "405 S Elm St Ste 203",
    "city_state_zip": "Denton, TX 76201",
    "phone": "(214) 555-0000",
    "owner_name": "Trevor Hopkins",
    "ein": "87-2033276",
    "tax_classification": "LLC",
}


def by_field(answers):
    return {a["field_name"]: a for a in answers}


def test_w9_answers_enforce_tier1_over_stale_kb():
    out = reg.build_acroform_answers("w9", STALE_KB)
    a = by_field(out["answers"])
    assert a["f1_01[0]"]["field_value"] == "NTXP LLC"
    assert a["f1_07[0]"]["field_value"] == "101 South Locust St Ste 605"
    assert a["f1_08[0]"]["field_value"] == "Denton, TX 76201"
    assert (a["f1_14[0]"]["field_value"], a["f1_15[0]"]["field_value"]) == ("87", "2033276")


def test_w9_checks_s_corp_only_and_never_the_llc_box():
    a = by_field(reg.build_acroform_answers("w9", STALE_KB)["answers"])
    assert a["c1_1[2]"]["field_value"] == "/3"
    assert "c1_1[5]" not in a and "f1_03[0]" not in a
    assert not any(k.startswith("c1_1[") and k != "c1_1[2]" for k in a)


def test_w9_missing_kb_values_are_reported_as_manual():
    out = reg.build_acroform_answers("w9", {})
    manual = {m["field_name"] for m in out["manual"]}
    assert "f1_14[0]" in manual and "f1_15[0]" in manual
    assert "f1_07[0]" not in manual


def test_unknown_layout_raises():
    with pytest.raises(KeyError):
        reg.build_acroform_answers("daily_report", {})


def test_resolve_overrides_identity_fields():
    values, sources = reg.resolve_kb_values(STALE_KB)
    assert values["owner_name"] == "Alison Hopkins"
    assert values["signer_name"] == "Alison Hopkins"
    assert values["contact_name"] == "Trevor Hopkins"
    assert values["phone"] == "469-248-7431"
    assert sources["street_address"] == "tier1"


def test_signer_defaults_to_alison_and_trevor_needs_circumstance(tmp_path):
    doc = tmp_path / "f.pdf"
    doc.write_bytes(b"%PDF-1.4 test")
    req = sig.generate_approval_request("f.pdf", "w9", None, [], document_path=str(doc))
    assert req["status"] == "pending_approval"
    assert req["approval_request"]["signer"]["name"] == "Alison Hopkins"
    assert sig.generate_approval_request("f.pdf", "w9", "Trevor Hopkins", [])["status"] == "needs_circumstance"
    ok = sig.generate_approval_request("f.pdf", "w9", "Trevor Hopkins", [], circumstance="Alison traveling")
    assert ok["status"] == "pending_approval"
    assert sig.generate_approval_request("f.pdf", "w9", "Jane Doe", [])["status"] == "denied"


def test_apply_signature_requires_matching_approval(tmp_path):
    doc = tmp_path / "f.pdf"
    doc.write_bytes(b"%PDF-1.4 test")
    good = {"decision": "approve", "signer": "Trevor Hopkins", "request_id": "r",
            "approved_by": "owner", "document_sha256": sig.document_digest(doc)}
    with pytest.raises(sig.SignatureNotApproved):
        sig.verify_approval(None, doc, "Alison Hopkins")
    with pytest.raises(sig.SignatureNotApproved):
        sig.verify_approval(good, doc, "Trevor Hopkins")
    good["circumstance"] = "Alison traveling"
    assert sig.verify_approval(good, doc, "Trevor Hopkins")["full_name"] == "Trevor Hopkins"
    doc.write_bytes(b"%PDF-1.4 edited")
    with pytest.raises(sig.SignatureNotApproved):
        sig.verify_approval(good, doc, "Trevor Hopkins")


def test_jev_routes_signatures_to_tier3():
    assert jev.route_signature()["signer"] == "Alison Hopkins"
    assert jev.route_signature("Trevor Hopkins")["executor"] == "needs_circumstance"
    assert jev.route_signature("Jane Doe")["executor"] == "denied"
    assert jev.route_signature("Trevor Hopkins", circumstance="x")["gate_tier"] == 3


def _w9_like_pdf(path):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path))
    form = c.acroForm
    for i, name in enumerate(["f1_01[0]", "f1_07[0]", "f1_08[0]", "f1_14[0]", "f1_15[0]"]):
        form.textfield(name=name, x=50, y=700 - i * 40, width=300, height=20)
    for i, name in enumerate(["c1_1[0]", "c1_1[2]", "c1_1[5]"]):
        form.checkbox(name=name, x=400, y=700 - i * 40, size=12)
    c.showPage()
    c.save()


def test_end_to_end_w9_fill(tmp_path):
    blank, out = tmp_path / "w9.pdf", tmp_path / "out.pdf"
    _w9_like_pdf(blank)
    answers = reg.build_acroform_answers("w9", STALE_KB)["answers"]
    fill.fill_acroform(str(blank), answers, str(out))
    from pypdf import PdfReader
    fields = {k.split(".")[-1]: v.get("/V") for k, v in PdfReader(str(out)).get_fields().items()}
    assert fields["f1_07[0]"] == "101 South Locust St Ste 605"
    assert fields["c1_1[2]"] not in (None, "/Off")
    assert fields["c1_1[5]"] in (None, "/Off")


def test_cli_writes_answers(tmp_path):
    import subprocess
    kb, out = tmp_path / "kb.json", tmp_path / "answers.json"
    kb.write_text(json.dumps(STALE_KB))
    r = subprocess.run([sys.executable, str(ROOT / "scripts/formflow_workflow_registry.py"),
                        "--answers", "w9", "--kb-json", str(kb), "--output", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert {a["field_name"] for a in json.loads(out.read_text())} >= {"f1_01[0]", "c1_1[2]"}


def test_numbered_folders_always_route_inside_the_project():
    for ft in ("safety_checklist", "inspection_request", "insurance_cert", "punch_list"):
        loc = jev.route_save_location(ft, project_name="Ralls")["location"]
        assert loc.startswith("!Active Projects/Ralls/"), (ft, loc)
    assert jev.route_save_location("w9", project_name="Ralls")["location"] == "!Company Documents"


def test_drive_scan_never_ingests_tier1_identity_fields():
    import formflow_drive_scanner as ds
    text = ("Insured: NTXP LLC\nStreet/Mailing Address: 405 S Elm St Ste 203\n"
            "City: Denton State: TX Zip Code: 76201\nPhone number: (214) 555-0000")
    fields = {f["field_name"] for f in ds.extract_fields_from_text(text)}
    assert not fields & set(sig.TIER1_FIELD_OVERRIDES)
