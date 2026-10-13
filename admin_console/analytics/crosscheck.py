"""Cross-check a negative trend against more sources before anyone acts on it.

For a flagged person and the flag's days, widen to JobTread (on-site logs), Calendar (PTO,
travel, all-day site meetings, no-shows), Plaud (long calls), Drive (project folders) and
Gmail (other threads).

  explained     a legitimate reason was found -> level down one (not below the rule's
                floor), the reason is kept on the flag
  confirmed     the trend shows in >= 2 channels -> confidence up; level kept, or raised
                by one (never above 2 - SMS is reserved for explicit rules) at >= 3 channels
  inconclusive  neither
"""

import datetime as dt
import logging
from collections import defaultdict

from admin_console import jev
from admin_console.analytics import util

log = logging.getLogger(__name__)

WIDEN = ("jobtread", "calendar", "plaud", "drive", "gmail")

# Which legitimate reasons can explain which KPI
EXPLAINERS = {
    "responsiveness_anomaly": {"onsite_log", "site_meeting", "ooo", "long_call"},
    "response_time": {"onsite_log", "site_meeting", "ooo", "long_call"},
    "unanswered_email": {"site_meeting", "ooo"},
    "no_shows": {"ooo", "site_meeting", "long_call"},
    "project_folder_access": {"ooo"},
    "wait_complaints": {"ooo"},
    "open_billing_questions": {"ooo"},
    "daily_report_quality": set(),
}
SKIP = {"internal_volatility", "po_invoice_integrity"}
CONFIRM_RAISE_CAP = 2


SEVERITY = ("note", "concern", "issue", "redflag")
URGENCY = ("low", "medium", "high", "critical")


def _step(scale, value, cap=None):
    i = min(scale.index(value) + 1, len(scale) - 1)
    if cap is not None:
        i = min(i, scale.index(cap))
    return scale[max(i, scale.index(value))]


def _pool_fetcher(events):
    def fetch(channel, person, start, end):
        return [e for e in events if e["source"] == channel and e["person"] == person
                and start <= util.as_utc(e["ts"]) <= end]
    return fetch


def _collector_fetcher(channel, person, start, end):
    from admin_console.analytics import collectors
    from admin_console.analytics.collectors import Unconfigured
    try:
        return collectors.module(channel).collect([person], start, end)
    except Unconfigured:
        return None
    except Exception as exc:  # noqa: BLE001
        log.info("crosscheck fetch %s failed: %s", channel, exc)
        return None


def flag_days(flag, now):
    """Central dates the flag is about: its own day plus the previous working day."""
    day = util.central(flag.get("ts") or now).date()
    prev = day - dt.timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= dt.timedelta(days=1)
    return {day.isoformat(), prev.isoformat()}


