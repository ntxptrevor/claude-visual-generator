"""NTXP Admin Console API server. Run: uvicorn admin_console.server.app:app (from the repo root)."""

import importlib
import json
import logging
import random
import secrets
import time
from datetime import date
from pathlib import Path

from fastapi import Body, FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from admin_console import config

from . import contacts, demo, gate, gws, search

log = logging.getLogger("ntxp.admin")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

ADMIN_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ADMIN_ROOT / "web"
RUNBOOK_SEED = ADMIN_ROOT / "runbook_seed.json"
DEMO_EMAIL = "trevor@ntxpllc.com"

ACTIONS = [
    {"id": "org_mail_search", "title": "Org-wide Gmail semantic search",
     "blurb": "Describe what you remember; get guided questions, then ranked hits from every NTXP mailbox.",
     "module": "search", "icon": "search"},
    {"id": "attention_today", "title": "What needs my attention today",
     "blurb": "Open flags, unanswered client threads and stalled approvals, ranked by urgency.",
     "module": "analytics", "icon": "alert"},
    {"id": "shared_contacts", "title": "Shared contacts",
     "blurb": "One deduplicated contact book across the directory, personal contacts and the shared DB.",
     "module": "contacts", "icon": "users"},
    {"id": "employee_analytics", "title": "Employee analytics",
     "blurb": "Responsiveness, follow-through and report quality per person, with evidence behind every flag.",
     "module": "analytics", "icon": "chart"},
    {"id": "project_pulse", "title": "Project pulse",
     "blurb": "One project across Gmail, Drive, JobTread and Calendar: who is involved and what is still open.",
     "module": "search", "icon": "pulse"},
    {"id": "ap_integrity", "title": "PO & invoice integrity check",
     "blurb": "Match vendor invoices to POs and flag overbilling, duplicates and missing backup before paying.",
     "module": "analytics", "icon": "receipt"},
    {"id": "drive_finder", "title": "Org-wide Drive finder",
     "blurb": "Find any file in any NTXP Drive by name or content, with owner and sharing status.",
     "module": "drive", "icon": "folder"},
    {"id": "sharing_audit", "title": "External sharing & security audit",
     "blurb": "Files shared outside ntxpllc.com or by public link, plus admin and sign-in posture.",
     "module": "drive", "icon": "shield"},
    {"id": "meeting_reliability", "title": "Meeting load & no-shows",
     "blurb": "Calendar load per person and who missed or declined late on client meetings.",
     "module": "analytics", "icon": "calendar"},
    {"id": "account_control", "title": "Account onboarding / offboarding",
     "blurb": "Suspend, restore, sign out or hand off an account; every change waits for owner approval.",
     "module": "users", "icon": "key"},
]

USER_ACTIONS = ("suspend", "unsuspend", "reset_signin", "transfer_drive")

app = FastAPI(title="NTXP Admin Console API", version="1")


def error(status, message, code):
    return JSONResponse({"error": message, "code": code}, status_code=status)


@app.middleware("http")
async def owner_only(request: Request, call_next):
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    email = (request.headers.get("x-forwarded-email") or "").strip().lower()
    if not email and config.DEMO:
        email = DEMO_EMAIL
    if not email:
        return error(403, "Sign-in required (no X-Forwarded-Email from oauth2-proxy)", "forbidden")
    if not config.is_owner(email):
        log.warning("denied %s %s for %s", request.method, request.url.path, email)
        return error(403, "This console is limited to NTXP owners", "forbidden")
    request.state.email = email
    return await call_next(request)


@app.exception_handler(contacts.ContactError)
async def contact_error(_request, exc):
    return error(exc.status, str(exc), exc.code)


@app.exception_handler(gate.GateError)
async def gate_error(_request, exc):
    return error(exc.status, str(exc), exc.code)


@app.exception_handler(StarletteHTTPException)
async def http_error(_request, exc):
    return error(exc.status_code, str(exc.detail), "http_" + str(exc.status_code))


