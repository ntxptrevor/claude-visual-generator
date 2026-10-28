#!/usr/bin/env python3
"""Drive a running NTXP Form Fill review GUI programmatically; every change shows live in the browser.

The GUI writes <session>/gui.json (owner-only) with its URL and token. This client reads the newest
one under NFF_HOME (or --session / --url) and talks to the same local API the browser uses, so a
script, an agent or ntxp-pdf-markups-and-redlines can mark up, stamp and edit a document while a
person watches it change.

Coordinates default to the ntxp-pdf-markups-and-redlines v3 convention: PDF points measured from
the page's top-left corner (use --origin bottom-left for raw PDF space).

Examples
  nff_live.py status
  nff_live.py cloud --page 1 --rect 96 128 268 232 --text "Clarify head height"
  nff_live.py arrow --page 1 --start 330 108 --end 262 158
  nff_live.py text --page 1 --rect 340 60 560 100 --text "RFI 042: confirm duct main elevation"
  nff_live.py stamp --page 1 --rect 400 640 590 740 --status "APPROVED AS NOTED" --reviewer "Alison Hopkins"
  nff_live.py import markups.v3.json
  nff_live.py field f3 "NTXP LLC"
  nff_live.py delete m1a2b3c4d5
  nff_live.py watch --count 3
  nff_live.py snapshot --page 1 --out page1.png
"""

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def nff_home():
    return Path(os.environ.get("NFF_HOME") or Path.home() / ".ntxp" / "nff")


def find_connection(session=None, url=None):
    if url:
        u = urlparse(url)
        token = (parse_qs(u.query).get("token") or [""])[0]
        if not token:
            raise SystemExit("ERROR: --url must include ?token=...")
        return {"base": f"{u.scheme}://{u.netloc}", "token": token}
    sessions = nff_home() / "sessions"
    if session:
        files = [sessions / session / "gui.json"]
    else:
        files = sorted(sessions.glob("*/gui.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files:
        if not f.is_file():
            continue
        info = json.loads(f.read_text())
        if not _listening(info.get("port")):
            continue  # stale file from a GUI that was killed before it could clean up
        u = urlparse(info["url"])
        return {"base": f"{u.scheme}://{u.netloc}", "token": info["token"]}
    raise SystemExit("ERROR: no running NTXP Form Fill GUI found (start nff_gui.py, or pass --url)")


def _listening(port):
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.5):
            return True
    except (OSError, TypeError, ValueError):
        return False


class Client:
    def __init__(self, conn, timeout=30):
        self.base, self.token, self.timeout = conn["base"], conn["token"], timeout

    def _req(self, method, path, body=None, raw=False):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"X-NFF-Token": self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = r.read()
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode()).get("error")
            except Exception:  # noqa: BLE001
                msg = str(e)
            raise SystemExit(f"ERROR {e.code}: {msg}")
        except urllib.error.URLError as e:
            raise SystemExit(f"ERROR: GUI not reachable at {self.base} ({e.reason})")
        return payload if raw else json.loads(payload.decode())

    def get(self, path, raw=False):
        return self._req("GET", path, raw=raw)

    def post(self, path, body):
        return self._req("POST", path, body)

    def events(self, since=None):
        """Yield {'event', 'rev'} from one server-sent event stream (the server ends it after 10 min)."""
        q = f"?since={since}" if since is not None else ""
        req = urllib.request.Request(self.base + "/api/events" + q, headers={"X-NFF-Token": self.token})
        with urllib.request.urlopen(req, timeout=60) as r:
            event, data = None, None
            for line in r:
                line = line.decode().rstrip("\n")
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
                elif line == "" and event:
                    yield {"event": event, **(json.loads(data) if data else {})}
                    event, data = None, None


def _markup_body(a, kind):
    body = {"kind": kind, "page": a.page, "origin": a.origin}
    if a.rect:
        body["rect"] = a.rect
    if a.start and a.end:
        body["start"], body["end"] = a.start, a.end
    if a.points:
        body["points"] = [[float(v) for v in p.split(",")] for p in a.points]
    for k in ("text", "color", "width", "subject", "trade", "author"):
        v = getattr(a, k, None)
        if v not in (None, ""):
            body[k] = v
    if kind == "stamp":
        body["status"] = a.status
        body["reviewer"] = a.reviewer or ""
        body["stamp_date"] = a.stamp_date or date.today().strftime("%m/%d/%Y")
    return body


