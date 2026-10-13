"""The improvement loop.

1. Precision per KPI from owner actions in Interactions:
     ack / resolve -> true positive, dismiss -> false positive, escalate -> under-scored.
   With enough new actions since the last change, the KPI's threshold is nudged one step
   within classify.BOUNDS (less sensitive when precision < 0.5, more sensitive when the
   owners keep escalating). Each change is written to Learning with before/after.
2. Tracks the kinds of requests the owners make (Interactions.request_type).
3. Recurring blockers: the same failure or stuck condition >= 3 times -> a proposed
   prevention flow (Learning) and a draft Runbook entry with status "proposed". Nothing
   here is auto-applied to a workflow; the owners approve runbook entries.
"""

import datetime as dt
import json
from collections import Counter, defaultdict

from admin_console.analytics import classify, store, util

MIN_ACTIONS = 5
LOW_PRECISION = 0.5
UNDER_SHARE = 0.3
BLOCKER_REPEAT = 3

TP, FP, UNDER = {"ack", "resolve"}, {"dismiss"}, {"escalate"}

PREVENTION = {
    "unanswered_email": ("Gmail", "Shared-inbox coverage: a Gmail filter forwards external client "
                         "threads unanswered after 24 h to office@, and a field-day auto-reply names a backup."),
    "wait_complaints": ("Gmail", "Gmail filter: external mail containing wait / no-show phrases is "
                        "forwarded to office@ on arrival, so the 4-business-hour window cannot be missed."),
    "open_billing_questions": ("Billing", "Route billing keywords to the AP queue with a 4-hour "
                               "acknowledgment template and a next-day owner digest."),
    "daily_report_quality": ("JobTread daily logs", "JobTread daily-log template with required photo, "
                             "crew count, work completed and tomorrow's plan fields."),
    "po_invoice_integrity": ("JobTread documents", "Make vendor, cost code, job and PO reference "
                             "required on PO and vendor-bill templates; reject totals that do not sum."),
    "no_shows": ("Calendar", "30-minute reminder plus decline-with-note for external meetings; "
                 "office confirms attendance for owner/agency meetings."),
    "project_folder_access": ("Drive", "Weekly project-folder digest to assigned people with the "
                              "latest RFIs, submittals and drawings linked."),
    "responsiveness_anomaly": ("Workload", "Check workload and field schedule; set email coverage on "
                               "full site days."),
    "internal_volatility": ("People", "Owner check-in conversation. Never automated discipline."),
}


# --------------------------------------------------------------------------- requests

def record_request(actor, request_type, note="", now=None):
    """Log an owner request (search, report view, run, flag action...)."""
    return store.append("Interactions", {
        "id": store.next_id("Interactions", "IX-" + util.central_day(now)), "at": util.iso(now),
        "actor": actor, "kind": "request", "request_type": request_type, "note": util.short_quote(note)})


def request_types(now=None, days=30):
    now = util.as_utc(now)
    since = now - dt.timedelta(days=days)
    rows = store.query("Interactions", lambda r: r.get("kind") in ("request", "flag_action")
                       and r.get("at") and util.as_utc(r["at"]) >= since)
    counts = Counter(r.get("request_type") or "unknown" for r in rows)
    if counts:
        store.upsert("Learning", {"id": f"requests|{util.central_day(now)}", "at": util.iso(now),
                                  "kind": "request_types", "n": sum(counts.values()),
                                  "status": "observed", "note": json.dumps(dict(counts.most_common()))})
    return dict(counts)


# --------------------------------------------------------------------------- precision

def _last_change(param):
    rows = store.query("Learning", lambda r: r.get("kind") == "threshold" and r.get("param") == param,
                       order_by="at")
    return rows[-1]["at"] if rows else None


def precision_by_kpi(since_by_kpi=None):
    acts = store.query("Interactions", {"kind": "flag_action"})
    stats = defaultdict(lambda: {"tp": 0, "fp": 0, "under": 0})
    for a in acts:
        kpi = a.get("kpi")
        since = (since_by_kpi or {}).get(kpi)
        if not kpi or (since and a.get("at") and util.as_utc(a["at"]) <= util.as_utc(since)):
            continue
        act = a.get("action")
        if act in TP:
            stats[kpi]["tp"] += 1
        elif act in FP:
            stats[kpi]["fp"] += 1
        elif act in UNDER:
            stats[kpi]["under"] += 1
    out = {}
    for kpi, s in stats.items():
        n = s["tp"] + s["fp"] + s["under"]
        pos = s["tp"] + s["under"]
        out[kpi] = dict(s, n=n, precision=round(pos / n, 2) if n else None)
    return out


