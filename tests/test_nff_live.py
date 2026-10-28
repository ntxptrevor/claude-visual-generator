"""Live view: markups, stamps, server-sent events, live snapshots and the nff_live.py client."""
import http.client
import json
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import nff_gui as gui  # noqa: E402
import nff_live as live  # noqa: E402
import nff_markup as markup  # noqa: E402
from test_nff_gui import call, make_form, server  # noqa: E402,F401

PAGES = [{"n": 1, "w": 612.0, "h": 792.0}, {"n": 2, "w": 2592.0, "h": 1728.0}]  # letter + ARCH D


# ------------------------------------------------------------------ markup module
def test_normalize_converts_top_left_and_applies_ntxp_rules():
    m = markup.normalize({"kind": "cloud", "page": 1, "rect": [100, 100, 300, 200], "color": "#D10000",
                          "opacity": 1.0}, PAGES)
    assert m["rect"] == [100.0, 592.0, 300.0, 692.0]          # top-left -> PDF space
    assert m["color"] == "#FF0000"                               # LOCK-02 legacy red
    assert m["opacity"] == 0.8 and m["halo"] is True             # LOCK-07 / LOCK-08
    box = markup.normalize({"kind": "bounding_box", "page": 1, "rect": [0, 0, 50, 50]}, PAGES)
    assert box["kind"] == "rectangle" and box["opacity"] == 1.0  # LOCK-10
    area = markup.normalize({"kind": "area_measure", "page": 1, "points": [[0, 0], [10, 0], [10, 10]],
                             "fill_opacity": 0.9}, PAGES)
    assert area["fill_opacity"] == 0.3                           # LOCK-09


def test_normalize_rejects_bad_input():
    for bad in ({"kind": "hexagon", "page": 1}, {"kind": "cloud", "page": 9, "rect": [0, 0, 9, 9]},
                {"kind": "text", "page": 1, "rect": [0, 0, 90, 40]},
                {"kind": "stamp", "page": 1, "rect": [0, 0, 90, 40], "status": "LOOKS GOOD"},
                {"kind": "arrow", "page": 1, "start": [1, 1], "end": [1, 1]},
                {"kind": "cloud", "page": 1, "rect": [0, 0, 9, 9], "color": "javascript:1"}):
        with pytest.raises(markup.MarkupError):
            markup.normalize(bad, PAGES)


def test_import_v3_manifest_inches_and_skips():
    manifest = {"schema_version": "3.0", "coordinate_mode": "inches", "markups": [
        {"id": "RFI-042-01", "kind": "cloud", "page": 2, "rect": [10, 5, 14, 8]},
        {"id": "RFI-042-02", "type": "leader", "page": 2, "geometry": {"start": [1, 1], "end": [3, 2]}},
        {"id": "RFI-042-03", "kind": "count_tag", "page": 2, "point": [1, 1]}]}
    out, skipped = markup.import_manifest(manifest, PAGES)
    assert [m["id"] for m in out] == ["RFI-042-01", "RFI-042-02"]
    assert out[0]["rect"] == [720.0, 1152.0, 1008.0, 1368.0]
    assert out[1]["kind"] == "arrow" and skipped[0]["id"] == "RFI-042-03"


def test_cloud_is_one_sided_outward():
    rect = [100, 100, 300, 200]
    for a, q, b in markup.cloud_points(rect):
        inside = rect[0] < q[0] < rect[2] and rect[1] < q[1] < rect[3]
        assert not inside  # every scallop bulges outward (LOCK-12)


