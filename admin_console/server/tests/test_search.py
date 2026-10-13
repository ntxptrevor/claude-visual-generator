from datetime import date, datetime, timedelta, timezone

import pytest

from admin_console.server import search

NOW = date(2026, 10, 9)
DIRECTORY = [{"email": "marcus.delgado@ntxpllc.com", "name": "Marcus Delgado"},
             {"email": "rosa.jimenez@ntxpllc.com", "name": "Rosa Jimenez"},
             {"email": "trevor@ntxpllc.com", "name": "Trevor Hopkins"},
             {"email": "alison@ntxpllc.com", "name": "Alison Hopkins"}]
PROJECTS = ["McShan Elementary Renovation", "Fire Station 4 HVAC"]


def draft(**kw):
    return {**search.empty_draft(), **kw}


@pytest.mark.parametrize("text,start,end", [
    ("last month", "2026-09-01", "2026-09-30"),
    ("this month", "2026-10-01", "2026-10-09"),
    ("since June", "2026-06-01", None),
    ("since November", "2025-11-01", None),
    ("since June 15", "2026-06-15", None),
    ("in March", "2026-03-01", "2026-03-31"),
    ("last 2 weeks", "2026-09-25", "2026-10-09"),
    ("past 30 days", "2026-09-09", "2026-10-09"),
    ("yesterday", "2026-10-08", "2026-10-08"),
    ("last week", "2026-09-28", "2026-10-04"),
    ("between 9/1 and 9/15", "2026-09-01", "2026-09-15"),
    ("after 2026-07-04 before 2026-08-01", "2026-07-04", "2026-08-01"),
    ("last year", "2025-01-01", "2025-12-31"),
])
def test_parse_dates(text, start, end):
    a, b, _ = search.parse_dates(text, NOW)
    assert (a.isoformat() if a else None, b.isoformat() if b else None) == (start, end)


def test_parse_dates_none():
    assert search.parse_dates("invoice from Marcus", NOW)[:2] == (None, None)


def test_parse_text_people_roles_and_keywords():
    intent, d = search.parse_text('emails from Marcus to rosa about "change order" with attachments', DIRECTORY, PROJECTS, NOW)
    assert intent == "message"
    assert d["from"] == "marcus.delgado@ntxpllc.com" and d["to"] == "rosa.jimenez@ntxpllc.com"
    assert d["keywords"] == ["change order"] and d["has_attachment"] is True


def test_ambiguous_last_name_not_matched_alone():
    _, d = search.parse_text("hopkins invoices", DIRECTORY, PROJECTS, NOW)
    assert d["people"] == [] and "hopkins" in d["keywords"]
    _, d = search.parse_text("Alison Hopkins invoices", DIRECTORY, PROJECTS, NOW)
    assert d["people"] == ["alison@ntxpllc.com"]


def test_intents():
    assert search.parse_text("how often do clients complain about waiting", DIRECTORY, PROJECTS, NOW)[0] == "trend"
    intent, d = search.parse_text("what is going on with McShan", DIRECTORY, PROJECTS, NOW)
    assert intent == "project" and d["project"] == "McShan Elementary Renovation"
    assert "mcshan" not in d["keywords"]
    assert search.parse_text("Rosa", DIRECTORY, PROJECTS, NOW)[0] == "person"
    assert search.parse_text("bonding capacity letter", DIRECTORY, PROJECTS, NOW)[0] == "message"


def test_email_address_in_text():
    _, d = search.parse_text("from bwalsh@dentonisd.example.org", DIRECTORY, PROJECTS, NOW)
    assert d["from"] == "bwalsh@dentonisd.example.org"


def test_guide_questions_rules_only():
    g = search.guide("invoice", DIRECTORY, PROJECTS, NOW)
    ids = [q["id"] for q in g["questions"]]
    assert ids[0] == "mailboxes" and "window" in ids and 2 <= len(ids) <= 4
    assert g["jev"]["tier"] == 0
    g = search.guide("invoice from Marcus last month with attachments", DIRECTORY, PROJECTS, NOW)
    ids = [q["id"] for q in g["questions"]]
    assert "window" not in ids and "attachments" not in ids
    assert "Marcus Delgado's mailbox" in g["questions"][0]["options"]