def tune(now=None):
    """Nudge thresholds within safe bounds. Returns the list of changes made."""
    now = util.as_utc(now)
    current = classify.thresholds()
    since = {kpi: _last_change(param) for kpi, param in classify.KPI_PARAM.items()}
    changes = []
    for kpi, s in precision_by_kpi(since).items():
        param = classify.KPI_PARAM.get(kpi)
        if not param or param not in classify.BOUNDS or s["n"] < MIN_ACTIONS:
            continue
        lo, hi, step, direction = classify.BOUNDS[param]
        before = current[param]
        if s["precision"] is not None and s["precision"] < LOW_PRECISION:
            after, why = before + direction * step, f"precision {s['precision']:.2f} < {LOW_PRECISION}: less sensitive"
        elif s["under"] / s["n"] >= UNDER_SHARE:
            after, why = before - direction * step, f"owners escalated {s['under']}/{s['n']}: more sensitive"
        else:
            continue
        after = round(max(lo, min(hi, after)), 3)
        if after == before:
            continue
        row = {"id": store.next_id("Learning", "LR-" + util.central_day(now)), "at": util.iso(now),
               "kind": "threshold", "kpi": kpi, "param": param, "before": before, "after": after,
               "precision": s["precision"], "n": s["n"], "status": "applied", "note": why}
        store.append("Learning", row)
        store.log_change("analytics.learning", "Learning", "threshold", param, f"{before} -> {after}: {why}")
        current[param] = after
        changes.append(row)
    return changes


# --------------------------------------------------------------------------- blockers

def _signatures(now, days=30):
    since = util.as_utc(now) - dt.timedelta(days=days)
    sig = Counter()
    detail = {}
    for r in store.query("ChangeLog", {"action": "failure"}):
        if r.get("at") and util.as_utc(r["at"]) >= since:
            sig[("failure", r.get("ref"))] += 1
            detail[("failure", r.get("ref"))] = r.get("summary", "")
    for f in store.rows("Flags"):
        if f.get("created") and util.as_utc(f["created"]) >= since:
            key = ("stuck", f"{f['kpi']}|{f['person']}")
            sig[key] += 1
            detail[key] = f.get("summary", "")
    return sig, detail


def blockers(now=None):
    """Propose prevention flows + draft Runbook entries for recurring conditions."""
    now = util.as_utc(now)
    sig, detail = _signatures(now)
    have = {r.get("param") for r in store.query("Learning", {"kind": "blocker"})}
    proposals = []
    for (kind, ref), count in sig.items():
        if count < BLOCKER_REPEAT or ref in have:
            continue
        if kind == "failure":
            workflow = f"Analytics collector: {ref}"
            symptom = f"Collector '{ref}' failed {count} times in 30 days: {detail[(kind, ref)]}"
            cause = "Expired or missing credentials, revoked DWD scope, or upstream API change."
            steps = [f"Open /api/health and confirm the '{ref}' source state.",
                     "Re-check the API key / DWD scopes in the NTXP vault and environment.",
                     "Run one analysis cycle (POST /api/analytics/run) and confirm the source is 'ok'.",
                     "If it still fails, capture the error text from ChangeLog and escalate."]
            flow = "Daily health check alerts the owners on the first failure instead of the third."
            escalate_to, tier = "trevor@ntxpllc.com", 2
        else:
            kpi, person = ref.split("|", 1)
            area, flow = PREVENTION.get(kpi, ("Operations", "Review the process with the owners."))
            workflow = f"{area}: recurring {kpi}"
            symptom = (f"{kpi} flagged {count} times in 30 days for {util.display_name(person)} "
                       f"(latest: {util.short_quote(detail[(kind, ref)], 120)})")
            cause = "Process gap - the same condition keeps recurring; a guardrail may prevent it."
            steps = ["Owner reviews the flag history and evidence in Employee Analytics.",
                     f"Proposed prevention flow: {flow}",
                     "Approve, edit or reject this runbook entry; nothing is applied automatically."]
            escalate_to, tier = "alison@ntxpllc.com", 2
        rb = {"id": store.next_id("Runbook", "RB-" + util.central_day(now)), "workflow": workflow,
              "symptom": util.short_quote(symptom), "likely_cause": cause, "steps": steps,
              "escalate_to": escalate_to, "tier": tier, "updated": util.iso(now), "status": "proposed"}
        store.append("Runbook", rb)
        store.append("Learning", {"id": store.next_id("Learning", "LR-" + util.central_day(now)),
                                  "at": util.iso(now), "kind": "blocker", "kpi": ref.split("|")[0],
                                  "param": ref, "n": count, "status": "proposed",
                                  "note": util.short_quote(f"Prevention flow: {flow} (runbook {rb['id']})")})
        proposals.append(rb)
    return proposals


def run(now=None):
    return {"threshold_changes": tune(now), "request_types": request_types(now),
            "blockers": blockers(now)}
