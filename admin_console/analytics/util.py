"""Small shared helpers: time zones, business hours, quotes, domain checks."""

import datetime as dt
import os
import re
from zoneinfo import ZoneInfo

from admin_console import config

UTC = dt.timezone.utc
CENTRAL = ZoneInfo(config.TIMEZONE or "America/Chicago")
QUOTE_MAX = 200

BUSINESS_START = 8   # 8 am Central
BUSINESS_END = 17    # 5 pm Central


def now_utc():
    return dt.datetime.now(UTC)


def as_utc(value):
    """Accept datetime / ISO string / None and return an aware UTC datetime."""
    if value is None:
        return now_utc()
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso(value):
    return as_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def central(value):
    return as_utc(value).astimezone(CENTRAL)


def central_day(value):
    return central(value).date().isoformat()


def business_hours_between(start, end):
    """Business hours (Mon-Fri, 8-17 Central) elapsed between two instants."""
    start, end = central(start), central(end)
    if end <= start:
        return 0.0
    total = 0.0
    day = start.date()
    while day <= end.date():
        if day.weekday() < 5:
            open_ = dt.datetime.combine(day, dt.time(BUSINESS_START), CENTRAL)
            close = dt.datetime.combine(day, dt.time(BUSINESS_END), CENTRAL)
            lo, hi = max(open_, start), min(close, end)
            if hi > lo:
                total += (hi - lo).total_seconds() / 3600.0
        day += dt.timedelta(days=1)
    return round(total, 2)


def add_business_hours(start, hours):
    """The instant `hours` business hours after `start`."""
    cur = central(start)
    left = float(hours)
    for _ in range(400):
        if cur.weekday() < 5:
            open_ = dt.datetime.combine(cur.date(), dt.time(BUSINESS_START), CENTRAL)
            close = dt.datetime.combine(cur.date(), dt.time(BUSINESS_END), CENTRAL)
            begin = max(cur, open_)
            if begin < close:
                avail = (close - begin).total_seconds() / 3600
                if avail >= left:
                    return (begin + dt.timedelta(hours=left)).astimezone(UTC)
                left -= avail
        cur = dt.datetime.combine(cur.date() + dt.timedelta(days=1), dt.time(0), CENTRAL)
    return cur.astimezone(UTC)


def in_quiet_hours(when):
    """Quiet hours are 9 pm - 6 am Central."""
    h = central(when).hour
    return h >= 21 or h < 6


def is_internal(email):
    return bool(email) and email.strip().lower().endswith("@" + config.DOMAIN.lower())


def all_internal(*emails):
    flat = [e for group in emails for e in (group if isinstance(group, (list, tuple, set)) else [group]) if e]
    return bool(flat) and all(is_internal(e) for e in flat)


def short_quote(text, limit=QUOTE_MAX):
    """Evidence quotes are capped at 200 chars; message bodies are never stored."""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def owner_emails():
    return tuple(e.lower() for e in config.OWNER_EMAILS)


def office_emails():
    raw = os.environ.get("NTXP_OFFICE_EMAILS", "office@" + config.DOMAIN)
    return tuple(e.strip().lower() for e in raw.split(",") if e.strip()) + owner_emails()


def display_name(email, roster=None):
    email = (email or "").lower()
    if email in config.OWNERS:
        return config.OWNERS[email]["name"]
    for p in roster or ():
        if p["email"].lower() == email:
            return p["name"]
    local = email.split("@")[0]
    return " ".join(part.capitalize() for part in re.split(r"[._-]", local) if part)


def median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    return float(vals[mid]) if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0
