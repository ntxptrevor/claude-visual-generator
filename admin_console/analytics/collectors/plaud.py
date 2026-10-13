"""Plaud adapter: recording metadata and mentions of a person (thin, mockable).

Env: PLAUD_API_KEY, PLAUD_API_URL (default https://api.plaud.ai). Only metadata is used -
title, start, duration, participants, people mentioned. Transcripts are not stored.

Events: long_call (duration_min >= 45), recording, mention.
"""

import json
import os
import urllib.parse
import urllib.request

from admin_console.analytics import demo, google, util
from admin_console.analytics.collectors import Unconfigured, event

LONG_CALL_MIN = 45


def status():
    if google.demo():
        return "ok"
    return "ok" if os.environ.get("PLAUD_API_KEY") else "unconfigured"


def fetch(start, end, timeout=30):
    key = os.environ.get("PLAUD_API_KEY")
    if not key:
        raise Unconfigured("plaud")
    base = os.environ.get("PLAUD_API_URL", "https://api.plaud.ai").rstrip("/")
    qs = urllib.parse.urlencode({"start": util.iso(start), "end": util.iso(end)})
    req = urllib.request.Request(f"{base}/v1/files?{qs}",
                                 headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    return data.get("files") or data.get("data") or data.get("items") or []


def collect(people, start, end, client=None):
    if google.demo() and client is None:
        return demo.events("plaud", people, start, end)
    if client is None and not os.environ.get("PLAUD_API_KEY"):
        raise Unconfigured("plaud")
    files = (client or fetch)(start, end)
    wanted = {p.lower() for p in people}
    out = []
    for f in files:
        owner = (f.get("owner_email") or f.get("owner") or "").lower()
        minutes = round(float(f.get("duration_sec") or f.get("duration") or 0) / 60.0, 1)
        mentions = [m.lower() for m in (f.get("mentions") or f.get("participants") or []) if "@" in m]
        ts = f.get("start_time") or f.get("created_at")
        base = dict(title=util.short_quote(f.get("title", ""), 120), duration_min=minutes,
                    mentions=mentions)
        if owner in wanted:
            kind = "long_call" if minutes >= LONG_CALL_MIN else "recording"
            out.append(event(owner, "plaud", kind, ts, f.get("id", ""), **base))
        for m in mentions:
            if m in wanted and m != owner:
                out.append(event(m, "plaud", "mention", ts, f.get("id", ""), **base))
    return out
