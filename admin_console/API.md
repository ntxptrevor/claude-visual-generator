# NTXP Admin Console — API Contract (v1)

Single source of truth for the web panel (`web/`), the API server (`server/`) and the
analytics engine (`analytics/`). Change this file first, then the code.

Host: `https://admin.ntxpllc.com`. Every request passes through oauth2-proxy (Google
sign-in). The server re-checks the `X-Forwarded-Email` header against `config.OWNER_EMAILS`
and returns 403 for anyone else, including when the header is missing.

All responses are JSON unless stated. Errors: `{"error": "message", "code": "slug"}`.
Every response that touched a model includes `"jev": {"tier": 0|1|2|3, "executor": str, "cost": float}`.

## Identity & health

| Method | Path | Returns |
|---|---|---|
| GET | `/api/me` | `{email, name, role: "owner"}` |
| GET | `/api/health` | `{sources: {gmail, drive, calendar, contacts, directory, reports, jobtread, plaud, quo, council, sheets_db}: "ok"\|"unconfigured"\|"error", demo: bool}` |
| GET | `/api/actions` | Top-ten owner actions: `[{id, title, blurb, module, icon}]` |

## Guided semantic search (Gmail org-wide, plus Drive)

1. `POST /api/search/guide` `{text}` → helps the owner say what they want.
   Returns `{intent: "message"|"trend"|"project"|"person", restated, questions:[{id, question, options:[str], multi: bool}], draft:{people:[str], users:[str], from, to, date_from, date_to, keywords:[str], project, has_attachment: bool, labels:[str]}}`.
2. `POST /api/search/run` `{draft, answers:{question_id: value}, scope: "gmail"|"drive"|"all", limit}` →
   `{results:[{id, source:"gmail"|"drive", user, from, to, subject, snippet, date, thread_id, link, score}], trend: null | {buckets:[{period, count}], by_person:[{person, count}], summary}, project: null | {name, people:[str], open_items:[str], summary}, jev}`

`date_*` are ISO dates. `users` limits which mailboxes are searched (default: all domain users).

## Shared Contacts

Contact object:
```json
{"id": "ws:people/c123", "source": "workspace|directory|shared",
 "name": "", "given": "", "family": "", "emails": [""], "phones": [""],
 "org": "", "title": "", "address": "", "notes": "", "labels": [""],
 "shared": false, "owner_user": "alison@ntxpllc.com", "updated": "ISO"}
```
`source`: `directory` = domain user profile, `workspace` = a user's personal Google Contacts,
`shared` = the IPDM shared contacts DB. A Workspace contact carrying the Google Contacts label
`★ NTXP Shared` is synced into the shared DB automatically (`shared: true`).

| Method | Path | Body / Query | Returns |
|---|---|---|---|
| GET | `/api/contacts` | `?source=all\|workspace\|directory\|shared&q=&limit=&cursor=` | `{contacts:[Contact], next_cursor}` |
| PATCH | `/api/contacts/{id}` | `{field: value}` (one or more fields) | `Contact` |
| POST | `/api/contacts/bulk` | `{ids:[], action:"share"\|"unshare"\|"label"\|"unlabel"\|"delete", label?}` | `{done:int, failed:[{id, error}], tier}` — `delete` is Tier 3 and returns `{needs_approval: true, summary}` until approved |
| POST | `/api/contacts/import` | multipart `file`, `?format=auto\|vcf\|google_csv\|outlook_csv\|csv&target=shared\|workspace&commit=false` | `{format, preview:[Contact], duplicates:[{incoming, existing_id}], created:int, skipped:int}` — `commit=false` previews only |
| GET | `/api/contacts/export` | `?ids=a,b&source=shared&format=google_csv` | `text/csv` in Google Contacts CSV format |
| POST | `/api/contacts/sync` | — | `{pulled:int, shared_added:int, shared_removed:int}` |

## Employee Analytics

