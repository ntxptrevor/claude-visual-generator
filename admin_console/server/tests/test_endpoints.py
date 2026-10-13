import json
from pathlib import Path

SAMPLES = Path(__file__).parent / "samples"

CONTACT_KEYS = {"id", "source", "name", "given", "family", "emails", "phones", "org", "title", "address",
                "notes", "labels", "shared", "owner_user", "updated"}
HEALTH_SOURCES = {"gmail", "drive", "calendar", "contacts", "directory", "reports", "jobtread", "plaud",
                  "quo", "council", "sheets_db"}
ACTION_IDS = ["org_mail_search", "attention_today", "shared_contacts", "employee_analytics", "project_pulse",
              "ap_integrity", "drive_finder", "sharing_audit", "meeting_reliability", "account_control"]
TILE_KEYS = {"id", "label", "value", "unit", "display", "target", "trend", "status", "kind", "breakdown", "report_id"}
PERSON_KEYS = {"email", "name", "role", "response_hrs", "unanswered", "baseline_dev", "open_flags", "top_level"}
FLAG_KEYS = {"id", "person", "kpi", "level", "urgency", "channel", "severity", "confidence", "volatility",
             "summary", "evidence", "crosscheck", "council", "created", "status", "escalations"}
REPORT_IDS = ["response_time", "unanswered_email", "wait_complaints", "no_shows", "responsiveness_anomaly",
              "project_folder_access", "daily_report_quality", "po_invoice_integrity", "open_billing_questions",
              "cross_channel_confirmation"]


def test_health(client):
    body = client.get("/api/health").json()
    assert body["demo"] is True
    assert set(body["sources"]) == HEALTH_SOURCES
    assert all(v == "unconfigured" for v in body["sources"].values())


def test_health_reports_configured_google(client, monkeypatch):
    monkeypatch.setenv("NTXP_GOOGLE_SA_EMAIL", "sa@x.iam.gserviceaccount.com")
    monkeypatch.setenv("NTXP_GOOGLE_ADMIN_SUBJECT", "trevor@ntxpllc.com")
    s = client.get("/api/health").json()["sources"]
    assert s["gmail"] == "ok" and s["jobtread"] == "unconfigured"


def test_actions(client):
    items = client.get("/api/actions").json()
    assert [a["id"] for a in items] == ACTION_IDS
    for a in items:
        assert set(a) == {"id", "title", "blurb", "module", "icon"} and all(a.values())
    assert items[4]["title"].startswith("Project pulse")


def test_search_guide_and_run(client):
    g = client.post("/api/search/guide", json={"text": "emails from Marcus about RFI 014 last month"}).json()
    assert g["intent"] in ("message", "trend", "project", "person")
    assert g["restated"] and 2 <= len(g["questions"]) <= 4
    for q in g["questions"]:
        assert set(q) == {"id", "question", "options", "multi"}
    assert set(g["draft"]) == {"people", "users", "from", "to", "date_from", "date_to", "keywords", "project",
                               "has_attachment", "labels"}
    assert g["draft"]["from"] == "marcus.delgado@ntxpllc.com"
    assert g["jev"] == {"tier": 0, "executor": "rules", "cost": 0.0}

    r = client.post("/api/search/run", json={"draft": {**g["draft"], "date_from": "", "date_to": ""},
                                              "answers": {}, "scope": "all", "limit": 10}).json()
    assert set(r) == {"results", "trend", "project", "jev"}
    assert r["results"], "demo data should match Marcus/RFI"
    for hit in r["results"]:
        assert set(hit) == {"id", "source", "user", "from", "to", "subject", "snippet", "date", "thread_id",
                            "link", "score"}
    scores = [h["score"] for h in r["results"]]
    assert scores == sorted(scores, reverse=True)


def test_search_trend_and_project(client):
    r = client.post("/api/search/run", json={"draft": {"keywords": ["daily report"]}, "intent": "trend",
                                              "answers": {"window": "Last 90 days"}}).json()
    assert r["trend"]["buckets"] and r["trend"]["summary"]
    assert {"period", "count"} == set(r["trend"]["buckets"][0])
    assert {"person", "count"} == set(r["trend"]["by_person"][0])
    p = client.post("/api/search/run", json={"draft": {"project": "McShan Elementary Renovation"},
                                              "answers": {"shape": "Everything about one project"}}).json()
    assert set(p["project"]) == {"name", "people", "open_items", "summary"}
    assert p["project"]["open_items"]


def test_search_validation(client):
    assert client.post("/api/search/guide", json={"text": " "}).status_code == 400
    assert client.post("/api/search/run", json={"answers": {}}).status_code == 400


def test_contacts_list_and_paging(client):
    body = client.get("/api/contacts?limit=5").json()
    assert len(body["contacts"]) == 5 and body["next_cursor"] == "5"
    for c in body["contacts"]:
        assert set(c) == CONTACT_KEYS
    rest = client.get(f"/api/contacts?limit=100&cursor={body['next_cursor']}").json()
    assert rest["next_cursor"] is None
    shared = client.get("/api/contacts?source=shared").json()["contacts"]
    assert shared and all(c["source"] == "shared" and c["shared"] for c in shared)
    assert client.get("/api/contacts?q=surety").json()["contacts"]
    assert client.get("/api/contacts?q=9405550142").json()["contacts"]
    assert client.get("/api/contacts?source=bogus").status_code == 400


