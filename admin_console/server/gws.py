"""Google Workspace access for the server: wraps scripts/google_workspace/ntxp_google_access."""

import os
import sys
from pathlib import Path

from admin_console import config

REPO_ROOT = Path(__file__).resolve().parents[2]
_ACCESS_DIR = REPO_ROOT / "scripts" / "google_workspace"
for _p in (str(REPO_ROOT), str(_ACCESS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ntxp_google_access  # noqa: E402

SOURCE_ENV = {
    "jobtread": ("JOBTREAD_GRANT_KEY",),
    "plaud": ("PLAUD_API_KEY",),
    "quo": ("QUO_API_KEY",),
    "council": ("NTXP_COUNCIL_SHEET_ID",),
}
GOOGLE_SOURCES = ("gmail", "drive", "calendar", "contacts", "directory", "reports")


def google_configured():
    has_key = bool(os.environ.get("NTXP_GOOGLE_SA_KEY") or os.environ.get("NTXP_GOOGLE_SA_EMAIL"))
    return has_key and bool(os.environ.get("NTXP_GOOGLE_ADMIN_SUBJECT"))


def sheets_configured():
    return google_configured() and bool(config.ADMIN_DB_SHEET_ID)


def live():
    return google_configured() and not config.DEMO


def service(name, user=None, allow_write=False):
    return ntxp_google_access.service(name, user=user, allow_write=allow_write)


def source_status():
    g = "ok" if google_configured() else "unconfigured"
    status = {name: g for name in GOOGLE_SOURCES}
    for name, envs in SOURCE_ENV.items():
        status[name] = "ok" if all(os.environ.get(e) for e in envs) else "unconfigured"
    status["sheets_db"] = "ok" if sheets_configured() else "unconfigured"
    return status


def domain_users():
    """Active primary emails in the domain via the Admin Directory API."""
    return [u["email"] for u in list_directory_users() if not u["suspended"]]


def list_directory_users():
    svc = service("directory")
    users, token = [], None
    while True:
        resp = svc.users().list(domain=config.DOMAIN, maxResults=200, pageToken=token,
                                orderBy="email").execute()
        for u in resp.get("users", []):
            users.append({
                "email": u["primaryEmail"],
                "name": u.get("name", {}).get("fullName", ""),
                "suspended": bool(u.get("suspended")),
                "last_login": u.get("lastLoginTime", ""),
                "is_admin": bool(u.get("isAdmin")),
                "org_unit": u.get("orgUnitPath", "/"),
            })
        token = resp.get("nextPageToken")
        if not token:
            return users


def read_tab(tab):
    """Rows of a tab in the admin DB sheet as dicts keyed by the header row."""
    resp = service("sheets").spreadsheets().values().get(
        spreadsheetId=config.ADMIN_DB_SHEET_ID, range=f"{tab}!A1:ZZ").execute()
    values = resp.get("values", [])
    if not values:
        return []
    header = values[0]
    return [dict(zip(header, row + [""] * (len(header) - len(row)))) for row in values[1:]]


def write_tab(tab, header, rows):
    """Replace a tab's contents with header + rows (list of dicts)."""
    values = [header] + [[str(r.get(h, "")) for h in header] for r in rows]
    vals = service("sheets", allow_write=True).spreadsheets().values()
    vals.clear(spreadsheetId=config.ADMIN_DB_SHEET_ID, range=f"{tab}!A1:ZZ").execute()
    vals.update(spreadsheetId=config.ADMIN_DB_SHEET_ID, range=f"{tab}!A1",
                valueInputOption="RAW", body={"values": values}).execute()


def append_row(tab, row):
    service("sheets", allow_write=True).spreadsheets().values().append(
        spreadsheetId=config.ADMIN_DB_SHEET_ID, range=f"{tab}!A1", valueInputOption="RAW",
        insertDataOption="INSERT_ROWS", body={"values": [[str(v) for v in row]]}).execute()
