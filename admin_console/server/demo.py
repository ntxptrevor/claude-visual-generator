"""Synthetic fixtures for demo mode. Employees are fictional; the owners are real."""

from datetime import datetime, timedelta, timezone

DOMAIN = "ntxpllc.com"

PEOPLE = [
    {"email": "alison@ntxpllc.com", "name": "Alison Hopkins", "role": "Owner", "org_unit": "/Owners", "is_admin": True},
    {"email": "trevor@ntxpllc.com", "name": "Trevor Hopkins", "role": "Operations Contact", "org_unit": "/Owners", "is_admin": True},
    {"email": "marcus.delgado@ntxpllc.com", "name": "Marcus Delgado", "role": "Project Manager", "org_unit": "/Field", "is_admin": False},
    {"email": "priya.natarajan@ntxpllc.com", "name": "Priya Natarajan", "role": "Estimator", "org_unit": "/Office", "is_admin": False},
    {"email": "caleb.whitfield@ntxpllc.com", "name": "Caleb Whitfield", "role": "Superintendent", "org_unit": "/Field", "is_admin": False},
    {"email": "rosa.jimenez@ntxpllc.com", "name": "Rosa Jimenez", "role": "Office Manager / AP", "org_unit": "/Office", "is_admin": False},
    {"email": "devin.okafor@ntxpllc.com", "name": "Devin Okafor", "role": "Assistant PM", "org_unit": "/Field", "is_admin": False},
    {"email": "hannah.price@ntxpllc.com", "name": "Hannah Price", "role": "Field Coordinator", "org_unit": "/Field", "is_admin": False},
]

PROJECTS = ["McShan Elementary Renovation", "Denton Courthouse Annex", "Lakeview Library Reroof",
            "Fire Station 4 HVAC", "Ryan High School Restrooms"]


def _today():
    return datetime.now(timezone.utc).date()


def iso_ago(days_ago, hour=9):
    d = datetime.now(timezone.utc).replace(hour=hour, minute=12, second=0, microsecond=0)
    return (d - timedelta(days=days_ago)).isoformat()


def users():
    out = []
    for i, p in enumerate(PEOPLE):
        out.append({"email": p["email"], "name": p["name"], "suspended": p["email"].startswith("hannah"),
                    "last_login": iso_ago(i % 4, 7 + i), "is_admin": p["is_admin"], "org_unit": p["org_unit"]})
    return out


def _msg(i, user, frm, to, subject, snippet, days_ago, attach=False, labels=("INBOX",), replied=True):
    return {"id": f"demo-msg-{i:03d}", "source": "gmail", "user": user, "from": frm, "to": to,
            "subject": subject, "snippet": snippet, "date": iso_ago(days_ago, 8 + i % 9),
            "thread_id": f"demo-thr-{i:03d}", "link": f"https://mail.google.com/mail/u/0/#all/demo-thr-{i:03d}",
            "has_attachment": attach, "labels": list(labels), "replied": replied, "score": 0.0}


