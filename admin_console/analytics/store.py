"""NTXP Admin Intelligence DB.

Backend: the Google Sheet `config.ADMIN_DB_SHEET_ID` (one tab per table), or a local JSON
file (`NTXP_ADMIN_DB_PATH`) in demo mode, in tests, or when Sheets is not configured.

Single writer: every write goes through the functions in this module and is serialized
with a process lock (plus an fcntl file lock for the JSON backend). Rows are flat dicts;
list/dict values are JSON-encoded in Sheets cells and decoded on read.
"""

import contextlib
import json
import os
import tempfile
import threading
from pathlib import Path

from admin_console import config
from admin_console.analytics import google, util

SCHEMA = {
    "Flags": ["id", "key", "person", "kpi", "level", "urgency", "channel", "severity",
              "confidence", "volatility", "summary", "evidence", "crosscheck", "council",
              "created", "status", "escalations", "updated", "deferred", "floor_level"],
    "Reports": ["id", "report_id", "title", "generated", "period_from", "period_to",
                "sources", "body", "jev"],
    "Interactions": ["id", "at", "actor", "kind", "request_type", "flag_id", "action",
                     "kpi", "level", "note"],
    "Baselines": ["id", "person", "metric", "median", "mad", "n", "latest", "z",
                  "window_days", "updated"],
    "Classifications": ["id", "flag_id", "at", "kpi", "rule", "urgency", "severity",
                        "level", "confidence", "volatility"],
    "DailyNotes": ["id", "date", "person", "items", "flag_ids", "created", "updated",
                   "consumed"],
    "Learning": ["id", "at", "kind", "kpi", "param", "before", "after", "precision", "n",
                 "status", "note"],
    "Runbook": ["id", "workflow", "symptom", "likely_cause", "steps", "escalate_to", "tier",
                "updated", "status"],
    "SharedContacts": ["id", "name", "given", "family", "emails", "phones", "org", "title",
                       "address", "notes", "labels", "owner_user", "source_ref", "updated"],
    "ChangeLog": ["id", "at", "actor", "tab", "action", "ref", "summary"],
}

JSON_COLUMNS = {"evidence", "crosscheck", "council", "escalations", "items", "flag_ids",
                "sources", "body", "jev", "steps", "emails", "phones", "labels"}
NUMERIC_COLUMNS = {"level", "confidence", "volatility", "median", "mad", "n", "latest", "z",
                   "window_days", "precision", "before", "after", "tier", "floor_level"}

_LOCK = threading.RLock()
_BACKEND = None


def default_path():
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(Path.home(), ".local", "share")
    return os.path.join(base, "ntxp", "admin_intelligence.json")


# --------------------------------------------------------------------------- backends

class JsonBackend:
    kind = "json"

    def __init__(self, path=None):
        self.path = path or os.environ.get("NTXP_ADMIN_DB_PATH") or default_path()

    @contextlib.contextmanager
    def _file_lock(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path + ".lock"
        with open(lock_path, "a+") as fh:
            try:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            try:
                yield
            finally:
                try:
                    import fcntl
                    fcntl.flock(fh, fcntl.LOCK_UN)
                except (ImportError, OSError):
                    pass

    def _read(self):
        try:
            with open(self.path) as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write(self, data):
        folder = Path(self.path).parent
        folder.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".adb-", suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=1, default=str)
        os.replace(tmp, self.path)

    def ensure_schema(self):
        with self._file_lock():
            data = self._read()
            created = [t for t in SCHEMA if t not in data]
            for t in created:
                data[t] = []
            data.setdefault("_headers", {})
            data["_headers"].update({t: cols for t, cols in SCHEMA.items()})
            self._write(data)
        return created

    def rows(self, tab):
        return list(self._read().get(tab, []))

    def mutate(self, tab, fn):
        with self._file_lock():
            data = self._read()
            rows = data.setdefault(tab, [])
            result = fn(rows)
            self._write(data)
            return result


class SheetsBackend:
    """Google Sheets backend. One tab per table, header row 1."""
    kind = "sheets"

    def __init__(self, sheet_id, svc=None):
        self.sheet_id = sheet_id
        self._svc = svc

    @property
    def svc(self):
        if self._svc is None:
            self._svc = google.service("sheets", allow_write=True)
        return self._svc

    def _values(self):
        return self.svc.spreadsheets().values()

    def ensure_schema(self):
        meta = self.svc.spreadsheets().get(spreadsheetId=self.sheet_id).execute()
        have = {s["properties"]["title"] for s in meta.get("sheets", [])}
        missing = [t for t in SCHEMA if t not in have]
        if missing:
            self.svc.spreadsheets().batchUpdate(
                spreadsheetId=self.sheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": t}}} for t in missing]},
            ).execute()
        for tab, cols in SCHEMA.items():
            got = self._values().get(spreadsheetId=self.sheet_id, range=f"{tab}!1:1").execute()
            header = (got.get("values") or [[]])[0]
            if header[: len(cols)] != cols:
                merged = cols + [c for c in header if c not in cols]
                self._values().update(spreadsheetId=self.sheet_id, range=f"{tab}!A1",
                                      valueInputOption="RAW", body={"values": [merged]}).execute()
        return missing

    def _table(self, tab):
        got = self._values().get(spreadsheetId=self.sheet_id, range=tab).execute()
        values = got.get("values") or []
        if not values:
            return SCHEMA[tab], []
        header = values[0]
        rows = []
        for raw in values[1:]:
            raw = list(raw) + [""] * (len(header) - len(raw))
            rows.append({h: _decode(h, v) for h, v in zip(header, raw)})
        return header, rows

    def rows(self, tab):
        return self._table(tab)[1]

    def mutate(self, tab, fn):
        header, rows = self._table(tab)
        before = [json.dumps(r, sort_keys=True, default=str) for r in rows]
        result = fn(rows)
        for i, row in enumerate(rows):
            line = [_encode(h, row.get(h)) for h in header]
            if i >= len(before):
                self._values().append(spreadsheetId=self.sheet_id, range=tab,
                                      valueInputOption="RAW", insertDataOption="INSERT_ROWS",
                                      body={"values": [line]}).execute()
            elif json.dumps(row, sort_keys=True, default=str) != before[i]:
                self._values().update(spreadsheetId=self.sheet_id, range=f"{tab}!A{i + 2}",
                                      valueInputOption="RAW", body={"values": [line]}).execute()
        return result


