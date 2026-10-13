"""Classification: KPI events -> proposed flags (urgency, severity, level, confidence,
volatility). Flags are proposals for owner review, never verdicts about a person.

Scales
  urgency   low | medium | high | critical
  severity  note | concern | issue | redflag
  channel   gmail | jobtread | calendar | drive | plaud | quo | quickbooks
  level     1 daily note | 2 email to owners | 3 SMS to owners

All tunable numbers live in THRESHOLDS; the learning loop nudges them within BOUNDS.
Emotional volatility is scored ONLY for internal NTXP<->NTXP messages; anything with an
external party is `None` and never scored.
"""

import datetime as dt
import logging
import os
import re
from collections import defaultdict

from admin_console import jev
from admin_console.analytics import baselines, google, util

log = logging.getLogger(__name__)

URGENCY = ("low", "medium", "high", "critical")
SEVERITY = ("note", "concern", "issue", "redflag")
CHANNELS = ("gmail", "jobtread", "calendar", "drive", "plaud", "quo", "quickbooks")
LEVELS = {1: "daily_note", 2: "email", 3: "sms"}

THRESHOLDS = {
    "z_minor": 2.0,               # robust z for a "lately vs norm" note
    "z_major": 3.5,               # robust z for a concern
    "unanswered_hrs": 24,         # inbound thread with no reply after this is unanswered
    "unanswered_l2_hrs": 48,      # an external thread this old ...
    "unanswered_l2_count": 3,     # ... and this many unanswered -> L2
    "complaint_forward_bh": 4,    # external complaint must reach the office within (bus. hrs)
    "billing_l2_bh": 8,           # open billing question older than 1 business day -> L2
    "l2_window_hrs": 24,          # still open this long after L2 -> L3
    "volatility_l3": 0.7,         # internal message volatility -> L3
    "volatility_note": 0.5,       # internal message volatility -> L1 note
    "quality_min": 0.6,           # daily log quality below this counts as weak
    "quality_concern_count": 3,   # this many weak logs in the lookback -> concern
    "folder_stale_days": 7,       # assigned project folder not opened for this many days
    "flag_lookback_days": 7,      # only events this recent can open a new flag
    "dedupe_hrs": 24,             # no repeat escalation at the same level within this window
}

# param: (min, max, step, direction) - direction +1 means "raise to make it less sensitive"
BOUNDS = {
    "z_minor": (1.5, 3.0, 0.25, +1),
    "z_major": (3.0, 5.0, 0.25, +1),
    "unanswered_l2_count": (2, 6, 1, +1),
    "unanswered_l2_hrs": (36, 96, 12, +1),
    "complaint_forward_bh": (2, 8, 1, +1),
    "billing_l2_bh": (4, 16, 2, +1),
    "volatility_l3": (0.6, 0.9, 0.05, +1),
    "volatility_note": (0.4, 0.7, 0.05, +1),
    "quality_min": (0.4, 0.75, 0.05, -1),
    "quality_concern_count": (2, 5, 1, +1),
    "folder_stale_days": (5, 21, 2, +1),
}

# which threshold the learning loop tunes for each KPI
KPI_PARAM = {
    "responsiveness_anomaly": "z_minor",
    "response_time": "z_minor",
    "unanswered_email": "unanswered_l2_count",
    "wait_complaints": "complaint_forward_bh",
    "open_billing_questions": "billing_l2_bh",
    "internal_volatility": "volatility_l3",
    "daily_report_quality": "quality_min",
    "project_folder_access": "folder_stale_days",
}

HAIKU_MODEL = os.environ.get("NTXP_VOLATILITY_MODEL", "claude-haiku-4-5-20251001")


def thresholds():
    """Defaults overridden by the latest applied threshold change in the Learning tab."""
    out = dict(THRESHOLDS)
    try:
        from admin_console.analytics import store
        rows = store.query("Learning", lambda r: r.get("kind") == "threshold"
                           and r.get("status") == "applied", order_by="at")
        for r in rows:
            if r.get("param") in out and r.get("after") is not None:
                out[r["param"]] = float(r["after"])
    except Exception as exc:  # noqa: BLE001
        log.debug("threshold overrides unavailable: %s", exc)
    return out


# --------------------------------------------------------------------------- confidence

def confidence(evidence_count, channels=1, baseline_n=None, z=None):
    """0-1 from evidence count, source agreement, baseline sample size and z magnitude."""
    e = min(1.0, evidence_count / 4.0)
    s = min(1.0, max(0, channels - 1) / 2.0)
    b = 0.5 if baseline_n is None else min(1.0, baseline_n / 20.0)
    zc = 0.5 if z is None else min(1.0, abs(z) / 5.0)
    return round(max(0.05, min(0.97, 0.2 + 0.3 * e + 0.2 * s + 0.15 * b + 0.15 * zc)), 2)


