#!/usr/bin/env python3
"""
NTXP Form Fill manual Drive scan -> proposals -> one-page checklist -> approved rows.

  python scripts/nff_scan.py --from-manifest docs.json [--days 30]     # [{id,title,mimeType,modifiedTime,folder,text}]
  python scripts/nff_scan.py --live [--days 30] [--company-folder ID] [--bids-folder ID]
  python scripts/nff_scan.py --list                                    # pending proposals (banking masked)
  python scripts/nff_scan.py --apply ID1,ID2 [--approve-tier3] [--live]

Nothing is added to the Sheet until a proposal is approved with --apply. Tier 1 fields, retired values,
prices, SSN/DOB are never proposed. Banking and tax-id proposals are flagged "Tier 3" and cannot be
applied without --approve-tier3 (explicit owner approval); their values are masked in all printouts
unless that flag is given.
"""

import argparse
import hashlib
import html
import io
import json
import os
import re
import sys
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nff_db as db  # noqa: E402
import nff_canonical as can  # noqa: E402
import nff_drive_scanner as scanner  # noqa: E402
from nff_signatures import TIER1_FIELD_OVERRIDES  # noqa: E402

DEFAULT_COMPANY_FOLDER = "1MBEgq8tlfCvJdeTqG6lGtrFaXKuvISM9"
DEFAULT_BIDS_FOLDER = "1rs1P8FuhQamouFRDv29f9hIR1rmKqKfs"

RETIRED_VALUES = ["405 S Elm St Ste 203", "405 S Elm St"]
PRICE_RE = re.compile(r"(price|amount|cost|total|bid_|fee)", re.I)
SKIP_FIELDS = {"ssn", "dob"}
TIER3_CATEGORIES = {"banking", "tax_id"}
CANONICAL_CATEGORIES = {"financial", "banking", "tax_id", "insurance", "bonding", "legal"}
FINAL_RE = re.compile(r"final|submitted|executed|signed|response", re.I)
KB_FILE_RE = re.compile(r"knowledge base|\bKB\b|\.json$", re.I)
FOLDER_MIME = "application/vnd.google-apps.folder"

EXTRA_EXTRACTORS = [
    (r"(?i)routing\s*(?:number|no\.?|#)?\s*[:\-]?\s*(\d{9})\b", "routing_number", "banking"),
    (r"(?i)(?:bank\s*)?account\s*(?:number|no\.?|#)\s*[:\-]?\s*(\d{4,17})\b", "bank_account_number", "banking"),
    (r"(?i)\b(?:EIN|Tax\s*ID)\b[^0-9\n]{0,15}(\d{2}-?\d{7})", "ein", "tax_id"),
]

KB_HEADERS = ["id", "category", "field_name", "field_value", "field_type", "confidence", "source",
              "alternates", "correction_count", "last_corrected", "correction_reason", "created_at", "updated_at"]


# ------------------------------------------------------------------ helpers
def _one_line(e):
    s = str(e).strip().splitlines()
    return (s[0] if s else type(e).__name__)[:200]


def retired_list(conn):
    extra = (db.get_state(conn, "setting:retired_values", "") or "")
    return RETIRED_VALUES + [x.strip() for x in re.split(r"[|;\n]", extra) if x.strip()]


def is_retired(value, retired):
    v = str(value).lower()
    return any(can.normalize(value) == can.normalize(r) or r.lower() in v for r in retired)


def setting(conn, key, default):
    return db.get_state(conn, "setting:" + key, None) or default


def parse_time(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def in_window(item, days):
    t = parse_time(item.get("modifiedTime"))
    if t is None:
        return True
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t >= datetime.now(timezone.utc) - timedelta(days=days)


def _kb_json_candidates(text):
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    out = []
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (str, int, float)) and str(v).strip():
                name = re.sub(r"\W+", "_", str(k)).strip("_").lower()
                cat = "banking" if re.search(r"routing|account|ach", name) else "other"
                out.append({"field_name": name, "field_value": str(v).strip(), "category": cat})
    return out


