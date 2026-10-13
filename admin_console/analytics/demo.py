"""Synthetic demo data. Fictional employees plus the two owners.

Deterministic for a given anchor time, so tests and the review panel see stable numbers.
Scenarios built in (all fictional):
  * Jake Romero  - responsiveness drop in the last two days, an external "still waiting"
                   complaint not forwarded to the office, a meeting no-show, project folder
                   not opened -> confirmed across channels.
  * Luis Ortega  - slow email yesterday, but on site all day (JobTread log + all-day site
                   meeting) -> crosscheck explains it.
  * Priya Shah   - open billing questions (one > 1 business day, one > 2), PO/invoice gaps.
  * Maria Delgado- one heated internal message (volatility), and an angry external email
                   that must never be volatility-scored.
  * Dana Whitfield - thin daily reports, missing photos.
"""

import datetime as dt
import random

from admin_console.analytics import util

ROSTER = [
    {"email": "alison@ntxpllc.com", "name": "Alison Hopkins", "role": "Owner"},
    {"email": "trevor@ntxpllc.com", "name": "Trevor Hopkins", "role": "Operations Contact"},
    {"email": "maria.delgado@ntxpllc.com", "name": "Maria Delgado", "role": "Project Manager"},
    {"email": "jake.romero@ntxpllc.com", "name": "Jake Romero", "role": "Superintendent"},
    {"email": "priya.shah@ntxpllc.com", "name": "Priya Shah", "role": "Office Administrator"},
    {"email": "luis.ortega@ntxpllc.com", "name": "Luis Ortega", "role": "Field Supervisor"},
    {"email": "dana.whitfield@ntxpllc.com", "name": "Dana Whitfield", "role": "Assistant PM"},
]

PROJECTS = {
    "LKV": "Lakeview ES Restroom Renovation",
    "FS4": "Denton Fire Station 4 Reroof",
    "HMS": "Hillcrest MS Gym Floor",
}

ASSIGNMENTS = {
    "maria.delgado@ntxpllc.com": ["LKV", "HMS"],
    "jake.romero@ntxpllc.com": ["LKV", "FS4"],
    "luis.ortega@ntxpllc.com": ["FS4"],
    "dana.whitfield@ntxpllc.com": ["HMS"],
    "priya.shah@ntxpllc.com": [],
}

NORM_HRS = {  # typical first-response hours
    "alison@ntxpllc.com": 2.0, "trevor@ntxpllc.com": 1.6, "maria.delgado@ntxpllc.com": 2.6,
    "jake.romero@ntxpllc.com": 3.0, "priya.shah@ntxpllc.com": 1.8,
    "luis.ortega@ntxpllc.com": 3.4, "dana.whitfield@ntxpllc.com": 2.4,
}

GOOD_LOG = ("Crew of four on site at 7 am. Set forms for the north restroom slab and placed "
            "rebar per sheet S-101. Plumbing inspection passed at 1 pm. Cleaned the area and "
            "secured the site at 3:30 pm. No safety incidents.")
THIN_LOG = "worked on stuff today guys were here did the floor and some other things tomorow more"

_CACHE = {}


def _ev(person, source, kind, ts, ref, **meta):
    return {"person": person, "source": source, "kind": kind, "ts": util.iso(ts),
            "ref": ref, "meta": meta}


def _at(day, hour, minute=0):
    return dt.datetime.combine(day, dt.time(hour, minute), util.CENTRAL)