def test_export_draws_markups(tmp_path):
    from pypdf import PdfReader
    import nff_render as render
    pdf = make_form(tmp_path / "f.pdf")
    pages = render.page_sizes(pdf)
    mks = [markup.normalize({"kind": "text", "page": 1, "rect": [300, 80, 560, 130],
                             "text": "RFI 042 CONFIRM DUCT"}, pages),
           markup.normalize({"kind": "stamp", "page": 1, "rect": [380, 600, 590, 700],
                             "status": "APPROVED AS NOTED", "reviewer": "Trevor Hopkins"}, pages),
           markup.normalize({"kind": "cloud", "page": 2, "rect": [60, 60, 300, 160], "text": "RFI 043 WALL TYPE"}, pages)]
    out = tmp_path / "out.pdf"
    res = render.export_pdf(pdf, [], [], out, markups=mks)
    assert res["drawn"] == 3
    text = PdfReader(str(out)).pages[0].extract_text()
    assert "RFI 042 CONFIRM DUCT" in text and "APPROVED AS NOTED" in text
    assert "RFI 043 WALL TYPE" in PdfReader(str(out)).pages[1].extract_text()


# ------------------------------------------------------------------ server
def test_markup_api_roundtrip_and_digest(server):  # noqa: F811
    s = server.session
    d0, r0 = s.digest(), s.rev
    st, data, _ = call(server, "POST", "/api/markup",
                       {"kind": "arrow", "page": 1, "start": [330, 108], "end": [262, 158], "text": "Conflict"})
    assert st == 200 and data["markup"]["kind"] == "arrow" and data["rev"] > r0
    mid = data["markup"]["id"]
    assert s.digest() != d0
    st, data, _ = call(server, "POST", "/api/markup/update", {"id": mid, "color": "#0000ff"})
    assert st == 200 and data["markup"]["color"] == "#0000FF" and data["markup"]["start"] == [330.0, 684.0]
    st, data, _ = call(server, "POST", "/api/markup", {"kind": "cloud", "page": 1, "rect": [1, 2]})
    assert st == 400
    st, data, _ = call(server, "GET", "/api/session")
    assert any(m["id"] == mid for m in data["markups"]) and "stamp_statuses" in data
    st, data, _ = call(server, "POST", "/api/markup/delete", {"id": mid})
    assert st == 200 and not s.state["markups"]


def test_import_endpoint(server):  # noqa: F811
    manifest = {"markups": [{"id": "A-1", "kind": "cloud", "page": 1, "rect": [96, 128, 268, 232]},
                            {"id": "A-2", "kind": "nope", "page": 1}]}
    st, data, _ = call(server, "POST", "/api/markups/import", {"manifest": manifest})
    assert st == 200 and data["added"] == ["A-1"] and data["skipped"][0]["id"] == "A-2"


def test_stamp_requires_tier3_approval_for_final_export(server):  # noqa: F811
    s = server.session
    call(server, "POST", "/api/markup", {"kind": "stamp", "page": 1, "rect": [380, 600, 590, 700],
                                         "status": "APPROVED", "reviewer": "Alison Hopkins"})
    assert [x["type"] for x in s.attested()] == ["stamp"]
    for f in s.state["fields"]:
        f["approved"] = True
        if f["type"] in ("signature", "initials"):
            f["value"] = ""
    st, data, _ = call(server, "POST", "/api/export", {"final": True})
    assert st == 409


def test_event_stream_pushes_programmatic_changes(server):  # noqa: F811
    port, token = server.server_address[1], server.session.token
    got = []

    def listen():
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        conn.request("GET", f"/api/events?since={server.session.rev}",
                     headers={"Host": f"127.0.0.1:{port}", "X-NFF-Token": token})
        r = conn.getresponse()
        got.append(r.getheader("Content-Type"))
        while True:
            line = r.fp.readline().decode()
            if line.startswith("event: change"):
                got.append(json.loads(r.fp.readline().decode()[5:]))
                break
        conn.close()

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(0.3)
    call(server, "POST", "/api/markup", {"kind": "rectangle", "page": 2, "rect": [72, 72, 200, 140]})
    t.join(10)
    assert got and got[0].startswith("text/event-stream")
    assert len(got) == 2 and got[1]["rev"] == server.session.rev


def test_event_stream_requires_token(server):  # noqa: F811
    st, _, _ = call(server, "GET", "/api/events", token=False)
    assert st == 401


