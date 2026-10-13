"""The ten prewired reports, the summary tiles and the people table.

Reports distill and collate collected events into sections, findings, evidence and
conclusions. Conclusions are labelled as proposals for owner review with a confidence -
never stated as facts about a person.
"""

import datetime as dt
from collections import Counter, defaultdict

from admin_console import jev
from admin_console.analytics import baselines, util

REPORTS = {
    "response_time": "Email response time",
    "unanswered_email": "Unanswered email",
    "wait_complaints": "Wait and no-show complaints",
    "no_shows": "Meeting no-shows",
    "responsiveness_anomaly": "Responsiveness vs personal norm",
    "project_folder_access": "Project folder access",
    "daily_report_quality": "Daily report quality",
    "po_invoice_integrity": "PO and vendor invoice integrity",
    "open_billing_questions": "Open billing questions",
    "cross_channel_confirmation": "Cross-channel confirmation",
}
REPORT_SOURCES = {
    "response_time": ["gmail"], "unanswered_email": ["gmail"], "wait_complaints": ["gmail"],
    "no_shows": ["calendar"], "responsiveness_anomaly": ["gmail"],
    "project_folder_access": ["drive"], "daily_report_quality": ["jobtread"],
    "po_invoice_integrity": ["jobtread"], "open_billing_questions": ["gmail", "quickbooks"],
    "cross_channel_confirmation": ["gmail", "calendar", "drive", "jobtread", "plaud"],
}
KPI_FOR_REPORT = {
    "response_time": {"responsiveness_anomaly"}, "responsiveness_anomaly": {"responsiveness_anomaly"},
    "unanswered_email": {"unanswered_email"}, "wait_complaints": {"wait_complaints"},
    "no_shows": {"no_shows"}, "project_folder_access": {"project_folder_access"},
    "daily_report_quality": {"daily_report_quality"},
    "po_invoice_integrity": {"po_invoice_integrity"},
    "open_billing_questions": {"open_billing_questions"},
}
PROPOSAL = "Proposal for owner review: "


class Ctx:
    """Everything a report needs, computed once per build."""

    def __init__(self, events, flags, now, roster):
        self.now = util.as_utc(now)
        self.events = events
        self.flags = flags
        self.roster = roster or []
        self.names = {p["email"]: p["name"] for p in self.roster}
        self.base = baselines.compute(events, self.now)
        self.wk = self.now - dt.timedelta(days=7)
        self.prev_wk = self.now - dt.timedelta(days=14)
        self.month = self.now - dt.timedelta(days=30)

    def name(self, email):
        return self.names.get(email) or util.display_name(email)

    def first(self, email):
        return self.name(email).split(" ")[0]

    def of(self, source, kind, since=None, until=None):
        return [e for e in self.events if e["source"] == source and e["kind"] == kind
                and (since is None or util.as_utc(e["ts"]) >= since)
                and (until is None or util.as_utc(e["ts"]) < until)]


def _ev(source, ref, note):
    return {"source": source, "ref": str(ref), "note": util.short_quote(note)}


def _conclusions(ctx, report_id, default_conf=0.6):
    kpis = KPI_FOR_REPORT.get(report_id)
    fl = [f for f in ctx.flags if (kpis is None or f["kpi"] in kpis)
          and f.get("status") in ("open", "ack")]
    if report_id == "cross_channel_confirmation":
        fl = [f for f in fl if (f.get("crosscheck") or {}).get("status") in ("confirmed", "explained")]
    out = []
    for f in sorted(fl, key=lambda f: (-f["level"], -f["confidence"]))[:8]:
        cc = (f.get("crosscheck") or {}).get("status", "pending")
        out.append({"text": f"{PROPOSAL}{ctx.name(f['person'])} - {f['summary']} "
                            f"(L{f['level']}, cross-check {cc}; flag {f['id']})",
                    "confidence": f["confidence"],
                    "council_id": (f.get("council") or {}).get("council_id")})
    if not out:
        out.append({"text": PROPOSAL + "nothing in this period needs attention.",
                    "confidence": default_conf, "council_id": None})
    return out


