import datetime as dt

import pytest

from admin_console.analytics import collectors, service, store, util
from admin_console.analytics.collectors import calendar, gmail, jobtread

from .conftest import NOW

TILE_KEYS = {"id", "label", "value", "unit", "display", "target", "trend", "status", "kind",
             "breakdown", "report_id"}
PERSON_KEYS = {"email", "name", "role", "response_hrs", "unanswered", "baseline_dev",
               "open_flags", "top_level"}
FLAG_KEYS = {"id", "person", "kpi", "level", "urgency", "channel", "severity", "confidence",
             "volatility", "summary", "evidence", "crosscheck", "council", "created", "status",
             "escalations"}
REPORT_KEYS = {"id", "title", "generated", "period", "sources", "sections", "conclusions", "jev"}
REPORT_IDS = ["response_time", "unanswered_email", "wait_complaints", "no_shows",
              "responsiveness_anomaly", "project_folder_access", "daily_report_quality",
              "po_invoice_integrity", "open_billing_questions", "cross_channel_confirmation"]


# --------------------------------------------------------------------------- collectors

def test_live_adapters_degrade_to_unconfigured(live):
    events, status, failures = collectors.collect_all(NOW)
    assert events == [] and failures == []
    assert set(status.values()) == {"unconfigured"}
    assert set(status) == set(collectors.SOURCES)


def _msg(i, frm, to, hours_ago, snippet="", subject="Punch list", cc=(), automated=False):
    return {"id": f"m{i}", "ts": util.as_utc(NOW) - dt.timedelta(hours=hours_ago), "from": frm,
            "to": list(to), "cc": list(cc), "subject": subject, "snippet": snippet, "automated": automated}


def test_gmail_thread_response_unanswered_complaint_forwarding():
    u = "jake@ntxpllc.com"
    replied = gmail.analyze_thread(u, [_msg(1, "pm@client.org", [u], 30),
                                       _msg(2, u, ["pm@client.org"], 27)], NOW, "t1")
    assert [e["kind"] for e in replied] == ["response"] and replied[0]["meta"]["internal"] is False
    open_ = gmail.analyze_thread(u, [_msg(1, "pm@client.org", [u], 30,
                                          snippet="We are still waiting on the walk. Super was a no-show.")],
                                 NOW, "t2")
    kinds = {e["kind"]: e for e in open_}
    assert "unanswered" in kinds and kinds["complaint"]["meta"]["forwarded"] is False
    assert kinds["complaint"]["meta"]["complaint_type"] == "no-show"
    fwd = gmail.analyze_thread(u, [_msg(1, "pm@client.org", [u], 30, snippet="3rd request for the punch list"),
                                   _msg(2, u, ["office@ntxpllc.com"], 29, subject="Fwd: Punch list")], NOW, "t3")
    comp = next(e for e in fwd if e["kind"] == "complaint")
    assert comp["meta"]["forwarded"] is True and comp["meta"]["forward_lag_bh"] >= 0


def test_gmail_excludes_newsletters_and_noreply():
    u = "jake@ntxpllc.com"
    assert gmail.analyze_thread(u, [_msg(1, "no-reply@vendor.com", [u], 40)], NOW) == []
    assert gmail.analyze_thread(u, [_msg(1, "news@vendor.com", [u], 40, automated=True)], NOW) == []


def test_gmail_internal_message_event_is_internal_only():
    u = "maria@ntxpllc.com"
    ev = gmail.analyze_thread(u, [_msg(1, u, ["dana@ntxpllc.com"], 2, snippet="hi")], NOW)
    assert ev[0]["kind"] == "message" and ev[0]["meta"]["internal"] is True
    ext = gmail.analyze_thread(u, [_msg(1, u, ["gc@client.org"], 2, snippet="hi")], NOW)
    assert all(e["kind"] != "message" for e in ext)