def extract(item):
    text = item.get("text") or ""
    form_type = (scanner.classify_file(item.get("title", "")) or scanner.classify_content(text) or {}).get("form_type")
    found = [{"field_name": r["field_name"], "field_value": r["field_value"], "category": r["category"]}
             for r in scanner.extract_fields_from_text(text, form_type)]
    names = {f["field_name"] for f in found}
    for pat, name, cat in EXTRA_EXTRACTORS:
        m = re.search(pat, text)
        if m and name not in names:
            found.append({"field_name": name, "field_value": m.group(1), "category": cat})
    if KB_FILE_RE.search(item.get("title", "")):
        found += [f for f in _kb_json_candidates(text) if f["field_name"] not in names]
    return found


# ------------------------------------------------------------------ proposals
def build_proposals(conn, items, days=30):
    retired = retired_list(conn)
    kb = {r["field_name"]: dict(r) for r in conn.execute("SELECT * FROM kb_fields")}
    canon = {}
    for r in conn.execute("SELECT * FROM canonical"):
        canon[r["field_name"]] = dict(r)

    cands, cats, meta = {}, {}, {}
    for item in items:
        if not in_window(item, days):
            continue
        for f in extract(item):
            name, val = f["field_name"], f["field_value"]
            if (name in TIER1_FIELD_OVERRIDES or name in SKIP_FIELDS or PRICE_RE.search(name)
                    or is_retired(val, retired)):
                continue
            c = {"field_value": val, "source_kind": "drive_scan", "source_title": item.get("title", ""),
                 "source_ref": str(item.get("id", "")), "source_date": str(item.get("modifiedTime", ""))[:10]}
            cands.setdefault(name, []).append(c)
            cats.setdefault(name, f["category"])
            meta[(name, can.normalize(val))] = c

    rows = []
    for name, scan_c in cands.items():
        cur_row = canon.get(name) or kb.get(name)
        current = cur_row["field_value"] if cur_row else ""
        category = (cur_row or {}).get("category") or cats[name]
        if cats[name] in TIER3_CATEGORIES:
            category = cats[name]
        all_c = list(scan_c)
        if cur_row:
            kind = "owner_canonical" if name in canon else "kb_manual"
            all_c.append({"field_value": current, "source_kind": kind, "source_title": "NTXP database",
                          "source_ref": "", "source_date": str((cur_row.get("updated_at") or cur_row.get("source_date") or ""))[:10]})
        decision = can.determine(name, all_c, category, retired)
        tier3 = category.lower() in TIER3_CATEGORIES
        seen = set()
        for c in scan_c:
            n = can.normalize(c["field_value"])
            if n in seen or (cur_row and n == can.normalize(current)):
                continue
            seen.add(n)
            kind = "NEW" if not cur_row else ("CONFLICT" if decision["status"] == "conflict" else "CHANGED")
            evidence = f"[{kind}]" + (" [Tier 3]" if tier3 else "") + f" {decision['basis']}"
            pid = hashlib.sha1(f"{name}|{n}".encode()).hexdigest()[:12]
            rows.append({"proposal_id": pid, "field_name": name, "proposed_value": c["field_value"],
                         "current_value": current, "category": category, "evidence": evidence,
                         "source_title": c["source_title"], "source_ref": c["source_ref"], "status": "pending"})
    return rows


def kind_of(p):
    m = re.match(r"\[(\w+)\]", p.get("evidence", ""))
    return m.group(1) if m else "NEW"


def is_tier3(p):
    return "[Tier 3]" in p.get("evidence", "") or str(p.get("category", "")).lower() in TIER3_CATEGORIES


def shown(p, which, reveal=False):
    v = p["proposed_value"] if which == "new" else p["current_value"]
    return v if reveal else can.mask(v, p["category"])


# ------------------------------------------------------------------ checklist
PAGE_W, PAGE_H = 612.0, 792.0
MARGIN, LEAD, FONT = 43.0, 12.0, 8.5


def _line_text(p):
    cur = shown(p, "cur") or "(none)"
    t3 = " [Tier 3]" if is_tier3(p) else ""
    return f"{p['field_name']}: {cur} -> {shown(p, 'new')}  [{kind_of(p)}]{t3}  src: {p['source_title']}"


def _fit(text, width, font="Helvetica", size=FONT):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    if stringWidth(text, font, size) <= width:
        return text
    while text and stringWidth(text + "...", font, size) > width:
        text = text[:-1]
    return text + "..."


