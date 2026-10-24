"""Tests for the NTXP Form Fill review GUI server (scripts/nff_gui.py) and export (nff_render.py)."""

import http.client
import json
import re
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nff_gui as gui  # noqa: E402
import nff_render as render  # noqa: E402


def make_form(path):
    """Two pages: AcroForm (text, email, checkbox) + flat page with blanks."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica", 11)
    c.drawString(72, 700, "Legal Business Name:")
    c.acroForm.textfield(name="vendor_name", tooltip="Legal Business Name", x=200, y=694,
                         width=300, height=18, fontSize=11)
    c.drawString(72, 660, "Contact Email:")
    c.acroForm.textfield(name="contact_email", x=200, y=654, width=300, height=18, fontSize=11)
    c.acroForm.checkbox(name="agree_terms", x=72, y=616, size=14)
    c.drawString(92, 619, "I agree to the vendor terms")
    c.showPage()
    c.setFont("Helvetica", 11)
    c.drawString(72, 690, "Company Name: ______________________________")
    c.drawString(72, 650, "Phone: ______________________")
    c.drawString(72, 610, "Total Amount: $____________________")
    c.drawString(72, 540, "Signature ______________________   Date: ______________")
    c.showPage()
    c.save()
    return path


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("NFF_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    pdf = make_form(tmp_path / "vendor_form.pdf")
    session = gui.Session.create(str(pdf), home=tmp_path / "home")
    httpd = gui.make_server(session, 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def call(httpd, method, path, body=None, token=True, headers=None, raw=None):
    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=30)
    h = {"Host": f"127.0.0.1:{httpd.server_address[1]}"}
    if token is True:
        h["X-NFF-Token"] = httpd.session.token
    elif token:
        h["X-NFF-Token"] = token
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    conn.request(method, path, body=data, headers=h)
    r = conn.getresponse()
    payload = r.read()
    conn.close()
    ctype = r.getheader("Content-Type", "")
    return r.status, (json.loads(payload) if "json" in ctype and payload else payload), r


def field_by_label(httpd, label):
    return next(f for f in httpd.session.state["fields"] if f["label"] == label)


# ----------------------------------------------------------------- formatting helpers

@pytest.mark.parametrize("raw,want", [
    ("1234", "$1,234.00"), ("1234.5", "$1,234.50"), ("$1,234.567", "$1,234.57"),
    ("-1234", "($1,234.00)"), ("(1234)", "($1,234.00)"), ("USD 12,000 abc", "$12,000.00"),
    ("0", "$0.00"), ("", ""), ("abc", ""), (None, ""), ("1.2.3", "$12.30"),
])
def test_format_currency(raw, want):
    assert render.format_currency(raw) == want


@pytest.mark.parametrize("raw,want", [
    ("4692487431", "(469) 248-7431"), ("469-248-7431", "(469) 248-7431"),
    ("+1 (469) 248 7431", "(469) 248-7431"), ("12345", "12345"), ("", ""),
])
def test_format_phone(raw, want):
    assert render.format_phone(raw) == want


def test_format_date_and_initials():
    assert render.format_date("2026-10-23") == "10/23/2026"
    assert render.format_date("1/2/26") == "01/02/2026"
    assert render.initials_of("Alison Hopkins") == "AH"


def test_snap_line_is_straight():
    x1, y1, x2, y2 = gui.snap_line(0, 0, 100, 7)          # nearly horizontal
    assert y2 == y1 and x2 > 99
    x1, y1, x2, y2 = gui.snap_line(0, 0, 6, 100)          # nearly vertical
    assert x2 == x1
    x1, y1, x2, y2 = gui.snap_line(10, 10, 60, 55)        # near 45 degrees
    assert abs((x2 - x1) - (y2 - y1)) < 0.05


# ----------------------------------------------------------------- session build

def test_session_detects_and_fills_with_tier1(server):
    fields = {f["label"]: f for f in server.session.state["fields"]}
    assert fields["Legal Business Name"]["value"] == "NTXP LLC"
    assert fields["Legal Business Name"]["state"] == "auto"
    assert fields["Phone"]["value"] == "(469) 248-7431" and fields["Phone"]["type"] == "phone"
    # prices and signatures are never auto-filled
    assert fields["Total Amount"]["type"] == "currency" and fields["Total Amount"]["value"] == ""
    assert fields["Signature"]["type"] == "signature" and fields["Signature"]["value"] == ""
    assert fields["Date"]["type"] == "date"
    assert fields["I agree to the vendor terms"]["type"] == "checkmark"
    sdir = server.session.dir
    assert (sdir / "pages" / "page-1.png").is_file() and (sdir / "state.json").is_file()


# ----------------------------------------------------------------- security

def test_token_required_on_every_api_route(server):
    for method, path, body in [("GET", "/api/session", None), ("GET", "/api/page/1.png", None),
                               ("GET", "/api/proposals", None), ("POST", "/api/field", {"id": "f1"}),
                               ("POST", "/api/export", {"final": True}), ("POST", "/api/stop", {}),
                               ("GET", "/api/download/x.pdf", None)]:
        status, _, _ = call(server, method, path, body, token=None)
        assert status == 401, path
        status, _, _ = call(server, method, path, body, token="wrong-token")
        assert status == 401, path
    status, data, _ = call(server, "GET", "/api/session")
    assert status == 200 and data["fields"]
    status, _, _ = call(server, "GET", f"/api/session?token={server.session.token}", token=None)
    assert status == 200


def test_static_files_and_headers(server):
    status, body, r = call(server, "GET", "/", token=None)
    assert status == 200 and b"NTXP Form Fill" in body
    assert "script-src 'self'" in r.getheader("Content-Security-Policy")
    assert r.getheader("Referrer-Policy") == "no-referrer"
    status, _, _ = call(server, "GET", "/app.js", token=None)
    assert status == 200
    status, _, _ = call(server, "GET", "/../scripts/nff_gui.py", token=None)
    assert status in (400, 404)


def test_bad_host_rejected(server):
    status, _, _ = call(server, "GET", "/api/session", headers={"Host": "evil.example.com"})
    assert status == 403


def test_path_traversal_blocked(server):
    for path in ["/api/download/../state.json", "/api/download/..%2Fstate.json",
                 "/api/download/%2e%2e%2f%2e%2e%2fnff.sqlite", "/api/download/..%5C..%5Cx.pdf",
                 "/api/download/%2Fetc%2Fpasswd", "/api/page/..%2F..%2Fstate.json",
                 "/api/download/source.py", "/api/field-image/..%2Fsource.pdf"]:
        status, _, _ = call(server, "GET", path)
        assert status in (400, 404), path
    s = server.session
    assert gui.safe_download_path(s, "../state.json") is None
    assert gui.safe_download_path(s, "/etc/passwd") is None
    assert gui.safe_download_path(s, "a/../../b.pdf") is None


def test_rejects_non_json_post(server):
    status, _, _ = call(server, "POST", "/api/field", raw=b"id=f1",
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert status == 415


# ----------------------------------------------------------------- field editing

def test_field_update_asks_to_save_and_records_decision(server, tmp_path):
    f = field_by_label(server, "Contact Email")
    status, data, _ = call(server, "POST", "/api/field", {"id": f["id"], "value": "ops@ntxpllc.com"})
    assert status == 200 and data["ask_save"] is True
    status, data, _ = call(server, "POST", "/api/field/save-decision", {"id": f["id"], "decision": "saved"})
    assert status == 200 and data["decision"] == "saved"
    home = Path(server.session.state["nff_home"])
    queue = [json.loads(line) for line in (home / "sheet_push_queue.jsonl").read_text().splitlines()]
    assert queue[-1]["action"] == "manual_entry" and queue[-1]["form_field_title"] == "Contact Email"
    assert queue[-1]["new_value"] == "ops@ntxpllc.com"
    if data["recorded_in"] == "nff_db.change_log":
        import nff_db
        rows = nff_db.pending_sheet_changes(nff_db.connect())
        assert rows[-1]["decision"] == "saved" and rows[-1]["form_field_title"] == "Contact Email"
    else:
        assert (server.session.dir / "change_log.jsonl").is_file()

    # editing an auto-filled value -> manual_edit; ignoring is recorded but not queued
    g = field_by_label(server, "Legal Business Name")
    _, data, _ = call(server, "POST", "/api/field", {"id": g["id"], "value": "NTXP LLC "})
    assert data["ask_save"] is False  # same value after normalisation
    _, data, _ = call(server, "POST", "/api/field", {"id": g["id"], "value": "NTXP Holdings"})
    assert data["ask_save"] is True and data["field"]["pending_save"]["action"] == "manual_edit"
    _, data, _ = call(server, "POST", "/api/field/save-decision", {"id": g["id"], "decision": "ignored"})
    assert data["sheet_queue"] is None


def test_field_values_normalised_by_type(server):
    money = field_by_label(server, "Total Amount")
    _, data, _ = call(server, "POST", "/api/field", {"id": money["id"], "value": "  -1234.5 dollars"})
    assert data["field"]["value"] == "($1,234.50)"
    assert data["ask_save"] is False  # prices never go to the KB
    phone = field_by_label(server, "Phone")
    _, data, _ = call(server, "POST", "/api/field", {"id": phone["id"], "value": "214.555.0100"})
    assert data["field"]["value"] == "(214) 555-0100"


def test_add_field_and_highlight(server):
    status, data, _ = call(server, "POST", "/api/field/add",
                           {"page": 2, "rect": [72, 470, 272, 488], "type": "text_word"})
    assert status == 200 and data["field"]["state"] == "user"
    status, data, _ = call(server, "POST", "/api/highlight",
                           {"page": 1, "x1": 72, "y1": 700, "x2": 300, "y2": 708})
    assert status == 200 and data["highlight"]["y1"] == data["highlight"]["y2"]
    status, _, _ = call(server, "POST", "/api/field/add", {"page": 9, "rect": [0, 0, 10, 10]})
    assert status == 400


# ----------------------------------------------------------------- review / signature / export

def _complete(server):
    box = field_by_label(server, "I agree to the vendor terms")  # reportlab marks it required
    call(server, "POST", "/api/field", {"id": box["id"], "value": "on"})
    for n in (1, 2):
        status, _, _ = call(server, "POST", "/api/page/approve", {"page": n})
        assert status == 200


def test_export_requires_completion_and_has_no_confidence_text(server):
    status, _, _ = call(server, "POST", "/api/export", {"final": True})
    assert status == 409
    money = field_by_label(server, "Total Amount")
    call(server, "POST", "/api/field", {"id": money["id"], "value": "1234.5"})
    _complete(server)
    status, review, _ = call(server, "POST", "/api/review", {})
    assert status == 200 and "confidence" in review
    status, data, _ = call(server, "POST", "/api/export", {"final": True})
    assert status == 200, data
    out = Path(data["path"])
    assert out.is_file() and out.parent.name == "exports"

    from pypdf import PdfReader
    reader = PdfReader(str(out))
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    assert "NTXP LLC" in text and "(469) 248-7431" in text
    assert "1,234.50" in text and "$$" not in text  # form prints its own "$"
    assert "onfidence" not in text and "%" not in text
    assert "/AcroForm" not in reader.trailer["/Root"]  # flattened
    fonts, sizes = set(), set()
    for p in reader.pages:
        for v in (p["/Resources"].get("/Font") or {}).values():
            fonts.add(str(v.get_object()["/BaseFont"]))
        contents = p["/Contents"].get_object()
        streams = contents if isinstance(contents, list) else [contents]
        for c in streams:
            sizes.update(re.findall(rb"/F\d+ ([\d.]+) Tf", c.get_object().get_data()))
    assert any(re.search(r"Helvetica|Arial|LiberationSans", f) for f in fonts)
    assert b"11" in sizes

    status, body, r = call(server, "GET", f"/api/download/{data['file']}")
    assert status == 200 and body[:4] == b"%PDF"


def test_signature_gate(server):
    sig = field_by_label(server, "Signature")
    call(server, "POST", "/api/field", {"id": sig["id"], "value": "Alison Hopkins"})
    _complete(server)
    status, review, _ = call(server, "POST", "/api/review", {})
    assert review["needs_signature_approval"] and review["blocking"] >= 1
    assert call(server, "POST", "/api/export", {"final": True})[0] == 409

    status, data, _ = call(server, "POST", "/api/signature/approve", {"signer": "Alison Hopkins"})
    assert status == 400  # explicit confirmation required
    status, data, _ = call(server, "POST", "/api/signature/approve",
                           {"signer": "Trevor Hopkins", "confirm": True})
    assert status == 400 and "Alison Hopkins" in data["error"]
    status, data, _ = call(server, "POST", "/api/signature/approve",
                           {"signer": "Somebody Else", "confirm": True})
    assert status == 403
    status, data, _ = call(server, "POST", "/api/signature/approve",
                           {"signer": "Alison Hopkins", "confirm": True})
    assert status == 200 and len(data["approval"]["document_sha256"]) == 64

    # any change after approval voids it
    phone = field_by_label(server, "Phone")
    _, upd, _ = call(server, "POST", "/api/field", {"id": phone["id"], "value": "4692487431", "style": {"size": 12}})
    assert upd["signature_approved"] is False
    assert call(server, "POST", "/api/export", {"final": True})[0] == 409

    status, data, _ = call(server, "POST", "/api/signature/approve",
                           {"signer": "Alison Hopkins", "confirm": True})
    assert status == 200
    status, data, _ = call(server, "POST", "/api/export", {"final": True})
    assert status == 200, data
    from pypdf import PdfReader
    text = "\n".join(p.extract_text() or "" for p in PdfReader(data["path"]).pages)
    assert "Alison Hopkins" in text
    assert list(server.session.dir.glob("signature_record_*.json"))


def test_stop_saves_draft_progress(server):
    status, data, _ = call(server, "POST", "/api/stop", {})
    assert status == 200
    assert "DRAFT" in data["file"] and Path(data["path"]).is_file() and Path(data["state_path"]).is_file()
    from pypdf import PdfReader
    text = "\n".join(p.extract_text() or "" for p in PdfReader(data["path"]).pages)
    assert "DRAFT" not in text.upper()  # draft is marked in the filename only


def test_scan_and_proposals_degrade_gracefully(server):
    status, data, _ = call(server, "POST", "/api/scan", {})
    assert status == 200 and (data["ok"] or "Claude" in data["message"])
    status, data, _ = call(server, "GET", "/api/proposals")
    assert status == 200 and isinstance(data["proposals"], list)
    status, data, _ = call(server, "POST", "/api/proposals/apply", {"ids": "all"})
    assert status == 400


# ----------------------------------------------------------------- review findings (PR #5)

def test_canonical_conflicts_are_held_not_autofilled(tmp_path):
    rows = [
        {"field_name": "naics_codes", "field_value": "236220", "source_kind": "owner_canonical",
         "source_title": "Exhibit A", "category": "other", "status": "approved"},
        {"field_name": "naics_codes", "field_value": "238160", "source_kind": "owner_canonical",
         "source_title": "SAM profile", "category": "other", "status": "approved"},
        {"field_name": "cage_code", "field_value": "8ABC1", "source_kind": "owner_canonical",
         "source_title": "Exhibit B", "category": "other", "status": "approved"},
        {"field_name": "cage_code", "field_value": "8ABC1", "source_kind": "kb_manual",
         "source_title": "KB", "category": "other", "status": "approved"},
        {"field_name": "routing_number", "field_value": "111000025", "source_kind": "owner_canonical",
         "source_title": "Exhibit C", "category": "banking", "status": "approved"},
    ]
    values, held = gui.resolve_canonical(rows)
    assert values == {"cage_code": "8ABC1"}
    assert held["naics_codes"]["status"] == "conflict"
    assert "routing_number" in held  # banking is Tier 3: never autofilled

    from reportlab.pdfgen import canvas
    pdf = tmp_path / "sam.pdf"
    c = canvas.Canvas(str(pdf))
    c.setFont("Helvetica", 11)
    c.drawString(72, 700, "NAICS Codes: ______________________")
    c.drawString(72, 660, "CAGE Code: ______________________")
    c.save()
    # The KB also has a (third) NAICS value: a held field must not fall back to it.
    fields, _, _ = gui.build_fields(pdf, "sam_registration", kb={"naics_codes": "999999"},
                                    canonical=values, held=held)
    by = {x["label"]: x for x in fields}
    assert by["NAICS Codes"]["value"] == "" and by["NAICS Codes"]["state"] == "review"
    assert "conflict" in by["NAICS Codes"]["reason"]
    assert by["CAGE Code"]["value"] == "8ABC1" and by["CAGE Code"]["state"] == "auto"


def test_prefilled_acroform_values_survive_flatten(tmp_path, monkeypatch):
    monkeypatch.setenv("NFF_HOME", str(tmp_path / "home"))
    from reportlab.pdfgen import canvas
    pdf = tmp_path / "prefilled.pdf"
    c = canvas.Canvas(str(pdf))
    c.setFont("Helvetica", 11)
    c.drawString(72, 700, "Purchase Order:")
    c.acroForm.textfield(name="po_number", x=200, y=694, width=200, height=18, value="PO-7781 Prefilled")
    c.acroForm.checkbox(name="union_job", x=72, y=650, size=14, checked=True)
    c.drawString(92, 653, "Union job")
    c.save()
    s = gui.Session.create(str(pdf), home=tmp_path / "home")
    by = {f["name"]: f for f in s.state["fields"]}
    assert by["po_number"]["value"] == "PO-7781 Prefilled" and by["po_number"]["state"] == "review"
    assert by["union_job"]["value"] == "on"
    out = gui.api_stop(s)["path"]
    from pypdf import PdfReader
    text = "\n".join(p.extract_text() or "" for p in PdfReader(out).pages)
    assert "PO-7781 Prefilled" in text
    # A widget the overlay does not draw keeps its existing appearance.
    kept = tmp_path / "kept.pdf"
    render.export_pdf(pdf, [], [], kept)
    text = "\n".join(p.extract_text() or "" for p in PdfReader(str(kept)).pages)
    assert "PO-7781 Prefilled" in text


def test_proposals_apply_records_change_log_and_queues_sheet_rows(server, monkeypatch):
    import nff_db
    if gui.optional("nff_scan") is None:
        pytest.skip("nff_scan not installed")
    for k in ("NTXP_GOOGLE_SA_KEY", "NTXP_GOOGLE_SA_EMAIL", "NTXP_GOOGLE_ADMIN_SUBJECT"):
        monkeypatch.delenv(k, raising=False)
    conn = nff_db.connect()
    nff_db.add_proposals(conn, [{"proposal_id": "p1", "field_name": "naics_codes", "proposed_value": "236220",
                                 "current_value": "", "category": "other", "evidence": "[NEW]",
                                 "source_title": "Final RFP response.pdf", "source_ref": "drive:1"}])
    status, data, _ = call(server, "POST", "/api/proposals/apply", {"ids": ["p1"]})
    assert status == 200, data
    assert data["applied"] == ["p1"]
    sheet = data["sheet"]
    assert sheet["row_count"] == 1 and (sheet["rows"]["KB"] or sheet["rows"]["Canonical"])
    assert sheet["status"] in ("appended_live", "queued_for_agent")
    if sheet["status"] == "queued_for_agent":
        assert sheet["written"] is False and Path(sheet["queue_file"]).is_file()
    log = [r for r in nff_db.pending_sheet_changes(conn) if r["action"] == "approved_proposal"]
    assert log and log[-1]["field_name"] == "naics_codes"
    assert nff_db.list_proposals(conn, "pending") == []


def test_flat_form_keeps_repeated_labels_and_checkboxes(tmp_path):
    pytest.importorskip("pdfplumber")
    import nff_detect_fields as det
    from reportlab.pdfgen import canvas
    pdf = tmp_path / "flat.pdf"
    c = canvas.Canvas(str(pdf))
    c.setFont("Helvetica", 11)
    c.drawString(72, 700, "Date: ______________")
    c.drawString(72, 660, "Name: ______________")
    c.drawString(72, 620, "[ ] Yes     [ ] No")
    c.showPage()
    c.setFont("Helvetica", 11)
    c.drawString(72, 700, "Date: ______________")
    c.save()
    fields = det.detect_visual_fields(str(pdf))
    names = [f["field_name"] for f in fields]
    assert "date" in names and "date_2" in names and len(set(names)) == len(names)
    boxes = [f for f in fields if f["field_type"] == "checkbox"]
    assert {b["field_name_raw"] for b in boxes} == {"Yes", "No"}
    assert all("x1" in b["position"] and "y1" in b["position"] for b in boxes)
