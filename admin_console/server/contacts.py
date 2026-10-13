"""Shared Contacts: directory profiles, personal Google Contacts and the IPDM shared DB sheet."""

import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from admin_console import config

from . import contact_formats as cf
from . import demo, gate, gws

TAB = "SharedContacts"
COLUMNS = ["id", "name", "given", "family", "emails", "phones", "org", "title", "address", "notes",
           "labels", "owner_user", "source_ref", "updated"]
CONTACT_KEYS = ("id", "source", "name", "given", "family", "emails", "phones", "org", "title", "address",
                "notes", "labels", "shared", "owner_user", "updated")
EDITABLE = {"name", "given", "family", "emails", "phones", "org", "title", "address", "notes", "labels"}
LIST_FIELDS = ("emails", "phones", "labels")
PERSON_FIELDS = "names,emailAddresses,phoneNumbers,organizations,addresses,biographies,memberships,metadata"
CACHE_TTL = 120


class ContactError(Exception):
    def __init__(self, message, code, status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def public(c):
    return {k: c.get(k, [] if k in LIST_FIELDS else "") for k in CONTACT_KEYS}


# ---------- pure conversions ----------

def row_to_contact(row):
    c = {k: row.get(k, "") for k in COLUMNS}
    for k in LIST_FIELDS:
        c[k] = [v for v in (row.get(k) or "").split("|") if v]
    c["id"] = row["id"] if row["id"].startswith("shared:") else "shared:" + row["id"]
    c["source"] = "shared"
    c["shared"] = True
    return c


def contact_to_row(c, source_ref=""):
    row = {k: c.get(k, "") for k in COLUMNS}
    for k in LIST_FIELDS:
        row[k] = "|".join(c.get(k) or [])
    row["id"] = c["id"] if c.get("id", "").startswith("shared:") else "shared:sc-" + secrets.token_hex(4)
    row["source_ref"] = source_ref or c.get("source_ref", "")
    row["updated"] = now_iso()
    return row


def person_to_contact(person, source, owner_user, group_names=None):
    group_names = group_names or {}
    names = (person.get("names") or [{}])[0]
    org = (person.get("organizations") or [{}])[0]
    addr = (person.get("addresses") or [{}])[0]
    labels = []
    for m in person.get("memberships") or []:
        rn = (m.get("contactGroupMembership") or {}).get("contactGroupResourceName", "")
        if rn in group_names:
            labels.append(group_names[rn])
    rn = person.get("resourceName", "")
    cid = f"dir:{owner_user}" if source == "directory" else f"ws:{owner_user}:{rn}"
    updated = ((person.get("metadata") or {}).get("sources") or [{}])[0].get("updateTime", "")
    c = cf.new_contact(
        id=cid, source=source,
        name=names.get("displayName", ""), given=names.get("givenName", ""), family=names.get("familyName", ""),
        emails=[e["value"] for e in person.get("emailAddresses") or [] if e.get("value")],
        phones=[p["value"] for p in person.get("phoneNumbers") or [] if p.get("value")],
        org=org.get("name", ""), title=org.get("title", ""),
        address=(addr.get("formattedValue") or "").replace("\n", ", "),
        notes=((person.get("biographies") or [{}])[0]).get("value", ""),
        labels=labels, owner_user=owner_user, updated=updated)
    c["shared"] = config.SHARED_CONTACTS_LABEL in labels
    c["etag"] = person.get("etag", "")
    c["resource"] = rn
    return c


def contact_to_person(fields):
    """People API body and updatePersonFields for the editable fields given."""
    body, mask = {}, []
    if {"name", "given", "family"} & set(fields):
        body["names"] = [{k2: fields[k1] for k1, k2 in (("given", "givenName"), ("family", "familyName"))
                          if k1 in fields}]
        if "name" in fields and not ({"given", "family"} & set(fields)):
            given, _, family = fields["name"].partition(" ")
            body["names"] = [{"givenName": given, "familyName": family}]
        mask.append("names")
    if "emails" in fields:
        body["emailAddresses"] = [{"value": e} for e in fields["emails"]]
        mask.append("emailAddresses")
    if "phones" in fields:
        body["phoneNumbers"] = [{"value": p} for p in fields["phones"]]
        mask.append("phoneNumbers")
    if {"org", "title"} & set(fields):
        body["organizations"] = [{"name": fields.get("org", ""), "title": fields.get("title", "")}]
        mask.append("organizations")
    if "address" in fields:
        body["addresses"] = [{"formattedValue": fields["address"]}] if fields["address"] else []
        mask.append("addresses")
    if "notes" in fields:
        body["biographies"] = [{"value": fields["notes"], "contentType": "TEXT_PLAIN"}]
        mask.append("biographies")
    return body, ",".join(mask)


def plan_sync(workspace, rows, pulled_users):
    """Upsert labelled workspace contacts into shared rows; drop rows whose source lost the label.

    Returns (new_rows, added, removed). Rows owned by users that failed to load are left alone.
    """
    label = config.SHARED_CONTACTS_LABEL
    labelled = {c["id"]: c for c in workspace if label in (c.get("labels") or [])}
    by_ref = {r.get("source_ref"): r for r in rows if r.get("source_ref", "").startswith("ws:")}
    out, added, removed = [], 0, 0
    for r in rows:
        ref = r.get("source_ref", "")
        if ref.startswith("ws:"):
            owner = ref[3:].split(":", 1)[0]
            if ref not in labelled and owner in pulled_users:
                removed += 1
                continue
            if ref in labelled:
                src = labelled[ref]
                r = {**r, **contact_to_row({**src, "labels": [x for x in src["labels"] if x != label]}, ref),
                     "id": r["id"]}
        out.append(r)
    for cid, c in labelled.items():
        if cid not in by_ref:
            out.append(contact_to_row({**c, "id": "", "labels": [x for x in c["labels"] if x != label]}, cid))
            added += 1
    return out, added, removed


def _clean_fields(fields):
    bad = set(fields) - EDITABLE
    if bad:
        raise ContactError(f"Fields not editable: {', '.join(sorted(bad))}", "bad_field")
    out = {}
    for k, v in fields.items():
        if k in LIST_FIELDS:
            if isinstance(v, str):
                v = [x.strip() for x in v.replace("|", ",").split(",")]
            out[k] = [str(x).strip() for x in v if str(x).strip()]
        else:
            out[k] = str(v)
    return out


def _parse_ws_id(cid):
    user, _, resource = cid[3:].partition(":")
    return user, resource


# ---------- backends ----------

class DemoBackend:
    def _all(self):
        return demo.state("contacts", lambda: [c for c in demo.contacts() if c["source"] != "shared"])

    def directory(self):
        return [c for c in self._all() if c["source"] == "directory"]

    def workspace(self):
        ws = [c for c in self._all() if c["source"] == "workspace"]
        return ws, {c["owner_user"] for c in ws} | set(config.OWNER_EMAILS)

    def shared_rows(self):
        def build():
            rows = []
            for c in demo.contacts():
                if c["source"] == "shared":
                    row = contact_to_row(c, demo.SHARED_SOURCE_REFS.get(c["id"], ""))
                    row["updated"] = c["updated"]
                    rows.append(row)
            return rows
        return demo.state("shared_rows", build)

    def write_shared(self, rows):
        demo.state("shared_rows", list)[:] = rows

    def _find(self, cid):
        for c in self._all():
            if c["id"] == cid:
                return c
        raise ContactError(f"Contact {cid} not found", "not_found", 404)

    def ws_update(self, c, fields):
        target = self._find(c["id"])
        target.update(fields)
        target["updated"] = now_iso()
        return dict(target)

    def ws_label(self, c, label, add):
        target = self._find(c["id"])
        labels = [x for x in target["labels"] if x != label] + ([label] if add else [])
        target["labels"] = labels
        target["shared"] = config.SHARED_CONTACTS_LABEL in labels
        return dict(target)

    def ws_delete(self, c):
        self._all().remove(self._find(c["id"]))

    def ws_create(self, c, user):
        new = public({**c, "id": f"ws:{user}:people/c{secrets.randbelow(10**9)}", "source": "workspace",
                      "owner_user": user, "updated": now_iso()})
        self._all().append(new)
        return new


class GoogleBackend:
    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()

    def _cached(self, key, fn):
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.time() - hit[0] < CACHE_TTL:
                return hit[1]
        value = fn()
        with self._lock:
            self._cache[key] = (time.time(), value)
        return value

    def invalidate(self):
        with self._lock:
            self._cache.clear()

    def directory(self):
        def load():
            subject = os.environ.get("NTXP_GOOGLE_ADMIN_SUBJECT")
            people = gws.service("contacts", user=subject).people()
            out, token = [], None
            while True:
                resp = people.listDirectoryPeople(
                    readMask="names,emailAddresses,phoneNumbers,organizations,addresses,metadata",
                    sources=["DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE"], pageSize=1000, pageToken=token).execute()
                for p in resp.get("people", []):
                    email = next((e["value"] for e in p.get("emailAddresses", []) if e.get("value")), "")
                    if email:
                        out.append(person_to_contact(p, "directory", email.lower()))
                token = resp.get("nextPageToken")
                if not token:
                    return out
        return self._cached("directory", load)

    def _groups(self, user, write=False):
        svc = gws.service("contacts", user=user, allow_write=write)
        resp = svc.contactGroups().list(pageSize=1000).execute()
        return svc, {g["resourceName"]: g.get("formattedName") or g.get("name", "")
                     for g in resp.get("contactGroups", [])}

    def _user_contacts(self, user):
        svc, groups = self._groups(user)
        out, token = [], None
        while True:
            resp = svc.people().connections().list(resourceName="people/me", personFields=PERSON_FIELDS,
                                                   pageSize=1000, pageToken=token).execute()
            out += [person_to_contact(p, "workspace", user, groups) for p in resp.get("connections", [])]
            token = resp.get("nextPageToken")
            if not token:
                return out

    def workspace(self):
        def load():
            users = gws.domain_users()
            contacts, pulled = [], set()
            with ThreadPoolExecutor(max_workers=8) as pool:
                for user, fut in [(u, pool.submit(self._user_contacts, u)) for u in users]:
                    try:
                        contacts += fut.result()
                        pulled.add(user)
                    except Exception:
                        continue
            return contacts, pulled
        return self._cached("workspace", load)

    def shared_rows(self):
        return [r for r in gws.read_tab(TAB) if r.get("id")]

    def write_shared(self, rows):
        gws.write_tab(TAB, COLUMNS, rows)

    def ws_update(self, c, fields):
        user, resource = _parse_ws_id(c["id"])
        svc = gws.service("contacts", user=user, allow_write=True).people()
        current = svc.get(resourceName=resource, personFields=PERSON_FIELDS).execute()
        body, mask = contact_to_person({**{k: c.get(k) for k in ("org", "title")}, **fields})
        body["etag"] = current["etag"]
        updated = svc.updateContact(resourceName=resource, updatePersonFields=mask, body=body,
                                    personFields=PERSON_FIELDS).execute()
        self.invalidate()
        return person_to_contact(updated, "workspace", user, self._groups(user)[1])

    def ws_label(self, c, label, add):
        user, resource = _parse_ws_id(c["id"])
        svc, groups = self._groups(user, write=True)
        group = next((rn for rn, name in groups.items() if name == label), None)
        if group is None:
            if not add:
                return c
            group = svc.contactGroups().create(body={"contactGroup": {"name": label}}).execute()["resourceName"]
        key = "resourceNamesToAdd" if add else "resourceNamesToRemove"
        svc.contactGroups().members().modify(resourceName=group, body={key: [resource]}).execute()
        self.invalidate()
        labels = [x for x in c.get("labels", []) if x != label] + ([label] if add else [])
        return {**c, "labels": labels, "shared": config.SHARED_CONTACTS_LABEL in labels}

    def ws_delete(self, c):
        user, resource = _parse_ws_id(c["id"])
        gws.service("contacts", user=user, allow_write=True).people().deleteContact(
            resourceName=resource).execute()
        self.invalidate()

    def ws_create(self, c, user):
        body, _ = contact_to_person({k: c[k] for k in EDITABLE if c.get(k)})
        person = gws.service("contacts", user=user, allow_write=True).people().createContact(
            body=body, personFields=PERSON_FIELDS).execute()
        self.invalidate()
        return person_to_contact(person, "workspace", user)


_google = GoogleBackend()


def backend():
    if gws.live():
        return _google
    return DemoBackend()


def _shared_available(b):
    return isinstance(b, DemoBackend) or gws.sheets_configured()


# ---------- operations ----------

def all_contacts(b, source="all"):
    out = []
    if source in ("all", "directory"):
        out += b.directory()
    if source in ("all", "workspace"):
        out += b.workspace()[0]
    if source in ("all", "shared") and _shared_available(b):
        out += [row_to_contact(r) for r in b.shared_rows()]
    return out


def _matches(c, q):
    hay = " ".join([c.get("name", ""), c.get("org", ""), c.get("title", ""), c.get("notes", ""),
                    *c.get("emails", []), *c.get("phones", []), *c.get("labels", [])]).lower()
    digits = cf.normalize_phone(q)
    return all(t in hay for t in q.lower().split()) or (
        bool(digits) and any(cf.normalize_phone(p) == digits for p in c.get("phones", [])))


def list_contacts(source="all", q="", limit=100, cursor=None):
    if source not in ("all", "workspace", "directory", "shared"):
        raise ContactError("source must be all, workspace, directory or shared", "bad_source")
    items = all_contacts(backend(), source)
    if q:
        items = [c for c in items if _matches(c, q)]
    items.sort(key=lambda c: (c.get("name") or "").lower())
    start = int(cursor) if cursor and str(cursor).isdigit() else 0
    limit = max(1, min(int(limit or 100), 1000))
    page = items[start:start + limit]
    nxt = str(start + limit) if start + limit < len(items) else None
    return {"contacts": [public(c) for c in page], "next_cursor": nxt}


def _find(b, cid):
    if cid.startswith("dir:"):
        pool = b.directory()
    elif cid.startswith("ws:"):
        pool = b.workspace()[0]
    elif cid.startswith("shared:"):
        pool = [row_to_contact(r) for r in b.shared_rows()] if _shared_available(b) else []
    else:
        raise ContactError(f"Unrecognized contact id {cid}", "bad_id")
    for c in pool:
        if c["id"] == cid:
            return c
    raise ContactError(f"Contact {cid} not found", "not_found", 404)


def _upsert_shared(b, contact, source_ref):
    rows = b.shared_rows()
    label = config.SHARED_CONTACTS_LABEL
    clean = {**contact, "labels": [x for x in contact.get("labels", []) if x != label]}
    for i, r in enumerate(rows):
        if source_ref and r.get("source_ref") == source_ref:
            rows[i] = {**contact_to_row(clean, source_ref), "id": r["id"]}
            b.write_shared(rows)
            return rows[i]
    row = contact_to_row({**clean, "id": ""}, source_ref)
    b.write_shared(rows + [row])
    return row


def _remove_shared(b, predicate):
    rows = b.shared_rows()
    keep = [r for r in rows if not predicate(r)]
    if len(keep) != len(rows):
        b.write_shared(keep)
    return len(rows) - len(keep)


def patch_contact(cid, fields):
    b = backend()
    fields = _clean_fields(fields)
    if not fields:
        raise ContactError("No fields to update", "empty")
    c = _find(b, cid)
    if c["source"] == "directory":
        raise ContactError("Directory profiles are read-only here. Edit the user in the Google Admin console "
                           "(Directory > Users) or share the contact and edit the shared copy.",
                           "read_only", 409)
    if c["source"] == "workspace":
        updated = b.ws_update(c, fields)
        if updated.get("shared") and _shared_available(b):
            _upsert_shared(b, updated, updated["id"])
        return public(updated)
    rows = b.shared_rows()
    for i, r in enumerate(rows):
        if row_to_contact(r)["id"] == cid:
            merged = {**row_to_contact(r), **fields}
            rows[i] = {**contact_to_row(merged, r.get("source_ref", "")), "id": r["id"]}
            b.write_shared(rows)
            ref = r.get("source_ref", "")
            if ref.startswith("ws:"):
                try:
                    b.ws_update(_find(b, ref), fields)
                except ContactError:
                    pass
            return public(row_to_contact(rows[i]))
    raise ContactError(f"Contact {cid} not found", "not_found", 404)


def bulk(ids, action, label, actor):
    if action not in ("share", "unshare", "label", "unlabel", "delete"):
        raise ContactError("action must be share, unshare, label, unlabel or delete", "bad_action")
    if not ids:
        raise ContactError("ids is required", "empty")
    if action in ("label", "unlabel") and not label:
        raise ContactError("label is required for label/unlabel", "bad_label")
    b = backend()
    if action == "delete":
        found = []
        for cid in ids:
            c = _find(b, cid)
            if c["source"] == "directory":
                raise ContactError("Directory profiles cannot be deleted from here", "read_only", 409)
            found.append(f"{c['name'] or cid} ({c['source']})")
        summary = f"Delete {len(ids)} contact(s): " + ", ".join(found[:10]) + ("…" if len(found) > 10 else "")
        staged = gate.stage("contacts.delete", summary, {"ids": sorted(ids)}, actor)
        return {**staged, "done": 0, "failed": [], "tier": 3}

    done, failed = 0, []
    shared_label = config.SHARED_CONTACTS_LABEL
    for cid in ids:
        try:
            c = _find(b, cid)
            if action == "share":
                if c["source"] == "workspace":
                    c = b.ws_label(c, shared_label, True)
                if c["source"] != "shared":
                    _require_sheet(b)
                    _upsert_shared(b, c, c["id"])
            elif action == "unshare":
                _require_sheet(b)
                if c["source"] == "shared":
                    ref = next((r.get("source_ref", "") for r in b.shared_rows()
                                if row_to_contact(r)["id"] == cid), "")
                    _remove_shared(b, lambda r: row_to_contact(r)["id"] == cid)
                    if ref.startswith("ws:"):
                        b.ws_label(_find(b, ref), shared_label, False)
                else:
                    if c["source"] == "workspace":
                        b.ws_label(c, shared_label, False)
                    _remove_shared(b, lambda r: r.get("source_ref") == cid)
            else:
                add = action == "label"
                if c["source"] == "directory":
                    raise ContactError("Directory profiles are read-only", "read_only", 409)
                if c["source"] == "workspace":
                    b.ws_label(c, label, add)
                else:
                    rows = b.shared_rows()
                    for i, r in enumerate(rows):
                        if row_to_contact(r)["id"] == cid:
                            labels = [x for x in row_to_contact(r)["labels"] if x != label] + ([label] if add else [])
                            rows[i] = {**r, "labels": "|".join(labels), "updated": now_iso()}
                    b.write_shared(rows)
            done += 1
        except Exception as e:
            failed.append({"id": cid, "error": str(e)})
    return {"done": done, "failed": failed, "tier": 2}


def _require_sheet(b):
    if not _shared_available(b):
        raise ContactError("Shared contacts DB is not configured (NTXP_ADMIN_DB_SHEET_ID)", "unconfigured", 503)


def execute_delete(payload, approver):
    b = backend()
    done, failed = 0, []
    for cid in payload["ids"]:
        try:
            c = _find(b, cid)
            if c["source"] == "workspace":
                b.ws_delete(c)
                if _shared_available(b):
                    _remove_shared(b, lambda r: r.get("source_ref") == cid)
            elif c["source"] == "shared":
                _remove_shared(b, lambda r: row_to_contact(r)["id"] == cid)
            else:
                raise ContactError("Directory profiles cannot be deleted", "read_only", 409)
            done += 1
        except Exception as e:
            failed.append({"id": cid, "error": str(e)})
    return {"done": done, "failed": failed, "tier": 3}


gate.register("contacts.delete", execute_delete)


def import_file(data, fmt, target, commit, actor):
    if target not in ("shared", "workspace"):
        raise ContactError("target must be shared or workspace", "bad_target")
    try:
        fmt, incoming = cf.parse(data, fmt)
    except ValueError as e:
        raise ContactError(str(e), "bad_format") from e
    b = backend()
    if target == "shared":
        existing = [row_to_contact(r) for r in b.shared_rows()] if _shared_available(b) else []
    else:
        existing = [c for c in b.workspace()[0] if c["owner_user"] == actor]
    for i, c in enumerate(incoming):
        c["id"] = f"import:{i}"
        c["source"] = target
        c["owner_user"] = actor
    unique, dupes = cf.dedupe(incoming, existing)
    created = 0
    if commit and unique:
        if target == "shared":
            _require_sheet(b)
            rows = b.shared_rows()
            b.write_shared(rows + [contact_to_row({**c, "id": ""}) for c in unique])
            created = len(unique)
        else:
            for c in unique:
                b.ws_create(c, actor)
                created += 1
    return {"format": fmt, "preview": [public(c) for c in incoming[:500]],
            "duplicates": [{"incoming": public(d["incoming"]), "existing_id": d["existing_id"]} for d in dupes],
            "created": created, "skipped": len(dupes)}


def export_csv(ids=None, source="shared"):
    b = backend()
    if ids:
        contacts = [_find(b, cid) for cid in ids]
    else:
        contacts = all_contacts(b, source or "shared")
    return cf.export_google_csv(contacts)


def sync():
    b = backend()
    workspace, pulled = b.workspace()
    _require_sheet(b)
    rows, added, removed = plan_sync(workspace, b.shared_rows(), pulled)
    b.write_shared(rows)
    return {"pulled": len(workspace), "shared_added": added, "shared_removed": removed}