@app.exception_handler(RequestValidationError)
async def validation_error(_request, exc):
    return error(422, "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()), "invalid")


@app.exception_handler(Exception)
async def unhandled(_request, exc):
    log.exception("unhandled error")
    return error(500, str(exc) or exc.__class__.__name__, "internal")


# ---------- identity ----------

@app.get("/api/me")
def me(request: Request):
    email = request.state.email
    return {"email": email, "name": config.OWNERS[email]["name"], "role": "owner"}


@app.get("/api/health")
def health():
    return {"sources": gws.source_status(), "demo": config.DEMO}


@app.get("/api/actions")
def actions():
    return ACTIONS


# ---------- search ----------

@app.post("/api/search/guide")
def search_guide(body: dict = Body(...)):
    text = str(body.get("text") or "").strip()
    if not text:
        return error(400, "text is required", "empty")
    return search.guide(text, search.directory_people())


@app.post("/api/search/run")
def search_run(request: Request, body: dict = Body(...)):
    draft = body.get("draft")
    if not isinstance(draft, dict):
        return error(400, "draft is required", "empty")
    answers = body.get("answers") or {}
    if not isinstance(answers, dict):
        return error(400, "answers must be an object", "invalid")
    return search.run(draft, answers, body.get("scope") or "gmail", body.get("limit") or 50,
                      request.state.email, search.directory_people(), body.get("intent"))


# ---------- contacts ----------

@app.get("/api/contacts")
def contacts_list(source: str = "all", q: str = "", limit: int = 100, cursor: str | None = None):
    return contacts.list_contacts(source, q, limit, cursor)


@app.get("/api/contacts/export")
def contacts_export(ids: str = "", source: str = "shared", format: str = "google_csv"):
    if format != "google_csv":
        return error(400, "Only format=google_csv is supported", "bad_format")
    body = contacts.export_csv([i for i in ids.split(",") if i], source)
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="ntxp-contacts-{date.today()}.csv"'})


@app.post("/api/contacts/bulk")
def contacts_bulk(request: Request, body: dict = Body(...)):
    ids = body.get("ids") or []
    if not isinstance(ids, list):
        return error(400, "ids must be a list", "invalid")
    return contacts.bulk([str(i) for i in ids], body.get("action"), body.get("label"), request.state.email)


@app.post("/api/contacts/import")
async def contacts_import(request: Request, file: UploadFile = File(...), format: str = "auto",
                          target: str = "shared", commit: bool = False):
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        return error(413, "File larger than 10 MB", "too_large")
    return contacts.import_file(data, format, target, commit, request.state.email)


@app.post("/api/contacts/sync")
def contacts_sync():
    return contacts.sync()


@app.patch("/api/contacts/{cid:path}")
def contacts_patch(cid: str, body: dict = Body(...)):
    return contacts.patch_contact(cid, body)


# ---------- analytics ----------

def analytics_service():
    """The analytics engine (it serves its own demo data), or None if it cannot load."""
    try:
        return importlib.import_module("admin_console.analytics.service")
    except Exception as e:
        log.warning("analytics.service unavailable, serving demo data: %s", e)
        return None


@app.get("/api/analytics/summary")
def analytics_summary():
    svc = analytics_service()
    return svc.get_summary() if svc else demo.summary()


@app.get("/api/analytics/report/{report_id}")
def analytics_report(report_id: str):
    svc = analytics_service()
    try:
        report = svc.get_report(report_id) if svc else demo.report(report_id)
    except KeyError:
        report = None
    if not report:
        return error(404, f"Unknown report {report_id}", "not_found")
    return report


def _demo_tiles():
    while True:
        tile = random.choice(demo.tiles())
        tile["value"] = round(tile["value"] * random.uniform(0.95, 1.05), 1)
        tile["display"] = str(tile["value"]) + ("%" if tile["unit"] == "%" else "")
        yield tile
        time.sleep(3)


@app.get("/api/analytics/stream")
def analytics_stream(limit: int = Query(0, ge=0)):
    svc = analytics_service()
    source = svc.subscribe() if svc else _demo_tiles()

    def events():
        yield ": connected\n\n"
        for n, tile in enumerate(source, 1):
            yield f"event: tile\ndata: {json.dumps(tile)}\n\n"
            if limit and n >= limit:
                return

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/analytics/run")
def analytics_run():
    svc = analytics_service()
    return svc.run_cycle() if svc else demo.run_cycle()


@app.get("/api/flags")
def flags_list(status: str = "open", level: int | None = None):
    if status not in ("open", "all"):
        return error(400, "status must be open or all", "invalid")
    svc = analytics_service()
    if svc:
        return {"flags": svc.list_flags(status=status, level=level)}
    items = demo.flag_store()
    if status == "open":
        items = [f for f in items if f["status"] in ("open", "ack")]
    if level:
        items = [f for f in items if f["level"] == level]
    return {"flags": items}


FLAG_STATUS = {"ack": "ack", "dismiss": "dismissed", "resolve": "resolved"}


@app.post("/api/flags/{flag_id}/action")
def flag_action(request: Request, flag_id: str, body: dict = Body(...)):
    action, note = body.get("action"), str(body.get("note") or "")
    if action not in ("ack", "dismiss", "escalate", "resolve"):
        return error(400, "action must be ack, dismiss, escalate or resolve", "invalid")
    svc = analytics_service()
    if svc:
        try:
            return svc.act_on_flag(flag_id, action, note, request.state.email)
        except KeyError:
            return error(404, f"Unknown flag {flag_id}", "not_found")
        except PermissionError as e:
            return error(403, str(e), "forbidden")
    for f in demo.flag_store():
        if f["id"] == flag_id:
            if action == "escalate":
                f["level"] = min(f["level"] + 1, 3)
                f["escalations"].append({"level": f["level"], "channel": "email",
                                         "at": demo.iso_ago(0), "to": list(config.OWNER_EMAILS)})
            else:
                f["status"] = FLAG_STATUS[action]
            return f
    return error(404, f"Unknown flag {flag_id}", "not_found")


# ---------- runbook ----------

def _seed_runbook():
    try:
        data = json.loads(RUNBOOK_SEED.read_text())
        return data.get("entries", []) if isinstance(data, dict) else list(data)
    except (OSError, ValueError):
        return demo.RUNBOOK


def _runbook_entries():
    if gws.live() and gws.sheets_configured():
        try:
            rows = gws.read_tab("Runbook")
            return [{**r, "steps": [s for s in r.get("steps", "").split("\n") if s.strip()],
                     "tier": int(r["tier"]) if str(r.get("tier", "")).isdigit() else 0} for r in rows]
        except Exception as e:
            log.warning("Runbook tab unavailable, using seed: %s", e)
    return demo.state("runbook", lambda: [dict(e) for e in _seed_runbook()])


@app.get("/api/runbook")
def runbook(q: str = ""):
    entries = _runbook_entries()
    if q:
        terms = q.lower().split()
        entries = [e for e in entries if all(t in json.dumps(e).lower() for t in terms)]
    return {"entries": entries}


RUNBOOK_FIELDS = ("id", "workflow", "symptom", "likely_cause", "steps", "escalate_to", "tier", "updated")


@app.post("/api/runbook")
def runbook_add(request: Request, body: dict = Body(...)):
    if not body.get("workflow") or not body.get("symptom"):
        return error(400, "workflow and symptom are required", "invalid")
    steps = body.get("steps") or []
    entry = {"id": "RB-" + secrets.token_hex(3).upper(), "workflow": str(body["workflow"]),
             "symptom": str(body["symptom"]), "likely_cause": str(body.get("likely_cause") or ""),
             "steps": [str(s) for s in (steps if isinstance(steps, list) else str(steps).split("\n")) if str(s).strip()],
             "escalate_to": str(body.get("escalate_to") or request.state.email),
             "tier": int(body.get("tier") or 0), "updated": date.today().isoformat()}
    if gws.live() and gws.sheets_configured():
        gws.append_row("Runbook", [("\n".join(entry[k]) if k == "steps" else entry[k]) for k in RUNBOOK_FIELDS])
    else:
        _runbook_entries().append(entry)
    return entry


# ---------- workspace control ----------

@app.get("/api/drive/search")
def drive_search(q: str = "", user: str = ""):
    if user and not user.lower().endswith("@" + config.DOMAIN):
        return error(400, f"user must be an @{config.DOMAIN} account", "invalid")
    return {"files": search.drive_search(q, user)}


@app.get("/api/users")
def users():
    return {"users": gws.list_directory_users() if gws.live() else demo.users()}


def _execute_user_action(payload, approver):
    email, action = payload["email"], payload["action"]
    if not gws.live():
        return {"email": email, "action": action, "status": "simulated (demo mode)"}
    users_api = gws.service("directory", allow_write=True).users()
    if action in ("suspend", "unsuspend"):
        users_api.update(userKey=email, body={"suspended": action == "suspend"}).execute()
    elif action == "reset_signin":
        users_api.signOut(userKey=email).execute()
    return {"email": email, "action": action, "status": "done"}


gate.register("users.action", _execute_user_action)


@app.post("/api/users/{email}/action")
def user_action(request: Request, email: str, body: dict = Body(...)):
    email = email.strip().lower()
    action, to = body.get("action"), (body.get("to") or "").strip().lower()
    if action not in USER_ACTIONS:
        return error(400, "action must be suspend, unsuspend, reset_signin or transfer_drive", "invalid")
    if not email.endswith("@" + config.DOMAIN):
        return error(400, f"Only @{config.DOMAIN} accounts can be changed", "invalid")
    if config.is_owner(email):
        return error(409, "Owner accounts cannot be changed from the console", "owner_account")
    if action == "transfer_drive":
        if not to.endswith("@" + config.DOMAIN):
            return error(400, f"transfer_drive needs `to`, an @{config.DOMAIN} account", "invalid")
        if gws.live():
            return error(501, "Drive transfer needs the Admin Data Transfer API, which the Google access "
                              "layer does not expose yet. Use Admin console > Data transfer.", "not_implemented")
    summary = {"suspend": f"Suspend {email}", "unsuspend": f"Restore {email}",
               "reset_signin": f"Sign {email} out of all sessions",
               "transfer_drive": f"Transfer Drive files from {email} to {to}"}[action]
    return gate.stage("users.action", summary, {"email": email, "action": action, "to": to},
                      request.state.email)


@app.get("/api/approve")
def approvals_pending():
    return {"pending": gate.pending()}


@app.post("/api/approve/{change_id}")
def approve(request: Request, change_id: str, body: dict | None = Body(None)):
    expected = (body or {}).get("payload_digest")
    return gate.approve(change_id, request.state.email, expected)


if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
