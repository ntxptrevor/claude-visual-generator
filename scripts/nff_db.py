#!/usr/bin/env python3
"""
NTXP Form Fill local database (SQLite, stdlib only, WAL).

Schema and public API follow .claude/skills/ntxp-form-fill/ARCHITECTURE.md.
The database lives outside the repo: NFF_HOME/nff.sqlite (NFF_HOME defaults to ~/.ntxp/nff).
It holds EIN and banking data, so values in confidential categories (banking, tax_id) are never
printed unmasked: pass masked=True to kb_values / canonical_rows for anything that is logged.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

CHANGE_LOG_HEADERS = [
    "logged_at", "field_name", "form_field_title", "form_name", "old_value",
    "new_value", "action", "decision", "user", "session_id", "notes",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_fields(
  field_name TEXT PRIMARY KEY, category TEXT, field_value TEXT, field_type TEXT,
  confidence INTEGER, source TEXT, alternates TEXT, correction_count INTEGER DEFAULT 0,
  updated_at TEXT, sheet_row INTEGER);
CREATE TABLE IF NOT EXISTS canonical(
  answer_id TEXT PRIMARY KEY, exhibit TEXT, category TEXT, field_name TEXT, field_value TEXT,
  source_kind TEXT, source_title TEXT, source_ref TEXT, source_date TEXT, status TEXT,
  verified_by TEXT, verified_at TEXT, notes TEXT, sheet_row INTEGER);
CREATE TABLE IF NOT EXISTS workflows(
  workflow_id TEXT PRIMARY KEY, form_type TEXT, form_pattern TEXT, field_map_json TEXT,
  save_location TEXT, jev_tier TEXT);
CREATE TABLE IF NOT EXISTS change_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, logged_at TEXT, field_name TEXT, form_field_title TEXT,
  form_name TEXT, old_value TEXT, new_value TEXT, action TEXT, decision TEXT, user TEXT,
  session_id TEXT, notes TEXT, pushed_to_sheet INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS field_outcomes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, field_name TEXT, source_kind TEXT, accepted INTEGER, at TEXT);
CREATE TABLE IF NOT EXISTS proposals(
  proposal_id TEXT PRIMARY KEY, created_at TEXT, field_name TEXT, proposed_value TEXT,
  current_value TEXT, category TEXT, evidence TEXT, source_title TEXT, source_ref TEXT,
  status TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS sync_state(key TEXT PRIMARY KEY, value TEXT);
"""

CONFIDENTIAL = {"banking", "tax_id"}


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nff_home():
    return Path(os.environ.get("NFF_HOME") or Path.home() / ".ntxp" / "nff")


def db_path():
    return nff_home() / "nff.sqlite"


def mask(value, category):
    """Mask banking / tax-id values (last 4 characters visible). Idempotent."""
    s = "" if value is None else str(value)
    if (category or "").lower() in CONFIDENTIAL and len(s) > 4:
        return "•" * (len(s) - 4) + s[-4:]
    return s


def connect(path=None):
    p = Path(path) if path else db_path()
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    old_umask = os.umask(0o077)  # DB holds banking and tax-id values: owner-only files
    try:
        conn = sqlite3.connect(str(p))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        os.umask(old_umask)
    for f in (p, Path(f"{p}-wal"), Path(f"{p}-shm")):
        if f.exists():
            os.chmod(f, 0o600)
    return conn


def kb_values(conn, masked=False):
    out = {}
    for r in conn.execute("SELECT field_name, category, field_value FROM kb_fields ORDER BY field_name"):
        out[r["field_name"]] = mask(r["field_value"], r["category"]) if masked else r["field_value"]
    return out


def canonical_rows(conn, masked=False):
    rows = []
    for r in conn.execute("SELECT * FROM canonical ORDER BY answer_id"):
        d = dict(r)
        if masked:
            d["field_value"] = mask(d["field_value"], d["category"])
        rows.append(d)
    return rows


def sensitive_field_names(conn):
    names = set()
    for t in ("kb_fields", "canonical"):
        for r in conn.execute(f"SELECT DISTINCT field_name FROM {t} WHERE lower(category) IN ('banking','tax_id')"):
            names.add(r[0])
    return names


def record_change(conn, **f):
    row = {h: "" for h in CHANGE_LOG_HEADERS}
    row.update({"logged_at": now(), "decision": "n/a"})
    row.update({k: ("" if v is None else v) for k, v in f.items() if k in CHANGE_LOG_HEADERS})
    cols = list(row)
    cur = conn.execute(f"INSERT INTO change_log({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                       [row[c] for c in cols])
    conn.commit()
    return cur.lastrowid


def record_outcome(conn, field_name, source_kind, accepted):
    conn.execute("INSERT INTO field_outcomes(field_name, source_kind, accepted, at) VALUES(?,?,?,?)",
                 (field_name, source_kind, 1 if accepted else 0, now()))
    conn.commit()


def outcome_counts(conn, field_name):
    r = conn.execute("SELECT COALESCE(SUM(accepted),0), COALESCE(SUM(1-accepted),0) "
                     "FROM field_outcomes WHERE field_name=?", (field_name,)).fetchone()
    return int(r[0]), int(r[1])


def add_proposals(conn, rows):
    """Insert proposals; an existing proposal_id keeps its status (rejected stays rejected)."""
    n = 0
    for r in rows:
        cur = conn.execute(
            "INSERT OR IGNORE INTO proposals(proposal_id, created_at, field_name, proposed_value, "
            "current_value, category, evidence, source_title, source_ref, status) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (r["proposal_id"], r.get("created_at") or now(), r["field_name"], r.get("proposed_value", ""),
             r.get("current_value", ""), r.get("category", "other"), r.get("evidence", ""),
             r.get("source_title", ""), r.get("source_ref", ""), r.get("status", "pending")))
        n += cur.rowcount
    conn.commit()
    return n


def list_proposals(conn, status="pending"):
    if status in (None, "all"):
        q = conn.execute("SELECT * FROM proposals ORDER BY category, field_name")
    else:
        q = conn.execute("SELECT * FROM proposals WHERE status=? ORDER BY category, field_name", (status,))
    return [dict(r) for r in q]


def set_proposal_status(conn, ids, status):
    ids = list(ids)
    for i in ids:
        conn.execute("UPDATE proposals SET status=? WHERE proposal_id=?", (status, str(i)))
    conn.commit()
    return len(ids)


def pending_sheet_changes(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM change_log WHERE pushed_to_sheet=0 ORDER BY id")]


def mark_pushed(conn, ids):
    for i in ids:
        conn.execute("UPDATE change_log SET pushed_to_sheet=1 WHERE id=?", (int(i),))
    conn.commit()


def get_state(conn, key, default=None):
    r = conn.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def set_state(conn, key, value):
    conn.execute("INSERT INTO sync_state(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, value if isinstance(value, str) else json.dumps(value)))
    conn.commit()


def main():
    conn = connect()
    print(json.dumps({"db": str(db_path()),
                      "kb_fields": conn.execute("SELECT COUNT(*) FROM kb_fields").fetchone()[0],
                      "canonical": conn.execute("SELECT COUNT(*) FROM canonical").fetchone()[0],
                      "workflows": conn.execute("SELECT COUNT(*) FROM workflows").fetchone()[0]}, indent=2))


if __name__ == "__main__":
    sys.exit(main())