def select_for_page(proposals):
    """Group by category; return (layout, hidden_count) sized to fit one page."""
    top, bottom = 90.0, 40.0
    capacity = int((PAGE_H - top - bottom) // LEAD) - 1  # last line reserved for the "+N more" note
    groups = {}
    for p in proposals:
        groups.setdefault(p["category"] or "other", []).append(p)
    layout, used, shown_n = [], 0, 0
    for cat in sorted(groups):
        if used + 2 > capacity:
            break
        layout.append(("h", cat))
        used += 1
        for p in groups[cat]:
            if used + 1 > capacity:
                break
            layout.append(("p", p))
            used += 1
            shown_n += 1
    return layout, len(proposals) - shown_n


def write_checklist(proposals, out_dir=None):
    out_dir = Path(out_dir) if out_dir else db.nff_home() / "proposals"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    layout, hidden = select_for_page(proposals)
    more = f"+{hidden} more in the GUI" if hidden else ""

    li = []
    for kind, v in layout:
        if kind == "h":
            li.append(f"<h2>{html.escape(v.upper())}</h2>")
        else:
            li.append(f'<label class="row"><input type="checkbox" data-id="{html.escape(v["proposal_id"])}"> '
                      f'<span>{html.escape(_line_text(v))}</span></label>')
    html_doc = (
        "<!doctype html><html><head><meta charset='utf-8'><title>NTXP Scan Checklist</title>"
        "<style>@page{size:8.5in 11in;margin:.5in}body{font:11px Helvetica,Arial,sans-serif;max-width:7.5in;margin:auto}"
        "h1{text-align:center;font-size:18px;margin:0}p.sub{text-align:center;margin:2px 0 10px}"
        "h2{font-size:11px;border-bottom:1px solid #000;margin:8px 0 3px}.row{display:block;padding:1px 0}"
        "</style></head><body><h1>NTXP Form Fill - Scan Checklist</h1>"
        f"<p class='sub'><b>{stamp}</b> - {len(proposals)} proposal(s) - check a line, then Apply approved</p>"
        + "\n".join(li) + (f"<p><b>{more}</b></p>" if more else "") + "</body></html>")
    html_path = out_dir / f"checklist-{stamp}.html"
    html_path.write_text(html_doc, encoding="utf-8")

    pdf_path = out_dir / f"checklist-{stamp}.pdf"
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(pdf_path), pagesize=(PAGE_W, PAGE_H))
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 50, "NTXP Form Fill - Scan Checklist")
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 66, f"{stamp}  |  {len(proposals)} proposal(s)  |  check a line, then Apply approved")
    y = PAGE_H - 90
    width = PAGE_W - 2 * MARGIN - 18
    for kind, v in layout:
        if kind == "h":
            c.setFont("Helvetica-Bold", 9.5)
            c.drawString(MARGIN, y - 8, v.upper())
            c.line(MARGIN, y - 10, PAGE_W - MARGIN, y - 10)
        else:
            c.rect(MARGIN, y - 8, 8, 8, stroke=1, fill=0)
            c.setFont("Helvetica", FONT)
            c.drawString(MARGIN + 14, y - 8, _fit(_line_text(v), width))
        y -= LEAD
    if more:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(MARGIN, y - 8, more)
    c.showPage()
    c.save()
    return {"html": str(html_path), "pdf": str(pdf_path), "shown": len(proposals) - hidden, "hidden": hidden}


# ------------------------------------------------------------------ apply
def queue_rows(out):
    """Durable local queue for approved rows that were not written live (the agent appends them)."""
    path = db.nff_home() / "sheet_append_queue.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"queued_at": db.now(), "canonical": out["canonical"], "kb": out["kb"],
                             "applied": out["applied"]}) + "\n")
    return path