def test_contacts_patch(client):
    r = client.patch("/api/contacts/dir:marcus.delgado@ntxpllc.com", json={"title": "PM"})
    assert r.status_code == 409 and r.json()["code"] == "read_only"
    r = client.patch("/api/contacts/shared:sc-0003", json={"title": "HVAC Estimating", "phones": "469-555-0163, 469-555-0000"})
    assert r.status_code == 200 and r.json()["title"] == "HVAC Estimating"
    assert r.json()["phones"] == ["469-555-0163", "469-555-0000"]
    r = client.patch("/api/contacts/ws:trevor@ntxpllc.com:people/c1001", json={"title": "Director of Construction"})
    assert r.json()["title"] == "Director of Construction"
    shared = {c["id"]: c for c in client.get("/api/contacts?source=shared").json()["contacts"]}
    assert shared["shared:sc-0001"]["title"] == "Director of Construction"
    assert client.patch("/api/contacts/shared:sc-0003", json={"id": "x"}).status_code == 400
    assert client.patch("/api/contacts/shared:nope", json={"title": "x"}).status_code == 404


def test_contacts_bulk_share_label_unshare(client):
    luis = "ws:trevor@ntxpllc.com:people/c1002"
    r = client.post("/api/contacts/bulk", json={"ids": [luis], "action": "share"}).json()
    assert r == {"done": 1, "failed": [], "tier": 2}
    shared = client.get("/api/contacts?source=shared&q=ortega").json()["contacts"]
    assert len(shared) == 1 and "★ NTXP Shared" not in shared[0]["labels"]
    ws = client.get("/api/contacts?source=workspace&q=ortega").json()["contacts"][0]
    assert ws["shared"] and "★ NTXP Shared" in ws["labels"]

    client.post("/api/contacts/bulk", json={"ids": [shared[0]["id"]], "action": "label", "label": "Electrical"})
    assert "Electrical" in client.get("/api/contacts?source=shared&q=ortega").json()["contacts"][0]["labels"]

    client.post("/api/contacts/bulk", json={"ids": [luis], "action": "unshare"})
    assert client.get("/api/contacts?source=shared&q=ortega").json()["contacts"] == []
    r = client.post("/api/contacts/bulk", json={"ids": ["dir:rosa.jimenez@ntxpllc.com"], "action": "label", "label": "x"}).json()
    assert r["done"] == 0 and r["failed"][0]["id"] == "dir:rosa.jimenez@ntxpllc.com"


def test_contacts_bulk_delete_is_staged(client):
    r = client.post("/api/contacts/bulk", json={"ids": ["shared:sc-0003"], "action": "delete"}).json()
    assert r["needs_approval"] is True and r["summary"] and r["change_id"] and r["tier"] == 3
    assert any(c["id"] == "shared:sc-0003" for c in client.get("/api/contacts?source=shared").json()["contacts"])
    done = client.post(f"/api/approve/{r['change_id']}").json()
    assert done["result"]["done"] == 1
    assert not any(c["id"] == "shared:sc-0003" for c in client.get("/api/contacts?source=shared").json()["contacts"])


def test_contacts_import_preview_and_commit(client):
    data = (SAMPLES / "google_legacy.csv").read_bytes()
    r = client.post("/api/contacts/import", files={"file": ("c.csv", data, "text/csv")}).json()
    assert r["format"] == "google_csv" and len(r["preview"]) == 2
    assert r["duplicates"][0]["existing_id"] == "shared:sc-0001"
    assert r["created"] == 0 and r["skipped"] == 1
    r = client.post("/api/contacts/import?commit=true&target=shared",
                    files={"file": ("c.csv", data, "text/csv")}).json()
    assert r["created"] == 1
    assert client.get("/api/contacts?source=shared&q=ortega").json()["contacts"]
    r = client.post("/api/contacts/import?target=workspace&commit=true",
                    files={"file": ("c.vcf", (SAMPLES / "vcard4.vcf").read_bytes(), "text/vcard")}).json()
    assert r["format"] == "vcf" and r["created"] == 2


def test_contacts_export(client):
    r = client.get("/api/contacts/export?source=shared")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.text.startswith("First Name,Middle Name,Last Name")
    assert "bwalsh@dentonisd.example.org" in r.text
    one = client.get("/api/contacts/export?ids=shared:sc-0002").text
    assert "glin@suretypartners.example.com" in one and "bwalsh" not in one


def test_contacts_sync(client):
    assert client.post("/api/contacts/sync").json() == {"pulled": 4, "shared_added": 0, "shared_removed": 0}
    client.post("/api/contacts/bulk", json={"ids": ["ws:alison@ntxpllc.com:people/c2001"], "action": "unlabel",
                                            "label": "★ NTXP Shared"})
    assert client.post("/api/contacts/sync").json()["shared_removed"] == 1


