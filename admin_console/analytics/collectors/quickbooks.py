"""QuickBooks Online adapter (optional, thin, mockable): disputed / questioned invoices.

Env: QBO_ACCESS_TOKEN, QBO_REALM_ID, QBO_BILLING_OWNER (email who answers billing,
default the first office address). Events: disputed_invoice.
"""

import json
import os
import urllib.parse
import urllib.request

from admin_console.analytics import demo, google, util
from admin_console.analytics.collectors import Unconfigured, event

BASE = "https://quickbooks.api.intuit.com/v3/company"


def status():
    if google.demo():
        return "ok"
    return "ok" if os.environ.get("QBO_ACCESS_TOKEN") and os.environ.get("QBO_REALM_ID") else "unconfigured"


def fetch(start, timeout=30):
    token, realm = os.environ.get("QBO_ACCESS_TOKEN"), os.environ.get("QBO_REALM_ID")
    if not (token and realm):
        raise Unconfigured("quickbooks")
    q = f"select * from Invoice where MetaData.LastUpdatedTime >= '{util.iso(start)}' MAXRESULTS 200"
    url = f"{BASE}/{realm}/query?{urllib.parse.urlencode({'query': q})}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r).get("QueryResponse", {}).get("Invoice", [])


def collect(people, start, end, client=None):
    if google.demo() and client is None:
        return demo.events("quickbooks", people, start, end)
    if client is None and status() != "ok":
        raise Unconfigured("quickbooks")
    owner = os.environ.get("QBO_BILLING_OWNER") or util.office_emails()[0]
    out = []
    for inv in (client or fetch)(start):
        memo = " ".join(str(inv.get(k) or "") for k in ("CustomerMemo", "PrivateNote")).lower()
        if not any(w in memo for w in ("dispute", "question", "short pay", "short-pay", "hold")):
            continue
        out.append(event(owner, "quickbooks", "disputed_invoice",
                         (inv.get("MetaData") or {}).get("LastUpdatedTime") or util.iso(end),
                         f"qbo-{inv.get('Id')}", invoice=inv.get("DocNumber"),
                         customer=(inv.get("CustomerRef") or {}).get("name", ""),
                         amount=inv.get("Balance"), answered=False))
    return out
