"""Guided org-wide semantic search over Gmail (and Drive)."""

import calendar
import json
import logging
import math
import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import getaddresses, parsedate_to_datetime

import httpx

from admin_console import config, jev

from . import demo, gws

log = logging.getLogger("ntxp.search")

HAIKU = "claude-haiku-4-5-20251001"
MAX_WORKERS = 8
PER_MAILBOX = 25
MAX_MAILBOXES = 200

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})

TREND_WORDS = ("trend", "how often", "pattern", "over time", "frequency", "how many times", "keeps", "always")
PROJECT_WORDS = ("project", "job", "jobsite", "job site")
ATTACH_WORDS = ("attachment", "attached", "attachments", "pdf", "invoice copy", "drawing set")

STOPWORDS = set("""a an the and or of for to from in on at by with about any all me my mine our we i you
emails email mail message messages thread threads find show search look looking get see what which who
when where why how is are was were be been that this these those it its did do does has have had
since last past this month months week weeks day days year years today yesterday between before after
during ago please need want everything anything something regarding re fw fwd sent received tell list
project projects job jobs trend trends pattern patterns often over time frequency many times keeps
attachment attachments attached pdf mailbox mailboxes inbox""".split())

Q_MAILBOXES, Q_WINDOW, Q_SHAPE, Q_ATTACH, Q_AUDIENCE = "mailboxes", "window", "shape", "attachments", "audience"
ALL_MAILBOXES, MY_MAILBOX = "All NTXP mailboxes", "Only my mailbox"
WINDOWS = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90, "Last 12 months": 365, "Any time": None}
SHAPES = {"A specific message or thread": "message", "A pattern over time": "trend",
          "Everything about one project": "project", "Everything involving a person": "person"}
ATTACH_ONLY, ATTACH_ANY = "Only messages with attachments", "Include messages without attachments"
AUDIENCES = {"Clients and outside parties": "external", "Internal NTXP only": "internal", "Both": "both"}


def today():
    return datetime.now(timezone.utc).date()


# ---------- Tier 0 parsing ----------

def empty_draft():
    return {"people": [], "users": [], "from": "", "to": "", "date_from": "", "date_to": "",
            "keywords": [], "project": "", "has_attachment": False, "labels": []}


def _month_start(y, m):
    return date(y, m, 1)


def _month_end(y, m):
    return date(y, m, calendar.monthrange(y, m)[1])


def _shift_month(y, m, delta):
    idx = y * 12 + (m - 1) + delta
    return idx // 12, idx % 12 + 1


def _past_month(m, now):
    return now.year if m <= now.month else now.year - 1


def _parse_one_date(token, now):
    token = token.strip().rstrip(".,")
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", token)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", token)
    if m:
        y = int(m[3]) if m[3] else now.year
        y = y + 2000 if y < 100 else y
        return date(y, int(m[1]), int(m[2]))
    m = re.fullmatch(r"([a-z]+)\.?(?:\s+(\d{1,2})(?:st|nd|rd|th)?)?(?:,?\s+(\d{4}))?", token.lower())
    if m and m[1] in MONTHS:
        mon = MONTHS[m[1]]
        y = int(m[3]) if m[3] else _past_month(mon, now)
        return date(y, mon, int(m[2]) if m[2] else 1)
    return None


DATE_TOKEN = r"(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?|[A-Za-z]{3,9}\.?(?:\s+\d{1,2}(?:st|nd|rd|th)?)?(?:,?\s+\d{4})?)"