def test_calendar_no_show_needs_attendance_data():
    item = {"id": "e1", "summary": "OAC", "start": {"dateTime": "2026-10-08T14:00:00-05:00"},
            "attendees": [{"email": "jake@ntxpllc.com", "responseStatus": "accepted"},
                          {"email": "owner@client.org", "responseStatus": "accepted"}],
            "conferenceData": {"conferenceId": "abc-defg-hij"}}
    assert calendar.classify_event("jake@ntxpllc.com", item, None)[0]["meta"]["attendance"] == "unknown"
    absent = calendar.classify_event("jake@ntxpllc.com", item, {"abc-defg-hij": {"owner@client.org"}})
    assert absent[0]["kind"] == "no_show" and absent[0]["meta"]["external"] is True
    pto = calendar.classify_event("jake@ntxpllc.com", {"id": "p", "summary": "PTO",
                                                       "start": {"date": "2026-10-08"}})
    assert pto[0]["kind"] == "ooo"


def test_jobtread_quality_and_integrity():
    good = jobtread.score_log_text("Crew of four on site at 7 am. Set forms and placed rebar per sheet "
                                   "S-101. Plumbing inspection passed at 1 pm. Cleaned the area and "
                                   "secured the site. No safety incidents.")
    bad = jobtread.score_log_text("worked on stuff today guys were here did the floor tomorow more")
    assert good["score"] >= 0.8 > 0.6 > bad["score"]
    assert "sentence case" in bad["issues"] and "missing end punctuation" in bad["issues"]
    chk = jobtread.check_document({"number": "INV-1", "vendor": "Acme", "job": "LKV", "cost_code": "09",
                                   "date": "2026-10-01", "lines": [100, 50], "total": 200}, "vendor_invoice")
    assert "po_ref" in chk["missing"] and "amounts do not sum" in chk["missing"] and not chk["amount_ok"]


def test_jobtread_adapter_is_mockable(live):
    def fake(query):
        if "dailyLogs" in str(query):
            return {"organization": {"dailyLogs": {"nodes": [
                {"id": "dl1", "date": "2026-10-08", "notes": "did stuff", "user": {"emailAddress": "dana@ntxpllc.com"},
                 "job": {"name": "HMS"}, "files": {"nodes": []}}]}}}
        return {"organization": {"documents": {"nodes": []}}}
    out = jobtread.collect(["dana@ntxpllc.com"], "2026-10-01T00:00:00Z", NOW, client=fake)
    assert out[0]["kind"] == "daily_log" and "no photos" in out[0]["meta"]["issues"]
    assert "text" not in out[0]["meta"]  # body not kept beyond the short quote


# --------------------------------------------------------------------------- service