def _report(ctx, report_id, sections, period_days=30):
    return {"id": report_id, "title": REPORTS[report_id], "generated": util.iso(ctx.now),
            "period": {"from": util.central_day(ctx.now - dt.timedelta(days=period_days)),
                       "to": util.central_day(ctx.now)},
            "sources": REPORT_SOURCES[report_id], "sections": sections,
            "conclusions": _conclusions(ctx, report_id),
            "jev": jev.stamp(jev.route("kpi_compute"))}


def _resp_by_person(ctx, since, until=None):
    by = defaultdict(list)
    for e in ctx.of("gmail", "response", since, until):
        by[e["person"]].append(e["meta"]["hours"])
    return {p: util.median(v) for p, v in by.items()}


# --------------------------------------------------------------------------- reports

def r_response_time(ctx):
    cur = _resp_by_person(ctx, ctx.wk)
    ext = defaultdict(list)
    for e in ctx.of("gmail", "response", ctx.wk):
        ext["internal" if e["meta"].get("internal") else "external"].append(e["meta"]["hours"])
    team = util.median([e["meta"]["hours"] for e in ctx.of("gmail", "response", ctx.wk)])
    s1 = {"heading": "Last 7 days - median first response (business hours)",
          "findings": [f"Team median {team:.1f} h." if team is not None else "No responses recorded."] +
                      [f"{ctx.name(p)}: {h:.1f} h (28-day norm {ctx.base.get(p, {}).get('median') or 0:.1f} h)"
                       for p, h in sorted(cur.items(), key=lambda kv: -kv[1])],
          "evidence": [_ev("gmail", f"baseline:{p}", f"n={b['n']} days, median {b['median'] or 0:.2f} h")
                       for p, b in ctx.base.items()]}
    s2 = {"heading": "Internal vs external threads",
          "findings": [f"{k.capitalize()}: median {util.median(v):.1f} h over {len(v)} threads"
                       for k, v in sorted(ext.items())], "evidence": []}
    return _report(ctx, "response_time", [s1, s2])


def r_unanswered(ctx):
    items = ctx.of("gmail", "unanswered")
    by = defaultdict(list)
    for e in items:
        by[e["person"]].append(e)
    findings = [f"{len(items)} inbound thread(s) unanswered > 24 h "
                f"({sum(1 for e in items if e['meta'].get('external'))} external). "
                "Newsletters, no-reply and automated mail are excluded."]
    findings += [f"{ctx.name(p)}: {len(v)} (oldest {max(e['meta']['age_hrs'] for e in v):.0f} h)"
                 for p, v in sorted(by.items(), key=lambda kv: -len(kv[1]))]
    ev = [_ev("gmail", e["ref"], f"{ctx.first(e['person'])} <- {e['meta'].get('sender')}: "
              f"{e['meta'].get('subject', '')} ({e['meta']['age_hrs']:.0f} h)") for e in items]
    return _report(ctx, "unanswered_email", [{"heading": "Open inbound threads", "findings": findings,
                                              "evidence": ev}])


def r_complaints(ctx):
    items = ctx.of("gmail", "complaint", ctx.month)
    types = Counter(e["meta"].get("complaint_type") for e in items)
    unfwd = [e for e in items if not e["meta"].get("forwarded")]
    findings = [f"{len(items)} external complaint(s) in 30 days: " +
                ", ".join(f"{k} {v}" for k, v in types.items()) if items else "No external complaints in 30 days.",
                f"{len(unfwd)} not forwarded to the office; target is within 4 business hours."]
    ev = [_ev("gmail", e["ref"], f"{ctx.first(e['person'])} / {e['meta'].get('sender')}: "
              f"\"{e['meta'].get('quote', '')}\" - "
              f"{'forwarded' if e['meta'].get('forwarded') else 'NOT forwarded'}") for e in items]
    return _report(ctx, "wait_complaints", [{"heading": "Complaints about waiting / no-shows",
                                             "findings": findings, "evidence": ev}])