def parse_dates(text, now=None):
    """Return (date_from, date_to, matched_spans) for relative and absolute date phrases."""
    now = now or today()
    t = text.lower()
    spans = []

    def hit(m):
        spans.append(m.span())

    m = re.search(r"\bbetween\s+" + DATE_TOKEN + r"\s+and\s+" + DATE_TOKEN, t)
    if m:
        a, b = _parse_one_date(m[1], now), _parse_one_date(m[2], now)
        if a and b:
            hit(m)
            return a, b, spans

    m = re.search(r"\b(?:last|past|previous)\s+(\d+)\s+(day|week|month|year)s?\b", t)
    if m:
        n, unit = int(m[1]), m[2]
        days = {"day": 1, "week": 7, "month": 30, "year": 365}[unit] * n
        hit(m)
        return now - timedelta(days=days), now, spans
    m = re.search(r"\b(\d+)\s+(day|week|month)s?\s+ago\b", t)
    if m:
        days = {"day": 1, "week": 7, "month": 30}[m[2]] * int(m[1])
        hit(m)
        return now - timedelta(days=days), now, spans

    fixed = [
        (r"\btoday\b", lambda: (now, now)),
        (r"\byesterday\b", lambda: (now - timedelta(days=1), now - timedelta(days=1))),
        (r"\bthis week\b", lambda: (now - timedelta(days=now.weekday()), now)),
        (r"\blast week\b", lambda: (now - timedelta(days=now.weekday() + 7), now - timedelta(days=now.weekday() + 1))),
        (r"\bthis month\b", lambda: (_month_start(now.year, now.month), now)),
        (r"\blast month\b", lambda: (_month_start(*_shift_month(now.year, now.month, -1)),
                                      _month_end(*_shift_month(now.year, now.month, -1)))),
        (r"\bthis year\b", lambda: (date(now.year, 1, 1), now)),
        (r"\blast year\b", lambda: (date(now.year - 1, 1, 1), date(now.year - 1, 12, 31))),
    ]
    for pat, fn in fixed:
        m = re.search(pat, t)
        if m:
            hit(m)
            a, b = fn()
            return a, b, spans

    date_from = date_to = None
    for m in re.finditer(r"\b(?:since|after|from)\s+" + DATE_TOKEN, t):
        if _parse_one_date(m[1], now):
            date_from = _parse_one_date(m[1], now)
            hit(m)
            break
    for m in re.finditer(r"\b(?:before|until|through)\s+" + DATE_TOKEN, t):
        if _parse_one_date(m[1], now):
            date_to = _parse_one_date(m[1], now)
            hit(m)
            break
    if date_from or date_to:
        return date_from, date_to, spans

    m = re.search(r"\b(?:in|during)\s+([a-z]{3,9})(?:\s+(\d{4}))?\b", t)
    if m and m[1] in MONTHS:
        mon = MONTHS[m[1]]
        y = int(m[2]) if m[2] else _past_month(mon, now)
        hit(m)
        return _month_start(y, mon), _month_end(y, mon), spans
    return None, None, spans


def match_people(text, directory):
    """Directory people named in text: [(email, matched_text, role)] where role is from|to|any."""
    found = []
    lowered = text.lower()
    firsts = Counter(p["name"].split()[0].lower() for p in directory if p.get("name"))
    lasts = Counter(p["name"].split()[-1].lower() for p in directory if p.get("name"))
    for p in directory:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        first, last = name.split()[0].lower(), name.split()[-1].lower()
        candidates = [name.lower(), p["email"].lower()]
        if firsts[first] == 1 and first not in STOPWORDS:
            candidates.append(first)
        if lasts[last] == 1 and last not in STOPWORDS and last != first:
            candidates.append(last)
        for cand in candidates:
            m = re.search(r"(?:\b(from|to|by|with|cc)\s+)?\b" + re.escape(cand) + r"(?:'s)?\b", lowered)
            if m:
                role = {"from": "from", "by": "from", "to": "to", "cc": "to"}.get(m[1] or "", "any")
                found.append((p["email"], m.group(0), role))
                break
    for m in re.finditer(r"(?:\b(from|to)\s+)?([\w.+-]+@[\w-]+(?:\.[\w-]+)+)", text):
        email = m[2].lower()
        if not any(f[0] == email for f in found):
            found.append((email, m.group(0), {"from": "from", "to": "to"}.get((m[1] or "").lower(), "any")))
    return found


