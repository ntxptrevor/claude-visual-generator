import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nff_db as db  # noqa: E402
import nff_scan as scan  # noqa: E402
import nff_sync as sync  # noqa: E402

KB = [["id", "category", "field_name", "field_value", "field_type", "confidence", "source"],
      ["1", "business", "cage_code", "1ABC2", "text", "90", "kb"],
      ["2", "banking", "routing_number", "111000025", "text", "90", "kb"],
      ["3", "contact", "fax", "(469) 555-0000", "phone", "80", "kb"]]
CANON = [["answer_id", "exhibit", "category", "field_name", "field_value", "status"],
         ["a1", "A", "insurance", "gl_limit", "1,000,000", "approved"]]
WF = [["workflow_id", "form_type", "form_pattern", "field_map_json", "save_location", "jev_tier"],
      ["w9", "w9", "W-?9", "{}", "Drive", "0"]]


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("NFF_HOME", str(tmp_path))
    return db.connect()


def write_json(tmp_path, tabs, name="tabs.json"):
    f = tmp_path / name
    f.write_text(json.dumps(tabs))
    return str(f)


def run_sync(tmp_path, tabs):
    return sync.main(["--from-json", write_json(tmp_path, tabs)])


def test_schema(conn, tmp_path):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"kb_fields", "canonical", "workflows", "change_log", "field_outcomes", "proposals", "sync_state"} <= names
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert (tmp_path / "nff.sqlite").exists()
    db.record_outcome(conn, "x", "kb", True)
    db.record_outcome(conn, "x", "kb", False)
    assert db.outcome_counts(conn, "x") == (1, 1)


def test_sync_upsert_overwrite_delete(conn, tmp_path):
    assert run_sync(tmp_path, {"KB": KB, "Canonical": CANON, "Workflows": WF}) == 0
    assert db.kb_values(conn)["cage_code"] == "1ABC2"
    assert conn.execute("SELECT COUNT(*) FROM change_log").fetchone()[0] == 0
    kb2 = [KB[0], ["1", "business", "cage_code", "9ZZZ9", "text", "90", "kb"], KB[2]]  # fax deleted
    assert run_sync(tmp_path, {"KB": kb2}) == 0
    vals = db.kb_values(conn)
    assert vals["cage_code"] == "9ZZZ9" and "fax" not in vals
    log = {r["old_value"]: dict(r) for r in conn.execute("SELECT * FROM change_log")}
    assert log["1ABC2"]["new_value"] == "9ZZZ9" and log["1ABC2"]["action"] == "sync_overwrite"
    assert log["1ABC2"]["form_field_title"] == "" and log["1ABC2"]["field_name"] == "cage_code"
    assert any(r["field_name"] == "fax" and r["new_value"] == "" for r in log.values())
    assert db.kb_values(conn)["routing_number"]
    assert len(db.canonical_rows(conn)) == 1  # untouched tab kept


def test_banking_masked(conn, tmp_path, capsys):
    run_sync(tmp_path, {"KB": KB})
    capsys.readouterr()
    assert db.kb_values(conn)["routing_number"] == "111000025"
    assert db.kb_values(conn, masked=True)["routing_number"].endswith("0025")
    assert "111000025" not in db.kb_values(conn, masked=True)["routing_number"]
    run_sync(tmp_path, {"KB": [KB[0], ["2", "banking", "routing_number", "222000025", "text", "90", "kb"]]})
    capsys.readouterr()
    for r in conn.execute("SELECT old_value,new_value FROM change_log WHERE field_name='routing_number'"):
        assert "111000025" not in (r[0] or "") and "222000025" not in (r[1] or "")
    sync.main(["--push-changes"])
    out = capsys.readouterr()
    assert "111000025" not in out.out and "222000025" not in out.out


def test_push_changes_shape(conn, tmp_path, capsys):
    run_sync(tmp_path, {"KB": KB})
    run_sync(tmp_path, {"KB": [KB[0], ["1", "business", "cage_code", "NEW11", "text", "90", "kb"]]})
    capsys.readouterr()
    assert sync.main(["--push-changes"]) == 0
    cap = capsys.readouterr()
    rows = json.loads(cap.out)
    assert rows and all(len(r) == len(db.CHANGE_LOG_HEADERS) for r in rows)
    assert db.CHANGE_LOG_HEADERS.index("action") == 6
    assert all(r[6] == "sync_overwrite" for r in rows)
    ids = cap.err.split("ids: ")[1].split()[0]
    assert sync.main(["--mark-pushed", ids]) == 0
    capsys.readouterr()
    assert db.pending_sheet_changes(conn) == []
    sync.main(["--push-changes"])
    assert json.loads(capsys.readouterr().out) == []
    sync.main(["--status"])
    assert "last_sync_at" in capsys.readouterr().out