def _encode(col, value):
    if value is None:
        return ""
    if col in JSON_COLUMNS or isinstance(value, (list, dict)):
        return json.dumps(value, default=str)
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return value


def _decode(col, value):
    if value in ("", None):
        return None
    if col in JSON_COLUMNS and isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    if col in NUMERIC_COLUMNS and isinstance(value, str):
        try:
            f = float(value)
            return int(f) if f.is_integer() and col in ("level", "n", "tier", "window_days",
                                                         "floor_level") else f
        except ValueError:
            return value
    if value in ("TRUE", "FALSE"):
        return value == "TRUE"
    return value


# --------------------------------------------------------------------------- selection

def backend():
    global _BACKEND
    with _LOCK:
        if _BACKEND is None:
            if config.ADMIN_DB_SHEET_ID and google.live():
                _BACKEND = SheetsBackend(config.ADMIN_DB_SHEET_ID)
            else:
                _BACKEND = JsonBackend()
        return _BACKEND


def use_backend(b):
    """Swap the backend (tests, or a fresh JSON path). Returns the previous one."""
    global _BACKEND
    with _LOCK:
        prev, _BACKEND = _BACKEND, b
        return prev


def use_json(path):
    return use_backend(JsonBackend(path))


def status():
    """'ok' when the Sheets DB is in use; 'unconfigured' when running on the local JSON file."""
    return "ok" if backend().kind == "sheets" else "unconfigured"


# --------------------------------------------------------------------------- API

def ensure_schema():
    with _LOCK:
        return backend().ensure_schema()


def _clean(tab, row):
    cols = SCHEMA[tab]
    return {c: row.get(c) for c in cols} | {k: v for k, v in row.items() if k not in cols}


def append(tab, row):
    return append_many(tab, [row])[0]


def append_many(tab, rows):
    _check(tab)
    rows = [_clean(tab, r) for r in rows]
    with _LOCK:
        def fn(table):
            table.extend(rows)
            return rows
        return backend().mutate(tab, fn)


def update(tab, row_id, fields):
    """Merge fields into the row with this id. Returns the new row, or None."""
    _check(tab)
    with _LOCK:
        def fn(table):
            for r in table:
                if r.get("id") == row_id:
                    r.update(fields)
                    return dict(r)
            return None
        return backend().mutate(tab, fn)


def upsert(tab, row, key="id"):
    _check(tab)
    row = _clean(tab, row)
    with _LOCK:
        def fn(table):
            for r in table:
                if r.get(key) == row.get(key):
                    r.update({k: v for k, v in row.items() if v is not None})
                    return dict(r)
            table.append(row)
            return dict(row)
        return backend().mutate(tab, fn)


def get(tab, row_id):
    for r in rows(tab):
        if r.get("id") == row_id:
            return r
    return None


def rows(tab):
    _check(tab)
    with _LOCK:
        return backend().rows(tab)


def query(tab, where=None, limit=None, order_by=None, reverse=False):
    """where: dict of equality filters, or a callable(row) -> bool."""
    out = rows(tab)
    if callable(where):
        out = [r for r in out if where(r)]
    elif where:
        out = [r for r in out if all(r.get(k) == v for k, v in where.items())]
    if order_by:
        out.sort(key=lambda r: (r.get(order_by) is None, r.get(order_by)), reverse=reverse)
    return out[:limit] if limit else out


def next_id(tab, prefix):
    """Sequential id like FL-2026-10-09-001 (prefix 'FL-2026-10-09')."""
    with _LOCK:
        n = sum(1 for r in rows(tab) if str(r.get("id", "")).startswith(prefix + "-"))
        return f"{prefix}-{n + 1:03d}"


def log_change(actor, tab, action, ref, summary):
    return append("ChangeLog", {"id": next_id("ChangeLog", "CL-" + util.central_day(None)),
                                "at": util.iso(None), "actor": actor, "tab": tab,
                                "action": action, "ref": ref, "summary": util.short_quote(summary)})


def _check(tab):
    if tab not in SCHEMA:
        raise KeyError(f"Unknown tab {tab!r}; choose from {sorted(SCHEMA)}")