def test_analytics_endpoints(client):
    s = client.get("/api/analytics/summary").json()
    assert s["updated"] and s["tiles"] and s["people"]
    for t in s["tiles"]:
        assert set(t) == TILE_KEYS
    for p in s["people"]:
        assert set(p) == PERSON_KEYS
    for rid in REPORT_IDS:
        rep = client.get(f"/api/analytics/report/{rid}").json()
        assert {"id", "title", "generated", "period", "sources", "sections", "conclusions", "jev"} <= set(rep)
    assert client.get("/api/analytics/report/nope").status_code == 404
    run = client.post("/api/analytics/run").json()
    assert {"flags_created", "flags_escalated", "jev"} == set(run)


def test_analytics_stream(client):
    r = client.get("/api/analytics/stream?limit=1")
    assert r.headers["content-type"].startswith("text/event-stream")
    lines = [ln for ln in r.text.splitlines() if ln]
    assert "event: tile" in lines
    tile = json.loads(next(ln for ln in lines if ln.startswith("data: "))[6:])
    assert set(tile) == TILE_KEYS


def test_flags(client):
    flags = client.get("/api/flags").json()["flags"]
    assert flags and all(set(f) == FLAG_KEYS for f in flags)
    assert all(f["level"] == 2 for f in client.get("/api/flags?level=2").json()["flags"])
    fid = flags[0]["id"]
    out = client.post(f"/api/flags/{fid}/action", json={"action": "resolve", "note": "handled"}).json()
    assert out["status"] == "resolved"
    assert fid not in [f["id"] for f in client.get("/api/flags").json()["flags"]]
    assert fid in [f["id"] for f in client.get("/api/flags?status=all").json()["flags"]]
    before = flags[1]
    esc = client.post(f"/api/flags/{before['id']}/action", json={"action": "escalate"}).json()
    assert esc["level"] == min(before["level"] + 1, 3)
    assert len(esc["escalations"]) > len(before["escalations"])
    assert client.post("/api/flags/NOPE/action", json={"action": "ack"}).status_code == 404
    assert client.get("/api/analytics/report/bogus").status_code == 404
    assert client.post(f"/api/flags/{fid}/action", json={"action": "nuke"}).status_code == 400


def test_analytics_falls_back_when_package_missing(prod_client, monkeypatch):
    import importlib

    from admin_console.server import app as app_module

    def boom(name):
        raise ImportError(name)

    monkeypatch.setattr(importlib, "import_module", boom)
    assert app_module.analytics_service() is None
    r = prod_client.get("/api/analytics/summary", headers={"X-Forwarded-Email": "trevor@ntxpllc.com"})
    assert r.status_code == 200 and r.json()["tiles"]


def test_runbook(client):
    entries = client.get("/api/runbook").json()["entries"]
    assert entries
    for e in entries:
        assert {"id", "workflow", "symptom", "likely_cause", "steps", "escalate_to", "tier"} <= set(e)
    new = client.post("/api/runbook", json={"workflow": "Contacts import", "symptom": "CSV shows 0 rows",
                                            "steps": ["Re-export as zqxw-encoded"]}).json()
    assert new["id"].startswith("RB-") and new["steps"] == ["Re-export as zqxw-encoded"]
    found = client.get("/api/runbook?q=zqxw").json()["entries"]
    assert [e["id"] for e in found] == [new["id"]]
    assert client.post("/api/runbook", json={"workflow": "x"}).status_code == 400


def test_drive_and_users(client):
    files = client.get("/api/drive/search?q=mcshan").json()["files"]
    assert files and all(set(f) == {"id", "name", "owner", "mime", "modified", "link", "shared_externally"}
                         for f in files)
    assert all(f["owner"] == "rosa.jimenez@ntxpllc.com"
               for f in client.get("/api/drive/search?user=rosa.jimenez@ntxpllc.com").json()["files"])
    assert client.get("/api/drive/search?user=x@gmail.com").status_code == 400
    users = client.get("/api/users").json()["users"]
    assert {u["email"] for u in users} >= {"alison@ntxpllc.com", "trevor@ntxpllc.com"}
    for u in users:
        assert set(u) == {"email", "name", "suspended", "last_login", "is_admin", "org_unit"}


def test_user_actions_staged(client):
    for action, extra in (("suspend", {}), ("unsuspend", {}), ("reset_signin", {}),
                          ("transfer_drive", {"to": "trevor@ntxpllc.com"})):
        r = client.post("/api/users/caleb.whitfield@ntxpllc.com/action", json={"action": action, **extra}).json()
        assert r["needs_approval"] is True and r["change_id"] and r["summary"]
    assert client.post("/api/users/caleb.whitfield@ntxpllc.com/action", json={"action": "transfer_drive"}).status_code == 400
    assert client.post("/api/users/x@gmail.com/action", json={"action": "suspend"}).status_code == 400
    assert client.post("/api/users/caleb.whitfield@ntxpllc.com/action", json={"action": "delete"}).status_code == 400