def r_no_shows(ctx):
    ns = ctx.of("calendar", "no_show", ctx.month)
    unknown = [e for e in ctx.of("calendar", "meeting", ctx.month) if e["meta"].get("attendance") == "unknown"]
    declines = ctx.of("calendar", "decline", ctx.month)
    by = Counter(e["person"] for e in ns)
    findings = [f"{len(ns)} no-show(s) confirmed by Meet attendance in 30 days."] + \
               [f"{ctx.name(p)}: {c}" for p, c in by.most_common()] + \
               [f"{len(unknown)} accepted meeting(s) with no attendance data (marked unknown, not counted).",
                f"{len(declines)} decline(s) (not counted as no-shows)."]
    ev = [_ev("calendar", e["ref"], f"{ctx.first(e['person'])}: {e['meta'].get('title')} - "
              f"attendance {e['meta'].get('attendance')}") for e in ns + unknown]
    return _report(ctx, "no_shows", [{"heading": "Accepted but absent", "findings": findings,
                                      "evidence": ev}])


def r_anomaly(ctx):
    rows = sorted(ctx.base.items(), key=lambda kv: -kv[1]["z"])
    findings = [f"{ctx.name(p)}: lately {b['latest'] or 0:.1f} h vs norm {b['median'] or 0:.1f} h "
                f"(robust z {b['z']:+.1f}{'' if b['usable'] else ', baseline too small'})"
                for p, b in rows]
    return _report(ctx, "responsiveness_anomaly", [{
        "heading": "Lately vs personal 28-day norm (median + MAD)", "findings": findings,
        "evidence": [_ev("gmail", f"baseline:{p}", f"recent days {', '.join(b['recent_days'])}; "
                         f"MAD {b['mad'] or 0:.2f}; n={b['n']}") for p, b in rows]}])


def r_folders(ctx):
    opens = ctx.of("drive", "folder_open", ctx.wk)
    stale = ctx.of("drive", "folder_stale")
    by = defaultdict(set)
    for e in opens:
        by[e["person"]].add(e["meta"].get("project"))
    findings = [f"{ctx.name(p)} opened: {', '.join(sorted(v))}" for p, v in sorted(by.items())] + \
               [f"{ctx.name(e['person'])} has not opened {e['meta'].get('project')} in "
                f"{e['meta'].get('days_since')} days" for e in stale]
    if not opens and not stale:
        findings = ["No project assignments configured (NTXP_PROJECT_ASSIGNMENTS) or no Drive data."]
    return _report(ctx, "project_folder_access", [{
        "heading": "Assigned project folders - last 7 days", "findings": findings,
        "evidence": [_ev("drive", e["ref"], f"{e['meta'].get('project')} stale "
                         f"{e['meta'].get('days_since')} d") for e in stale]}], period_days=7)


def r_quality(ctx):
    logs = ctx.of("jobtread", "daily_log", ctx.wk)
    by = defaultdict(list)
    for e in logs:
        by[e["person"]].append(e)
    issues = Counter(i for e in logs for i in e["meta"].get("issues", []) if not i.startswith("spelling"))
    findings = [f"{len(logs)} daily log(s) in 7 days; "
                f"{sum(1 for e in logs if not e['meta'].get('has_photos'))} without photos."] + \
               [f"{ctx.name(p)}: avg quality {sum(e['meta']['quality'] for e in v) / len(v):.2f} "
                f"over {len(v)} log(s)" for p, v in sorted(by.items())] + \
               ([f"Common issues: {', '.join(f'{k} ({v})' for k, v in issues.most_common(4))}"] if issues else [])
    weak = [e for e in logs if e["meta"]["quality"] < 0.6 or not e["meta"].get("has_photos")]
    return _report(ctx, "daily_report_quality", [{
        "heading": "Tier 0 quality check (sentence case, spelling, run-ons, length, photos)",
        "findings": findings,
        "evidence": [_ev("jobtread", e["ref"], f"{e['meta'].get('job')}: {e['meta']['quality']} - "
                         f"\"{e['meta'].get('quote', '')}\"") for e in weak]}], period_days=7)


