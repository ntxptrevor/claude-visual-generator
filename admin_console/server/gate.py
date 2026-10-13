"""Tier 3 change gate: stage, approve once, execute."""

import copy
import hashlib
import json
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone

from admin_console import config

from . import gws

log = logging.getLogger("ntxp.gate")

TTL = timedelta(minutes=15)
_lock = threading.Lock()
_staged = {}
_executors = {}


class GateError(Exception):
    def __init__(self, message, code, status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def now():
    return datetime.now(timezone.utc)


def digest(payload):
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def register(kind, fn):
    _executors[kind] = fn


def stage(kind, summary, payload, actor):
    if kind not in _executors:
        raise GateError(f"No executor for change kind '{kind}'", "unknown_kind", 500)
    created = now()
    change = {
        "change_id": "CH-" + secrets.token_hex(6),
        "kind": kind,
        "summary": summary,
        "payload": copy.deepcopy(payload),
        "payload_digest": digest(payload),
        "staged_by": actor,
        "created": created.isoformat(),
        "expires": (created + TTL).isoformat(),
    }
    with _lock:
        _staged[change["change_id"]] = change
    _log("stage", change, actor)
    return {"needs_approval": True, "summary": summary, "change_id": change["change_id"],
            "payload_digest": change["payload_digest"], "expires": change["expires"]}


def pending():
    with _lock:
        return [{k: v for k, v in c.items() if k != "payload"} for c in _staged.values()]


def approve(change_id, email, expected_digest=None):
    if not config.is_owner(email):
        raise GateError("Only an NTXP owner can approve staged changes", "not_owner", 403)
    with _lock:
        change = _staged.pop(change_id, None)
    if change is None:
        raise GateError("Unknown or already-used change id", "not_found", 404)
    if now() > datetime.fromisoformat(change["expires"]):
        _log("expired", change, email)
        raise GateError("Staged change expired; stage it again", "expired", 410)
    if digest(change["payload"]) != change["payload_digest"] or (
            expected_digest and expected_digest != change["payload_digest"]):
        _log("digest_mismatch", change, email)
        raise GateError("Payload digest no longer matches the staged change", "digest_mismatch", 409)
    _log("approve", change, email)
    result = _executors[change["kind"]](change["payload"], email)
    _log("execute", change, email)
    return {"change_id": change_id, "kind": change["kind"], "summary": change["summary"],
            "approved_by": email, "result": result}


def reset():
    with _lock:
        _staged.clear()


def _log(event, change, actor):
    log.info("gate %s %s %s by %s", event, change["change_id"], change["kind"], actor)
    if not gws.sheets_configured() or config.DEMO:
        return
    try:
        gws.append_row("ChangeLog", [now().isoformat(), event, change["change_id"], change["kind"],
                                     change["summary"], change["payload_digest"], actor])
    except Exception as e:
        log.warning("ChangeLog append failed: %s", e)