def dataset(anchor):
    """All synthetic events for 35 days ending at `anchor`."""
    anchor = util.as_utc(anchor)
    key = util.iso(anchor)[:13]
    if key in _CACHE:
        return _CACHE[key]
    rng = random.Random(9071)
    today = util.central(anchor).date()
    days = [today - dt.timedelta(days=i) for i in range(34, -1, -1)]
    workdays = [d for d in days if d.weekday() < 5]
    last2 = workdays[-2:]
    yesterday = workdays[-2] if len(workdays) > 1 else workdays[-1]
    ev = []

    # ---------------- gmail: responses
    for d in workdays:
        for p in ROSTER:
            email = p["email"]
            norm = NORM_HRS[email]
            for k in range(rng.randint(3, 6)):
                hrs = max(0.2, rng.gauss(norm, norm * 0.18))
                if email == "jake.romero@ntxpllc.com" and d in last2:
                    hrs = norm * rng.uniform(3.2, 4.0)
                if email == "luis.ortega@ntxpllc.com" and d == yesterday:
                    hrs = norm * rng.uniform(2.6, 3.0)
                internal = rng.random() < 0.45
                tid = f"thr-{email.split('@')[0]}-{d:%m%d}-{k}"
                ev.append(_ev(email, "gmail", "response", _at(d, 8 + k, 15), tid,
                              hours=round(hrs, 2), internal=internal,
                              counterpart="office@ntxpllc.com" if internal else "client@example.org"))

    now_c = util.central(anchor)

    # ---------------- gmail: unanswered inbound (>24h)
    def unanswered(email, hours_ago, sender, subject, i):
        ts = now_c - dt.timedelta(hours=hours_ago)
        ev.append(_ev(email, "gmail", "unanswered", ts, f"thr-un-{email.split('@')[0]}-{i}",
                      age_hrs=hours_ago, sender=sender, external=not util.is_internal(sender),
                      subject=subject))

    unanswered("jake.romero@ntxpllc.com", 52, "pm@lakeviewisd.example.org", "Restroom closeout punch list", 1)
    unanswered("jake.romero@ntxpllc.com", 30, "facilities@lakeviewisd.example.org", "Access for Saturday work", 2)
    unanswered("jake.romero@ntxpllc.com", 75, "estimating@acme-tile.example.com", "Tile submittal resend", 3)
    unanswered("jake.romero@ntxpllc.com", 28, "maria.delgado@ntxpllc.com", "Need FS4 photos", 4)
    unanswered("priya.shah@ntxpllc.com", 26, "ar@supplyhouse.example.com", "Statement October", 1)
    unanswered("dana.whitfield@ntxpllc.com", 33, "coach@hillcrestisd.example.org", "Gym floor schedule", 1)

    # ---------------- gmail: complaints (external)
    ev.append(_ev("jake.romero@ntxpllc.com", "gmail", "complaint", now_c - dt.timedelta(hours=20),
                  "thr-cmp-lkv-1", sender="pm@lakeviewisd.example.org", external=True,
                  phrases=["still waiting", "no-show"], complaint_type="no-show",
                  quote=("We are still waiting on the punch list walk. Your super was a no-show "
                         "Tuesday and nobody called."),
                  forwarded=False, forward_lag_bh=None))
    ev.append(_ev("maria.delgado@ntxpllc.com", "gmail", "complaint", now_c - dt.timedelta(days=6),
                  "thr-cmp-hms-1", sender="coach@hillcrestisd.example.org", external=True,
                  phrases=["haven't heard back"], complaint_type="waiting on response",
                  quote="Haven't heard back about the gym floor cure time. Please advise.",
                  forwarded=True, forward_lag_bh=1.5))
    ev.append(_ev("dana.whitfield@ntxpllc.com", "gmail", "complaint", now_c - dt.timedelta(days=12),
                  "thr-cmp-hms-2", sender="coach@hillcrestisd.example.org", external=True,
                  phrases=["following up again"], complaint_type="follow-up",
                  quote="Following up again on the bleacher protection plan.",
                  forwarded=True, forward_lag_bh=3.0))

    # ---------------- gmail: billing questions
    ev.append(_ev("priya.shah@ntxpllc.com", "gmail", "billing_question",
                  now_c - dt.timedelta(hours=40), "thr-bill-1",
                  sender="ap@lakeviewisd.example.org", subject="Pay app 4 retainage question",
                  answered=False, will_delay_work=False))
    ev.append(_ev("priya.shah@ntxpllc.com", "gmail", "billing_question",
                  now_c - dt.timedelta(hours=70), "thr-bill-2",
                  sender="accounts@acme-tile.example.com", subject="Invoice 2231 short-paid?",
                  answered=False, will_delay_work=True))
    ev.append(_ev("priya.shah@ntxpllc.com", "gmail", "billing_question",
                  now_c - dt.timedelta(days=9), "thr-bill-3",
                  sender="ap@fs4.example.gov", subject="W-9 request", answered=True,
                  will_delay_work=False))

    # ---------------- gmail: internal and external messages (text kept in memory only)
    ev.append(_ev("maria.delgado@ntxpllc.com", "gmail", "message", now_c - dt.timedelta(hours=5),
                  "msg-int-1", to=["dana.whitfield@ntxpllc.com"], sender="maria.delgado@ntxpllc.com",
                  internal=True,
                  text=("This is RIDICULOUS!!! I asked THREE times for the HMS submittals and "
                        "nothing. I'm sick of this, I can't keep covering for it. Never again!!")))
    ev.append(_ev("trevor@ntxpllc.com", "gmail", "message", now_c - dt.timedelta(hours=7),
                  "msg-int-2", to=["priya.shah@ntxpllc.com"], sender="trevor@ntxpllc.com",
                  internal=True, text="Thanks for pulling the lien waivers together, nice work."))
    ev.append(_ev("maria.delgado@ntxpllc.com", "gmail", "message", now_c - dt.timedelta(hours=9),
                  "msg-ext-1", to=["maria.delgado@ntxpllc.com"], sender="angry.parent@example.com",
                  internal=False,
                  text="THIS IS UNACCEPTABLE!!! The noise is ridiculous and I am furious!!!"))

    # ---------------- calendar
    for d in workdays:
        for p in ROSTER:
            ev.append(_ev(p["email"], "calendar", "meeting", _at(d, 10), f"cal-{p['email'][:4]}-{d:%m%d}",
                          title="Coordination", attendance="present", external=False))
    tuesday = next((d for d in reversed(workdays) if d.weekday() == 1), workdays[-1])
    ev.append(_ev("jake.romero@ntxpllc.com", "calendar", "no_show", _at(tuesday, 14),
                  "cal-lkv-punch", title="Lakeview punch walk", attendance="absent", external=True))
    ev.append(_ev("jake.romero@ntxpllc.com", "calendar", "meeting", _at(workdays[-9], 9),
                  "cal-fs4-oac", title="FS4 OAC meeting", attendance="unknown", external=True))
    ev.append(_ev("dana.whitfield@ntxpllc.com", "calendar", "decline", _at(workdays[-3], 13),
                  "cal-hms-coord", title="HMS coordination", external=False))
    ev.append(_ev("luis.ortega@ntxpllc.com", "calendar", "site_meeting", _at(yesterday, 7),
                  "cal-fs4-site", title="FS4 roof deck inspection - all day on site", all_day=True))
    ev.append(_ev("alison@ntxpllc.com", "calendar", "ooo", _at(workdays[-6], 0),
                  "cal-ooo-1", title="PTO", ooo_type="pto", all_day=True))

    # ---------------- drive (project folder access)
    for email, codes in ASSIGNMENTS.items():
        for code in codes:
            if email == "jake.romero@ntxpllc.com" and code == "LKV":
                ev.append(_ev(email, "drive", "folder_stale", now_c, f"drv-{code}",
                              project=PROJECTS[code], days_since=11))
                continue
            for d in workdays[-10:]:
                if rng.random() < 0.6:
                    ev.append(_ev(email, "drive", "folder_open", _at(d, 9, 30), f"drv-{code}",
                                  project=PROJECTS[code]))

    # ---------------- jobtread daily logs, POs, invoices
    for d in workdays[-10:]:
        for email, job, text, photos in (
            ("jake.romero@ntxpllc.com", "LKV", GOOD_LOG, True),
            ("luis.ortega@ntxpllc.com", "FS4", GOOD_LOG.replace("restroom slab", "roof deck"), True),
            ("dana.whitfield@ntxpllc.com", "HMS", THIN_LOG if d in workdays[-4:] else GOOD_LOG,
             d not in workdays[-4:]),
        ):
            if email == "jake.romero@ntxpllc.com" and d in last2:
                continue  # no on-site log while email lagged -> not explained
            ev.append(_ev(email, "jobtread", "daily_log", _at(d, 16), f"jt-log-{job}-{d:%m%d}",
                          job=PROJECTS[job], text=text, has_photos=photos, on_site=True))
    ev.append(_ev("priya.shah@ntxpllc.com", "jobtread", "purchase_order", now_c - dt.timedelta(days=2),
                  "jt-po-1182", number="PO-1182", vendor="Acme Tile", job=PROJECTS["LKV"],
                  cost_code="09-3000", lines=[1200.0, 800.0], total=2000.0, date="2026-10-07"))
    ev.append(_ev("priya.shah@ntxpllc.com", "jobtread", "purchase_order", now_c - dt.timedelta(days=3),
                  "jt-po-1183", number="PO-1183", vendor="", job=PROJECTS["FS4"],
                  cost_code="", lines=[5400.0], total=5400.0, date="2026-10-06"))
    ev.append(_ev("priya.shah@ntxpllc.com", "jobtread", "vendor_invoice", now_c - dt.timedelta(days=1),
                  "jt-inv-2231", number="INV-2231", vendor="Acme Tile", job=PROJECTS["LKV"],
                  cost_code="09-3000", lines=[1200.0, 950.0], total=2000.0, date="2026-10-08",
                  po_ref=""))
    ev.append(_ev("priya.shah@ntxpllc.com", "jobtread", "vendor_invoice", now_c - dt.timedelta(days=4),
                  "jt-inv-2219", number="INV-2219", vendor="Denton Roofing Supply", job=PROJECTS["FS4"],
                  cost_code="07-5000", lines=[3100.0], total=3100.0, date="2026-10-05",
                  po_ref="PO-1177"))

    # ---------------- plaud
    ev.append(_ev("trevor@ntxpllc.com", "plaud", "long_call", _at(workdays[-1], 9),
                  "plaud-rec-77", title="Owner/architect call - FS4", duration_min=95,
                  mentions=["luis.ortega@ntxpllc.com"]))

    # ---------------- quickbooks
    ev.append(_ev("priya.shah@ntxpllc.com", "quickbooks", "disputed_invoice",
                  now_c - dt.timedelta(days=3), "qbo-inv-1043", invoice="1043",
                  customer="Lakeview ISD", amount=18450.0, answered=False))

    _CACHE[key] = ev
    return ev


_ANCHOR = {"at": None}


def set_anchor(at):
    """Pin the synthetic timeline to a cycle's `now` so narrow crosscheck queries agree."""
    _ANCHOR["at"] = util.as_utc(at) if at else None


def events(source, people, start, end, anchor=None):
    start, end = util.as_utc(start), util.as_utc(end)
    anchor = anchor or _ANCHOR["at"] or end
    wanted = {p.lower() for p in people} if people else None
    out = []
    for e in dataset(anchor):
        if e["source"] != source:
            continue
        if wanted is not None and e["person"] not in wanted:
            continue
        if start <= util.as_utc(e["ts"]) <= end:
            out.append(e)
    return out