def r_integrity(ctx):
    docs = ctx.of("jobtread", "purchase_order", ctx.month) + ctx.of("jobtread", "vendor_invoice", ctx.month)
    bad = [e for e in docs if e["meta"].get("missing")]
    findings = [f"{len(docs)} PO/invoice document(s) checked; {len(docs) - len(bad)} complete "
                f"({_pct(len(docs) - len(bad), len(docs))}%).",
                "Required: vendor, job, cost code, date, number, line amounts that sum to the total, "
                "and a PO reference on vendor invoices."]
    ev = [_ev("jobtread", e["ref"], f"{e['meta'].get('number')}: missing {', '.join(e['meta']['missing'])}")
          for e in bad]
    return _report(ctx, "po_invoice_integrity", [{"heading": "Required fields and amounts",
                                                  "findings": findings, "evidence": ev}])


def r_billing(ctx):
    qs = [e for e in ctx.of("gmail", "billing_question", ctx.month) + ctx.of("quickbooks", "disputed_invoice", ctx.month)]
    open_ = [e for e in qs if not e["meta"].get("answered")]
    findings = [f"{len(open_)} open of {len(qs)} billing question(s)/disputes in 30 days."] + \
               [f"{e['meta'].get('subject') or 'Invoice ' + str(e['meta'].get('invoice'))}: open "
                f"{util.business_hours_between(e['ts'], ctx.now):.1f} business h"
                f"{' - may delay work' if e['meta'].get('will_delay_work') else ''}" for e in open_]
    ev = [_ev(e["source"], e["ref"], f"{e['meta'].get('sender') or e['meta'].get('customer')}") for e in open_]
    return _report(ctx, "open_billing_questions", [{"heading": "Unanswered billing questions",
                                                    "findings": findings, "evidence": ev}])


def r_cross(ctx):
    st = Counter((f.get("crosscheck") or {}).get("status", "pending") for f in ctx.flags)
    findings = [f"{k}: {v}" for k, v in st.most_common()] or ["No flags this period."]
    ev = [_ev(",".join((f.get("crosscheck") or {}).get("sources_checked", [])), f["id"],
              f"{ctx.first(f['person'])} {f['kpi']}: {(f.get('crosscheck') or {}).get('status')} - "
              f"{'; '.join((f.get('crosscheck') or {}).get('explanations', []))}")
          for f in ctx.flags if (f.get("crosscheck") or {}).get("status") in ("explained", "confirmed")]
    return _report(ctx, "cross_channel_confirmation", [{
        "heading": "Negative trends checked against JobTread, Calendar, Plaud, Drive and Gmail",
        "findings": findings, "evidence": ev}], period_days=7)


BUILDERS = {
    "response_time": r_response_time, "unanswered_email": r_unanswered,
    "wait_complaints": r_complaints, "no_shows": r_no_shows,
    "responsiveness_anomaly": r_anomaly, "project_folder_access": r_folders,
    "daily_report_quality": r_quality, "po_invoice_integrity": r_integrity,
    "open_billing_questions": r_billing, "cross_channel_confirmation": r_cross,
}


def build_all(events, flags, now=None, roster=None):
    ctx = Ctx(events, flags, now, roster)
    return {rid: fn(ctx) for rid, fn in BUILDERS.items()}, ctx


# --------------------------------------------------------------------------- tiles

def _pct(a, b):
    return round(100.0 * a / b, 1) if b else 100.0


def _status(value, target, higher_is_better, watch_band=0.15):
    if value is None:
        return "watch"
    if higher_is_better:
        return "good" if value >= target else ("watch" if value >= target * (1 - watch_band) else "bad")
    return "good" if value <= target else ("watch" if value <= target * (1 + watch_band * 3) else "bad")


