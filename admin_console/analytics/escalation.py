"""The escalation ladder. Messages go ONLY to the two owners.

  L1  daily note   -> DailyNotes tab, batched one row per person per day (read by the
                      existing morning scheduled task)
  L2  email        -> Gmail API send as NTXP_ALERT_SENDER (default trevor@ntxpllc.com) to
                      config.OWNER_EMAILS, one digest per cycle
  L3  SMS          -> Quo (OpenPhone) API to config.owner_phone(owner) for both owners, plus
                      the detail email

Recipients are never parameters: they are computed here from config and checked again
right before sending, so sending to anyone else is impossible from this module.
Dedupe: no repeat at the same level within THRESHOLDS["dedupe_hrs"].
Quiet hours 9 pm - 6 am Central: L2/L3 are held (noted in the daily note, marked deferred)
unless urgency is critical; the next cycle after 6 am sends them.
Undeliverable channels fall back down the ladder (SMS -> email -> daily note) and the
escalation records the channel actually used. Every escalation is recorded on the flag and
in Interactions.
"""

import base64
import json
import logging
import os
import urllib.request
from email.mime.text import MIMEText

from admin_console import config, jev
from admin_console.analytics import google, store, util

log = logging.getLogger(__name__)

QUO_URL = "https://api.openphone.com/v1/messages"
STALE_RAISE_KPIS = {"open_billing_questions"}
DISCLAIMER = ("Proposal for owner review - not a finding about any person. No action has been "
              "taken; evidence and confidence are attached.")

# Test hooks: {"email": fn(to, subject, body), "sms": fn(to_phone, text)}
TRANSPORT = {}
OUTBOX = []  # demo-mode deliveries (never leave the process)


# --------------------------------------------------------------------------- recipients

def owner_emails():
    return [e.lower() for e in config.OWNER_EMAILS]


def owner_phones():
    return [p for p in (config.owner_phone(e) for e in config.OWNER_EMAILS) if p]


def _guard(kind, to):
    allowed = set(owner_emails()) if kind == "email" else set(owner_phones())
    if not to or any(t not in allowed for t in to):
        raise PermissionError(f"escalation {kind} may only go to the two owners")


# --------------------------------------------------------------------------- transports

def email_ready():
    return google.configured()


def sms_ready():
    return bool(os.environ.get("QUO_API_KEY") and os.environ.get("QUO_FROM_NUMBER") and owner_phones())


def _send_email(subject, body):
    to = owner_emails()
    _guard("email", to)
    if "email" in TRANSPORT:
        TRANSPORT["email"](list(to), subject, body)
        return "sent", to
    if google.demo():
        OUTBOX.append({"channel": "email", "to": list(to), "subject": subject, "body": body})
        return "demo", to
    if not email_ready():
        return "unconfigured", to
    sender = os.environ.get("NTXP_ALERT_SENDER", "trevor@ntxpllc.com")
    msg = MIMEText(body)
    msg["to"], msg["from"], msg["subject"] = ", ".join(to), sender, subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    google.service("gmail", user=sender, allow_write=True).users().messages().send(
        userId="me", body={"raw": raw}).execute()
    return "sent", to


def _send_sms(text):
    phones = owner_phones()
    if "sms" in TRANSPORT:
        if not phones:
            return "unconfigured", []
        _guard("sms", phones)
        for p in phones:
            TRANSPORT["sms"](p, text)
        return "sent", phones
    if google.demo():
        to = phones or [f"sms:{e}" for e in owner_emails()]
        OUTBOX.append({"channel": "sms", "to": to, "text": text})
        return "demo", owner_emails()
    if not sms_ready():
        return "unconfigured", []
    _guard("sms", phones)
    for p in phones:
        req = urllib.request.Request(
            QUO_URL, method="POST",
            data=json.dumps({"content": text[:1500], "from": os.environ["QUO_FROM_NUMBER"],
                             "to": [p]}).encode(),
            headers={"Content-Type": "application/json", "Authorization": os.environ["QUO_API_KEY"]})
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
    return "sent", phones


# --------------------------------------------------------------------------- helpers

def _recent(flag, level, now, hours):
    for e in flag.get("escalations") or []:
        if e.get("level") == level and (now - util.as_utc(e["at"])).total_seconds() < hours * 3600:
            return True
    return False


def raise_stale(flag, now, th):
    """L2 still open after the L2 window -> L3 (anything open and not acknowledged)."""
    if flag.get("status") != "open" or flag["level"] != 2 or flag["kpi"] not in STALE_RAISE_KPIS:
        return False
    l2 = [e for e in flag.get("escalations") or [] if e.get("level") == 2]
    if l2 and (now - util.as_utc(l2[0]["at"])).total_seconds() / 3600 > th["l2_window_hrs"]:
        flag["level"] = 3
        if flag["urgency"] in ("low", "medium"):
            flag["urgency"] = "high"
        return True
    return False