# --------------------------------------------------------------------------- volatility

ANGER = ("furious", "angry", "ridiculous", "unacceptable", "sick of", "fed up", "pissed",
         "outraged", "livid", "insane", "stupid", "idiot", "incompetent", "hate", "disgusted")
FRUSTRATION = ("again", "how many times", "three times", "every time", "can't keep",
               "cant keep", "nothing", "still", "keep asking", "for the last time", "seriously")
DISTRESS = ("overwhelmed", "stressed", "can't handle", "burned out", "burnt out", "exhausted",
            "i quit", "done with this", "breaking down", "can't do this", "falling apart")
PROFANITY = ("damn", "hell", "crap", "shit", "fuck", "wtf", "bs", "bullshit", "ass")
NEGATIONS = ("not", "no", "never", "nothing", "can't", "cannot", "won't", "don't", "didn't",
             "isn't", "wasn't", "nobody", "none")


def _hits(low, terms):
    return sum(len(re.findall(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", low)) for t in terms)


def volatility_tier0(text):
    text = text or ""
    low = text.lower().replace("’", "'")
    words = re.findall(r"[A-Za-z']+", text)
    n = max(1, len(words))
    caps = sum(1 for w in words if len(w) >= 4 and w.isupper()) / n
    comps = {
        "anger": min(1.0, _hits(low, ANGER) / 2.0),
        "frustration": min(1.0, _hits(low, FRUSTRATION) / 3.0),
        "distress": min(1.0, _hits(low, DISTRESS) / 2.0),
        "profanity": min(1.0, _hits(low, PROFANITY) / 1.0),
        "caps": min(1.0, caps / 0.08),
        "exclaim": min(1.0, text.count("!") / 3.0),
        "negation": min(1.0, (sum(1 for w in words if w.lower() in NEGATIONS) / n) / 0.15),
    }
    weights = {"anger": 0.3, "frustration": 0.2, "distress": 0.2, "profanity": 0.15,
               "caps": 0.1, "exclaim": 0.1, "negation": 0.05}
    return round(min(1.0, sum(comps[k] * weights[k] for k in comps)), 2), comps


def _tier1_volatility(text):
    """Claude Haiku refinement. Returns 0-1 or None when unavailable."""
    if google.demo() or not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=HAIKU_MODEL, max_tokens=20,
            system=("Rate the emotional volatility (anger, frustration, distress) of an internal "
                    "workplace message from 0.00 (calm) to 1.00 (highly volatile). Reply with the "
                    "number only. This is a proposal for owner review, not a judgement."),
            messages=[{"role": "user", "content": util.short_quote(text, 1200)}])
        if resp.stop_reason == "refusal":
            return None
        txt = next((b.text for b in resp.content if b.type == "text"), "")
        m = re.search(r"[01](?:\.\d+)?", txt)
        return max(0.0, min(1.0, float(m.group()))) if m else None
    except Exception as exc:  # noqa: BLE001
        log.info("tier1 volatility unavailable: %s", exc)
        return None


def score_volatility(text, sender, recipients):
    """Returns (score or None, jev stamp). None whenever any party is outside NTXP."""
    if not util.all_internal([sender] + list(recipients or [])):
        return None, jev.stamp(jev.route("kpi_compute"))
    base, _ = volatility_tier0(text)
    decision = jev.route("volatility")
    if "anthropic" in decision.get("forbidden_seats", []):  # never true; defensive
        return base, jev.stamp(jev.route("classify_message"))
    if decision["tier"] == 1 and base >= 0.3:
        refined = _tier1_volatility(text)
        if refined is not None:
            return round(0.5 * base + 0.5 * refined, 2), jev.stamp(decision)
    return base, jev.stamp(jev.route("classify_message"))


# --------------------------------------------------------------------------- rules

def _flag(person, kpi, channel, level, urgency, severity, summary, evidence, rule, ts, ref,
          conf, volatility=None, floor=1, sources=None):
    assert urgency in URGENCY and severity in SEVERITY and channel in CHANNELS and level in LEVELS
    return {"key": f"{kpi}|{person}|{ref}", "person": person, "kpi": kpi, "channel": channel,
            "level": level, "urgency": urgency, "severity": severity, "confidence": conf,
            "volatility": volatility, "summary": summary,
            "evidence": [dict(ev, note=util.short_quote(ev.get("note", ""))) for ev in evidence][:12],
            "rule": rule, "ts": util.iso(ts), "floor_level": floor,
            "sources": sorted(set(sources or [channel]))}


def _ev(source, ref, note):
    return {"source": source, "ref": str(ref), "note": util.short_quote(note)}


def classify(events, now=None, base=None, th=None, roster=None):
    """Return (candidate flags, jev stamps). `base` = baselines.compute(...) output."""
    now = util.as_utc(now)
    th = th or thresholds()
    base = base if base is not None else baselines.compute(events, now)
    since = now - dt.timedelta(days=th["flag_lookback_days"])
    recent = [e for e in events if util.as_utc(e["ts"]) >= since]
    by = defaultdict(list)
    for e in recent:
        by[(e["source"], e["kind"])].append(e)
    out, stamps = [], [jev.stamp(jev.route("kpi_compute"))]
    today = util.central_day(now)

    # 1. responsiveness: lately vs norm
    stamps.append(jev.stamp(jev.route("baseline_anomaly")))
    for person, b in base.items():
        if not b["usable"] or b["z"] < th["z_minor"]:
            continue
        major = b["z"] >= th["z_major"]
        out.append(_flag(
            person, "responsiveness_anomaly", "gmail", 1, "medium" if major else "low",
            "concern" if major else "note",
            f"Email first-response time lately {b['latest']:.1f} business h vs a norm of "
            f"{b['median']:.1f} h (robust z {b['z']:+.1f}).",
            [_ev("gmail", f"baseline:{person}", f"median {b['median']:.2f} h, MAD {b['mad']:.2f}, "
                 f"n={b['n']} days; recent days {', '.join(b['recent_days'])}")],
            "z_major" if major else "z_minor", now, today,
            confidence(2, 1, b["n"], b["z"])))

    # 2. unanswered email
    un = defaultdict(list)
    for e in by[("gmail", "unanswered")]:
        if e["meta"].get("age_hrs", 0) > th["unanswered_hrs"]:
            un[e["person"]].append(e)
    for person, items in un.items():
        ext = [e for e in items if e["meta"].get("external")]
        old_ext = [e for e in ext if e["meta"]["age_hrs"] >= th["unanswered_l2_hrs"]]
        l2 = len(items) >= th["unanswered_l2_count"] and old_ext
        out.append(_flag(
            person, "unanswered_email", "gmail", 2 if l2 else 1, "medium" if l2 else "low",
            "issue" if l2 else "concern",
            f"{len(items)} inbound thread(s) unanswered > {int(th['unanswered_hrs'])} h "
            f"({len(ext)} external, oldest {max(e['meta']['age_hrs'] for e in items):.0f} h).",
            [_ev("gmail", e["ref"], f"{'external' if e['meta'].get('external') else 'internal'} "
                 f"from {e['meta'].get('sender', '?')}: {e['meta'].get('subject', '')} "
                 f"({e['meta']['age_hrs']:.0f} h)") for e in items],
            "unanswered_l2" if l2 else "unanswered", now, today, confidence(len(items))))

    # 3. external wait / no-show complaints
    for e in by[("gmail", "complaint")]:
        m = e["meta"]
        lag = m.get("forward_lag_bh")
        elapsed = util.business_hours_between(e["ts"], now)
        late = (not m.get("forwarded") and elapsed > th["complaint_forward_bh"]) or \
               (m.get("forwarded") and lag is not None and lag > th["complaint_forward_bh"])
        fwd = ("forwarded to the office after %.1f business h" % lag) if m.get("forwarded") \
            else f"not forwarded to the office ({elapsed:.1f} business h elapsed)"
        out.append(_flag(
            e["person"], "wait_complaints", "gmail", 3 if late else 2, "high", "redflag",
            f"External complaint ({m.get('complaint_type')}) from {m.get('sender')}; {fwd}.",
            [_ev("gmail", e["ref"], f"\"{m.get('quote', '')}\"")],
            "complaint_unforwarded" if late else "complaint", e["ts"], e["ref"],
            confidence(1 + len(m.get("phrases", [])), 1), floor=2))

    # 4. no-shows (accepted but absent per Meet attendance)
    for e in by[("calendar", "no_show")]:
        m = e["meta"]
        ext = m.get("external")
        out.append(_flag(
            e["person"], "no_shows", "calendar", 2 if ext else 1, "high" if ext else "medium",
            "issue", f"Accepted '{m.get('title')}' but Meet attendance shows absent"
                     f"{' (external meeting)' if ext else ''}.",
            [_ev("calendar", e["ref"], f"{m.get('title')} - attendance {m.get('attendance')}")],
            "no_show_external" if ext else "no_show", e["ts"], e["ref"], confidence(2)))

    # 5. project folder access
    for e in by[("drive", "folder_stale")]:
        m = e["meta"]
        if m.get("days_since", 0) < th["folder_stale_days"]:
            continue
        out.append(_flag(
            e["person"], "project_folder_access", "drive", 1, "low", "note",
            f"Has not opened the {m.get('project')} folder in {m.get('days_since')} days.",
            [_ev("drive", e["ref"], f"{m.get('project')}: last open {m.get('days_since')} days ago")],
            "folder_stale", now, e["ref"], confidence(1)))

    # 6. daily report quality
    weak = defaultdict(list)
    for e in by[("jobtread", "daily_log")]:
        m = e["meta"]
        if m.get("quality", 1) < th["quality_min"] or not m.get("has_photos"):
            weak[e["person"]].append(e)
    for person, items in weak.items():
        many = len(items) >= th["quality_concern_count"]
        out.append(_flag(
            person, "daily_report_quality", "jobtread", 1, "medium" if many else "low",
            "concern" if many else "note",
            f"{len(items)} daily log(s) below the quality bar or missing photos in the last "
            f"{int(th['flag_lookback_days'])} days.",
            [_ev("jobtread", e["ref"], f"{e['meta'].get('job')}: quality {e['meta'].get('quality')}; "
                 f"{'; '.join(e['meta'].get('issues', []))}") for e in items],
            "log_quality", now, today, confidence(len(items))))

    # 7. PO / vendor invoice integrity
    for e in by[("jobtread", "purchase_order")] + by[("jobtread", "vendor_invoice")]:
        m = e["meta"]
        if not m.get("missing"):
            continue
        money = not m.get("amount_ok", True)
        label = "PO" if e["kind"] == "purchase_order" else "Vendor invoice"
        out.append(_flag(
            e["person"], "po_invoice_integrity", "jobtread", 2 if money else 1,
            "medium" if money else "low", "issue" if money else "concern",
            f"{label} {m.get('number')} missing: {', '.join(m['missing'])}.",
            [_ev("jobtread", e["ref"], f"{label} {m.get('number')} ({m.get('vendor') or 'no vendor'}): "
                 f"{', '.join(m['missing'])}")],
            "doc_amounts" if money else "doc_fields", e["ts"], e["ref"], confidence(len(m["missing"]))))

    # 8. open billing questions
    for e in by[("gmail", "billing_question")] + by[("quickbooks", "disputed_invoice")]:
        m = e["meta"]
        if m.get("answered"):
            continue
        age_bh = util.business_hours_between(e["ts"], now)
        if age_bh <= th["billing_l2_bh"]:
            continue
        crossed = util.add_business_hours(e["ts"], th["billing_l2_bh"])
        stale = (now - crossed).total_seconds() / 3600 > th["l2_window_hrs"]
        delay = bool(m.get("will_delay_work"))
        level = 3 if (stale or delay) else 2
        what = m.get("subject") or f"invoice {m.get('invoice')} ({m.get('customer')})"
        out.append(_flag(
            e["person"], "open_billing_questions", "quickbooks" if e["source"] == "quickbooks" else "gmail",
            level, "critical" if delay else "high", "issue",
            f"Billing question open {age_bh:.1f} business h: {what}"
            f"{' - may delay work' if delay else ''}.",
            [_ev(e["source"], e["ref"], f"{m.get('sender') or m.get('customer')}: {what}")],
            "billing_delay" if delay else ("billing_stale" if stale else "billing_open"),
            e["ts"], e["ref"], confidence(2), floor=2))

    # 9. internal emotional volatility (internal-only by construction)
    for e in by[("gmail", "message")]:
        m = e["meta"]
        score, stamp = score_volatility(m.get("text", ""), m.get("sender") or e["person"], m.get("to"))
        stamps.append(stamp)
        if score is None or score < th["volatility_note"]:
            continue
        hot = score >= th["volatility_l3"]
        out.append(_flag(
            e["person"], "internal_volatility", "gmail", 3 if hot else 1,
            "high" if hot else "low", "redflag" if hot else "note",
            f"Internal message scored {score:.2f} on emotional volatility "
            f"(to {', '.join(m.get('to', []))}). Context may be missing - check in, don't assume.",
            [_ev("gmail", e["ref"], f"\"{util.short_quote(m.get('text', ''), 160)}\"")],
            "volatility_l3" if hot else "volatility_note", e["ts"], e["ref"],
            confidence(1, 1, None, None), volatility=score))
    return out, stamps