def test_live_snapshot_png_reflects_markups(server):  # noqa: F811
    st, before, r = call(server, "GET", "/api/page/1/live.png")
    assert st == 200 and r.getheader("Content-Type") == "image/png" and before[:8] == b"\x89PNG\r\n\x1a\n"
    call(server, "POST", "/api/markup", {"kind": "area", "page": 1, "rect": [72, 72, 400, 300]})
    st, after, _ = call(server, "GET", "/api/page/1/live.png")
    assert st == 200 and after != before
    st, _, _ = call(server, "GET", "/api/page/99/live.png")
    assert st == 404


def test_live_client_drives_running_session(server, tmp_path, monkeypatch, capsys):  # noqa: F811
    url = f"http://127.0.0.1:{server.server_address[1]}/?token={server.session.token}"
    assert live.main(["--url", url, "cloud", "--page", "1", "--rect", "96", "128", "268", "232"]) == 0
    assert live.main(["--url", url, "stamp", "--page", "1", "--rect", "380", "40", "590", "140",
                      "--status", "REVISE AND RESUBMIT", "--reviewer", "Alison Hopkins"]) == 0
    kinds = [m["kind"] for m in server.session.state["markups"]]
    assert kinds == ["cloud", "stamp"]
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({"markups": [{"kind": "line", "page": 2, "start": [10, 10], "end": [90, 10]}]}))
    assert live.main(["--url", url, "import", str(manifest)]) == 0
    out = tmp_path / "snap.png"
    assert live.main(["--url", url, "snapshot", "--page", "1", "--out", str(out)]) == 0
    assert out.read_bytes()[:4] == b"\x89PNG"
    capsys.readouterr()
    assert live.main(["--url", url, "status"]) == 0
    assert json.loads(capsys.readouterr().out)["markups"] == 3


def test_stamps_stay_out_of_drafts_and_snapshots_until_approved(server, tmp_path):  # noqa: F811
    from pypdf import PdfReader
    s = server.session
    call(server, "POST", "/api/markup", {"kind": "stamp", "page": 1, "rect": [380, 600, 590, 700],
                                         "status": "APPROVED", "reviewer": "Alison Hopkins"})
    call(server, "POST", "/api/markup", {"kind": "text", "page": 1, "rect": [300, 80, 560, 130], "text": "DRAFT NOTE"})
    out = tmp_path / "draft.pdf"
    s.write_pdf(out, include_signatures=False)
    text = PdfReader(str(out)).pages[0].extract_text()
    assert "DRAFT NOTE" in text and "APPROVED" not in text
    signed = tmp_path / "signed.pdf"
    s.write_pdf(signed, include_signatures=True)
    assert "APPROVED" in PdfReader(str(signed)).pages[0].extract_text()


def test_stamp_reviewer_must_match_signer(server):  # noqa: F811
    call(server, "POST", "/api/markup", {"kind": "stamp", "page": 1, "rect": [380, 600, 590, 700],
                                         "status": "APPROVED", "reviewer": "Trevor Hopkins"})
    st, data, _ = call(server, "POST", "/api/signature/approve", {"signer": "Alison Hopkins", "confirm": True})
    assert st == 400 and "does not match signer" in data["error"]


def test_partial_geometry_update_and_stamp_status(server):  # noqa: F811
    st, data, _ = call(server, "POST", "/api/markup", {"kind": "arrow", "page": 1, "start": [100, 100], "end": [200, 150]})
    mid = data["markup"]["id"]
    st, data, _ = call(server, "POST", "/api/markup/update", {"id": mid, "start": [100, 100], "end": [300, 150]})
    assert st == 200 and data["markup"]["start"] == [100.0, 692.0] and data["markup"]["end"] == [300.0, 642.0]
    st, data, _ = call(server, "POST", "/api/markup/update", {"id": mid, "end": [300, 150]})
    assert st == 400  # partial geometry is refused rather than mixed across frames
    st, data, _ = call(server, "POST", "/api/markup", {"kind": "stamp", "page": 1, "rect": [380, 600, 590, 700],
                                                        "status": "APPROVED"})
    sid = data["markup"]["id"]
    st, data, _ = call(server, "POST", "/api/markup/update", {"id": sid, "status": "rejected"})
    assert st == 200 and data["markup"]["stamp_status"] == "REJECTED" and "status" not in data["markup"]


