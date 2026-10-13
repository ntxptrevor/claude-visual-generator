"""Public interface for the API server (see admin_console/API.md):

    get_summary() -> dict
    get_report(report_id) -> dict
    list_flags(status="open", level=None) -> list[dict]
    act_on_flag(flag_id, action, note, actor) -> dict
    run_cycle(now=None) -> dict
    subscribe() -> Iterator[dict]

run_cycle: collect -> baselines -> classify -> crosscheck -> council (L2+ confirmed) ->
escalate -> reports -> learning. Flags are proposals for owner review; nothing here takes
disciplinary action.
"""

import json
import logging
import threading
import time

from admin_console import config, jev
from admin_console.analytics import (baselines, classify, collectors, council, crosscheck,
                                     escalation, google, learning, reports, store, util)

log = logging.getLogger(__name__)

FLAG_KEYS = ("id", "person", "kpi", "level", "urgency", "channel", "severity", "confidence",
             "volatility", "summary", "evidence", "crosscheck", "council", "created", "status",
             "escalations")
AGGREGATED = {"responsiveness_anomaly", "unanswered_email", "daily_report_quality"}
ACTIONS = {"ack": "ack", "dismiss": "dismissed", "resolve": "resolved", "escalate": "open"}
SUMMARY_ID = "_summary"

_CYCLE_LOCK = threading.Lock()


# --------------------------------------------------------------------------- helpers

def _public(row):
    f = {k: row.get(k) for k in FLAG_KEYS}
    f["level"] = int(f["level"] or 1)
    f["confidence"] = float(f["confidence"] or 0.0)
    f["volatility"] = None if f["volatility"] in (None, "") else float(f["volatility"])
    f["evidence"] = list(f["evidence"] or [])
    f["crosscheck"] = f["crosscheck"] or {"status": "pending", "sources_checked": [], "explanations": []}
    f["escalations"] = list(f["escalations"] or [])
    return f


def _combine(stamps):
    stamps = [s for s in stamps if s]
    if not stamps:
        return jev.stamp(jev.route("kpi_compute"))
    top = max(stamps, key=lambda s: s["tier"])
    return {"tier": top["tier"], "executor": top["executor"],
            "cost": round(sum(s.get("cost", 0.0) for s in stamps if s["tier"] > 0), 4)}


def _save_flag(flag, now):
    row = {k: flag.get(k) for k in store.SCHEMA["Flags"]}
    row["updated"] = util.iso(now)
    store.upsert("Flags", row)


def _match(existing, cand):
    for f in existing:
        if f.get("key") == cand["key"]:
            return f
    if cand["kpi"] in AGGREGATED:
        for f in existing:
            if f["kpi"] == cand["kpi"] and f["person"] == cand["person"] and f.get("status") in ("open", "ack"):
                return f
    return None


def _new_flag(cand, now):
    fid = store.next_id("Flags", "FL-" + util.central_day(now))
    flag = {k: cand.get(k) for k in ("key", "person", "kpi", "level", "urgency", "channel",
                                     "severity", "confidence", "volatility", "summary",
                                     "evidence", "floor_level")}
    flag.update({"id": fid, "created": util.iso(now), "status": "open", "escalations": [],
                 "council": None, "deferred": False, "ts": cand["ts"], "sources": cand.get("sources"),
                 "crosscheck": {"status": "pending", "sources_checked": [], "explanations": []}})
    return flag


def _empty_summary(now=None):
    ctx = reports.Ctx([], [], now, collectors.roster())
    return {"updated": util.iso(now), "tiles": reports.tiles(ctx), "people": reports.people_rows(ctx)}


# --------------------------------------------------------------------------- run_cycle