def apply_proposals(conn, ids, approve_tier3=False, user="", writer=None):
    """Build Sheet rows for approved proposals. `writer` (append_live, or the local queue by default)
    runs before anything is marked approved, so a failed write leaves the proposals pending and retryable."""
    writer = writer or queue_rows
    props = {p["proposal_id"]: p for p in db.list_proposals(conn, "all")}
    canon_rows, kb_rows, skipped = [], [], []
    canon_group, kb_group = [], []
    today, stamp = datetime.now().strftime("%Y-%m-%d"), db.now()
    for i in ids:
        p = props.get(i)
        if not p or p["status"] != "pending":
            skipped.append({"id": i, "reason": "not found or not pending"})
            continue
        if is_tier3(p) and not approve_tier3:
            skipped.append({"id": i, "reason": "Tier 3 (banking/tax id): rerun with --approve-tier3 after explicit owner approval"})
            continue
        val = p["proposed_value"]
        if p["category"].lower() in CANONICAL_CATEGORIES:
            canon_rows.append([f"scan-{i}", "", p["category"], p["field_name"], val, "drive_scan", p["source_title"],
                               p["source_ref"], today, "approved", user, stamp, "approved from scan proposal"])
            canon_group.append(p)
        else:
            kb_rows.append([uuid.uuid4().hex[:8], p["category"], p["field_name"], val,
                            scanner._infer_field_type(p["field_name"], val), 75, "drive_scan", "", 0, "", "",
                            stamp, stamp])
            kb_group.append(p)
    out = {"applied": [], "skipped": skipped,
           "canonical": {"headers": can.CANONICAL_HEADERS, "rows": canon_rows},
           "kb": {"headers": KB_HEADERS, "rows": kb_rows}}
    # One Sheet tab at a time. A tab's proposals are marked approved only after that tab's own
    # append succeeds, so a retry after a later failure never repeats rows that already landed.
    for tab, group in (("canonical", canon_group), ("kb", kb_group)):
        if not group:
            continue
        if writer:
            writer({"applied": [p["proposal_id"] for p in group], "skipped": skipped,
                    "canonical": {"headers": can.CANONICAL_HEADERS, "rows": canon_rows if tab == "canonical" else []},
                    "kb": {"headers": KB_HEADERS, "rows": kb_rows if tab == "kb" else []}})
        for p in group:
            db.set_proposal_status(conn, [p["proposal_id"]], "approved")
            db.record_change(conn, field_name=p["field_name"], old_value=can.mask(p["current_value"], p["category"]),
                             new_value=can.mask(p["proposed_value"], p["category"]), action="approved_proposal",
                             decision="saved", user=user,
                             notes=f"scan proposal {p['proposal_id']} from {p['source_title']}")
            out["applied"].append(p["proposal_id"])
    return out


def mask_apply_output(out):
    """Printable copy: mask value columns unless Tier 3 was explicitly approved."""
    o = json.loads(json.dumps(out))
    for r in o["canonical"]["rows"]:
        r[4] = can.mask(r[4], r[2])
    return o


def append_live(out):
    import nff_sync
    svc = nff_sync.sheets_service(write=True)
    for tab, key in (("Canonical", "canonical"), ("KB", "kb")):
        rows = out[key]["rows"]
        if rows:
            try:
                svc.spreadsheets().values().append(
                    spreadsheetId=nff_sync.sheet_id(), range=f"{tab}!A:A", valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS", body={"values": rows}).execute()
            except Exception as e:
                raise RuntimeError(f"Could not append to {tab} tab: {_one_line(e)}") from None


# ------------------------------------------------------------------ live Drive
def _drive():
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "google_workspace"))
        from ntxp_google_access import service
        return service("drive")
    except Exception as e:
        raise RuntimeError(f"Live Google access unavailable: {_one_line(e)}") from None


def _list(drive, q):
    files, token = [], None
    while True:
        r = drive.files().list(q=q, pageSize=200, pageToken=token, orderBy="modifiedTime desc",
                               fields="nextPageToken, files(id,name,mimeType,modifiedTime,parents)",
                               supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        files += r.get("files", [])
        token = r.get("nextPageToken")
        if not token or len(files) > 1000:
            return files


def _pdf_text(data):
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join((pg.extract_text() or "") for pg in pdf.pages)
    except ImportError:
        pass
    from pypdf import PdfReader
    return "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(data)).pages)


def _docx_text(data):
    try:
        import docx
        d = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in d.paragraphs)
    except ImportError:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        return re.sub(r"<[^>]+>", " ", xml.replace("</w:p>", "\n"))


def _text_of(drive, f):
    mt, fid = f["mimeType"], f["id"]
    if mt == "application/vnd.google-apps.document":
        data = drive.files().export_media(fileId=fid, mimeType="text/plain").execute()
    elif mt == "application/vnd.google-apps.spreadsheet":
        data = drive.files().export_media(fileId=fid, mimeType="text/csv").execute()
    elif mt == "application/pdf" or mt.endswith("wordprocessingml.document") \
            or mt.startswith("text/") or mt == "application/json":
        data = drive.files().get_media(fileId=fid, supportsAllDrives=True).execute()
        if mt == "application/pdf":
            return _pdf_text(data)
        if mt.endswith("wordprocessingml.document"):
            return _docx_text(data)
    else:
        return ""
    return (data.decode("utf-8", "ignore") if isinstance(data, bytes) else str(data))[:200000]