def crosscheck(flag, events=None, now=None, fetch=None, th=None):
    """Mutates and returns `flag` with a `crosscheck` block; adjusts level/confidence."""
    now = util.as_utc(now)
    th = th or {"z_minor": 2.0, "flag_lookback_days": 7}
    route = jev.route("crosscheck_fetch")
    if flag["kpi"] in SKIP:
        flag["crosscheck"] = {"status": "inconclusive", "sources_checked": [],
                              "explanations": ["not applicable to this KPI"]}
        return flag
    fetch = fetch or (_pool_fetcher(events) if events is not None else _collector_fetcher)
    person = flag["person"]
    days = flag_days(flag, now)
    lookback = now - dt.timedelta(days=th.get("flag_lookback_days", 7))
    wide_start = now - dt.timedelta(days=35)
    got, checked = {}, []
    for ch in WIDEN:
        evs = fetch(ch, person, wide_start, now)
        if evs is None:
            continue
        checked.append(ch)
        got[ch] = evs

    on_day = lambda e: util.central_day(e["ts"]) in days  # noqa: E731
    reasons = []
    allowed = EXPLAINERS.get(flag["kpi"], set())
    for e in got.get("calendar", []):
        if e["kind"] == "ooo" and on_day(e) and "ooo" in allowed:
            reasons.append(f"Calendar: {e['meta'].get('ooo_type', 'out of office')} - "
                           f"{e['meta'].get('title', '')} ({util.central_day(e['ts'])})")
        if e["kind"] == "site_meeting" and on_day(e) and "site_meeting" in allowed:
            reasons.append(f"Calendar: all-day site meeting - {e['meta'].get('title', '')} "
                           f"({util.central_day(e['ts'])})")
    if "onsite_log" in allowed:
        for e in got.get("jobtread", []):
            if e["kind"] == "daily_log" and e["meta"].get("on_site") and on_day(e):
                reasons.append(f"JobTread: on-site daily log for {e['meta'].get('job', '')} "
                               f"({util.central_day(e['ts'])})")
                break
    if "long_call" in allowed:
        for e in got.get("plaud", []):
            if e["kind"] in ("long_call", "mention") and on_day(e) and \
                    e["meta"].get("duration_min", 0) >= 45:
                reasons.append(f"Plaud: on a {e['meta']['duration_min']:.0f}-min call/meeting "
                               f"'{e['meta'].get('title', '')}'")
                break

    # negative signals per channel (recent window)
    neg = defaultdict(list)
    neg[flag["channel"]].append(flag["kpi"])
    rec = {ch: [e for e in evs if util.as_utc(e["ts"]) >= lookback] for ch, evs in got.items()}
    if any(e["kind"] in ("unanswered", "complaint") for e in rec.get("gmail", [])):
        neg["gmail"].append("unanswered/complaint threads")
    if any(e["kind"] == "no_show" for e in rec.get("calendar", [])):
        neg["calendar"].append("meeting no-show")
    if any(e["kind"] == "folder_stale" for e in rec.get("drive", [])):
        neg["drive"].append("project folder not opened")
    logs = [e for e in got.get("jobtread", []) if e["kind"] == "daily_log"]
    if logs:
        logged_days = {util.central_day(e["ts"]) for e in logs}
        workdays = {d for d in days if dt.date.fromisoformat(d).weekday() < 5}
        if workdays and not (workdays & logged_days) and len(logged_days) >= 5:
            neg["jobtread"].append("no daily log on flagged days (usually logs)")
        if any(e["meta"].get("quality", 1) < 0.6 for e in logs if util.as_utc(e["ts"]) >= lookback):
            neg["jobtread"].append("weak daily logs")

    level, floor = flag["level"], flag.get("floor_level") or 1
    if reasons:
        status = "explained"
        flag["level"] = max(floor, level - 1)
        flag["confidence"] = round(max(0.05, flag["confidence"] - 0.15), 2)
        notes = reasons + [f"Proposed downgrade L{level} -> L{flag['level']} pending owner review."
                           if flag["level"] != level else "Level kept at the rule's floor."]
    elif len(neg) >= 2:
        status = "confirmed"
        flag["confidence"] = round(min(0.97, flag["confidence"] + 0.1 * (len(neg) - 1)), 2)
        if len(neg) >= 3 and level < CONFIRM_RAISE_CAP:
            flag["level"] = level + 1
            flag["severity"] = _step(SEVERITY, flag["severity"])
            flag["urgency"] = _step(URGENCY, flag["urgency"], cap="high")
        notes = [f"Tracks across {len(neg)} channels: " +
                 "; ".join(f"{ch}: {', '.join(v)}" for ch, v in sorted(neg.items()))]
    else:
        status = "inconclusive"
        notes = ["No legitimate reason found and no second channel shows the same trend."]
    flag["crosscheck"] = {"status": status, "sources_checked": checked, "explanations": notes}
    flag.setdefault("sources", [])
    flag["sources"] = sorted(set(flag["sources"]) | set(neg))
    flag["_jev"] = jev.stamp(route)
    return flag