def run_cycle(now=None):
    """One full collect -> score -> flag -> escalate pass. Returns
    {flags_created, flags_escalated, jev}."""
    with _CYCLE_LOCK:
        now = util.as_utc(now)
        store.ensure_schema()
        th = classify.thresholds()
        roster = collectors.roster()
        stamps = [jev.stamp(jev.route("gmail_fetch")), jev.stamp(jev.route("drive_fetch"))]

        events, status, failures = collectors.collect_all(now, people=[p["email"] for p in roster])
        for fail in failures:
            store.log_change("analytics", "collectors", "failure", fail["source"], fail["error"])

        base = baselines.compute(events, now)
        baselines.save(base, now)

        candidates, cstamps = classify.classify(events, now, base, th, roster)
        stamps += cstamps

        existing = store.rows("Flags")
        created, updated = [], []
        for cand in candidates:
            match = _match(existing, cand)
            if match:
                if match.get("status") in ("resolved", "dismissed"):
                    continue  # the owners closed it; do not reopen the same item
                match["evidence"] = cand["evidence"]
                match["summary"] = cand["summary"]
                match["confidence"] = max(float(match.get("confidence") or 0), cand["confidence"])
                if cand["level"] > int(match["level"]) and (match.get("crosscheck") or {}).get("status") != "explained":
                    match["level"], match["urgency"], match["severity"] = cand["level"], cand["urgency"], cand["severity"]
                updated.append(match)
                continue
            flag = _new_flag(cand, now)
            crosscheck.crosscheck(flag, events, now, th=th)
            stamps.append(flag.pop("_jev", None))
            if flag["level"] >= 2 and flag["crosscheck"]["status"] == "confirmed":
                stamps.append(jev.stamp(jev.route("council_conclusion")) if council.status() == "ok" else None)
                flag["council"] = council.conclude(flag)
            store.append("Classifications", {
                "id": store.next_id("Classifications", "CF-" + util.central_day(now)),
                "flag_id": flag["id"], "at": util.iso(now), "kpi": flag["kpi"], "rule": cand["rule"],
                "urgency": flag["urgency"], "severity": flag["severity"], "level": flag["level"],
                "confidence": flag["confidence"], "volatility": flag["volatility"]})
            _save_flag(flag, now)
            existing.append(flag)
            created.append(flag)

        open_flags = [f for f in existing if f.get("status") == "open"]
        escalated = escalation.escalate_all(open_flags, now, th)
        for f in open_flags + updated:
            f.pop("_jev", None)
            _save_flag(f, now)
        stamps.append(jev.stamp(jev.route("notify_owner")) if escalated else None)

        all_flags = [_public(f) for f in store.rows("Flags")]
        built, ctx = reports.build_all(events, all_flags, now, roster)
        for rid, rep in built.items():
            store.upsert("Reports", {"id": rid, "report_id": rid, "title": rep["title"],
                                     "generated": rep["generated"], "period_from": rep["period"]["from"],
                                     "period_to": rep["period"]["to"], "sources": rep["sources"],
                                     "body": rep, "jev": rep["jev"]})
        summary = {"updated": util.iso(now), "tiles": reports.tiles(ctx),
                   "people": reports.people_rows(ctx), "sources": status}
        store.upsert("Reports", {"id": SUMMARY_ID, "report_id": SUMMARY_ID, "title": "Summary",
                                 "generated": util.iso(now), "body": summary,
                                 "jev": jev.stamp(jev.route("kpi_compute"))})

        learning.run(now)
        return {"flags_created": len(created), "flags_escalated": escalated, "jev": _combine(stamps)}


# --------------------------------------------------------------------------- reads

def _stored(row_id):
    row = store.get("Reports", row_id)
    body = (row or {}).get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = None
    return body


def get_summary():
    """{updated, tiles:[Tile], people:[PersonRow]} from the latest cycle."""
    store.ensure_schema()
    body = _stored(SUMMARY_ID)
    if body is None and google.demo():
        run_cycle()
        body = _stored(SUMMARY_ID)
    if body is None:
        return _empty_summary()
    return {"updated": body["updated"], "tiles": body["tiles"], "people": body["people"]}


def get_report(report_id):
    if report_id not in reports.REPORTS:
        raise KeyError(f"unknown report_id {report_id!r}")
    store.ensure_schema()
    body = _stored(report_id)
    if body is None and google.demo():
        run_cycle()
        body = _stored(report_id)
    if body is None:
        built, _ = reports.build_all([], [], None, collectors.roster())
        body = built[report_id]
    return body


def list_flags(status="open", level=None):
    """status: 'open' (open + acknowledged), 'all', or an exact status."""
    store.ensure_schema()
    rows = [_public(r) for r in store.rows("Flags")]
    if status == "open":
        rows = [r for r in rows if r["status"] in ("open", "ack")]
    elif status and status != "all":
        rows = [r for r in rows if r["status"] == status]
    if level not in (None, ""):
        rows = [r for r in rows if r["level"] == int(level)]
    rows.sort(key=lambda r: r["created"] or "", reverse=True)
    rows.sort(key=lambda r: -r["level"])
    return rows


def act_on_flag(flag_id, action, note, actor):
    """Record an owner action on a flag. Only owners may act. Returns the Flag."""
    if not config.is_owner(actor):
        raise PermissionError("only the owners may act on flags")
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {sorted(ACTIONS)}")
    with _CYCLE_LOCK:
        row = store.get("Flags", flag_id)
        if row is None:
            raise KeyError(f"unknown flag {flag_id!r}")
        now = util.now_utc()
        before = row.get("status")
        row["status"] = ACTIONS[action]
        if action == "escalate":
            row["level"] = min(3, int(row["level"]) + 1)
            if row["level"] == 3 and row["urgency"] in ("low", "medium"):
                row["urgency"] = "high"
        store.append("Interactions", {
            "id": store.next_id("Interactions", "IX-" + util.central_day(now)), "at": util.iso(now),
            "actor": actor.lower(), "kind": "flag_action", "request_type": f"flag_{action}",
            "flag_id": flag_id, "action": action, "kpi": row["kpi"], "level": row["level"],
            "note": util.short_quote(note)})
        if action == "escalate":
            escalation.escalate_all([row], now, owner_requested=True)
        _save_flag(row, now)
        store.log_change(actor.lower(), "Flags", action, flag_id,
                         f"{before} -> {row['status']} (L{row['level']}) {note or ''}")
        return _public(row)


def subscribe(poll_seconds=5.0, max_events=None):
    """Yield Tile dicts whenever a value changes (polls the store)."""
    last, sent = {}, 0
    while True:
        try:
            tiles = get_summary()["tiles"]
        except Exception as exc:  # noqa: BLE001 - keep the stream alive
            log.warning("subscribe poll failed: %s", exc)
            tiles = []
        for t in tiles:
            sig = json.dumps(t, sort_keys=True)
            if last.get(t["id"]) != sig:
                last[t["id"]] = sig
                yield t
                sent += 1
                if max_events and sent >= max_events:
                    return
        time.sleep(poll_seconds)


__all__ = ["get_summary", "get_report", "list_flags", "act_on_flag", "run_cycle", "subscribe"]