def messages():
    A, T = "alison@ntxpllc.com", "trevor@ntxpllc.com"
    MD, PN = "marcus.delgado@ntxpllc.com", "priya.natarajan@ntxpllc.com"
    CW, RJ, DO = "caleb.whitfield@ntxpllc.com", "rosa.jimenez@ntxpllc.com", "devin.okafor@ntxpllc.com"
    owner = "bwalsh@dentonisd.example.org"
    arch = "kchen@studioforma.example.com"
    sub = "estimating@lonestarmech.example.com"
    rows = [
        (MD, MD, owner, "McShan Elementary Renovation - RFI 014 ceiling grid conflict",
         "Brenda, attached is RFI 014 on the ceiling grid conflict at corridor B. Need response by Friday.", 2, True),
        (MD, owner, MD, "RE: McShan Elementary Renovation - RFI 014 ceiling grid conflict",
         "Marcus, architect is reviewing. Expect an answer early next week.", 1, False),
        (RJ, sub, RJ, "Invoice 4471 - Fire Station 4 HVAC rooftop units",
         "Please find invoice 4471 for RTU-1 and RTU-2 delivery. PO reference 2026-118.", 5, True),
        (RJ, RJ, T, "PO 2026-118 vs invoice 4471 mismatch",
         "Trevor, invoice 4471 bills $48,900 but PO 2026-118 was issued at $46,250. Holding payment.", 4, False, False),
        (PN, PN, arch, "Lakeview Library Reroof - bid clarification on tapered insulation",
         "Kevin, can you confirm the tapered insulation layout on sheet A-501 is to the drains?", 12, False),
        (PN, arch, PN, "RE: Lakeview Library Reroof - bid clarification on tapered insulation",
         "Priya, yes, slope to drains at 1/4 in per foot. Addendum 2 will follow.", 11, True),
        (CW, CW, MD, "Daily report - McShan Elementary 10/06",
         "Crew of 6 on site. Demo of restroom 112 complete. Waiting on plumbing inspection.", 3, True),
        (CW, CW, MD, "Daily report - McShan Elementary 10/07",
         "Crew of 5. Ceiling grid on hold for RFI 014. Inspector rescheduled to Thursday.", 2, True),
        (DO, owner, DO, "Denton Courthouse Annex - waiting on revised schedule",
         "Devin, we have been waiting two weeks on the revised schedule. Please advise.", 6, False, False),
        (DO, owner, DO, "Denton Courthouse Annex - still waiting on schedule",
         "Following up again on the schedule update. This is now holding up our board item.", 1, False, False),
        (A, T, A, "Bonding capacity letter for Ryan High School Restrooms",
         "Alison, surety needs the updated WIP schedule before they issue the capacity letter.", 9, True),
        (T, sub, T, "Fire Station 4 HVAC - change order request CO-03",
         "Requesting CO-03 for added curb adapters, $3,180. Backup attached.", 15, True),
        (MD, MD, CW, "McShan Elementary - punch list walk Thursday",
         "Caleb, owner walk moved to Thursday 10 AM. Please have rooms 108-114 ready.", 0, False, False),
        (RJ, RJ, A, "Open billing questions - September pay app",
         "Alison, two line items on the McShan pay app need backup before we submit.", 7, True),
        (PN, PN, T, "Estimate ready for review - Ryan High School Restrooms",
         "Trevor, estimate is in the bid folder. Total $412,600 with 8% contingency.", 20, True),
        (DO, DO, owner, "RE: Denton Courthouse Annex - waiting on revised schedule",
         "Brenda, apologies for the delay. Revised schedule attached.", 0, True),
        (MD, sub, MD, "McShan Elementary - mechanical submittal resubmittal",
         "Marcus, resubmitting M-04 with the corrected unit ventilator data.", 35, True),
        (CW, CW, MD, "Daily report - McShan Elementary 09/02",
         "Crew of 4. Mobilized. Temporary fencing set.", 37, True),
        (RJ, sub, RJ, "Invoice 4310 - Lakeview Library Reroof materials",
         "Invoice 4310 for TPO membrane delivery, PO 2026-097.", 40, True),
        (T, T, MD, "Weekly ops sync - agenda",
         "Agenda: McShan RFI status, Fire Station 4 CO-03, Courthouse schedule.", 8, False),
    ]
    out = []
    for i, r in enumerate(rows):
        user, frm, to, subj, snip, days, attach = r[:7]
        replied = r[7] if len(r) > 7 else True
        out.append(_msg(i, user, frm, to, subj, snip, days, attach, replied=replied))
    return out


