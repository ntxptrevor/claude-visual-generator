"""Gmail adapter (per user, via domain-wide delegation, metadata + snippets only).

Events:
  response          first reply to a thread where the user was a recipient (business hours)
  unanswered        inbound thread with no reply after 24 h (newsletters / no-reply excluded)
  complaint         external wait / no-show complaint, with whether it reached the office
  billing_question  inbound billing question and whether it was answered
  message           internal NTXP<->NTXP message the user sent (snippet kept in memory only,
                    used for volatility; never stored beyond a 200-char evidence quote)
"""

import datetime as dt
import email.utils
import os
import re

from admin_console.analytics import demo, google, util
from admin_console.analytics.collectors import Unconfigured, event

COMPLAINT_PHRASES = (
    "still waiting", "haven't heard back", "havent heard back", "have not heard back",
    "no response", "didn't show", "did not show", "no-show", "no show", "following up again",
    "3rd request", "third request", "second request", "2nd request", "nobody called",
    "never showed",
)
BILLING_WORDS = ("invoice", "billing", "pay app", "payment", "retainage", "short-paid",
                 "short paid", "remittance", "statement", "w-9", "w9", "past due", "balance due")
AUTOMATED_SENDER = re.compile(r"(no-?reply|do-?not-?reply|notifications?|mailer-daemon|"
                              r"postmaster|newsletter|bounce|alerts?@|marketing)", re.I)
UNANSWERED_HOURS = 24


def status():
    if google.demo():
        return "ok"
    return "ok" if google.configured() else "unconfigured"


def collect(people, start, end, client=None):
    if google.demo() and client is None:
        return demo.events("gmail", people, start, end)
    if client is None and not google.configured():
        raise Unconfigured("gmail")
    out = []
    max_threads = int(os.environ.get("NTXP_GMAIL_MAX_THREADS", "300"))
    for user in people:
        svc = client(user) if callable(client) else (client or google.service("gmail", user=user))
        q = f"after:{int(util.as_utc(start).timestamp())} before:{int(util.as_utc(end).timestamp())}"
        token, seen = None, 0
        while seen < max_threads:
            resp = svc.users().threads().list(userId="me", q=q, maxResults=100,
                                              pageToken=token).execute()
            for t in resp.get("threads", []):
                seen += 1
                full = svc.users().threads().get(
                    userId="me", id=t["id"], format="metadata",
                    metadataHeaders=["From", "To", "Cc", "Subject", "List-Unsubscribe",
                                     "List-Id", "Precedence", "Auto-Submitted"]).execute()
                out.extend(analyze_thread(user, [_parse(m) for m in full.get("messages", [])],
                                          end, thread_id=t["id"]))
            token = resp.get("nextPageToken")
            if not token:
                break
    return out


def _parse(msg):
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    addrs = lambda v: [a.lower() for _, a in email.utils.getaddresses([v or ""]) if a]  # noqa: E731
    return {
        "id": msg.get("id"),
        "ts": dt.datetime.fromtimestamp(int(msg.get("internalDate", "0")) / 1000, util.UTC),
        "from": (addrs(headers.get("from")) or [""])[0],
        "to": addrs(headers.get("to")), "cc": addrs(headers.get("cc")),
        "subject": headers.get("subject", ""), "snippet": msg.get("snippet", ""),
        "automated": bool(headers.get("list-unsubscribe") or headers.get("list-id")
                          or headers.get("precedence", "").lower() in ("bulk", "list", "junk")
                          or headers.get("auto-submitted", "no").lower() != "no"),
    }


def is_automated(msg):
    return msg.get("automated") or bool(AUTOMATED_SENDER.search(msg.get("from", "")))


def complaint_phrases(text):
    low = (text or "").lower().replace("’", "'")
    return [p for p in COMPLAINT_PHRASES if p in low]


def complaint_type(phrases):
    joined = " ".join(phrases)
    if any(k in joined for k in ("show", "nobody called")):
        return "no-show"
    if any(k in joined for k in ("request", "following up")):
        return "follow-up"
    return "waiting on response"


def analyze_thread(user, msgs, now, thread_id=""):
    """Pure function: one thread's messages (parsed dicts) -> events for `user`."""
    user = user.lower()
    msgs = sorted(msgs, key=lambda m: m["ts"])
    now = util.as_utc(now)
    out = []
    if not msgs:
        return out
    subject = msgs[0].get("subject", "")

    # internal messages the user sent (for volatility; internal-only by construction)
    for m in msgs:
        recips = m["to"] + m["cc"]
        if m["from"] == user and recips and util.all_internal([m["from"]] + recips):
            out.append(event(user, "gmail", "message", m["ts"], f"{thread_id}/{m['id']}",
                             to=recips, sender=user, internal=True, text=m["snippet"]))

    inbound = [m for m in msgs if m["from"] != user and user in (m["to"] + m["cc"])
               and not is_automated(m)]
    if not inbound:
        return out
    first = inbound[0]
    external = not util.is_internal(first["from"])
    reply = next((m for m in msgs if m["from"] == user and m["ts"] > first["ts"]), None)

    if reply:
        out.append(event(user, "gmail", "response", reply["ts"], thread_id,
                         hours=util.business_hours_between(first["ts"], reply["ts"]),
                         wall_hours=round((reply["ts"] - first["ts"]).total_seconds() / 3600, 2),
                         internal=not external, counterpart=first["from"]))
    last = msgs[-1]
    if not reply and last["from"] != user:
        age = (now - first["ts"]).total_seconds() / 3600
        if age > UNANSWERED_HOURS:
            out.append(event(user, "gmail", "unanswered", first["ts"], thread_id,
                             age_hrs=round(age, 1), sender=first["from"], external=external,
                             subject=util.short_quote(subject, 120)))

    for m in inbound:
        if util.is_internal(m["from"]):
            continue
        phrases = complaint_phrases(m["snippet"] + " " + m["subject"])
        if phrases:
            office = set(util.office_emails())
            fwd = next((x for x in msgs if x["ts"] > m["ts"] and util.is_internal(x["from"])
                        and office & set(x["to"] + x["cc"])), None)
            out.append(event(user, "gmail", "complaint", m["ts"], thread_id, sender=m["from"],
                             external=True, phrases=phrases, complaint_type=complaint_type(phrases),
                             quote=util.short_quote(m["snippet"]), forwarded=bool(fwd),
                             forward_lag_bh=util.business_hours_between(m["ts"], fwd["ts"]) if fwd else None))
            break

    low = subject.lower() + " " + first["snippet"].lower()
    if external and any(w in low for w in BILLING_WORDS):
        out.append(event(user, "gmail", "billing_question", first["ts"], thread_id,
                         sender=first["from"], subject=util.short_quote(subject, 120),
                         answered=bool(reply),
                         will_delay_work=any(w in low for w in ("stop work", "hold", "delay",
                                                                "won't release", "short-paid"))))
    return out
