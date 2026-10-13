import datetime as dt

import pytest

from admin_console import config
from admin_console.analytics import crosscheck, escalation, store, util

from .conftest import NOW

P = "luis@ntxpllc.com"


def e(source, kind, hours_ago=3, **meta):
    ts = util.as_utc(NOW) - dt.timedelta(hours=hours_ago)
    return {"person": P, "source": source, "kind": kind, "ts": util.iso(ts), "ref": f"{source}-{kind}",
            "meta": meta}


def flag(kpi="responsiveness_anomaly", level=1, channel="gmail", **kw):
    f = {"id": "FL-T-001", "key": f"{kpi}|{P}|x", "person": P, "kpi": kpi, "channel": channel,
         "level": level, "urgency": "medium", "severity": "concern", "confidence": 0.6,
         "volatility": None, "summary": "s", "evidence": [], "ts": NOW, "floor_level": 1,
         "status": "open", "escalations": [], "council": None}
    f.update(kw)
    return f


def mock_fetch(events_by_channel):
    calls = []

    def fetch(ch, person, start, end):
        calls.append(ch)
        return events_by_channel.get(ch, [])
    return fetch, calls


def test_explained_by_onsite_log_downgrades_one_level():
    fetch, calls = mock_fetch({"jobtread": [e("jobtread", "daily_log", job="FS4", on_site=True, quality=0.9)]})
    f = crosscheck.crosscheck(flag(level=2), now=NOW, fetch=fetch)
    assert f["crosscheck"]["status"] == "explained"
    assert f["level"] == 1
    assert any("JobTread" in x for x in f["crosscheck"]["explanations"])
    assert set(calls) == {"jobtread", "calendar", "plaud", "drive", "gmail"}
    assert f["crosscheck"]["sources_checked"] == ["jobtread", "calendar", "plaud", "drive", "gmail"]


def test_explained_by_pto_keeps_rule_floor():
    fetch, _ = mock_fetch({"calendar": [e("calendar", "ooo", title="PTO", ooo_type="pto")]})
    f = crosscheck.crosscheck(flag("wait_complaints", level=2, floor_level=2), now=NOW, fetch=fetch)
    assert f["crosscheck"]["status"] == "explained" and f["level"] == 2


def test_confirmed_across_channels_raises_confidence_and_level():
    fetch, _ = mock_fetch({
        "calendar": [e("calendar", "no_show", title="OAC", attendance="absent")],
        "drive": [e("drive", "folder_stale", project="LKV", days_since=11)],
    })
    f = crosscheck.crosscheck(flag(level=1), now=NOW, fetch=fetch)
    assert f["crosscheck"]["status"] == "confirmed"
    assert f["confidence"] > 0.6 and f["level"] == 2 and f["severity"] == "issue"


def test_confirmed_never_raises_above_two():
    fetch, _ = mock_fetch({
        "calendar": [e("calendar", "no_show", title="OAC", attendance="absent")],
        "drive": [e("drive", "folder_stale", project="LKV", days_since=11)],
    })
    f = crosscheck.crosscheck(flag(level=2), now=NOW, fetch=fetch)
    assert f["level"] == 2


def test_inconclusive_and_unconfigured_sources_skipped():
    def fetch(ch, person, start, end):
        return None if ch == "plaud" else []
    f = crosscheck.crosscheck(flag(level=1), now=NOW, fetch=fetch)
    assert f["crosscheck"]["status"] == "inconclusive"
    assert "plaud" not in f["crosscheck"]["sources_checked"]


# --------------------------------------------------------------------------- escalation

@pytest.fixture
def phones(monkeypatch):
    monkeypatch.setenv("NTXP_ALISON_SMS", "+19405550101")
    monkeypatch.setenv("NTXP_TREVOR_SMS", "+19405550102")


@pytest.fixture
def transport():
    sent = {"email": [], "sms": []}
    escalation.TRANSPORT["email"] = lambda to, subject, body: sent["email"].append((to, subject, body))
    escalation.TRANSPORT["sms"] = lambda to, text: sent["sms"].append((to, text))
    store.ensure_schema()
    return sent