def drive_files():
    base = [
        ("McShan Elementary - RFI Log.xlsx", "marcus.delgado@ntxpllc.com", "application/vnd.google-apps.spreadsheet", 2, False),
        ("McShan Elementary - Pay App 03.pdf", "rosa.jimenez@ntxpllc.com", "application/pdf", 7, True),
        ("Fire Station 4 HVAC - PO 2026-118.pdf", "rosa.jimenez@ntxpllc.com", "application/pdf", 5, False),
        ("Lakeview Library Reroof - Bid Form.docx", "priya.natarajan@ntxpllc.com", "application/vnd.google-apps.document", 11, True),
        ("Denton Courthouse Annex - Schedule Rev 2.mpp", "devin.okafor@ntxpllc.com", "application/octet-stream", 0, False),
        ("Ryan HS Restrooms - Estimate.xlsx", "priya.natarajan@ntxpllc.com", "application/vnd.google-apps.spreadsheet", 20, False),
        ("NTXP Safety Manual 2026.pdf", "alison@ntxpllc.com", "application/pdf", 60, True),
        ("Daily Reports - McShan Elementary", "caleb.whitfield@ntxpllc.com", "application/vnd.google-apps.folder", 2, False),
    ]
    return [{"id": f"demo-file-{i:02d}", "name": n, "owner": o, "mime": mime, "modified": iso_ago(d),
             "link": f"https://drive.google.com/file/d/demo-file-{i:02d}/view", "shared_externally": ext}
            for i, (n, o, mime, d, ext) in enumerate(base)]


def _contact(cid, source, name, emails, phones, org="", title="", labels=(), shared=False,
             owner_user="", address="", notes="", days=3):
    given, _, family = name.partition(" ")
    return {"id": cid, "source": source, "name": name, "given": given, "family": family,
            "emails": list(emails), "phones": list(phones), "org": org, "title": title,
            "address": address, "notes": notes, "labels": list(labels), "shared": shared,
            "owner_user": owner_user, "updated": iso_ago(days)}


def contacts():
    out = []
    for i, p in enumerate(PEOPLE):
        out.append(_contact(f"dir:{p['email']}", "directory", p["name"], [p["email"]],
                            ["469-248-7431"] if p["role"] in ("Owner", "Operations Contact") else [],
                            "NTXP LLC", p["role"], owner_user=p["email"], days=30 + i,
                            address="101 South Locust St Ste 605, Denton, TX 76201"))
    out += [
        _contact("ws:trevor@ntxpllc.com:people/c1001", "workspace", "Brenda Walsh",
                 ["bwalsh@dentonisd.example.org"], ["940-555-0142"], "Denton ISD (example)",
                 "Construction Manager", ["★ NTXP Shared", "Owners"], True, "trevor@ntxpllc.com"),
        _contact("ws:trevor@ntxpllc.com:people/c1002", "workspace", "Luis Ortega",
                 ["luis@ortegaelectric.example.com"], ["214-555-0199"], "Ortega Electric (example)",
                 "Estimator", ["Subcontractors"], False, "trevor@ntxpllc.com"),
        _contact("ws:alison@ntxpllc.com:people/c2001", "workspace", "Grace Lin",
                 ["glin@suretypartners.example.com"], ["972-555-0110"], "Surety Partners (example)",
                 "Account Executive", ["★ NTXP Shared"], True, "alison@ntxpllc.com"),
        _contact("ws:marcus.delgado@ntxpllc.com:people/c3001", "workspace", "Kevin Chen",
                 ["kchen@studioforma.example.com"], ["817-555-0177"], "Studio Forma Architects (example)",
                 "Project Architect", [], False, "marcus.delgado@ntxpllc.com"),
        _contact("shared:sc-0001", "shared", "Brenda Walsh", ["bwalsh@dentonisd.example.org"], ["940-555-0142"],
                 "Denton ISD (example)", "Construction Manager", ["Owners"], True, "trevor@ntxpllc.com"),
        _contact("shared:sc-0002", "shared", "Grace Lin", ["glin@suretypartners.example.com"], ["972-555-0110"],
                 "Surety Partners (example)", "Account Executive", ["Surety"], True, "alison@ntxpllc.com"),
        _contact("shared:sc-0003", "shared", "Lone Star Mechanical Estimating",
                 ["estimating@lonestarmech.example.com"], ["469-555-0163"], "Lone Star Mechanical (example)",
                 "", ["Subcontractors", "HVAC"], True, "rosa.jimenez@ntxpllc.com",
                 notes="Preferred HVAC sub for TIPS jobs."),
    ]
    return out