def test_guide_uses_haiku_when_key_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(search, "haiku", lambda *a, **k: '{"restated": "Refined.", "questions": '
                        '[{"id": "window", "question": "When?", "options": ["Last 7 days"], "multi": false}]}')
    g = search.guide("invoice", DIRECTORY, PROJECTS, NOW)
    assert g["restated"] == "Refined." and g["questions"][0]["question"] == "When?"
    assert g["jev"] == {"tier": 1, "executor": "claude-haiku", "cost": 0.002}


def test_guide_haiku_garbage_falls_back(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(search, "haiku", lambda *a, **k: "not json")
    g = search.guide("invoice", DIRECTORY, PROJECTS, NOW)
    assert g["jev"]["tier"] == 0 and g["questions"][0]["id"] == "mailboxes"


def test_build_gmail_query_full():
    q = search.build_gmail_query(draft(
        **{"from": "marcus.delgado@ntxpllc.com", "to": "rosa.jimenez@ntxpllc.com",
           "people": ["trevor@ntxpllc.com"], "date_from": "2026-09-01", "date_to": "2026-09-30",
           "has_attachment": True, "labels": ["Job Files"], "keywords": ["change order", "CO-03"],
           "project": "Fire Station 4 HVAC"}))
    assert q == ('from:marcus.delgado@ntxpllc.com to:rosa.jimenez@ntxpllc.com '
                 '(from:trevor@ntxpllc.com OR to:trevor@ntxpllc.com OR cc:trevor@ntxpllc.com) '
                 'after:2026/09/01 before:2026/10/01 has:attachment label:Job-Files '
                 '("Fire Station 4 HVAC" OR fire) ("change order" OR CO-03)')


def test_build_gmail_query_minimal_and_quote_safety():
    assert search.build_gmail_query(draft()) == ""
    assert search.build_gmail_query(draft(keywords=['say "hi" now'])) == '"say hi now"'
    assert search.build_gmail_query(draft(project="McShan Elementary Renovation")) == \
        '("McShan Elementary Renovation" OR mcshan)'


def test_build_drive_query():
    q = search.build_drive_query(draft(keywords=["o'neil"], date_from="2026-09-01"))
    assert q == "trashed = false and (fullText contains 'o\\'neil') and modifiedTime > '2026-09-01T00:00:00'"


def test_apply_answers():
    d, intent, audience = search.apply_answers(
        draft(), {"mailboxes": ["Only my mailbox", "Rosa Jimenez's mailbox"], "window": "Last 30 days",
                  "shape": "A pattern over time", "attachments": "Only messages with attachments",
                  "audience": "Internal NTXP only"}, "alison@ntxpllc.com", DIRECTORY, NOW)
    assert d["users"] == ["alison@ntxpllc.com", "rosa.jimenez@ntxpllc.com"]
    assert d["date_from"] == "2026-09-09" and d["has_attachment"] is True
    assert intent == "trend" and audience == "internal"
    d, _, _ = search.apply_answers(draft(), {"mailboxes": ["All NTXP mailboxes"]}, "x", DIRECTORY, NOW)
    assert d["users"] == []


def _msg(subject, snippet="", frm="a@x.com", to="b@ntxpllc.com", days=0):
    when = datetime(2026, 10, 9, tzinfo=timezone.utc) - timedelta(days=days)
    return {"id": subject, "subject": subject, "snippet": snippet, "from": frm, "to": to, "date": when.isoformat()}


def test_score_components():
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    d = draft(keywords=["invoice"])
    assert search.score(_msg("Invoice 4471"), d, now) == pytest.approx(3 + 2)
    assert search.score(_msg("x", "invoice attached"), d, now) == pytest.approx(1 + 2)
    assert search.score(_msg("x", days=30), d, now) == pytest.approx(2 * 2.718281828 ** -1, rel=1e-3)
    people = draft(people=["b@ntxpllc.com"])
    assert search.score(_msg("x", frm="Bee <B@ntxpllc.com>", days=10000), people, now) == pytest.approx(2.0)


def test_rank_orders_by_score_then_recency():
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    d = draft(keywords=["rfi"])
    ranked = search.rank([_msg("old note", days=60), _msg("RFI 014", days=5), _msg("RFI 015", days=1)], d, now)
    assert [r["id"] for r in ranked] == ["RFI 015", "RFI 014", "old note"]


def test_matches_draft_and_audience():
    m = _msg("RFI 014", frm="Marcus <marcus.delgado@ntxpllc.com>", to="bwalsh@dentonisd.example.org", days=3)
    m["has_attachment"] = False
    assert search.matches_draft(m, draft(keywords=["rfi"], **{"from": "marcus.delgado@ntxpllc.com"}))
    assert not search.matches_draft(m, draft(has_attachment=True))
    assert not search.matches_draft(m, draft(date_from="2026-10-08"))
    assert search.audience_match(m, "external") and not search.audience_match(m, "internal")


def test_trend_buckets_weekly_and_monthly():
    rs = [_msg("a", frm="marcus.delgado@ntxpllc.com", days=d) for d in (0, 1, 8, 9, 10)]
    t = search.trend_of(rs, draft(keywords=["a"]), DIRECTORY)
    assert sum(b["count"] for b in t["buckets"]) == 5 and len(t["buckets"]) == 2
    assert t["by_person"] == [{"person": "Marcus Delgado", "count": 5}]
    assert "5 messages" in t["summary"]
    rs = [_msg("a", days=d) for d in (0, 40, 100, 130)]
    assert all(len(b["period"]) == 7 for b in search.trend_of(rs, draft(), DIRECTORY)["buckets"])


def test_project_open_items():
    a = {**_msg("RFI", frm="owner@client.com", to="marcus.delgado@ntxpllc.com", days=2),
         "user": "marcus.delgado@ntxpllc.com", "thread_id": "t1"}
    b = {**_msg("RE: RFI", frm="marcus.delgado@ntxpllc.com", to="owner@client.com", days=1),
         "user": "marcus.delgado@ntxpllc.com", "thread_id": "t1"}
    c = {**_msg("Schedule?", frm="owner@client.com", to="rosa.jimenez@ntxpllc.com", days=1),
         "user": "rosa.jimenez@ntxpllc.com", "thread_id": "t2"}
    p = search.project_of([a, b, c], draft(project="McShan"), DIRECTORY)
    assert len(p["open_items"]) == 1 and "Schedule?" in p["open_items"][0]
    assert "Marcus Delgado" in p["people"] and "owner@client.com" in p["people"]


def test_shared_externally():
    assert not search.shared_externally([{"type": "user", "emailAddress": "a@ntxpllc.com"},
                                         {"type": "domain", "domain": "ntxpllc.com"}])
    assert search.shared_externally([{"type": "anyone"}])
    assert search.shared_externally([{"type": "user", "emailAddress": "arch@studio.com"}])
    assert search.shared_externally([{"type": "domain", "domain": "dentonisd.org"}])


def test_run_live_path_fans_out(monkeypatch):
    calls = []

    class Exec:
        def __init__(self, v):
            self.v = v

        def execute(self):
            return self.v

    class Messages:
        def __init__(self, user):
            self.user = user

        def list(self, userId, q, maxResults):
            calls.append((self.user, q))
            return Exec({"messages": [{"id": self.user[:1] + "1"}]})

        def get(self, userId, id, format, metadataHeaders):
            assert format == "metadata"
            return Exec({"id": id, "threadId": "t" + id, "snippet": "invoice 4471",
                         "payload": {"headers": [{"name": "From", "value": "v@vendor.com"},
                                                 {"name": "To", "value": self.user},
                                                 {"name": "Subject", "value": "Invoice"},
                                                 {"name": "Date", "value": "Tue, 06 Oct 2026 10:00:00 -0500"}]}})

    class Gmail:
        def __init__(self, user):
            self._m = Messages(user)

        def users(self):
            return self

        def messages(self):
            return self._m

    monkeypatch.setattr(search.gws, "live", lambda: True)
    monkeypatch.setattr(search.gws, "domain_users", lambda: ["marcus.delgado@ntxpllc.com", "rosa.jimenez@ntxpllc.com"])
    monkeypatch.setattr(search.gws, "service", lambda name, user=None, allow_write=False: Gmail(user))
    out = search.run(draft(keywords=["invoice"]), {}, "gmail", 10, "trevor@ntxpllc.com", DIRECTORY)
    assert sorted(u for u, _ in calls) == ["marcus.delgado@ntxpllc.com", "rosa.jimenez@ntxpllc.com"]
    assert all(q == "invoice" for _, q in calls)
    assert len(out["results"]) == 2 and out["results"][0]["date"].startswith("2026-10-06")