def test_live_fails_cleanly(conn, monkeypatch, capsys):
    for k in ("NTXP_GOOGLE_SA_KEY", "NTXP_GOOGLE_SA_EMAIL", "NTXP_GOOGLE_ADMIN_SUBJECT"):
        monkeypatch.delenv(k, raising=False)
    assert sync.main(["--live"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("ERROR:") and len(err.strip().splitlines()) == 1
    assert scan.main(["--live"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("ERROR:") and len(err.strip().splitlines()) == 1


DOCS = [
    {"id": "d1", "title": "Vendor Registration final.pdf", "mimeType": "application/pdf",
     "modifiedTime": "2026-10-20T10:00:00Z", "folder": "company",
     "text": "Company Name: NTXP LLC\nAddress: 405 S Elm St Ste 203 Denton\nPhone: 214-555-1111\n"
             "CAGE: 7XYZ9\nFax: (469) 555-0000\nRouting Number: 999999999\nBid Amount: 123,456\n"
             "Email: bids@ntxpllc.com\nDOB: 01/02/1980\n"},
    {"id": "d2", "title": "old.pdf", "mimeType": "application/pdf", "modifiedTime": "2020-01-01T00:00:00Z",
     "text": "Email: stale@example.com"},
]


@pytest.fixture
def seeded(conn, tmp_path):
    run_sync(tmp_path, {"KB": KB, "Canonical": CANON})
    return conn


def test_scan_proposals(seeded, tmp_path):
    props = scan.build_proposals(seeded, DOCS, 30)
    by = {p["field_name"]: p for p in props}
    assert set(by) == {"cage_code", "routing_number", "email"}
    assert by["cage_code"]["evidence"].startswith("[CHANGED]") or by["cage_code"]["evidence"].startswith("[CONFLICT]")
    assert by["email"]["evidence"].startswith("[NEW]")
    assert "[Tier 3]" in by["routing_number"]["evidence"]
    for banned in ("phone", "company_name", "street_address", "bid_amount", "dob"):
        assert banned not in by
    assert all("405 S Elm" not in p["proposed_value"] for p in props)
    assert "stale@example.com" not in {p["proposed_value"] for p in props}


def test_checklist_html_pdf(seeded, tmp_path):
    props = scan.build_proposals(seeded, DOCS, 30)
    db.add_proposals(seeded, props)
    res = scan.write_checklist(db.list_proposals(seeded))
    page = Path(res["html"]).read_text()
    assert page.count('type="checkbox"') == 3 and "checked" not in page
    assert "999999999" not in page
    from pypdf import PdfReader
    assert len(PdfReader(res["pdf"]).pages) == 1
    # overflow: many proposals still one page, with a "+N more" note
    many = [{"proposal_id": f"p{i}", "field_name": f"field_{i}", "proposed_value": "v" * 300, "current_value": "",
             "category": f"cat{i % 4}", "evidence": "[NEW] x", "source_title": "t" * 200, "source_ref": ""}
            for i in range(200)]
    res = scan.write_checklist(many, tmp_path / "big")
    assert len(PdfReader(res["pdf"]).pages) == 1 and res["hidden"] > 0
    assert "more in the GUI" in Path(res["html"]).read_text()


def test_apply(seeded, tmp_path, capsys):
    db.add_proposals(seeded, scan.build_proposals(seeded, DOCS, 30))
    by = {p["field_name"]: p for p in db.list_proposals(seeded)}
    ids = ",".join([by["email"]["proposal_id"], by["routing_number"]["proposal_id"]])
    out = scan.apply_proposals(seeded, ids.split(","))
    assert len(out["applied"]) == 1 and "Tier 3" in out["skipped"][0]["reason"]
    row = out["kb"]["rows"][0]
    assert row[out["kb"]["headers"].index("field_name")] == "email"
    assert db.list_proposals(seeded, "approved")[0]["field_name"] == "email"
    cl = [dict(r) for r in seeded.execute("SELECT * FROM change_log WHERE action='approved_proposal'")]
    assert len(cl) == 1 and cl[0]["field_name"] == "email" and cl[0]["pushed_to_sheet"] == 0
    # CLI path: tier 3 approved, output masked unless confirmed
    rid = by["routing_number"]["proposal_id"]
    capsys.readouterr()
    assert scan.main(["--apply", rid, "--approve-tier3"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["canonical"]["rows"][0][3] == "routing_number" and out["canonical"]["rows"][0][9] == "approved"
    assert len(out["canonical"]["rows"][0]) == len(out["canonical"]["headers"])


def test_failed_live_write_stays_pending(seeded):
    db.add_proposals(seeded, scan.build_proposals(seeded, DOCS, 30))
    pid = {p["field_name"]: p for p in db.list_proposals(seeded)}["email"]["proposal_id"]

    def boom(out):
        raise RuntimeError("Could not append to KB tab: expired credentials")

    with pytest.raises(RuntimeError):
        scan.apply_proposals(seeded, [pid], writer=boom)
    assert pid in {p["proposal_id"] for p in db.list_proposals(seeded, "pending")}
    assert not seeded.execute("SELECT 1 FROM change_log WHERE action='approved_proposal'").fetchone()
    out = scan.apply_proposals(seeded, [pid], writer=lambda o: None)
    assert out["applied"] == [pid]


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_db_files_owner_only(tmp_path):
    p = tmp_path / "home" / "nff.sqlite"
    c = db.connect(p)
    c.execute("INSERT INTO sync_state(key, value) VALUES('k','v')")
    c.commit()
    assert (p.parent.stat().st_mode & 0o777) == 0o700
    assert (p.stat().st_mode & 0o777) == 0o600
    c.close()