SHARED_SOURCE_REFS = {"shared:sc-0001": "ws:trevor@ntxpllc.com:people/c1001",
                      "shared:sc-0002": "ws:alison@ntxpllc.com:people/c2001"}

_store = {}


def state(key, factory):
    """Mutable demo state, rebuilt from fixtures after reset()."""
    if key not in _store:
        _store[key] = factory()
    return _store[key]


def reset():
    _store.clear()


TILES = [
    ("response_time", "Median response time", 3.4, "h", 4, -0.8, "good", "gauge"),
    ("unanswered_email", "Unanswered > 48h", 7, "", 3, 2, "bad", "bar"),
    ("wait_complaints", "Client wait complaints", 2, "", 0, 1, "watch", "ring"),
    ("no_shows", "Meeting no-shows (30d)", 1, "", 0, 0, "watch", "ring"),
    ("project_folder_access", "Project folder coverage", 92, "%", 100, 4, "watch", "gauge"),
    ("daily_report_quality", "Daily report quality", 81, "%", 85, -3, "watch", "gauge"),
    ("po_invoice_integrity", "PO / invoice matches", 96, "%", 100, -2, "watch", "pie"),
    ("open_billing_questions", "Open billing questions", 2, "", 0, 0, "watch", "bar"),
]


def tiles():
    staff = [p for p in PEOPLE if p["role"] not in ("Owner",)]
    out = []
    for n, (tid, label, value, unit, target, trend, status, kind) in enumerate(TILES):
        breakdown = [{"label": p["name"].split()[0], "value": round(value * (0.6 + 0.15 * ((i + n) % 5)), 1)}
                     for i, p in enumerate(staff[:5])]
        out.append({"id": tid, "label": label, "value": value, "unit": unit,
                    "display": f"{value}{unit if unit == '%' else ''}", "target": target, "trend": trend,
                    "status": status, "kind": kind, "breakdown": breakdown, "report_id": tid})
    return out


def people_rows():
    rows = []
    for i, p in enumerate(PEOPLE):
        rows.append({"email": p["email"], "name": p["name"], "role": p["role"],
                     "response_hrs": round(1.8 + i * 0.7, 1), "unanswered": [0, 1, 2, 0, 1, 3, 4, 0][i],
                     "baseline_dev": round([-0.2, 0.1, 0.4, -0.1, 0.3, 0.8, 1.6, 0.0][i], 2),
                     "open_flags": [0, 0, 1, 0, 0, 1, 2, 0][i], "top_level": [0, 0, 1, 0, 0, 1, 2, 0][i]})
    return rows


def summary():
    return {"updated": iso_ago(0, datetime.now(timezone.utc).hour), "tiles": tiles(), "people": people_rows()}


REPORT_TITLES = {
    "response_time": "Email response time by person",
    "unanswered_email": "Unanswered email older than 48 hours",
    "wait_complaints": "Client complaints about waiting",
    "no_shows": "Meeting no-shows",
    "responsiveness_anomaly": "Responsiveness anomalies vs. baseline",
    "project_folder_access": "Project folder access coverage",
    "daily_report_quality": "Daily report quality",
    "po_invoice_integrity": "PO and invoice integrity",
    "open_billing_questions": "Open billing questions",
    "cross_channel_confirmation": "Cross-channel confirmation of flags",
}


def report(report_id):
    if report_id not in REPORT_TITLES:
        return None
    today = _today()
    return {
        "id": report_id, "title": REPORT_TITLES[report_id], "generated": iso_ago(0),
        "period": {"from": (today - timedelta(days=30)).isoformat(), "to": today.isoformat()},
        "sources": ["gmail", "jobtread", "calendar"],
        "sections": [
            {"heading": "What we found",
             "findings": ["Devin Okafor has two client threads on Denton Courthouse Annex waiting more than 48 hours.",
                          "Response time for the field team is within target; office team is slightly slower than baseline."],
             "evidence": [{"source": "gmail", "ref": "demo-thr-008", "note": "Client follow-up after 6 days"},
                          {"source": "gmail", "ref": "demo-thr-009", "note": "Second follow-up, mentions board item"}]},
            {"heading": "Cross-checks",
             "findings": ["JobTread shows the revised schedule was uploaded today, which explains part of the delay."],
             "evidence": [{"source": "jobtread", "ref": "JT-DCA-schedule", "note": "Schedule rev 2 uploaded"}]},
        ],
        "conclusions": [{"text": "Watch item, not yet a performance issue. Re-check in 7 days.",
                         "confidence": 0.72, "council_id": None}],
        "jev": {"tier": 0, "executor": "demo", "cost": 0.0},
    }