GENERIC_PROJECT_WORDS = {"school", "high", "elementary", "middle", "renovation", "building", "addition",
                         "phase", "station", "center", "county", "city"}


def distinctive_words(project):
    return [w for w in re.findall(r"[a-z0-9]+", project.lower())
            if w not in STOPWORDS and len(w) > 3 and w not in GENERIC_PROJECT_WORDS]


def project_terms(project):
    words = distinctive_words(project)
    return [project] + words[:1] if words and words[0] != project.lower() else [project]


def match_project(text, projects):
    lowered = text.lower()
    for proj in projects:
        if proj.lower() in lowered:
            return proj, proj.lower()
    for proj in projects:
        for w in distinctive_words(proj)[:2]:
            if re.search(r"\b" + re.escape(w) + r"\b", lowered):
                return proj, w
    m = re.search(r"\b(?:project|job)\s+(?:called\s+|named\s+)?\"?([A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*)*)", text)
    if m:
        return m[1], m[1].lower()
    return "", ""


def known_projects():
    env = os.environ.get("NTXP_PROJECT_NAMES", "")
    if env:
        return [p.strip() for p in env.split("|") if p.strip()]
    return demo.PROJECTS if config.DEMO or not gws.google_configured() else []


def parse_text(text, directory, projects, now=None):
    """Tier 0 rule-based parse into (intent, draft)."""
    draft = empty_draft()
    work = text
    quoted = re.findall(r"\"([^\"]+)\"|“([^”]+)”", work)
    phrases = [a or b for a, b in quoted]
    work = re.sub(r"\"[^\"]+\"|“[^”]+”", " ", work)

    date_from, date_to, spans = parse_dates(work, now)
    for s, e in sorted(spans, reverse=True):
        work = work[:s] + " " + work[e:]
    draft["date_from"] = date_from.isoformat() if date_from else ""
    draft["date_to"] = date_to.isoformat() if date_to else ""

    for email, matched, role in match_people(work, directory):
        if role == "from" and not draft["from"]:
            draft["from"] = email
        elif role == "to" and not draft["to"]:
            draft["to"] = email
        elif email not in draft["people"]:
            draft["people"].append(email)
        work = re.sub(re.escape(matched), " ", work, flags=re.I)

    project, matched = match_project(text, projects)
    if project:
        draft["project"] = project
        for w in [matched] + re.findall(r"[a-z0-9]+", project.lower()):
            work = re.sub(r"\b" + re.escape(w) + r"\b", " ", work, flags=re.I)

    lowered = text.lower()
    draft["has_attachment"] = any(re.search(r"\b" + w + r"\b", lowered) for w in ATTACH_WORDS)
    words = [w for w in re.findall(r"[A-Za-z0-9][\w&'-]*", work)
             if w.lower() not in STOPWORDS and len(w) > 2 and w.lower() not in MONTHS]
    draft["keywords"] = phrases + list(dict.fromkeys(w.lower() for w in words))

    if any(w in lowered for w in TREND_WORDS):
        intent = "trend"
    elif project or re.search(r"\b(?:project|job)\b", lowered):
        intent = "project"
    elif (draft["people"] or draft["from"] or draft["to"]) and not draft["keywords"]:
        intent = "person"
    else:
        intent = "message"
    return intent, draft


def restate(intent, draft, directory):
    names = {p["email"]: p["name"] for p in directory}
    parts = {"message": "a specific message", "trend": "a pattern over time",
             "project": "everything about a project", "person": "everything involving a person"}[intent]
    out = [f"Looking for {parts}"]
    if draft["keywords"]:
        out.append("about " + ", ".join(f'"{k}"' if " " in k else k for k in draft["keywords"][:6]))
    if draft["project"]:
        out.append(f"on {draft['project']}")
    if draft["from"]:
        out.append(f"from {names.get(draft['from'], draft['from'])}")
    if draft["to"]:
        out.append(f"to {names.get(draft['to'], draft['to'])}")
    if draft["people"]:
        out.append("involving " + ", ".join(names.get(e, e) for e in draft["people"]))
    if draft["date_from"] and draft["date_to"]:
        out.append(f"between {draft['date_from']} and {draft['date_to']}")
    elif draft["date_from"]:
        out.append(f"since {draft['date_from']}")
    elif draft["date_to"]:
        out.append(f"before {draft['date_to']}")
    if draft["has_attachment"]:
        out.append("with attachments")
    return " ".join(out) + "."