| Method | Path | Returns |
|---|---|---|
| GET | `/api/analytics/summary` | `{updated, tiles:[Tile], people:[PersonRow]}` |
| GET | `/api/analytics/report/{report_id}` | `Report` |
| GET | `/api/analytics/stream` | Server-Sent Events: `event: tile` with a `Tile` JSON body whenever a value changes |
| POST | `/api/analytics/run` | Runs one analysis cycle now: `{flags_created, flags_escalated, jev}` |
| GET | `/api/flags` | `?status=open\|all&level=1\|2\|3` → `{flags:[Flag]}` |
| POST | `/api/flags/{id}/action` | `{action:"ack"\|"dismiss"\|"escalate"\|"resolve", note}` → `Flag` |

```json
Tile = {"id": "response_time", "label": "Median response time", "value": 3.4, "unit": "h",
        "display": "3.4", "target": 4, "trend": -0.8, "status": "good|watch|bad",
        "kind": "gauge|pie|ring|bar",
        "breakdown": [{"label": "Trevor", "value": 2.1}], "report_id": "response_time"}

PersonRow = {"email": "", "name": "", "role": "", "response_hrs": 0.0, "unanswered": 0,
             "baseline_dev": 0.0, "open_flags": 0, "top_level": 0}

Report = {"id": "", "title": "", "generated": "ISO", "period": {"from": "", "to": ""},
          "sources": ["gmail", "jobtread"], "sections": [{"heading": "", "findings": [""],
          "evidence": [{"source": "", "ref": "", "note": ""}]}],
          "conclusions": [{"text": "", "confidence": 0.0, "council_id": null}], "jev": {}}

Flag = {"id": "FL-2026-10-09-001", "person": "email", "kpi": "unanswered_email",
        "level": 1, "urgency": "low|medium|high|critical",
        "channel": "gmail|jobtread|calendar|drive|plaud|quo|quickbooks",
        "severity": "note|concern|issue|redflag",
        "confidence": 0.0, "volatility": 0.0,
        "summary": "", "evidence": [{"source": "", "ref": "", "note": ""}],
        "crosscheck": {"status": "pending|explained|confirmed|inconclusive",
                       "sources_checked": [""], "explanations": [""]},
        "council": null | {"council_id": "", "agreement": 0.0, "conclusion": ""},
        "created": "ISO", "status": "open|ack|resolved|dismissed",
        "escalations": [{"level": 1, "channel": "daily_note|email|sms", "at": "ISO", "to": [""]}]}
```
`confidence` and `volatility` are 0–1. `volatility` (emotional volatility) is computed only
for internal NTXP-to-NTXP messages and is never shown for external parties.

### Prewired reports (`report_id`)
`response_time`, `unanswered_email`, `wait_complaints`, `no_shows`, `responsiveness_anomaly`,
`project_folder_access`, `daily_report_quality`, `po_invoice_integrity`, `open_billing_questions`,
`cross_channel_confirmation`.

## Admin Runbook (for humans when a workflow is stuck)

| Method | Path | Returns |
|---|---|---|
| GET | `/api/runbook` | `?q=` → `{entries:[{id, workflow, symptom, likely_cause, steps:[str], escalate_to, tier, updated}]}` |
| POST | `/api/runbook` | Add an entry (owner) → entry |

## Workspace control

| Method | Path | Returns |
|---|---|---|
| GET | `/api/drive/search` | `?q=&user=` → `{files:[{id, name, owner, mime, modified, link, shared_externally}]}` |
| GET | `/api/users` | `{users:[{email, name, suspended, last_login, is_admin, org_unit}]}` |
| POST | `/api/users/{email}/action` | `{action:"suspend"\|"unsuspend"\|"reset_signin"\|"transfer_drive", to?}` → Tier 3: `{needs_approval:true, summary, change_id}` |
| POST | `/api/approve/{change_id}` | Owner approves a staged Tier 3 change → result |

## Python interfaces (server ↔ analytics)

`server/` imports these from `analytics.service` — nothing else:
```python
get_summary() -> dict                       # /api/analytics/summary
get_report(report_id: str) -> dict          # /api/analytics/report/{id}
list_flags(status="open", level=None) -> list[dict]
act_on_flag(flag_id: str, action: str, note: str, actor: str) -> dict
run_cycle(now=None) -> dict                 # one full collect → score → flag → escalate pass
subscribe() -> Iterator[dict]               # yields Tile dicts for SSE
```
Both sides use `admin_console/config.py` (settings, owners) and `admin_console/jev.py`
(routing + confidentiality) — do not duplicate them.
