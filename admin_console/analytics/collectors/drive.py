"""Drive adapter: did each person open their project folders? (Admin Reports `drive`).

People -> projects come from `NTXP_PROJECT_ASSIGNMENTS` (JSON text or a path) or the IPDM
org file `NTXP_IPDM_ORG_FILE`. Accepted shapes:
  {"person@ntxpllc.com": [{"project": "Name", "folder_id": "abc"}, "Other Project"]}
  {"assignments": {...same...}}
Absent or unreadable -> no assignments, status "unconfigured" (never an error).
"""

import json
import os

from admin_console.analytics import demo, google, util
from admin_console.analytics.collectors import Unconfigured, event

STALE_DAYS = 7


def assignments():
    for env in ("NTXP_PROJECT_ASSIGNMENTS", "NTXP_IPDM_ORG_FILE"):
        raw = os.environ.get(env, "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw) if raw.startswith("{") else json.load(open(raw))
        except (OSError, json.JSONDecodeError):
            continue
        data = data.get("assignments", data)
        out = {}
        for person, items in data.items():
            if "@" not in person:
                continue
            norm = []
            for it in items or []:
                if isinstance(it, str):
                    norm.append({"project": it, "folder_id": ""})
                elif isinstance(it, dict) and it.get("project"):
                    norm.append({"project": it["project"], "folder_id": it.get("folder_id", "")})
            out[person.lower()] = norm
        return out
    return {}


def status():
    if google.demo():
        return "ok"
    return "ok" if google.configured() and assignments() else "unconfigured"


def collect(people, start, end, client=None, assigned=None):
    if google.demo() and client is None:
        return demo.events("drive", people, start, end)
    assigned = assigned if assigned is not None else assignments()
    if client is None and not google.configured():
        raise Unconfigured("drive")
    if not assigned:
        return []
    svc = client or google.service("reports")
    out = []
    end = util.as_utc(end)
    for user in people:
        projects = assigned.get(user.lower()) or []
        if not projects:
            continue
        last_open = {}
        token = None
        while True:
            resp = svc.activities().list(userKey=user, applicationName="drive",
                                         startTime=util.iso(start), endTime=util.iso(end),
                                         maxResults=1000, pageToken=token).execute()
            for item in resp.get("items", []):
                ts = item.get("id", {}).get("time")
                for ev in item.get("events", []):
                    params = {p["name"]: p.get("value") or p.get("multiValue")
                              for p in ev.get("parameters", [])}
                    doc_id = params.get("doc_id", "")
                    title = (params.get("doc_title") or "").lower()
                    for p in projects:
                        if (p["folder_id"] and p["folder_id"] == doc_id) or \
                                p["project"].lower() in title:
                            out.append(event(user, "drive", "folder_open", ts, doc_id or p["project"],
                                             project=p["project"]))
                            if ts and ts > last_open.get(p["project"], ""):
                                last_open[p["project"]] = ts
            token = resp.get("nextPageToken")
            if not token:
                break
        for p in projects:
            seen = last_open.get(p["project"])
            days = (end - util.as_utc(seen)).days if seen else (end - util.as_utc(start)).days
            if days >= STALE_DAYS:
                out.append(event(user, "drive", "folder_stale", end, p["folder_id"] or p["project"],
                                 project=p["project"], days_since=days))
    return out