def questions_for(intent, draft, directory):
    names = {p["email"]: p["name"] for p in directory}
    named = [e for e in [draft["from"], draft["to"], *draft["people"]] if e and e in names]
    qs = [{"id": Q_MAILBOXES, "question": "Whose mailboxes should I search?",
           "options": [ALL_MAILBOXES, MY_MAILBOX] + [f"{names[e]}'s mailbox" for e in dict.fromkeys(named)],
           "multi": True}]
    if not draft["date_from"] and not draft["date_to"]:
        qs.append({"id": Q_WINDOW, "question": "What time window?",
                   "options": list(WINDOWS), "multi": False})
    if intent in ("message", "person"):
        qs.append({"id": Q_SHAPE, "question": "Are you after one message, or a pattern?",
                   "options": list(SHAPES), "multi": False})
    if not draft["has_attachment"] and intent != "trend":
        qs.append({"id": Q_ATTACH, "question": "Should results include attachments only?",
                   "options": [ATTACH_ANY, ATTACH_ONLY], "multi": False})
    if len(qs) < 4:
        qs.append({"id": Q_AUDIENCE, "question": "Client correspondence or internal?",
                   "options": list(AUDIENCES), "multi": False})
    return qs[:4]


def haiku(system, prompt, max_tokens=600):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=20,
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                "content-type": "application/json"},
                       json={"model": HAIKU, "max_tokens": max_tokens, "system": system,
                             "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    except (httpx.HTTPError, ValueError) as e:
        log.warning("Haiku call failed: %s", e)
        return None


def _refine_questions(text, intent, draft, questions):
    system = ("You help a construction company owner phrase an org-wide email search. Return ONLY JSON: "
              '{"restated": str, "questions": [{"id": str, "question": str, "options": [str], "multi": bool}]}. '
              "Keep the given question ids and option strings; you may reword questions, reorder, drop "
              "irrelevant ones, and add at most one with id \"clarify\". Max 4 questions.")
    prompt = json.dumps({"request": text, "intent": intent, "draft": draft, "questions": questions})
    raw = haiku(system, prompt)
    if not raw:
        return None
    try:
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        qs = [q for q in data["questions"] if {"id", "question", "options"} <= set(q)][:4]
        for q in qs:
            q["multi"] = bool(q.get("multi"))
            q["options"] = [str(o) for o in q["options"]]
        return (data.get("restated") or None), qs or None
    except (ValueError, KeyError, TypeError):
        return None


def guide(text, directory, projects=None, now=None):
    projects = known_projects() if projects is None else projects
    intent, draft = parse_text(text, directory, projects, now)
    restated = restate(intent, draft, directory)
    questions = questions_for(intent, draft, directory)
    decision = jev.route("query_build")
    refined = _refine_questions(text, intent, draft, questions) if os.environ.get("ANTHROPIC_API_KEY") else None
    if refined:
        restated = refined[0] or restated
        questions = refined[1] or questions
        decision = jev.route("guide_questions")
    return {"intent": intent, "restated": restated, "questions": questions, "draft": draft,
            "jev": jev.stamp(decision)}


# ---------- answers -> draft ----------

def apply_answers(draft, answers, actor, directory, now=None):
    """Fold clarifying answers into a copy of the draft. Returns (draft, intent_override, audience)."""
    now = now or today()
    d = {**empty_draft(), **(draft or {})}
    d = {k: (list(v) if isinstance(v, list) else v) for k, v in d.items()}
    answers = answers or {}
    by_label = {f"{p['name']}'s mailbox": p["email"] for p in directory}

    mb = answers.get(Q_MAILBOXES)
    picks = mb if isinstance(mb, list) else ([mb] if mb else [])
    if picks and ALL_MAILBOXES not in picks:
        users = [actor if p == MY_MAILBOX else by_label.get(p, p) for p in picks]
        d["users"] = [u for u in dict.fromkeys(users) if "@" in u]

    window = answers.get(Q_WINDOW)
    if window in WINDOWS and WINDOWS[window]:
        d["date_from"] = (now - timedelta(days=WINDOWS[window])).isoformat()
        d["date_to"] = ""

    intent = SHAPES.get(answers.get(Q_SHAPE))
    if answers.get(Q_ATTACH) == ATTACH_ONLY:
        d["has_attachment"] = True
    elif answers.get(Q_ATTACH) == ATTACH_ANY:
        d["has_attachment"] = False
    audience = AUDIENCES.get(answers.get(Q_AUDIENCE), "both")
    return d, intent, audience


# ---------- query building ----------

def _term(word):
    word = word.replace('"', "").strip()
    return f'"{word}"' if re.search(r"\s", word) else word


def _gmail_date(iso, plus_days=0):
    d = date.fromisoformat(iso) + timedelta(days=plus_days)
    return d.strftime("%Y/%m/%d")


def build_gmail_query(draft):
    parts = []
    if draft.get("from"):
        parts.append(f"from:{draft['from']}")
    if draft.get("to"):
        parts.append(f"to:{draft['to']}")
    people = [p for p in draft.get("people") or [] if p not in (draft.get("from"), draft.get("to"))]
    if people:
        parts.append("(" + " OR ".join(f"from:{p} OR to:{p} OR cc:{p}" for p in people) + ")")
    if draft.get("date_from"):
        parts.append(f"after:{_gmail_date(draft['date_from'])}")
    if draft.get("date_to"):
        parts.append(f"before:{_gmail_date(draft['date_to'], 1)}")
    if draft.get("has_attachment"):
        parts.append("has:attachment")
    for label in draft.get("labels") or []:
        parts.append("label:" + re.sub(r"\s+", "-", label.strip()))
    if draft.get("project"):
        terms = project_terms(draft["project"])
        parts.append(_term(terms[0]) if len(terms) == 1 else "(" + " OR ".join(_term(t) for t in terms) + ")")
    keywords = [k for k in draft.get("keywords") or [] if k.strip()]
    if len(keywords) == 1:
        parts.append(_term(keywords[0]))
    elif keywords:
        parts.append("(" + " OR ".join(_term(k) for k in keywords) + ")")
    return " ".join(parts)


def build_drive_query(draft):
    terms = (project_terms(draft["project"]) if draft.get("project") else []) + list(draft.get("keywords") or [])
    clauses = ["trashed = false"]
    if terms:
        clauses.append("(" + " or ".join(
            "fullText contains '{}'".format(t.replace("\\", "\\\\").replace("'", "\\'")) for t in terms) + ")")
    if draft.get("date_from"):
        clauses.append(f"modifiedTime > '{draft['date_from']}T00:00:00'")
    if draft.get("date_to"):
        clauses.append(f"modifiedTime < '{(date.fromisoformat(draft['date_to']) + timedelta(days=1)).isoformat()}T00:00:00'")
    return " and ".join(clauses)


# ---------- scoring ----------

def _addresses(field):
    return [a.lower() for _, a in getaddresses([field or ""]) if a]


def _parse_iso(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def score(result, draft, now=None):
    now = now or datetime.now(timezone.utc)
    subject = (result.get("subject") or "").lower()
    snippet = (result.get("snippet") or "").lower()
    s = 0.0
    terms = list(draft.get("keywords") or [])
    for k in terms:
        k = k.lower()
        if k in subject:
            s += 3.0
        if k in snippet:
            s += 1.0
    if draft.get("project"):
        p = draft["project"].lower()
        if p in subject:
            s += 4.0
        elif p in snippet:
            s += 2.0
        elif any(w in subject for w in distinctive_words(p)):
            s += 1.5
    people = {e.lower() for e in [draft.get("from"), draft.get("to"), *(draft.get("people") or [])] if e}
    involved = set(_addresses(result.get("from"))) | set(_addresses(result.get("to")))
    s += 2.0 * len(people & involved)
    when = _parse_iso(result.get("date") or "")
    if when:
        age_days = max((now - when).total_seconds() / 86400, 0)
        s += 2.0 * math.exp(-age_days / 30)
    return round(s, 3)


def rank(results, draft, now=None):
    for r in results:
        r["score"] = score(r, draft, now)
    return sorted(results, key=lambda r: (r["score"], r.get("date") or ""), reverse=True)


def matches_draft(msg, draft):
    """Local evaluation of a draft against a message dict (used for demo data)."""
    involved = set(_addresses(msg.get("from"))) | set(_addresses(msg.get("to"))) | {msg.get("user", "").lower()}
    if draft.get("from") and draft["from"].lower() not in _addresses(msg.get("from")):
        return False
    if draft.get("to") and draft["to"].lower() not in _addresses(msg.get("to")):
        return False
    people = [p.lower() for p in draft.get("people") or [] if p not in (draft.get("from"), draft.get("to"))]
    if people and not any(p in involved for p in people):
        return False
    when = (msg.get("date") or "")[:10]
    if draft.get("date_from") and when < draft["date_from"]:
        return False
    if draft.get("date_to") and when > draft["date_to"]:
        return False
    if draft.get("has_attachment") and not msg.get("has_attachment"):
        return False
    text = f"{msg.get('subject', '')} {msg.get('snippet', '')}".lower()
    if draft.get("project") and not any(t.lower() in text for t in project_terms(draft["project"])):
        return False
    keywords = [k.lower() for k in draft.get("keywords") or []]
    return not keywords or any(k in text for k in keywords)


def audience_match(msg, audience):
    if audience not in ("internal", "external"):
        return True
    addrs = _addresses(msg.get("from")) + _addresses(msg.get("to"))
    internal = all(a.endswith("@" + config.DOMAIN) for a in addrs) if addrs else True
    return internal if audience == "internal" else not internal


# ---------- trend & project ----------

def _period(dt, monthly):
    if monthly:
        return dt.strftime("%Y-%m")
    monday = dt.date() - timedelta(days=dt.weekday())
    return monday.isoformat()


def trend_of(results, draft, directory):
    dates = [d for d in (_parse_iso(r.get("date") or "") for r in results) if d]
    if not dates:
        return {"buckets": [], "by_person": [], "summary": "No matching messages in the window."}
    monthly = (max(dates) - min(dates)).days > 92
    buckets = Counter(_period(d, monthly) for d in dates)
    names = {p["email"]: p["name"] for p in directory}
    people = Counter()
    for r in results:
        sender = (_addresses(r.get("from")) or [""])[0]
        people[names.get(sender, sender)] += 1
    out = {"buckets": [{"period": k, "count": buckets[k]} for k in sorted(buckets)],
           "by_person": [{"person": p, "count": c} for p, c in people.most_common(10) if p]}
    out["summary"] = trend_summary_template(out, monthly, draft)
    return out


def trend_summary_template(trend, monthly, draft):
    total = sum(b["count"] for b in trend["buckets"])
    unit = "month" if monthly else "week"
    peak = max(trend["buckets"], key=lambda b: b["count"])
    subject = ", ".join(draft.get("keywords") or []) or draft.get("project") or "this search"
    top = trend["by_person"][0] if trend["by_person"] else None
    counts = [b["count"] for b in trend["buckets"]]
    direction = ("rising" if counts[-1] > counts[0] else "falling" if counts[-1] < counts[0] else "flat") \
        if len(counts) > 1 else "a single period"
    text = (f"{total} messages about {subject} across {len(counts)} {unit}(s); "
            f"busiest {unit} {peak['period']} with {peak['count']}. Trend is {direction}.")
    if top:
        text += f" Most from {top['person']} ({top['count']})."
    return text


def project_of(results, draft, directory):
    names = {p["email"]: p["name"] for p in directory}
    people = []
    for r in results:
        for a in _addresses(r.get("from")) + _addresses(r.get("to")):
            label = names.get(a, a)
            if label not in people:
                people.append(label)
    latest = {}
    for r in results:
        tid = r.get("thread_id") or r["id"]
        if tid not in latest or (r.get("date") or "") > (latest[tid].get("date") or ""):
            latest[tid] = r
    open_items = []
    for r in sorted(latest.values(), key=lambda r: r.get("date") or ""):
        sender = (_addresses(r.get("from")) or [""])[0]
        if r.get("replied") is False or (r.get("replied") is None and sender != (r.get("user") or "").lower()):
            open_items.append(f"{r.get('subject')} — waiting on {names.get(r.get('user'), r.get('user'))} "
                              f"since {(r.get('date') or '')[:10]} (from {names.get(sender, sender)})")
    name = draft.get("project") or ", ".join(draft.get("keywords") or []) or "Project"
    summary = (f"{len(results)} messages on {name} involving {len(people)} people; "
               f"{len(open_items)} thread(s) look unanswered.")
    return {"name": name, "people": people, "open_items": open_items[:15], "summary": summary}


# ---------- live fetch ----------

def _header(headers, name):
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _gmail_mailbox(user, q, limit):
    gmail = gws.service("gmail", user=user)
    resp = gmail.users().messages().list(userId="me", q=q, maxResults=min(limit, PER_MAILBOX)).execute()
    out = []
    for ref in resp.get("messages", []):
        msg = gmail.users().messages().get(userId="me", id=ref["id"], format="metadata",
                                           metadataHeaders=["From", "To", "Subject", "Date"]).execute()
        hs = msg.get("payload", {}).get("headers", [])
        try:
            when = parsedate_to_datetime(_header(hs, "Date")).isoformat()
        except (TypeError, ValueError):
            when = datetime.fromtimestamp(int(msg.get("internalDate", 0)) / 1000, timezone.utc).isoformat()
        out.append({"id": msg["id"], "source": "gmail", "user": user, "from": _header(hs, "From"),
                    "to": _header(hs, "To"), "subject": _header(hs, "Subject"), "snippet": msg.get("snippet", ""),
                    "date": when, "thread_id": msg.get("threadId", ""),
                    "link": f"https://mail.google.com/mail/u/{user}/#all/{msg.get('threadId', '')}",
                    "score": 0.0})
    return out


def _drive_user(user, q, limit):
    drive = gws.service("drive", user=user)
    resp = drive.files().list(q=q, pageSize=min(limit, 50), corpora="user",
                              fields="files(id,name,mimeType,modifiedTime,webViewLink,owners(emailAddress))").execute()
    return [{"id": f["id"], "source": "drive", "user": user,
             "from": (f.get("owners") or [{}])[0].get("emailAddress", ""), "to": "",
             "subject": f["name"], "snippet": f.get("mimeType", ""), "date": f.get("modifiedTime", ""),
             "thread_id": "", "link": f.get("webViewLink", ""), "score": 0.0}
            for f in resp.get("files", [])]


def _fan_out(fn, users, q, limit):
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fn, u, q, limit): u for u in users[:MAX_MAILBOXES]}
        for fut, user in futures.items():
            try:
                results += fut.result()
            except Exception as e:
                errors.append({"user": user, "error": str(e)})
                log.warning("search %s failed for %s: %s", fn.__name__, user, e)
    return results, errors


