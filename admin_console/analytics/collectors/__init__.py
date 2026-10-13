"""Source adapters. Each returns normalized events:

    {"person": email, "source": str, "kind": str, "ts": ISO, "ref": str, "meta": {...}}

Every adapter has `status()` -> "ok" | "unconfigured" | "error" and
`collect(people, start, end, client=None)`. In demo mode they serve synthetic events;
without credentials they report "unconfigured" and return [] - never raise.
"""

import datetime as dt
import importlib
import logging

from admin_console import config
from admin_console.analytics import demo, google, util

log = logging.getLogger(__name__)

SOURCES = ("gmail", "calendar", "drive", "jobtread", "plaud", "quickbooks")


class Unconfigured(RuntimeError):
    """The source has no credentials in this environment."""


def module(source):
    return importlib.import_module(f"admin_console.analytics.collectors.{source}")


def roster():
    """People to analyse: Directory users when live, the synthetic roster in demo."""
    if google.demo() or not google.configured():
        if google.demo():
            return [dict(p) for p in demo.ROSTER]
        return [{"email": e, "name": i["name"], "role": i["title"]} for e, i in config.OWNERS.items()]
    try:
        svc = google.service("directory")
        users, token = [], None
        while True:
            resp = svc.users().list(domain=config.DOMAIN, maxResults=200, pageToken=token,
                                    query="isSuspended=false").execute()
            for u in resp.get("users", []):
                email = u["primaryEmail"].lower()
                role = (config.OWNERS.get(email) or {}).get("title") or \
                    ((u.get("organizations") or [{}])[0].get("title") or "")
                users.append({"email": email, "name": u.get("name", {}).get("fullName", email),
                              "role": role})
            token = resp.get("nextPageToken")
            if not token:
                return users
    except Exception as exc:  # noqa: BLE001 - degrade, never crash the cycle
        log.warning("directory roster failed: %s", exc)
        return [{"email": e, "name": i["name"], "role": i["title"]} for e, i in config.OWNERS.items()]


def collect_all(now=None, window_days=35, people=None, only=None):
    """Run every adapter. Returns (events, status_by_source, failures)."""
    end = util.as_utc(now)
    start = end - dt.timedelta(days=window_days)
    if google.demo():
        demo.set_anchor(end)
    people = people or [p["email"] for p in roster()]
    events, status, failures = [], {}, []
    for source in only or SOURCES:
        mod = module(source)
        try:
            got = mod.collect(people, start, end)
            status[source] = mod.status()
            events.extend(got)
        except Unconfigured:
            status[source] = "unconfigured"
        except Exception as exc:  # noqa: BLE001
            log.warning("collector %s failed: %s", source, exc)
            status[source] = "error"
            failures.append({"source": source, "error": util.short_quote(str(exc), 160)})
    events.sort(key=lambda e: e["ts"])
    return events, status, failures


def event(person, source, kind, ts, ref, **meta):
    return {"person": (person or "").lower(), "source": source, "kind": kind,
            "ts": util.iso(ts), "ref": str(ref), "meta": meta}