def flags():
    today = _today().isoformat()
    base = [
        ("devin.okafor@ntxpllc.com", "unanswered_email", 2, "high", "gmail", "issue", 0.84,
         "Two client emails on Denton Courthouse Annex waited more than 48 hours for a reply.",
         "explained", ["jobtread"], ["Revised schedule uploaded to JobTread today."]),
        ("rosa.jimenez@ntxpllc.com", "po_invoice_integrity", 1, "medium", "quickbooks", "concern", 0.91,
         "Invoice 4471 exceeds PO 2026-118 by $2,650; payment correctly held.",
         "confirmed", ["gmail", "drive"], []),
        ("marcus.delgado@ntxpllc.com", "wait_complaints", 1, "low", "gmail", "note", 0.58,
         "Owner asked twice for RFI 014 status on McShan Elementary.",
         "pending", [], []),
        ("caleb.whitfield@ntxpllc.com", "daily_report_quality", 1, "low", "drive", "note", 0.66,
         "Daily reports for 10/06-10/07 lack photos.", "inconclusive", ["drive"], []),
    ]
    out = []
    for i, (person, kpi, level, urg, ch, sev, conf, summ, cstat, checked, expl) in enumerate(base, 1):
        out.append({
            "id": f"FL-{today}-{i:03d}", "person": person, "kpi": kpi, "level": level, "urgency": urg,
            "channel": ch, "severity": sev, "confidence": conf, "volatility": round(0.1 * i, 2),
            "summary": summ, "evidence": [{"source": ch, "ref": f"demo-ref-{i}", "note": summ}],
            "crosscheck": {"status": cstat, "sources_checked": checked, "explanations": expl},
            "council": None, "created": iso_ago(i - 1), "status": "open",
            "escalations": [{"level": 1, "channel": "daily_note", "at": iso_ago(i - 1), "to": ["trevor@ntxpllc.com"]}],
        })
    return out


def flag_store():
    return state("flags", flags)


def run_cycle():
    return {"flags_created": 1, "flags_escalated": 0, "jev": {"tier": 0, "executor": "demo", "cost": 0.0}}


RUNBOOK = [
    {"id": "RB-001", "workflow": "Org-wide Gmail search", "symptom": "Search returns no results for a known email",
     "likely_cause": "The mailbox owner is suspended or outside the delegated scopes.",
     "steps": ["Open Users and confirm the account is active.",
               "Run `python scripts/google_workspace/ntxp_google_access.py whoami --user <email>`.",
               "If it fails, re-authorize domain-wide delegation scopes in the Admin console."],
     "escalate_to": "trevor@ntxpllc.com", "tier": 0, "updated": "2026-10-01"},
    {"id": "RB-002", "workflow": "Shared contacts sync", "symptom": "Labelled contact not appearing in Shared Contacts",
     "likely_cause": "Label name differs from '★ NTXP Shared' or the sync has not run.",
     "steps": ["Confirm the label name exactly matches, including the star.", "Click Sync in Shared Contacts."],
     "escalate_to": "trevor@ntxpllc.com", "tier": 0, "updated": "2026-10-01"},
    {"id": "RB-003", "workflow": "Account offboarding", "symptom": "Approval link says expired",
     "likely_cause": "Staged changes expire after 15 minutes.",
     "steps": ["Stage the action again from Users.", "Approve within 15 minutes."],
     "escalate_to": "alison@ntxpllc.com", "tier": 3, "updated": "2026-10-01"},
]
