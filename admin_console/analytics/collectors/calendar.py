"""Calendar adapter: meetings, declines, no-shows, PTO/travel and all-day site meetings.

No-show = accepted, but absent from the Meet attendance log (Admin Reports `meet`
activity). Without attendance data the meeting is `attendance: "unknown"` - never assumed.
"""

import re

from admin_console.analytics import demo, google, util
from admin_console.analytics.collectors import Unconfigured, event

OOO_WORDS = re.compile(r"\b(pto|vacation|out of office|ooo|sick|travel|flight|holiday)\b", re.I)
SITE_WORDS = re.compile(r"\b(site|walk|inspection|field|pour|punch)\b", re.I)


def status():
    if google.demo():
        return "ok"
    return "ok" if google.configured() else "unconfigured"


def meet_attendance(start, end, client=None):
    """{conference_id: set(participant emails)} from Admin Reports meet activity, or None."""
    try:
        svc = client or google.service("reports")
        seen, token = {}, None
        while True:
            resp = svc.activities().list(userKey="all", applicationName="meet",
                                         startTime=util.iso(start), endTime=util.iso(end),
                                         maxResults=1000, pageToken=token).execute()
            for item in resp.get("items", []):
                for ev in item.get("events", []):
                    params = {p["name"]: p.get("value") for p in ev.get("parameters", [])}
                    code = (params.get("meeting_code") or params.get("conference_id") or "").lower()
                    who = (params.get("identifier") or item.get("actor", {}).get("email") or "").lower()
                    if code and who:
                        seen.setdefault(code, set()).add(who)
            token = resp.get("nextPageToken")
            if not token:
                return seen
    except Exception:  # noqa: BLE001 - attendance is optional
        return None


def collect(people, start, end, client=None, reports_client=None):
    if google.demo() and client is None:
        return demo.events("calendar", people, start, end)
    if client is None and not google.configured():
        raise Unconfigured("calendar")
    attendance = meet_attendance(start, end, reports_client)
    out = []
    for user in people:
        svc = client(user) if callable(client) else (client or google.service("calendar", user=user))
        token = None
        while True:
            resp = svc.events().list(calendarId="primary", timeMin=util.iso(start),
                                     timeMax=util.iso(end), singleEvents=True, maxResults=250,
                                     pageToken=token).execute()
            for item in resp.get("items", []):
                out.extend(classify_event(user, item, attendance))
            token = resp.get("nextPageToken")
            if not token:
                break
    return out


def classify_event(user, item, attendance=None):
    """Pure function: one Calendar event -> analytics events for `user`."""
    user = user.lower()
    title = item.get("summary", "") or ""
    start = item.get("start", {})
    ts = start.get("dateTime") or (start.get("date", "") + "T06:00:00-05:00")
    all_day = "date" in start and "dateTime" not in start
    ref = item.get("id", "")
    if item.get("eventType") == "outOfOffice" or OOO_WORDS.search(title):
        kind = "travel" if re.search(r"travel|flight", title, re.I) else "pto"
        return [event(user, "calendar", "ooo", ts, ref, title=title, ooo_type=kind, all_day=all_day)]
    if all_day and SITE_WORDS.search(title):
        return [event(user, "calendar", "site_meeting", ts, ref, title=title, all_day=True)]
    attendees = item.get("attendees") or []
    me = next((a for a in attendees if a.get("email", "").lower() == user or a.get("self")), None)
    if not me:
        return []
    external = any(not util.is_internal(a.get("email", "")) for a in attendees if not a.get("resource"))
    rs = me.get("responseStatus")
    if rs == "declined":
        return [event(user, "calendar", "decline", ts, ref, title=title, external=external)]
    if rs != "accepted":
        return []
    code = ((item.get("conferenceData") or {}).get("conferenceId") or "").lower()
    if attendance is None or not code or code not in attendance:
        presence = "unknown"
    else:
        presence = "present" if user in attendance[code] else "absent"
    kind = "no_show" if presence == "absent" else "meeting"
    return [event(user, "calendar", kind, ts, ref, title=title, attendance=presence, external=external)]
