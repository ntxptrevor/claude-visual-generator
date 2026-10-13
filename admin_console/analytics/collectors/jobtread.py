"""JobTread adapter (Pave API) plus Tier 0 checks for daily logs, POs and vendor invoices.

Env: JOBTREAD_GRANT_KEY, NTXP_JOBTREAD_ORG_ID. Endpoint https://api.jobtread.com/pave,
POST JSON {"query": {...}}. The HTTP layer is one function (`pave`) so tests and the
demo mock it completely. JobTread schemas drift; parsing is defensive and the queries are
kept in one place (`QUERIES`).

Events:
  daily_log        meta: job, quality (0-1), issues[], has_photos, on_site, quote
  purchase_order   meta: number, missing[], amount_ok
  vendor_invoice   meta: number, missing[], amount_ok, po_ref
"""

import json
import os
import re
import urllib.request

from admin_console.analytics import demo, google, util
from admin_console.analytics.collectors import Unconfigured, event

ENDPOINT = "https://api.jobtread.com/pave"

CONSTRUCTION_VOCAB = set("""
site crew crews foreman super superintendent sub subs subcontractor subcontractors inspection
inspector passed failed rebar slab slabs footing footings forms formwork pour poured concrete
grout mortar masonry block brick framing framed studs stud drywall sheetrock tape taped mud
texture paint painted primer primed tile tiled grout thinset backer board plumbing plumber
rough trim electrical electrician conduit wire wiring panel breaker hvac duct ductwork unit
units roof roofing reroof deck decking membrane flashing insulation insulated ceiling grid
door doors frame frames hardware window windows glazing sealant caulk caulked demo demolition
demolished debris dumpster haul hauled cleanup cleaned swept secured safety incident incidents
toolbox talk ppe osha punch list walk walkthrough submittal submittals rfi rfis change order
owner architect engineer drawings sheet sheets spec specs scope schedule delay delayed weather
rain crane lift scaffold scaffolding excavation trench backfill compaction survey layout
restroom restrooms gym floor flooring bleacher bleachers station campus classroom hallway
north south east west elevation level install installed installing remove removed removing
delivered delivery deliveries material materials order ordered received staged staging
""".split())

COMMON_WORDS = set("""
a about above after again all also am an and any are around as at back be been before being
below between both but by came can come could day days did do does done down during each
early end for from get got had has have he her here him his how i if in into is it its just
last late left like made make many may me more morning most much must my need needed new next
no not now of off on once one only or other our out over per put ready same set she should
since so some still such than that the their them then there these they this those through
to today tomorrow too two three four five six under until up us very was we well were what
when where which while who will with work worked working would yes yet you your all afternoon
noon pm am crew's start started finish finished complete completed continue continued
check checked approved approval call called meeting met team area areas room rooms per
first second third half full ok okay good bad issue issues problem problems note notes
""".split())


def status():
    if google.demo():
        return "ok"
    return "ok" if os.environ.get("JOBTREAD_GRANT_KEY") else "unconfigured"


# --------------------------------------------------------------------------- Tier 0 checks

def _known(word):
    w = word.lower().strip("'")
    if w in CONSTRUCTION_VOCAB or w in COMMON_WORDS:
        return True
    for suffix in ("s", "es", "ed", "d", "ing", "'s"):
        if w.endswith(suffix) and (w[: -len(suffix)] in CONSTRUCTION_VOCAB
                                   or w[: -len(suffix)] in COMMON_WORDS):
            return True
    return False


def score_log_text(text):
    """Grammar / quality heuristic (Tier 0, $0). Returns {score 0-1, issues[], words}."""
    text = (text or "").strip()
    issues = []
    if not text:
        return {"score": 0.0, "issues": ["empty log"], "words": 0}
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    words = re.findall(r"[A-Za-z][A-Za-z']*", text)
    n = len(words)
    # spelling: ignore proper nouns mid-sentence, sheet numbers, short words
    checkable = [w for i, w in enumerate(words) if len(w) > 2 and not (w[0].isupper() and i > 0)]
    spell = sum(_known(w) for w in checkable) / len(checkable) if checkable else 1.0
    case = sum(s[0].isupper() for s in sentences) / len(sentences)
    runon = sum(len(s.split()) > 40 for s in sentences) / len(sentences)
    punct = 1.0 if text[-1] in ".!?" else 0.0
    length = min(1.0, n / 30.0)
    if spell < 0.85:
        issues.append(f"spelling: {round((1 - spell) * 100)}% of words unrecognized")
    if case < 1.0:
        issues.append("sentence case")
    if runon > 0:
        issues.append("run-on sentences")
    if not punct:
        issues.append("missing end punctuation")
    if n < 20:
        issues.append(f"short ({n} words)")
    score = 0.30 * spell + 0.20 * case + 0.20 * length + 0.15 * (1 - runon) + 0.15 * punct
    return {"score": round(score, 2), "issues": issues, "words": n}