def _tile(id_, label, value, unit, target, trend, status, kind, breakdown, report_id, fmt="{:.1f}"):
    value = round(float(value), 2) if value is not None else 0.0
    return {"id": id_, "label": label, "value": value, "unit": unit,
            "display": fmt.format(value), "target": target,
            "trend": round(float(trend or 0.0), 2), "status": status, "kind": kind,
            "breakdown": [{"label": b["label"], "value": round(float(b["value"]), 2)} for b in breakdown],
            "report_id": report_id}


def responsiveness_scores(ctx):
    unans = Counter(e["person"] for e in ctx.of("gmail", "unanswered"))
    out = {}
    for p in {r["email"] for r in ctx.roster} | set(ctx.base):
        z = (ctx.base.get(p) or {}).get("z", 0.0) or 0.0
        out[p] = max(0.0, min(100.0, 100 - 12 * max(0.0, z) - 6 * unans.get(p, 0)))
    return out


def tiles(ctx):
    t = []
    team = util.median([e["meta"]["hours"] for e in ctx.of("gmail", "response", ctx.wk)])
    prev = util.median([e["meta"]["hours"] for e in ctx.of("gmail", "response", ctx.prev_wk, ctx.wk)])
    cur = _resp_by_person(ctx, ctx.wk)
    t.append(_tile("response_time", "Median response time", team or 0, "h", 4,
                   (team or 0) - (prev or team or 0), _status(team, 4, False), "gauge",
                   [{"label": ctx.first(p), "value": v} for p, v in sorted(cur.items())],
                   "response_time"))

    scores = responsiveness_scores(ctx)
    team_score = sum(scores.values()) / len(scores) if scores else 100.0
    t.append(_tile("responsiveness_score", "Team responsiveness score", team_score, "pts", 85,
                   0.0, _status(team_score, 85, True), "gauge",
                   [{"label": ctx.first(p), "value": v} for p, v in sorted(scores.items())],
                   "responsiveness_anomaly", "{:.0f}"))

    un = Counter(e["person"] for e in ctx.of("gmail", "unanswered"))
    total = sum(un.values())
    t.append(_tile("unanswered_email", "Unanswered email > 24 h", total, "threads", 0, 0.0,
                   "good" if total == 0 else ("watch" if total <= 3 else "bad"), "pie",
                   [{"label": ctx.first(p), "value": c} for p, c in un.most_common()],
                   "unanswered_email", "{:.0f}"))

    comp = ctx.of("gmail", "complaint", ctx.month)
    ctypes = Counter(e["meta"].get("complaint_type") for e in comp)
    comp_prev = len(ctx.of("gmail", "complaint", ctx.month - dt.timedelta(days=30), ctx.month))
    t.append(_tile("wait_complaints", "Complaint types (30 d)", len(comp), "complaints", 0,
                   len(comp) - comp_prev, "good" if not comp else ("watch" if len(comp) <= 1 else "bad"),
                   "pie", [{"label": k, "value": v} for k, v in ctypes.most_common()],
                   "wait_complaints", "{:.0f}"))

    logs = ctx.of("jobtread", "daily_log", ctx.wk)
    ok = [e for e in logs if e["meta"]["quality"] >= 0.6 and e["meta"].get("has_photos")]
    q = _pct(len(ok), len(logs))
    logs_prev = ctx.of("jobtread", "daily_log", ctx.prev_wk, ctx.wk)
    q_prev = _pct(sum(1 for e in logs_prev if e["meta"]["quality"] >= 0.6 and e["meta"].get("has_photos")),
                  len(logs_prev))
    t.append(_tile("daily_report_quality", "Daily reports meeting the bar", q, "%", 90, q - q_prev,
                   _status(q, 90, True), "ring",
                   [{"label": "meets bar", "value": len(ok)}, {"label": "below bar", "value": len(logs) - len(ok)}],
                   "daily_report_quality", "{:.0f}%"))

    docs = ctx.of("jobtread", "purchase_order", ctx.month) + ctx.of("jobtread", "vendor_invoice", ctx.month)
    clean = [e for e in docs if not e["meta"].get("missing")]
    integ = _pct(len(clean), len(docs))
    t.append(_tile("po_invoice_integrity", "PO / invoice integrity", integ, "%", 95, 0.0,
                   _status(integ, 95, True), "ring",
                   [{"label": "complete", "value": len(clean)}, {"label": "missing fields", "value": len(docs) - len(clean)}],
                   "po_invoice_integrity", "{:.0f}%"))

    ns = Counter(e["person"] for e in ctx.of("calendar", "no_show", ctx.month))
    t.append(_tile("no_shows", "Meeting no-shows (30 d)", sum(ns.values()), "meetings", 0, 0.0,
                   "good" if not ns else ("watch" if sum(ns.values()) == 1 else "bad"), "bar",
                   [{"label": ctx.first(p), "value": c} for p, c in ns.most_common()],
                   "no_shows", "{:.0f}"))

    stale = ctx.of("drive", "folder_stale")
    opened = {(e["person"], e["meta"].get("project")) for e in ctx.of("drive", "folder_open", ctx.wk)}
    assigned = len(opened | {(e["person"], e["meta"].get("project")) for e in stale})
    access = _pct(assigned - len(stale), assigned)
    t.append(_tile("project_folder_access", "Project folders opened (7 d)", access, "%", 100, 0.0,
                   _status(access, 100, True, 0.1), "ring",
                   [{"label": "opened", "value": assigned - len(stale)}, {"label": "not opened", "value": len(stale)}],
                   "project_folder_access", "{:.0f}%"))

    open_bq = [e for e in ctx.of("gmail", "billing_question") + ctx.of("quickbooks", "disputed_invoice")
               if not e["meta"].get("answered")]
    ages = Counter("> 2 bus. days" if util.business_hours_between(e["ts"], ctx.now) > 16 else
                   ("> 1 bus. day" if util.business_hours_between(e["ts"], ctx.now) > 8 else "< 1 bus. day")
                   for e in open_bq)
    t.append(_tile("open_billing_questions", "Open billing questions", len(open_bq), "open", 0, 0.0,
                   "good" if not open_bq else ("watch" if not ages.get("> 1 bus. day") and not ages.get("> 2 bus. days") else "bad"),
                   "bar", [{"label": k, "value": v} for k, v in sorted(ages.items())],
                   "open_billing_questions", "{:.0f}"))

    st = Counter((f.get("crosscheck") or {}).get("status", "pending") for f in ctx.flags
                 if f.get("status") in ("open", "ack"))
    t.append(_tile("cross_channel_confirmation", "Cross-checked flags", st.get("confirmed", 0),
                   "confirmed", 0, 0.0, "good" if not st.get("confirmed") else "watch", "pie",
                   [{"label": k, "value": v} for k, v in st.most_common()],
                   "cross_channel_confirmation", "{:.0f}"))
    return t


def people_rows(ctx):
    cur = _resp_by_person(ctx, ctx.wk)
    un = Counter(e["person"] for e in ctx.of("gmail", "unanswered"))
    rows = []
    for p in ctx.roster:
        email = p["email"]
        open_flags = [f for f in ctx.flags if f["person"] == email and f.get("status") in ("open", "ack")]
        rows.append({"email": email, "name": p["name"], "role": p.get("role", ""),
                     "response_hrs": round(float(cur.get(email) or 0.0), 2),
                     "unanswered": int(un.get(email, 0)),
                     "baseline_dev": round(float((ctx.base.get(email) or {}).get("z") or 0.0), 2),
                     "open_flags": len(open_flags),
                     "top_level": max((f["level"] for f in open_flags), default=0)})
    return rows
