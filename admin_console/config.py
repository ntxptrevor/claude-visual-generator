"""Shared settings for the NTXP Admin Console. Values come from the environment only."""

import os

DOMAIN = os.environ.get("NTXP_GOOGLE_DOMAIN", "ntxpllc.com")

# Only these two accounts may use admin.ntxpllc.com (oauth2-proxy enforces it too).
OWNER_EMAILS = ("trevor@ntxpllc.com", "alison@ntxpllc.com")

OWNERS = {
    "alison@ntxpllc.com": {"name": "Alison Hopkins", "title": "Owner",
                           "phone_env": "NTXP_ALISON_SMS"},
    "trevor@ntxpllc.com": {"name": "Trevor Hopkins", "title": "Operations Contact",
                           "phone_env": "NTXP_TREVOR_SMS"},
}

ADMIN_DB_SHEET_ID = os.environ.get("NTXP_ADMIN_DB_SHEET_ID", "")
SHARED_CONTACTS_LABEL = os.environ.get("NTXP_SHARED_CONTACTS_LABEL", "★ NTXP Shared")
TIMEZONE = os.environ.get("NTXP_TIMEZONE", "America/Chicago")

# Demo mode serves synthetic data so the panel can be reviewed before credentials exist.
DEMO = os.environ.get("NTXP_ADMIN_DEMO", "").lower() in ("1", "true", "yes")

# Model Council ceilings (live values live in the Council sheet's 01 Config tab).
COUNCIL_CEILING_TASK = 2.00
COUNCIL_CEILING_DAY = 15.00


def owner_phone(email):
    info = OWNERS.get(email.lower())
    return os.environ.get(info["phone_env"], "") if info else ""


def is_owner(email):
    return bool(email) and email.strip().lower() in OWNER_EMAILS