def check_document(doc, kind):
    """PO / vendor-invoice required fields. Returns {missing[], amount_ok}."""
    missing = [f for f in ("vendor", "job", "cost_code", "date", "number") if not doc.get(f)]
    if kind == "vendor_invoice" and not doc.get("po_ref"):
        missing.append("po_ref")
    lines = [float(x) for x in (doc.get("lines") or []) if x not in (None, "")]
    total = doc.get("total")
    amount_ok = bool(lines) and total not in (None, "") and abs(sum(lines) - float(total)) < 0.01
    if not amount_ok:
        missing.append("amounts do not sum")
    return {"missing": missing, "amount_ok": amount_ok}


def enrich(e):
    """Add Tier 0 scores to a raw jobtread event (demo or live)."""
    m = e["meta"]
    if e["kind"] == "daily_log":
        q = score_log_text(m.get("text", ""))
        m["quality"] = q["score"]
        m["issues"] = q["issues"] + ([] if m.get("has_photos") else ["no photos"])
        m["quote"] = util.short_quote(m.pop("text", ""), 160)
    elif e["kind"] in ("purchase_order", "vendor_invoice"):
        m.update(check_document(m, e["kind"]))
    return e


# --------------------------------------------------------------------------- Pave client

def pave(query, key=None, timeout=30):
    key = key or os.environ.get("JOBTREAD_GRANT_KEY")
    if not key:
        raise Unconfigured("jobtread")
    body = {"query": {"$": {"grantKey": key}, **query}}
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _q_org(org_id, inner):
    return {"organization": {"$": {"id": org_id}, **inner}} if org_id else {"currentGrant": {"organization": inner}}


QUERIES = {
    "daily_logs": lambda org, since: _q_org(org, {"dailyLogs": {
        "$": {"size": 100, "where": [["date", ">=", since[:10]]]},
        "nodes": {"id": {}, "date": {}, "notes": {}, "user": {"name": {}, "emailAddress": {}},
                  "job": {"name": {}}, "files": {"nodes": {"id": {}}}}}}),
    "purchase_orders": lambda org, since: _q_org(org, {"documents": {
        "$": {"size": 100, "where": [["type", "=", "vendorOrder"], ["createdAt", ">=", since]]},
        "nodes": {"id": {}, "number": {}, "issueDate": {}, "createdAt": {}, "price": {},
                  "account": {"name": {}}, "job": {"name": {}},
                  "lineItems": {"nodes": {"price": {}, "costCode": {"number": {}}}},
                  "createdByUser": {"emailAddress": {}}}}}),
    "vendor_invoices": lambda org, since: _q_org(org, {"documents": {
        "$": {"size": 100, "where": [["type", "=", "vendorBill"], ["createdAt", ">=", since]]},
        "nodes": {"id": {}, "number": {}, "issueDate": {}, "createdAt": {}, "price": {},
                  "account": {"name": {}}, "job": {"name": {}}, "externalId": {},
                  "lineItems": {"nodes": {"price": {}, "costCode": {"number": {}}}},
                  "createdByUser": {"emailAddress": {}}}}}),
}


def _find_nodes(obj):
    """First list of nodes anywhere in a Pave response."""
    if isinstance(obj, dict):
        if isinstance(obj.get("nodes"), list):
            return obj["nodes"]
        for v in obj.values():
            got = _find_nodes(v)
            if got is not None:
                return got
    return None


def collect(people, start, end, client=None):
    if google.demo() and client is None:
        return [enrich(e) for e in _copy(demo.events("jobtread", people, start, end))]
    if client is None and not os.environ.get("JOBTREAD_GRANT_KEY"):
        raise Unconfigured("jobtread")
    call = client or pave
    org = os.environ.get("NTXP_JOBTREAD_ORG_ID", "")
    since = util.iso(start)
    wanted = {p.lower() for p in people}
    out = []
    for node in _find_nodes(call(QUERIES["daily_logs"](org, since))) or []:
        who = ((node.get("user") or {}).get("emailAddress") or "").lower()
        if who not in wanted:
            continue
        out.append(enrich(event(who, "jobtread", "daily_log", node.get("date") or since,
                                node.get("id"), job=(node.get("job") or {}).get("name", ""),
                                text=node.get("notes", ""), on_site=True,
                                has_photos=bool(_find_nodes(node.get("files") or {}) or []))))
    for kind, qname in (("purchase_order", "purchase_orders"), ("vendor_invoice", "vendor_invoices")):
        for node in _find_nodes(call(QUERIES[qname](org, since))) or []:
            who = ((node.get("createdByUser") or {}).get("emailAddress") or "").lower()
            items = (node.get("lineItems") or {}).get("nodes") or []
            codes = [((i.get("costCode") or {}).get("number")) for i in items]
            out.append(enrich(event(who or "unassigned", "jobtread", kind,
                                    node.get("createdAt") or since, node.get("id"),
                                    number=node.get("number"),
                                    vendor=(node.get("account") or {}).get("name", ""),
                                    job=(node.get("job") or {}).get("name", ""),
                                    cost_code=codes[0] if codes and all(codes) else "",
                                    lines=[i.get("price") for i in items], total=node.get("price"),
                                    date=node.get("issueDate"),
                                    po_ref=node.get("externalId") if kind == "vendor_invoice" else None)))
    return out


def _copy(events):
    return [dict(e, meta=dict(e["meta"])) for e in events]