def test_run_cycle_demo_contract_shapes():
    res = service.run_cycle(NOW)
    assert set(res) == {"flags_created", "flags_escalated", "jev"}
    assert res["flags_created"] > 5 and res["flags_escalated"] > 0
    assert set(res["jev"]) == {"tier", "executor", "cost"}

    s = service.get_summary()
    assert set(s) == {"updated", "tiles", "people"}
    kinds = {t["kind"] for t in s["tiles"]}
    assert kinds == {"gauge", "pie", "ring", "bar"}
    ids = {t["id"]: t for t in s["tiles"]}
    assert ids["response_time"]["kind"] == "gauge" and ids["responsiveness_score"]["kind"] == "gauge"
    assert ids["unanswered_email"]["kind"] == "pie" and ids["wait_complaints"]["kind"] == "pie"
    assert ids["daily_report_quality"]["kind"] == "ring" and ids["po_invoice_integrity"]["kind"] == "ring"
    assert ids["no_shows"]["kind"] == "bar"
    for t in s["tiles"]:
        assert set(t) == TILE_KEYS and t["status"] in ("good", "watch", "bad")
        assert t["report_id"] in REPORT_IDS
        assert all(set(b) == {"label", "value"} for b in t["breakdown"])
    assert {p["email"] for p in s["people"]} >= {"alison@ntxpllc.com", "trevor@ntxpllc.com"}
    for p in s["people"]:
        assert set(p) == PERSON_KEYS
    names = {p["email"]: (p["name"], p["role"]) for p in s["people"]}
    assert names["alison@ntxpllc.com"] == ("Alison Hopkins", "Owner")
    assert names["trevor@ntxpllc.com"] == ("Trevor Hopkins", "Operations Contact")

    flags = service.list_flags("all")
    for f in flags:
        assert set(f) == FLAG_KEYS
        assert 0 <= f["confidence"] <= 1 and f["level"] in (1, 2, 3)
        assert f["crosscheck"]["status"] in ("pending", "explained", "confirmed", "inconclusive")
        assert f["evidence"] and all(len(e["note"]) <= 200 for e in f["evidence"])
        for x in f["escalations"]:
            assert set(x) == {"level", "channel", "at", "to"}
            assert x["channel"] in ("daily_note", "email", "sms")
        if f["kpi"] != "internal_volatility":
            assert f["volatility"] is None
    assert any(f["crosscheck"]["status"] == "explained" and "luis" in f["person"] for f in flags)
    assert any(f["crosscheck"]["status"] == "confirmed" and "jake" in f["person"] for f in flags)
    assert service.list_flags(level=3) and all(f["level"] == 3 for f in service.list_flags(level=3))

    for rid in REPORT_IDS:
        r = service.get_report(rid)
        assert set(r) == REPORT_KEYS and r["id"] == rid
        assert set(r["period"]) == {"from", "to"}
        for sec in r["sections"]:
            assert set(sec) == {"heading", "findings", "evidence"}
        for c in r["conclusions"]:
            assert set(c) == {"text", "confidence", "council_id"}
            assert c["text"].startswith("Proposal for owner review")
    with pytest.raises(KeyError):
        service.get_report("nope")


def test_run_cycle_is_idempotent_for_same_items():
    service.run_cycle(NOW)
    n = len(service.list_flags("all"))
    again = service.run_cycle(util.as_utc(NOW) + dt.timedelta(hours=1))
    assert again["flags_created"] == 0 and again["flags_escalated"] == 0
    assert len(service.list_flags("all")) == n


def test_act_on_flag_owner_only_and_recorded():
    service.run_cycle(NOW)
    f = service.list_flags()[0]
    with pytest.raises(PermissionError):
        service.act_on_flag(f["id"], "dismiss", "x", "jake.romero@ntxpllc.com")
    with pytest.raises(ValueError):
        service.act_on_flag(f["id"], "fire", "x", "alison@ntxpllc.com")
    out = service.act_on_flag(f["id"], "dismiss", "false alarm", "alison@ntxpllc.com")
    assert out["status"] == "dismissed" and set(out) == FLAG_KEYS
    ix = store.query("Interactions", {"kind": "flag_action"})
    assert ix[-1]["action"] == "dismiss" and ix[-1]["request_type"] == "flag_dismiss"
    assert f["id"] not in {x["id"] for x in service.list_flags()}
    low = next(x for x in service.list_flags() if x["level"] == 1)
    up = service.act_on_flag(low["id"], "escalate", "look closer", "trevor@ntxpllc.com")
    assert up["level"] == 2 and up["escalations"][-1]["channel"] == "email"


def test_get_summary_auto_runs_in_demo_and_subscribe_yields_tiles():
    s = service.get_summary()
    assert s["tiles"]
    tiles = list(service.subscribe(poll_seconds=0, max_events=3))
    assert len(tiles) == 3 and all(set(t) == TILE_KEYS for t in tiles)


def test_summary_without_data_when_not_demo(live):
    s = service.get_summary()
    assert set(s) == {"updated", "tiles", "people"} and s["tiles"]
    assert service.list_flags() == []
    res = service.run_cycle(NOW)
    assert res["flags_created"] == 0