def run(draft, answers, scope, limit, actor, directory, intent=None):
    draft, override, audience = apply_answers(draft, answers, actor, directory)
    intent = override or intent or "message"
    limit = max(1, min(int(limit or 50), 500))
    scope = scope if scope in ("gmail", "drive", "all") else "gmail"
    decision = jev.route("gmail_fetch")

    if gws.live():
        users = draft["users"] or gws.domain_users()
        results = []
        if scope in ("gmail", "all"):
            results += _fan_out(_gmail_mailbox, users, build_gmail_query(draft), limit)[0]
        if scope in ("drive", "all"):
            results += _fan_out(_drive_user, users, build_drive_query(draft), limit)[0]
    else:
        pool = demo.messages() if scope in ("gmail", "all") else []
        if scope in ("drive", "all"):
            pool += [{"id": f["id"], "source": "drive", "user": f["owner"], "from": f["owner"], "to": "",
                      "subject": f["name"], "snippet": f["mime"], "date": f["modified"], "thread_id": "",
                      "link": f["link"], "score": 0.0} for f in demo.drive_files()]
        results = [dict(m) for m in pool if matches_draft(m, draft)
                   and (not draft["users"] or m["user"] in draft["users"])]

    results = [r for r in results if audience_match(r, audience)]
    ranked = rank(results, draft)[:limit]

    trend = project = None
    gmail_hits = [r for r in ranked if r["source"] == "gmail"]
    if intent == "trend":
        trend = trend_of(gmail_hits, draft, directory)
        if os.environ.get("ANTHROPIC_API_KEY") and trend["buckets"]:
            better = haiku("Summarize this email trend for a construction company owner in two plain sentences. "
                           "No speculation about motives.", json.dumps({"draft": draft, "trend": trend}), 200)
            if better:
                trend["summary"] = better.strip()
                decision = jev.route("trend_summary")
    elif intent == "project":
        project = project_of(gmail_hits, draft, directory)

    public = ("id", "source", "user", "from", "to", "subject", "snippet", "date", "thread_id", "link", "score")
    return {"results": [{k: r.get(k, "") for k in public} for r in ranked], "trend": trend,
            "project": project, "jev": jev.stamp(decision)}