def add_daily_note(flag, now):
    day = util.central_day(now)
    row_id = f"{day}|{flag['person']}"
    existing = store.get("DailyNotes", row_id)
    items = list((existing or {}).get("items") or [])
    ids = list((existing or {}).get("flag_ids") or [])
    if flag["id"] not in ids:
        items.append({"flag_id": flag["id"], "kpi": flag["kpi"], "level": flag["level"],
                      "summary": util.short_quote(flag["summary"]),
                      "confidence": flag["confidence"]})
        ids.append(flag["id"])
    store.upsert("DailyNotes", {"id": row_id, "date": day, "person": flag["person"],
                                "items": items, "flag_ids": ids,
                                "created": (existing or {}).get("created") or util.iso(now),
                                "updated": util.iso(now), "consumed": False})


def _record(flag, level, channel, to, now, delivery):
    entry = {"level": level, "channel": channel, "at": util.iso(now), "to": list(to)}
    flag.setdefault("escalations", []).append(entry)
    store.append("Interactions", {
        "id": store.next_id("Interactions", "IX-" + util.central_day(now)), "at": util.iso(now),
        "actor": "analytics", "kind": "escalation", "request_type": f"escalate_{channel}",
        "flag_id": flag["id"], "action": f"L{level}", "kpi": flag["kpi"], "level": level,
        "note": f"delivery={delivery}"})
    return entry


def _name(email):
    return util.display_name(email)


def _email_body(flags):
    lines = [DISCLAIMER, ""]
    for f in flags:
        lines += [f"[L{f['level']} {f['severity'].upper()} / {f['urgency']}] {f['id']} - "
                  f"{_name(f['person'])} - {f['kpi']}",
                  f"  {f['summary']}",
                  f"  Confidence {f['confidence']:.2f}; cross-check: "
                  f"{(f.get('crosscheck') or {}).get('status', 'pending')}"]
        for x in (f.get("crosscheck") or {}).get("explanations", [])[:2]:
            lines.append(f"    - {x}")
        for ev in f.get("evidence", [])[:3]:
            lines.append(f"  * [{ev['source']}] {ev['note']}")
        if f.get("council"):
            lines.append(f"  Council ({f['council']['agreement']:.0%}): {f['council']['conclusion']}")
        lines.append("")
    lines.append("Review and act in the Admin Console: https://admin.ntxpllc.com (Employee Analytics).")
    return "\n".join(lines)


# --------------------------------------------------------------------------- main entry

def escalate_all(flags, now=None, th=None, owner_requested=False):
    """Escalate a batch of open flags. Mutates flags; returns the number escalated.
    owner_requested=True (an owner pressed "escalate") skips quiet hours."""
    from admin_console.analytics import classify
    now = util.as_utc(now)
    th = th or classify.thresholds()
    quiet = util.in_quiet_hours(now) and not owner_requested
    to_email, to_sms, count = [], [], 0
    for f in flags:
        if f.get("status") != "open":
            continue
        raise_stale(f, now, th)
        level = f["level"]
        if level == 1 or (quiet and f["urgency"] != "critical"):
            if quiet and level > 1:
                f["deferred"] = True
            if not _recent(f, 1, now, th["dedupe_hrs"]):
                add_daily_note(f, now)
                _record(f, 1, "daily_note", ["DailyNotes"], now, "stored")
                count += 1
            continue
        f["deferred"] = False
        if _recent(f, level, now, th["dedupe_hrs"]):
            continue
        (to_sms if level == 3 else to_email).append(f)

    route = jev.route("notify_owner")
    escalated = set()
    if to_sms:
        detail = [f for f in to_sms if not _recent_channel(f, "email", now, th["dedupe_hrs"])]
        text = ("NTXP Analytics L3 (owner review): " + "; ".join(
            f"{_name(f['person'])} - {f['kpi']} ({f['urgency']})" for f in to_sms))[:300] + \
            ". Details by email / admin console."
        delivery, to = _send_sms(text)
        if delivery == "unconfigured":
            for f in to_sms:
                f["_fallback"] = True  # one rung down: the email records level 3 via email
            to_email.extend(to_sms)
        else:
            for f in to_sms:
                _record(f, 3, "sms", to, now, delivery)
                escalated.add(f["id"])
            to_email.extend(detail)
    if to_email:
        subject = (f"[NTXP Analytics] {len(to_email)} item(s) for owner review - "
                   f"{util.central(now):%b %d %I:%M %p} CT")
        delivery, to = _send_email(subject, _email_body(to_email))
        for f in to_email:
            sms_done = f["level"] == 3 and not f.get("_fallback")
            if delivery == "unconfigured":
                if not sms_done:
                    add_daily_note(f, now)
                    _record(f, f["level"], "daily_note", ["DailyNotes"], now,
                            "email/sms unconfigured")
            elif not sms_done:
                _record(f, f["level"], "email", to, now, delivery)
            else:
                f.setdefault("_detail_email", util.iso(now))
            f.pop("_fallback", None)
            escalated.add(f["id"])
    for f in flags:
        f.setdefault("_jev", jev.stamp(route))
    return count + len(escalated)


def _recent_channel(flag, channel, now, hours):
    return any(e.get("channel") == channel and
               (now - util.as_utc(e["at"])).total_seconds() < hours * 3600
               for e in flag.get("escalations") or [])