def test_digest_unchanged_without_markups(server):  # noqa: F811
    s = server.session
    s.state.pop("markups", None)
    d = s.digest()
    s.state["markups"] = []
    assert s.digest() == d


@pytest.fixture()
def plan_server(tmp_path, monkeypatch):
    """A markup-only construction sheet (no form fields)."""
    from reportlab.pdfgen import canvas
    monkeypatch.setenv("NFF_HOME", str(tmp_path / "home"))
    pdf = tmp_path / "A101.pdf"
    c = canvas.Canvas(str(pdf), pagesize=(2592, 1728))
    c.setLineWidth(3)
    c.rect(360, 420, 520, 360)
    c.save()
    session = gui.Session.create(str(pdf), home=tmp_path / "home")
    httpd = gui.make_server(session, 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def test_markup_only_set_exports_and_stamp_needs_then_gets_approval(plan_server):
    from pypdf import PdfReader
    s = plan_server.session
    assert not s.state["fields"] and not s.progress()["completed"]
    call(plan_server, "POST", "/api/markup", {"kind": "cloud", "page": 1, "rect": [860, 380, 1320, 780],
                                              "text": "RFI 043"})
    assert s.progress()["completed"]
    call(plan_server, "POST", "/api/markup", {"kind": "stamp", "page": 1, "rect": [2150, 1250, 2450, 1450],
                                              "status": "APPROVED AS NOTED"})
    st, review, _ = call(plan_server, "POST", "/api/review", {})
    assert review["needs_signature_approval"] is True and not review["can_export"]
    st, before, _ = call(plan_server, "GET", "/api/page/1/live.png")
    st, data, _ = call(plan_server, "POST", "/api/signature/approve", {"signer": "Alison Hopkins", "confirm": True})
    assert st == 200, data
    st, after, _ = call(plan_server, "GET", "/api/page/1/live.png")
    assert st == 200 and after != before  # the approved stamp now shows in the snapshot
    assert s.state["markups"][1]["reviewer"] == "Alison Hopkins"
    st, data, _ = call(plan_server, "POST", "/api/export", {"final": True})
    assert st == 200, data
    text = PdfReader(data["path"]).pages[0].extract_text()
    assert "APPROVED AS NOTED" in text and "RFI 043" in text and "Alison Hopkins" in text


def test_cloud_segment_survives_update(server):  # noqa: F811
    st, data, _ = call(server, "POST", "/api/markup", {"kind": "cloud", "page": 1, "rect": [96, 128, 268, 232],
                                                        "cloud_segment_length": 14})
    mid = data["markup"]["id"]
    st, data, _ = call(server, "POST", "/api/markup/update", {"id": mid, "color": "#0000FF"})
    assert data["markup"]["cloud_segment"] == 14.0


def test_page_sizes_report_crop_box_and_rotation(tmp_path):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import RectangleObject
    from reportlab.pdfgen import canvas
    import nff_render as render
    src = tmp_path / "src.pdf"
    c = canvas.Canvas(str(src), pagesize=(612, 792))
    c.showPage(); c.showPage(); c.save()
    w = PdfWriter()
    for i, p in enumerate(PdfReader(str(src)).pages):
        w.add_page(p)
        if i == 1:
            w.pages[-1].rotate(90)
            w.pages[-1].cropbox = RectangleObject([50, 40, 600, 780])
    out = tmp_path / "rot.pdf"
    w.write(str(out))
    a, b = render.page_sizes(out)
    assert a == {"w": 612.0, "h": 792.0, "ox": 0.0, "oy": 0.0, "rot": 0}
    assert b == {"w": 550.0, "h": 740.0, "ox": 50.0, "oy": 40.0, "rot": 90}
    # the markup frame uses the crop box: top-left (0, 0) is the crop box's top-left corner
    m = markup.normalize({"kind": "rectangle", "page": 2, "rect": [0, 0, 10, 10]}, [a, b])
    assert m["rect"] == [50.0, 770.0, 60.0, 780.0]
