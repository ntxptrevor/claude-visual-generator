# NTXP Google Workspace Access

One shared access layer for every NTXP skill: Gmail, Drive, Calendar, Sheets, Docs,
Slides, Forms, Contacts (People + org directory), Tasks, Admin Directory, Admin
Reports, and Maps. **Google Voice has no public API and cannot be automated.**

## 1. One-time setup (Workspace super admin, once per org)

```bash
gcloud auth login
bash scripts/google_workspace/setup_dwd.sh
```

Then do the one manual step it prints (paste the Client ID and scopes at
https://admin.google.com/ac/owl/domainwidedelegation) and store the printed values in the
NTXP secrets vault as environment variables:

| Variable | Value |
|---|---|
| `NTXP_GOOGLE_SA_KEY` | Service-account key JSON (key mode) |
| `NTXP_GOOGLE_SA_EMAIL` | Service-account email (keyless mode, if org policy blocks keys) |
| `NTXP_GOOGLE_ADMIN_SUBJECT` | Super-admin user impersonated by default |
| `NTXP_GOOGLE_MAPS_KEY` | Maps Platform API key |
| `NTXP_GOOGLE_DOMAIN` | Optional, defaults to `ntxpllc.com` |

Verify: `python3 scripts/google_workspace/ntxp_google_access.py whoami`

## 2. Copy into any other repo or skill (paste in a terminal at that repo's root)

```bash
mkdir -p scripts/google_workspace && for f in ntxp_google_access.py setup_dwd.sh README.md; do curl -fsSL "https://raw.githubusercontent.com/ntxptrevor/claude-visual-generator/master/scripts/google_workspace/$f" -o "scripts/google_workspace/$f"; done && chmod +x scripts/google_workspace/*.py scripts/google_workspace/*.sh && pip install -q google-auth google-api-python-client && python3 scripts/google_workspace/ntxp_google_access.py services
```

Setup runs once per org, not per repo. Every copy uses the same vault variables.

## 3. Paste into any SKILL.md

```markdown
## Google Workspace Access
Use `scripts/google_workspace/ntxp_google_access.py` for all Google data
(Gmail, Drive, Calendar, Sheets, Docs, Slides, Forms, Contacts, Tasks, Admin
Directory/Reports, Maps). Credentials come only from NTXP_GOOGLE_* environment
variables, never from files in the repo.
- `service(name, user=..., allow_write=False)`; read-only unless allow_write=True.
- Impersonate only @ntxpllc.com users; default is NTXP_GOOGLE_ADMIN_SUBJECT.
- Every write passes the NTXP change gate. Sends, deletes, sharing, permission
  changes and bulk actions are Tier 3: explain and wait for approval.
- Google Voice has no API; do not attempt it.
```

## Safety rules (built in)

- Read-only scopes unless a caller passes `allow_write=True`.
- Impersonation refuses any account outside `NTXP_GOOGLE_DOMAIN`.
- Keys live only in environment variables; `.gitignore` blocks key files. This repo is
  public: never paste a key into code, a skill file, or a commit.
- Domain-wide delegation lets the service account act as any NTXP user. Revoke it at
  the same Admin-console page if a key is ever exposed, then rotate the key.
