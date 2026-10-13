"""Per-person rolling robust baselines (median + MAD over 28 days) and robust z-scores.

"Lately vs norm": the recent value is the median of the last `recent_days` working days;
the baseline is the 28 days before that. A baseline with fewer than MIN_SAMPLES days is
reported but never used to raise a flag (`usable: False`).
"""

import datetime as dt
from collections import defaultdict

from admin_console.analytics import util

WINDOW_DAYS = 28
MIN_SAMPLES = 8
RECENT_DAYS = 2
MAD_SCALE = 1.4826  # makes MAD comparable to a standard deviation for normal data

# metric -> (source, kind, meta field, daily aggregate)
METRICS = {
    "response_hrs": ("gmail", "response", "hours", "median"),
    "unanswered": ("gmail", "unanswered", None, "count"),
}


def robust_stats(values):
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None, None, 0
    med = util.median(vals)
    mad = util.median([abs(v - med) for v in vals])
    return med, mad, len(vals)


def robust_z(x, med, mad):
    """Robust z = (x - median) / (1.4826 * MAD), with a floor so a flat history does not
    turn a tiny change into an infinite score."""
    if x is None or med is None:
        return 0.0
    scale = MAD_SCALE * (mad or 0.0)
    scale = max(scale, 0.05 * abs(med), 0.1)
    return round((x - med) / scale, 2)


def daily_series(events, metric):
    source, kind, field, agg = METRICS[metric]
    buckets = defaultdict(lambda: defaultdict(list))
    for e in events:
        if e["source"] == source and e["kind"] == kind:
            buckets[e["person"]][util.central_day(e["ts"])].append(
                e["meta"].get(field) if field else 1)
    out = {}
    for person, days in buckets.items():
        out[person] = {d: (util.median(v) if agg == "median" else float(len(v)))
                       for d, v in days.items()}
    return out


def compute(events, now=None, metric="response_hrs", window_days=WINDOW_DAYS,
            recent_days=RECENT_DAYS, min_samples=MIN_SAMPLES):
    """{person: {metric, median, mad, n, latest, z, usable, recent_days:[...]}}"""
    today = util.central(now).date()
    series = daily_series(events, metric)
    out = {}
    for person, days in series.items():
        ordered = sorted(d for d in days if dt.date.fromisoformat(d) <= today)
        recent = ordered[-recent_days:]
        history = [d for d in ordered[:-recent_days]
                   if (today - dt.date.fromisoformat(d)).days <= window_days + recent_days + 4]
        history = history[-window_days:]
        med, mad, n = robust_stats([days[d] for d in history])
        latest = util.median([days[d] for d in recent]) if recent else None
        out[person] = {"metric": metric, "median": med, "mad": mad, "n": n, "latest": latest,
                       "z": robust_z(latest, med, mad), "usable": n >= min_samples,
                       "recent_days": recent}
    return out


def save(results, now=None):
    from admin_console.analytics import store
    stamp = util.iso(now)
    for person, r in results.items():
        store.upsert("Baselines", {
            "id": f"{person}|{r['metric']}", "person": person, "metric": r["metric"],
            "median": r["median"], "mad": r["mad"], "n": r["n"], "latest": r["latest"],
            "z": r["z"], "window_days": WINDOW_DAYS, "updated": stamp})
