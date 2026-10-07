#!/usr/bin/env python3
"""
NTXP Google Workspace access — one module for every skill.

Org-wide access through a service account with domain-wide delegation (DWD).
Credentials come only from the environment (populate it from the NTXP vault):

  NTXP_GOOGLE_SA_KEY         service-account JSON (contents or a file path), or
  NTXP_GOOGLE_SA_EMAIL       keyless mode: signs via IAM using local ADC
  NTXP_GOOGLE_ADMIN_SUBJECT  super-admin user to impersonate by default
  NTXP_GOOGLE_DOMAIN         impersonation is limited to this domain (ntxpllc.com)
  NTXP_GOOGLE_MAPS_KEY       Maps Platform API key

Read-only by default. Write scopes need allow_write=True, and every write must
still pass the NTXP change gate (Tier 3 for sends, deletes, sharing, bulk).

Library:
    from ntxp_google_access import service, maps_geocode
    gmail = service("gmail", user="alison@ntxpllc.com")
    drive = service("drive", allow_write=True)

CLI:
    python ntxp_google_access.py scopes [--csv]
    python ntxp_google_access.py services
    python ntxp_google_access.py whoami [--user someone@ntxpllc.com]
    python ntxp_google_access.py geocode "101 South Locust St Ste 605, Denton, TX"
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

G = "https://www.googleapis.com/auth/"

SERVICES = {
    "gmail":     ("gmail", "v1", ["gmail.readonly"], ["gmail.modify", "gmail.send", "gmail.compose"]),
    "drive":     ("drive", "v3", ["drive.readonly"], ["drive"]),
    "calendar":  ("calendar", "v3", ["calendar.readonly"], ["calendar"]),
    "sheets":    ("sheets", "v4", ["spreadsheets.readonly"], ["spreadsheets"]),
    "docs":      ("docs", "v1", ["documents.readonly"], ["documents"]),
    "slides":    ("slides", "v1", ["presentations.readonly"], ["presentations"]),
    "forms":     ("forms", "v1", ["forms.body.readonly", "forms.responses.readonly"], ["forms.body"]),
    "contacts":  ("people", "v1", ["contacts.readonly", "directory.readonly",
                                   "contacts.other.readonly"], ["contacts"]),
    "tasks":     ("tasks", "v1", ["tasks.readonly"], ["tasks"]),
    "directory": ("admin", "directory_v1", ["admin.directory.user.readonly",
                                            "admin.directory.group.readonly",
                                            "admin.directory.resource.calendar.readonly"],
                  ["admin.directory.user", "admin.directory.group"]),
    "reports":   ("admin", "reports_v1", ["admin.reports.audit.readonly",
                                          "admin.reports.usage.readonly"], []),
}

UNSUPPORTED = {
    "voice": "Google Voice has no public API for calls, texts or voicemail.",
}


def all_scopes():
    scopes = []
    for _, _, read, write in SERVICES.values():
        for s in read + write:
            if G + s not in scopes:
                scopes.append(G + s)
    return scopes


def _domain():
    return os.environ.get("NTXP_GOOGLE_DOMAIN", "ntxpllc.com").lower()


def _check_subject(user):
    if not user:
        raise RuntimeError("No user to impersonate. Set NTXP_GOOGLE_ADMIN_SUBJECT or pass user=.")
    if not user.lower().endswith("@" + _domain()):
        raise PermissionError(f"Impersonation limited to @{_domain()} accounts: {user}")
    return user


def credentials(scopes, user=None):
    from google.oauth2 import service_account

    subject = _check_subject(user or os.environ.get("NTXP_GOOGLE_ADMIN_SUBJECT"))
    raw = os.environ.get("NTXP_GOOGLE_SA_KEY", "").strip()

    if raw:
        info = json.loads(raw) if raw.startswith("{") else json.load(open(raw))
        return service_account.Credentials.from_service_account_info(
            info, scopes=scopes, subject=subject)

    sa_email = os.environ.get("NTXP_GOOGLE_SA_EMAIL")
    if not sa_email:
        raise RuntimeError("Set NTXP_GOOGLE_SA_KEY (key mode) or NTXP_GOOGLE_SA_EMAIL (keyless).")

    import google.auth
    from google.auth import iam
    from google.auth.transport.requests import Request

    source, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    signer = iam.Signer(Request(), source, sa_email)
    return service_account.Credentials(
        signer, sa_email, "https://oauth2.googleapis.com/token",
        scopes=scopes, subject=subject)


def service(name, user=None, allow_write=False):
    if name in UNSUPPORTED:
        raise NotImplementedError(UNSUPPORTED[name])
    if name not in SERVICES:
        raise KeyError(f"Unknown service '{name}'. Choose from {sorted(SERVICES)}")

    from googleapiclient.discovery import build

    api, version, read, write = SERVICES[name]
    scopes = [G + s for s in (write if allow_write and write else read)]
    return build(api, version, credentials=credentials(scopes, user),
                 cache_discovery=False)


def maps_geocode(address):
    key = os.environ.get("NTXP_GOOGLE_MAPS_KEY")
    if not key:
        raise RuntimeError("Set NTXP_GOOGLE_MAPS_KEY.")
    url = ("https://maps.googleapis.com/maps/api/geocode/json?"
           + urllib.parse.urlencode({"address": address, "key": key}))
    with urllib.request.urlopen(url, timeout=20) as r:
        data = json.load(r)
    if data.get("status") != "OK":
        raise RuntimeError(f"Geocode failed: {data.get('status')} {data.get('error_message', '')}")
    top = data["results"][0]
    return {"formatted_address": top["formatted_address"],
            "location": top["geometry"]["location"],
            "place_id": top["place_id"]}


def main():
    p = argparse.ArgumentParser(description="NTXP Google Workspace access")
    sub = p.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scopes", help="Scopes to authorize for domain-wide delegation")
    sc.add_argument("--csv", action="store_true")
    sub.add_parser("services", help="List available services")
    w = sub.add_parser("whoami", help="Verify access by reading a Gmail profile")
    w.add_argument("--user")
    g = sub.add_parser("geocode", help="Maps geocode test")
    g.add_argument("address")
    a = p.parse_args()

    if a.cmd == "scopes":
        print(",".join(all_scopes()) if a.csv else "\n".join(all_scopes()))
    elif a.cmd == "services":
        for n, (api, ver, read, write) in SERVICES.items():
            print(f"{n:10s} {api}/{ver:13s} read={len(read)} write={len(write)}")
        print("maps       geocode via API key")
        for n, why in UNSUPPORTED.items():
            print(f"{n:10s} UNSUPPORTED: {why}")
    elif a.cmd == "whoami":
        prof = service("gmail", user=a.user).users().getProfile(userId="me").execute()
        print(json.dumps({"email": prof["emailAddress"],
                          "messages_total": prof.get("messagesTotal")}, indent=2))
    elif a.cmd == "geocode":
        print(json.dumps(maps_geocode(a.address), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, PermissionError, NotImplementedError, KeyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