def drive_search(q, user):
    if not gws.live():
        files = demo.drive_files()
        if q:
            files = [f for f in files if q.lower() in f["name"].lower()]
        if user:
            files = [f for f in files if f["owner"] == user.lower()]
        return files
    users = [user] if user else gws.domain_users()
    query = "trashed = false"
    if q:
        safe = q.replace("\\", "\\\\").replace("'", "\\'")
        query += f" and (name contains '{safe}' or fullText contains '{safe}')"

    def one(u, qq, _limit):
        resp = gws.service("drive", user=u).files().list(
            q=qq, pageSize=50, corpora="user",
            fields="files(id,name,mimeType,modifiedTime,webViewLink,owners(emailAddress),"
                   "permissions(type,emailAddress,domain))").execute()
        return [{"id": f["id"], "name": f["name"], "owner": (f.get("owners") or [{}])[0].get("emailAddress", u),
                 "mime": f.get("mimeType", ""), "modified": f.get("modifiedTime", ""),
                 "link": f.get("webViewLink", ""), "shared_externally": shared_externally(f.get("permissions"))}
                for f in resp.get("files", [])]

    files, _ = _fan_out(one, users, query, 50)
    seen = {}
    for f in files:
        seen.setdefault(f["id"], f)
    return sorted(seen.values(), key=lambda f: f["modified"], reverse=True)


def shared_externally(permissions):
    for p in permissions or []:
        if p.get("type") == "anyone":
            return True
        if p.get("type") == "domain" and (p.get("domain") or "").lower() != config.DOMAIN:
            return True
        if p.get("type") in ("user", "group") and p.get("emailAddress") and \
                not p["emailAddress"].lower().endswith("@" + config.DOMAIN):
            return True
    return False


def directory_people():
    if gws.live():
        try:
            return [{"email": u["email"], "name": u["name"]} for u in gws.list_directory_users()]
        except Exception as e:
            log.warning("directory lookup failed: %s", e)
    return [{"email": p["email"], "name": p["name"]} for p in demo.PEOPLE]