def collect_live(conn, days, company_folder, bids_folder):
    drive = _drive()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    items = []

    def walk(folder, depth=2):
        # A new final response inside an old folder does not move the folder's own modifiedTime,
        # so folders are always walked and only the files are date-filtered.
        out = []
        for f in _list(drive, f"'{folder}' in parents and trashed=false"):
            if f["mimeType"] == FOLDER_MIME:
                if depth > 1:
                    out += walk(f["id"], depth - 1)
            elif f.get("modifiedTime", "") > since:
                out.append(f)
        return out

    def add(f, folder_label):
        try:
            t = _text_of(drive, f)
        except Exception as e:
            print(f"warning: could not read {f['name']}: {_one_line(e)}", file=sys.stderr)
            return
        if t:
            items.append({"id": f["id"], "title": f["name"], "mimeType": f["mimeType"],
                          "modifiedTime": f.get("modifiedTime", ""), "folder": folder_label, "text": t})

    try:
        for f in walk(company_folder):
            add(f, "company_docs")
        for sub in _list(drive, f"'{bids_folder}' in parents and trashed=false and mimeType='{FOLDER_MIME}'"):
            files = walk(sub["id"])
            finals = [f for f in files if FINAL_RE.search(f["name"])]
            picks = finals[:1] + [f for f in files if KB_FILE_RE.search(f["name"]) and f not in finals[:1]]
            for f in picks:
                add(f, "closed_bids/" + sub["name"])
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Drive scan failed: {_one_line(e)}") from None
    return items


# ------------------------------------------------------------------ CLI
def main(argv=None):
    p = argparse.ArgumentParser(description="NTXP Form Fill Drive scan")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--live", action="store_true")
    src.add_argument("--from-manifest", metavar="FILE")
    p.add_argument("--days", type=int)
    p.add_argument("--company-folder")
    p.add_argument("--bids-folder")
    p.add_argument("--list", action="store_true")
    p.add_argument("--apply", metavar="IDS")
    p.add_argument("--approve-tier3", action="store_true")
    p.add_argument("--user", default=os.environ.get("NFF_USER", ""))
    a = p.parse_args(argv)
    try:
        conn = db.connect()
        if a.list:
            for x in db.list_proposals(conn, "pending"):
                print(f"{x['proposal_id']}  {_line_text(x)}")
            return 0
        if a.apply:
            ids = [i for i in re.split(r"[,\s]+", a.apply) if i]
            out = apply_proposals(conn, ids, a.approve_tier3, a.user, writer=append_live if a.live else None)
            if not a.live and (out["canonical"]["rows"] or out["kb"]["rows"]):
                print(f"queued Sheet rows: {db.nff_home() / 'sheet_append_queue.jsonl'}", file=sys.stderr)
            if a.live and (out["canonical"]["rows"] or out["kb"]["rows"]):
                print(json.dumps({"appended_live": True, "applied": out["applied"], "skipped": out["skipped"]}, indent=2))
            else:
                print(json.dumps(out if a.approve_tier3 else mask_apply_output(out), indent=2, ensure_ascii=False))
            return 0
        days = a.days or int(setting(conn, "scan_recent_days", 30))
        if a.live:
            items = collect_live(conn, days, a.company_folder or setting(conn, "company_docs_folder_id", DEFAULT_COMPANY_FOLDER),
                                 a.bids_folder or setting(conn, "closed_bids_folder_id", DEFAULT_BIDS_FOLDER))
        elif a.from_manifest:
            items = json.load(open(a.from_manifest, encoding="utf-8"))
        else:
            p.error("choose --live, --from-manifest, --list or --apply")
        new = build_proposals(conn, items, days)
        added = db.add_proposals(conn, new)
        pending = db.list_proposals(conn, "pending")
        res = write_checklist(pending)
        print(json.dumps({"documents": len(items), "new_proposals": added, "pending": len(pending), **res}, indent=2))
        return 0
    except (RuntimeError, ValueError, OSError, KeyError, ImportError) as e:
        print(f"ERROR: {_one_line(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
