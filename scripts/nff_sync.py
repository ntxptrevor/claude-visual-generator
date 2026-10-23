#!/usr/bin/env python3
"""
NTXP Form Filler sync: Google Sheet -> SQLite (one way, the Sheet wins).

  python scripts/nff_sync.py --from-json tabs.json      # {tab: [[header...], [row...]]} (Sheets MCP get_values)
  python scripts/nff_sync.py --from-csv-dir DIR          # KB.csv, Canonical.csv, Workflows.csv [, Settings.csv]
  python scripts/nff_sync.py --live                      # Sheets API (needs NTXP_GOOGLE_* credentials)
  python scripts/nff_sync.py --status
  python scripts/nff_sync.py --push-changes [--live]     # change_log -> Sheet "Change Log" tab (or print JSON rows)
  python scripts/nff_sync.py --mark-pushed 3,4,5         # after the agent appended the printed rows

Tabs absent from the input are left untouched; a tab present with only a header deletes its rows.
Banking / tax-id values are masked in every printout and in change_log rows written by sync.
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nff_db as db  # noqa: E402

DEFAULT_SHEET_ID = "1KYFkZoEWNvbAYqZ0Vq4LOUPh9QM4MiIYyqPmDyIelQA"

TABS = {
    "KB": {"table": "kb_fields", "key": "field_name",
           "cols": ["category", "field_value", "field_type", "confidence", "source", "alternates",
                    "correction_count", "updated_at"],
           "ints": {"confidence", "correction_count"}, "value": "field_value"},
    "Canonical": {"table": "canonical", "key": "answer_id",
                  "cols": ["exhibit", "category", "field_name", "field_value", "source_kind", "source_title",
                           "source_ref", "source_date", "status", "verified_by", "verified_at", "notes"],
                  "ints": set(), "value": "field_value"},
    "Workflows": {"table": "workflows", "key": "workflow_id",
                  "cols": ["form_type", "form_pattern", "field_map_json", "save_location", "jev_tier"],
                  "ints": set(), "value": "field_map_json"},
}
SETTING_PREFIX = "setting:"


def sheet_id():
    return os.environ.get("NFF_SHEET_ID") or DEFAULT_SHEET_ID


# ---------------------------------------------------------------- input readers
def read_json(path):
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, dict) and "tabs" in data:
        data = data["tabs"]
    return {k: v.get("values", v) if isinstance(v, dict) else v for k, v in data.items()}


def read_csv_dir(d):
    out = {}
    for f in Path(d).glob("*.csv"):
        for tab in list(TABS) + ["Settings", "Change Log"]:
            if f.stem.lower().replace("_", " ") == tab.lower():
                with open(f, newline="", encoding="utf-8") as fh:
                    out[tab] = [list(r) for r in csv.reader(fh)]
    return out


def sheets_service(write=False):
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "google_workspace"))
        from ntxp_google_access import service
        return service("sheets", allow_write=write)
    except Exception as e:  # missing libs, credentials, domain check
        raise RuntimeError(f"Live Google access unavailable: {_one_line(e)}") from None


def read_live():
    svc = sheets_service()
    out = {}
    for tab in list(TABS) + ["Settings"]:
        try:
            r = svc.spreadsheets().values().get(spreadsheetId=sheet_id(), range=tab).execute()
            out[tab] = r.get("values", [])
        except Exception as e:
            if tab == "Settings" or "Unable to parse range" in str(e):
                continue
            raise RuntimeError(f"Could not read tab '{tab}': {_one_line(e)}") from None
    return out


def _one_line(e):
    s = str(e).strip().splitlines()
    return (s[0] if s else type(e).__name__)[:200]


# ---------------------------------------------------------------- sync core
def _records(tab, rows):
    spec = TABS[tab]
    if not rows:
        return []
    header = [str(h).strip().lower() for h in rows[0]]
    if spec["key"] not in header:
        raise ValueError(f"Tab '{tab}' has no '{spec['key']}' column")
    out = []
    for i, raw in enumerate(rows[1:], start=2):
        cells = list(raw) + [""] * (len(header) - len(raw))
        rec = {h: ("" if c is None else str(c).strip()) for h, c in zip(header, cells)}
        if not rec.get(spec["key"]):
            continue
        rec["_row"] = i
        out.append(rec)
    return out


def _coerce(spec, rec):
    vals = {}
    for c in spec["cols"]:
        v = rec.get(c, "")
        if c in spec["ints"]:
            try:
                v = int(float(v)) if v != "" else 0
            except ValueError:
                v = 0
        vals[c] = v
    return vals


def _log_value(row_or_vals, category):
    return db.mask(row_or_vals, category)


def sync_tab(conn, tab, rows):
    spec = TABS[tab]
    table, key = spec["table"], spec["key"]
    recs = _records(tab, rows)
    existing = {r[key]: dict(r) for r in conn.execute(f"SELECT * FROM {table}")}
    seen, stats = set(), {"added": 0, "updated": 0, "deleted": 0, "unchanged": 0}

    for rec in recs:
        k = rec[key]
        if k in seen:
            continue
        seen.add(k)
        vals = _coerce(spec, rec)
        cur = existing.get(k)
        has_row = "sheet_row" in [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        extra = {"sheet_row": rec["_row"]} if has_row else {}
        if cur is None:
            cols = [key] + list(vals) + list(extra)
            conn.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                         [k] + list(vals.values()) + list(extra.values()))
            stats["added"] += 1
            continue
        changed = any(str(cur.get(c) if cur.get(c) is not None else "") != str(v) for c, v in vals.items())
        if changed:
            sets = {**vals, **extra}
            conn.execute(f"UPDATE {table} SET {','.join(c + '=?' for c in sets)} WHERE {key}=?",
                         list(sets.values()) + [k])
            vc = spec["value"]
            if str(cur.get(vc) or "") != str(vals[vc]):
                cat = vals.get("category", cur.get("category", ""))
                fname = vals.get("field_name") or k if tab != "Workflows" else k
                db.record_change(conn, field_name=fname, form_field_title="",
                                 old_value=_log_value(cur.get(vc), cat), new_value=_log_value(vals[vc], cat),
                                 action="sync_overwrite", decision="n/a", user="sync",
                                 notes=f"{tab} tab: Sheet value replaced local value")
            stats["updated"] += 1
        else:
            if extra and cur.get("sheet_row") != extra["sheet_row"]:
                conn.execute(f"UPDATE {table} SET sheet_row=? WHERE {key}=?", (rec["_row"], k))
            stats["unchanged"] += 1

    for k, cur in existing.items():
        if k in seen:
            continue
        conn.execute(f"DELETE FROM {table} WHERE {key}=?", (k,))
        vc = spec["value"]
        cat = cur.get("category", "")
        db.record_change(conn, field_name=(cur.get("field_name") or k) if tab != "Workflows" else k,
                         form_field_title="", old_value=_log_value(cur.get(vc), cat), new_value="",
                         action="sync_overwrite", decision="n/a", user="sync",
                         notes=f"{tab} tab: row removed from Sheet")
        stats["deleted"] += 1
    conn.commit()
    return stats


def sync_settings(conn, rows):
    n = 0
    for r in rows[1:] if rows else []:
        if len(r) >= 2 and str(r[0]).strip():
            db.set_state(conn, SETTING_PREFIX + str(r[0]).strip(), str(r[1]).strip())
            n += 1
    return n


def sync_all(conn, tabs):
    result = {}
    by_lower = {k.lower(): k for k in tabs}
    for tab in TABS:
        src = by_lower.get(tab.lower())
        if src is not None:
            result[tab] = sync_tab(conn, tab, tabs[src])
    if "settings" in by_lower:
        result["Settings"] = {"settings": sync_settings(conn, tabs[by_lower["settings"]])}
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {s['table']}").fetchone()[0] for t, s in TABS.items()}
    db.set_state(conn, "last_sync_at", db.now())
    db.set_state(conn, "rows_per_tab", counts)
    db.set_state(conn, "last_sheet_revision", sheet_id())
    return result


def status(conn):
    return {"db": str(db.db_path()), "last_sync_at": db.get_state(conn, "last_sync_at", "never"),
            "rows": {t: conn.execute(f"SELECT COUNT(*) FROM {s['table']}").fetchone()[0] for t, s in TABS.items()},
            "pending_change_log_rows": len(db.pending_sheet_changes(conn)),
            "pending_proposals": len(db.list_proposals(conn, "pending"))}


# ---------------------------------------------------------------- change log push
def change_rows(conn, masked=True):
    """Pending change_log rows as (ids, 2-D list in Sheet header order)."""
    sens = db.sensitive_field_names(conn) if masked else set()
    ids, rows = [], []
    for c in db.pending_sheet_changes(conn):
        ids.append(c["id"])
        row = []
        for h in db.CHANGE_LOG_HEADERS:
            v = "" if c.get(h) is None else str(c[h])
            if masked and c["field_name"] in sens and h in ("old_value", "new_value"):
                v = db.mask(v, "banking")
            row.append(v)
        rows.append(row)
    return ids, rows


def push_live(conn, ids, rows):
    if not rows:
        return 0
    svc = sheets_service(write=True)
    try:
        svc.spreadsheets().values().append(
            spreadsheetId=sheet_id(), range="Change Log!A:K", valueInputOption="RAW",
            insertDataOption="INSERT_ROWS", body={"values": rows}).execute()
    except Exception as e:
        raise RuntimeError(f"Could not append to Change Log tab: {_one_line(e)}") from None
    db.mark_pushed(conn, ids)
    return len(ids)


def main(argv=None):
    p = argparse.ArgumentParser(description="NTXP Form Filler Sheet -> SQLite sync")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--live", action="store_true", help="use the Sheets API (NTXP_GOOGLE_* env)")
    src.add_argument("--from-json", metavar="FILE")
    src.add_argument("--from-csv-dir", metavar="DIR")
    p.add_argument("--status", action="store_true")
    p.add_argument("--push-changes", action="store_true")
    p.add_argument("--mark-pushed", metavar="IDS")
    a = p.parse_args(argv)

    try:
        conn = db.connect()
        if a.mark_pushed:
            ids = [int(x) for x in a.mark_pushed.replace(",", " ").split()]
            db.mark_pushed(conn, ids)
            print(f"Marked {len(ids)} change_log row(s) as pushed.")
            return 0
        if a.status and not (a.live or a.from_json or a.from_csv_dir or a.push_changes):
            print(json.dumps(status(conn), indent=2))
            return 0
        if a.push_changes:
            ids, rows = change_rows(conn)
            if a.live:
                print(f"Pushed {push_live(conn, ids, rows)} change_log row(s) to the Change Log tab.")
            else:
                print(json.dumps(rows, ensure_ascii=False))
                if ids:
                    print(f"# ids: {','.join(map(str, ids))}  (append the array above to 'Change Log', "
                          f"then run --mark-pushed {','.join(map(str, ids))})", file=sys.stderr)
            return 0
        if a.live:
            tabs = read_live()
        elif a.from_json:
            tabs = read_json(a.from_json)
        elif a.from_csv_dir:
            tabs = read_csv_dir(a.from_csv_dir)
        else:
            p.error("choose --live, --from-json, --from-csv-dir, --status or --push-changes")
        result = sync_all(conn, tabs)
        print(json.dumps({"synced": result, **status(conn)}, indent=2))
        return 0
    except (RuntimeError, ValueError, OSError, KeyError) as e:
        print(f"ERROR: {_one_line(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