def main(argv=None):
    ap = argparse.ArgumentParser(description="Drive a running NTXP Form Fill GUI (live view)")
    ap.add_argument("--session", help="session id (default: newest running GUI)")
    ap.add_argument("--url", help="GUI URL including ?token=")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    for kind in ("cloud", "rectangle", "ellipse", "arrow", "line", "polyline", "ink", "text", "area", "stamp"):
        p = sub.add_parser(kind, help=f"add a {kind} markup")
        p.add_argument("--page", type=int, required=True)
        p.add_argument("--rect", type=float, nargs=4, metavar=("X0", "Y0", "X1", "Y1"))
        p.add_argument("--start", type=float, nargs=2, metavar=("X", "Y"))
        p.add_argument("--end", type=float, nargs=2, metavar=("X", "Y"))
        p.add_argument("--points", nargs="+", metavar="X,Y")
        p.add_argument("--text")
        p.add_argument("--color")
        p.add_argument("--width", type=float)
        p.add_argument("--subject")
        p.add_argument("--trade")
        p.add_argument("--author", default=os.environ.get("NFF_USER", ""))
        p.add_argument("--origin", choices=("top-left", "bottom-left"), default="top-left")
        if kind == "stamp":
            p.add_argument("--status", required=True)
            p.add_argument("--reviewer")
            p.add_argument("--stamp-date")
    p = sub.add_parser("import", help="load an ntxp-pdf-markups-and-redlines manifest")
    p.add_argument("manifest")
    p.add_argument("--replace", action="store_true", help="replace existing markups (stamps are kept)")
    p = sub.add_parser("delete", help="delete a markup")
    p.add_argument("id")
    p = sub.add_parser("field", help="set a field value")
    p.add_argument("id")
    p.add_argument("value")
    p.add_argument("--approve", action="store_true")
    p = sub.add_parser("watch", help="print live change events")
    p.add_argument("--count", type=int, default=0, help="stop after N changes (0 = run until Ctrl-C)")
    p = sub.add_parser("snapshot", help="save a PNG of a page with every overlay applied")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    c = Client(find_connection(a.session, a.url))
    if a.cmd == "status":
        st = c.get("/api/session")
        out = {"session_id": st["session_id"], "form": st["form_name"], "rev": st.get("rev"),
               "pages": len(st["pages"]), "fields": len(st["fields"]), "markups": len(st.get("markups", [])),
               "progress": st["progress"]}
    elif a.cmd == "import":
        manifest = json.loads(Path(a.manifest).read_text())
        out = c.post("/api/markups/import", {"manifest": manifest, "replace": a.replace})
    elif a.cmd == "delete":
        out = c.post("/api/markup/delete", {"id": a.id})
    elif a.cmd == "field":
        body = {"id": a.id, "value": a.value}
        if a.approve:
            body["approve"] = True
        r = c.post("/api/field", body)
        out = {"ok": r["ok"], "field": {k: r["field"].get(k) for k in ("id", "label", "value", "approved")}}
    elif a.cmd == "watch":
        n, since = 0, None
        try:
            while True:  # reconnect from the last revision, as the browser's EventSource does
                try:
                    for ev in c.events(since):
                        print(json.dumps(ev), flush=True)
                        since = ev.get("rev", since)
                        if ev["event"] == "change":
                            n += 1
                            if a.count and n >= a.count:
                                return 0
                except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
                    print(json.dumps({"event": "reconnecting", "reason": str(e)[:120]}), flush=True)
                    time.sleep(1.5)
        except KeyboardInterrupt:
            return 0
    elif a.cmd == "snapshot":
        png = c.get(f"/api/page/{a.page}/live.png", raw=True)
        Path(a.out).write_bytes(png)
        out = {"ok": True, "out": a.out, "bytes": len(png)}
    else:
        out = c.post("/api/markup", _markup_body(a, a.cmd))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