def test_l2_email_only_to_owners_and_dedupes(transport):
    f = flag(level=2)
    n = escalation.escalate_all([f], NOW)
    assert n == 1 and len(transport["email"]) == 1
    to, subject, body = transport["email"][0]
    assert sorted(to) == sorted(config.OWNER_EMAILS)
    assert "Proposal for owner review" in body
    assert f["escalations"][0]["channel"] == "email" and f["escalations"][0]["level"] == 2
    # same level within 24 h -> no repeat
    assert escalation.escalate_all([f], util.as_utc(NOW) + dt.timedelta(hours=2)) == 0
    assert len(transport["email"]) == 1
    ix = store.query("Interactions", {"kind": "escalation"})
    assert ix and ix[0]["flag_id"] == f["id"]


def test_l3_sms_to_both_owner_phones_plus_detail_email(transport, phones):
    f = flag(level=3, urgency="high")
    escalation.escalate_all([f], NOW)
    assert sorted(p for p, _ in transport["sms"]) == ["+19405550101", "+19405550102"]
    assert len(transport["email"]) == 1
    assert [x["channel"] for x in f["escalations"]] == ["sms"]


def test_l3_falls_back_to_email_without_phones(transport):
    f = flag(level=3, urgency="high")
    escalation.escalate_all([f], NOW)
    assert transport["sms"] == [] and len(transport["email"]) == 1
    assert f["escalations"][0] == {"level": 3, "channel": "email", "at": util.iso(NOW),
                                   "to": list(config.OWNER_EMAILS)}


def test_l1_daily_note_batched_per_person_per_day(transport):
    a, b = flag(level=1), flag(level=1, id="FL-T-002", kpi="no_shows")
    escalation.escalate_all([a, b], NOW)
    notes = store.rows("DailyNotes")
    assert len(notes) == 1 and notes[0]["person"] == P and len(notes[0]["items"]) == 2
    assert transport["email"] == [] and transport["sms"] == []


def test_quiet_hours_defer_unless_critical(transport, phones):
    night = "2026-10-09T04:30:00Z"  # 11:30 pm CT Thursday
    assert util.in_quiet_hours(night)
    normal, critical = flag(level=3, urgency="high"), flag(level=3, urgency="critical", id="FL-T-009")
    escalation.escalate_all([normal, critical], night)
    assert normal.get("deferred") is True
    assert [x["channel"] for x in normal["escalations"]] == ["daily_note"]
    assert [x["channel"] for x in critical["escalations"]] == ["sms"]
    # the morning cycle sends the deferred one
    escalation.escalate_all([normal], "2026-10-09T12:30:00Z")
    assert normal["escalations"][-1]["channel"] == "sms" and normal["deferred"] is False


def test_stale_billing_l2_raises_to_l3_after_window(transport, phones):
    f = flag("open_billing_questions", level=2, urgency="high")
    escalation.escalate_all([f], NOW)
    assert f["level"] == 2
    escalation.escalate_all([f], util.as_utc(NOW) + dt.timedelta(hours=25))
    assert f["level"] == 3 and f["escalations"][-1]["channel"] == "sms"


def test_sending_to_anyone_else_is_impossible(phones):
    with pytest.raises(PermissionError):
        escalation._guard("email", ["someone@ntxpllc.com"])
    with pytest.raises(PermissionError):
        escalation._guard("sms", ["+12145550000"])
    escalation._guard("email", list(config.OWNER_EMAILS))
    import inspect
    assert "to" not in inspect.signature(escalation._send_email).parameters
    assert "to" not in inspect.signature(escalation._send_sms).parameters


def test_acked_flags_are_not_escalated(transport):
    f = flag(level=2, status="ack")
    assert escalation.escalate_all([f], NOW) == 0 and transport["email"] == []


def test_demo_mode_never_sends(phones):
    store.ensure_schema()
    f = flag(level=3, urgency="high")
    escalation.escalate_all([f], NOW)
    assert {o["channel"] for o in escalation.OUTBOX} == {"sms", "email"}
