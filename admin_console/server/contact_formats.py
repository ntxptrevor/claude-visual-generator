"""Contact file formats: vCard 3.0/4.0, Google CSV (legacy + current), Outlook CSV, generic CSV."""

import csv
import io
import quopri
import re

FIELDS = ("name", "given", "family", "emails", "phones", "org", "title", "address", "notes", "labels")

GOOGLE_MULTI = " ::: "


def new_contact(**kw):
    c = {"id": "", "source": "shared", "name": "", "given": "", "family": "", "emails": [],
         "phones": [], "org": "", "title": "", "address": "", "notes": "", "labels": [],
         "shared": False, "owner_user": "", "updated": ""}
    c.update(kw)
    if c["name"] and not c["given"] and not c["family"] and c["name"] != c["org"] and "@" not in c["name"]:
        parts = c["name"].split()
        if len(parts) > 1:
            c["given"], c["family"] = " ".join(parts[:-1]), parts[-1]
    if not c["name"]:
        c["name"] = " ".join(p for p in (c["given"], c["family"]) if p) or (
            c["org"] or (c["emails"][0] if c["emails"] else ""))
    return c


def _uniq(values):
    out = []
    for v in values:
        v = v.strip()
        if v and v not in out:
            out.append(v)
    return out


def normalize_email(e):
    return e.strip().lower()


def normalize_phone(p):
    digits = re.sub(r"\D", "", p or "")
    return digits[-10:] if len(digits) >= 7 else ""


def normalize_name(n):
    tokens = re.sub(r"[^a-z0-9 ]", " ", (n or "").lower()).split()
    return " ".join(sorted(tokens))


# ---------- detection ----------

def decode(data):
    if isinstance(data, str):
        return data
    for enc in ("utf-8-sig", "utf-16"):
        try:
            text = data.decode(enc)
            if enc == "utf-16" and "\x00" in text:
                continue
            return text
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _csv_header(text):
    first = text.lstrip().splitlines()[0] if text.strip() else ""
    try:
        return [h.strip() for h in next(csv.reader([first], delimiter=_delimiter(text)))]
    except StopIteration:
        return []


def detect_format(text):
    if re.search(r"^\s*BEGIN:VCARD", text, re.I | re.M):
        return "vcf"
    header = {h.lower() for h in _csv_header(text)}
    if "e-mail 1 - value" in header or ("given name" in header and "group membership" in header):
        return "google_csv"
    if "e-mail address" in header or ("business phone" in header and "job title" in header):
        return "outlook_csv"
    return "csv"


def parse(data, fmt="auto"):
    text = decode(data)
    fmt = detect_format(text) if fmt in (None, "", "auto") else fmt
    parser = {"vcf": parse_vcard, "google_csv": parse_google_csv,
              "outlook_csv": parse_outlook_csv, "csv": parse_generic_csv}.get(fmt)
    if parser is None:
        raise ValueError(f"Unknown contact format '{fmt}'")
    return fmt, parser(text)


# ---------- vCard ----------

def _unfold(text):
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if lines and raw[:1] in (" ", "\t"):
            lines[-1] += raw[1:]
        elif lines and lines[-1].endswith("=") and "QUOTED-PRINTABLE" in lines[-1].split(":", 1)[0].upper():
            lines[-1] += "\n" + raw
        else:
            lines.append(raw)
    return [ln for ln in lines if ln.strip()]


def _split_unescaped(value, sep):
    parts, cur, i = [], "", 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            cur += value[i:i + 2]
            i += 2
            continue
        if ch == sep:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    parts.append(cur)
    return parts


def _unescape(v):
    return re.sub(r"\\([\\,;nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v)


def _parse_property(line):
    in_quote, idx = False, -1
    for i, ch in enumerate(line):
        if ch == '"':
            in_quote = not in_quote
        elif ch == ":" and not in_quote:
            idx = i
            break
    if idx < 0:
        return None
    head, value = line[:idx], line[idx + 1:]
    parts = head.split(";")
    name = parts[0].split(".")[-1].upper()
    params = {"TYPE": []}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            k = k.upper()
            vals = [x.strip('"') for x in v.strip('"').split(",")]
            if k == "TYPE":
                params["TYPE"] += [x.lower() for x in vals]
            else:
                params[k] = vals[0]
        else:
            params["TYPE"].append(p.lower())
    if params.get("ENCODING", "").upper() == "QUOTED-PRINTABLE" or "quoted-printable" in params["TYPE"]:
        params["TYPE"] = [t for t in params["TYPE"] if t != "quoted-printable"]
        charset = params.get("CHARSET", "utf-8")
        value = quopri.decodestring(value.replace("=\n", "").encode("latin-1", "replace")).decode(
            charset, "replace")
    return name, params, value


def parse_vcard(text):
    contacts, card = [], None
    for line in _unfold(text):
        prop = _parse_property(line)
        if prop is None:
            continue
        name, params, value = prop
        if name == "BEGIN" and value.strip().upper() == "VCARD":
            card = {"emails": [], "phones": [], "labels": [], "fn": "", "n": None,
                    "org": "", "title": "", "address": "", "notes": []}
        elif name == "END" and card is not None:
            contacts.append(_card_to_contact(card))
            card = None
        elif card is not None:
            _apply_vcard_prop(card, name, params, value)
    return contacts


def _apply_vcard_prop(card, name, params, value):
    if name == "FN":
        card["fn"] = _unescape(value).strip()
    elif name == "N":
        card["n"] = [_unescape(x).strip() for x in _split_unescaped(value, ";")]
    elif name == "EMAIL":
        card["emails"].append(re.sub(r"^mailto:", "", _unescape(value), flags=re.I))
    elif name == "TEL":
        card["phones"].append(re.sub(r"^tel:", "", _unescape(value), flags=re.I))
    elif name == "ORG":
        card["org"] = _unescape(_split_unescaped(value, ";")[0]).strip()
    elif name == "TITLE":
        card["title"] = _unescape(value).strip()
    elif name == "ADR" and not card["address"]:
        comps = [_unescape(x).strip() for x in _split_unescaped(value, ";")] + [""] * 7
        _pobox, ext, street, city, region, postal, country = comps[:7]
        line1 = " ".join(p for p in (street, ext) if p)
        tail = " ".join(p for p in (region, postal) if p)
        card["address"] = ", ".join(p for p in (line1, city, tail, country) if p)
    elif name == "NOTE":
        card["notes"].append(_unescape(value).strip())
    elif name == "CATEGORIES":
        card["labels"] += [_unescape(x) for x in _split_unescaped(value, ",")]


def _card_to_contact(card):
    family = given = ""
    if card["n"]:
        family = card["n"][0]
        given = " ".join(p for p in card["n"][1:3] if p) if len(card["n"]) > 1 else ""
    return new_contact(name=card["fn"], given=given, family=family,
                       emails=_uniq(card["emails"]), phones=_uniq(card["phones"]),
                       org=card["org"], title=card["title"], address=card["address"],
                       notes="\n".join(n for n in card["notes"] if n), labels=_uniq(card["labels"]))


# ---------- CSV ----------

def _delimiter(text):
    sample = "\n".join(text.splitlines()[:5])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _rows(text):
    reader = csv.DictReader(io.StringIO(text.lstrip()), delimiter=_delimiter(text))
    for row in reader:
        yield {(k or "").strip(): (v or "").strip() for k, v in row.items() if k is not None}


def _numbered(row, pattern):
    """Values of columns like 'E-mail 3 - Value', in numeric order, splitting ' ::: '."""
    found = []
    for key, val in row.items():
        m = re.fullmatch(pattern, key, re.I)
        if m and val:
            found.append((int(m.group(1)), val))
    out = []
    for _, val in sorted(found):
        out += val.split(GOOGLE_MULTI.strip())
    return _uniq(out)


def _labels_from_google(value):
    return [lbl for lbl in _uniq(value.split(":::")) if not lbl.startswith("* ")]


def parse_google_csv(text):
    contacts = []
    for row in _rows(text):
        given = row.get("First Name") or row.get("Given Name", "")
        middle = row.get("Middle Name") or row.get("Additional Name", "")
        family = row.get("Last Name") or row.get("Family Name", "")
        address = row.get("Address 1 - Formatted", "")
        if not address:
            address = ", ".join(p for p in (row.get("Address 1 - Street", ""), row.get("Address 1 - City", ""),
                                            " ".join(p for p in (row.get("Address 1 - Region", ""),
                                                                 row.get("Address 1 - Postal Code", "")) if p),
                                            row.get("Address 1 - Country", "")) if p)
        c = new_contact(
            name=row.get("Name", "") or " ".join(p for p in (given, middle, family) if p),
            given=" ".join(p for p in (given, middle) if p), family=family,
            emails=_numbered(row, r"E-mail (\d+) - Value"),
            phones=_numbered(row, r"Phone (\d+) - Value"),
            org=row.get("Organization Name") or row.get("Organization 1 - Name", ""),
            title=row.get("Organization Title") or row.get("Organization 1 - Title", ""),
            address=address.replace("\n", ", "),
            notes=row.get("Notes", ""),
            labels=_labels_from_google(row.get("Labels") or row.get("Group Membership", "")))
        if _has_data(c):
            contacts.append(c)
    return contacts


OUTLOOK_PHONES = ("Business Phone", "Business Phone 2", "Mobile Phone", "Primary Phone",
                  "Company Main Phone", "Home Phone", "Home Phone 2", "Other Phone")


def parse_outlook_csv(text):
    contacts = []
    for row in _rows(text):
        given = " ".join(p for p in (row.get("First Name", ""), row.get("Middle Name", "")) if p)
        address = ""
        for kind in ("Business", "Home", "Other"):
            street = row.get(f"{kind} Street", "")
            if street or row.get(f"{kind} City"):
                tail = " ".join(p for p in (row.get(f"{kind} State", ""),
                                            row.get(f"{kind} Postal Code", "")) if p)
                address = ", ".join(p for p in (street, row.get(f"{kind} City", ""), tail,
                                                row.get(f"{kind} Country/Region", "")) if p)
                break
        c = new_contact(
            given=given, family=row.get("Last Name", ""),
            emails=_uniq([row.get("E-mail Address", ""), row.get("E-mail 2 Address", ""),
                          row.get("E-mail 3 Address", "")]),
            phones=_uniq([row.get(k, "") for k in OUTLOOK_PHONES]),
            org=row.get("Company", ""), title=row.get("Job Title", ""), address=address,
            notes=row.get("Notes", ""),
            labels=_uniq(re.split(r"[;,]", row.get("Categories", ""))))
        if _has_data(c):
            contacts.append(c)
    return contacts


GENERIC = [
    ("given", ("first name", "first", "given name", "given", "firstname", "fname")),
    ("family", ("last name", "last", "family name", "family", "surname", "lastname", "lname")),
    ("name", ("name", "full name", "fullname", "display name", "contact", "contact name")),
    ("org", ("company", "organization", "organisation", "org", "business", "employer", "company name")),
    ("title", ("job title", "title", "position", "role")),
    ("address", ("address", "street address", "mailing address", "full address")),
    ("notes", ("notes", "note", "comments", "comment", "description")),
    ("labels", ("labels", "label", "tags", "tag", "groups", "group", "categories", "category")),
]


def _generic_role(header):
    h = re.sub(r"\s+", " ", header.strip().lower().replace("_", " "))
    for field, names in GENERIC:
        if h in names:
            return field
    if "mail" in h:
        return "emails"
    if any(k in h for k in ("phone", "mobile", "cell", "tel", "fax")):
        return "phones"
    return None


def parse_generic_csv(text):
    contacts = []
    for row in _rows(text):
        data = {"emails": [], "phones": [], "labels": []}
        for key, val in row.items():
            role = _generic_role(key)
            if not role or not val:
                continue
            if role in ("emails", "phones"):
                data[role] += re.split(r"[;|]", val)
            elif role == "labels":
                data[role] += re.split(r"[;|,]", val)
            elif not data.get(role):
                data[role] = val
        if not data["emails"]:
            data["emails"] = [v for v in row.values() if re.fullmatch(r"[^@\s]+@[^@\s]+\.\w+", v)]
        for k in ("emails", "phones", "labels"):
            data[k] = _uniq(data[k])
        c = new_contact(**data)
        if _has_data(c):
            contacts.append(c)
    return contacts


def _has_data(c):
    return bool(c["name"] or c["emails"] or c["phones"])


# ---------- export ----------

EXPORT_HEAD = ["First Name", "Middle Name", "Last Name", "Phonetic First Name", "Phonetic Middle Name",
               "Phonetic Last Name", "Name Prefix", "Name Suffix", "Nickname", "File As",
               "Organization Name", "Organization Title", "Organization Department", "Birthday",
               "Notes", "Photo", "Labels"]


def export_google_csv(contacts):
    n_email = max([len(c.get("emails") or []) for c in contacts] + [1])
    n_phone = max([len(c.get("phones") or []) for c in contacts] + [1])
    header = list(EXPORT_HEAD)
    for i in range(1, n_email + 1):
        header += [f"E-mail {i} - Label", f"E-mail {i} - Value"]
    for i in range(1, n_phone + 1):
        header += [f"Phone {i} - Label", f"Phone {i} - Value"]
    header += ["Address 1 - Label", "Address 1 - Formatted"]

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(header)
    for c in contacts:
        given, family = c.get("given", ""), c.get("family", "")
        if not given and not family and c.get("name"):
            parts = c["name"].split()
            given, family = (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else (parts[0], "")
        row = {"First Name": given, "Last Name": family, "File As": c.get("name", ""),
               "Organization Name": c.get("org", ""), "Organization Title": c.get("title", ""),
               "Notes": c.get("notes", ""), "Labels": GOOGLE_MULTI.join(c.get("labels") or [])}
        for i, e in enumerate(c.get("emails") or [], 1):
            row[f"E-mail {i} - Label"], row[f"E-mail {i} - Value"] = "Work", e
        for i, p in enumerate(c.get("phones") or [], 1):
            row[f"Phone {i} - Label"], row[f"Phone {i} - Value"] = ("Work" if i == 1 else "Mobile"), p
        if c.get("address"):
            row["Address 1 - Label"], row["Address 1 - Formatted"] = "Work", c["address"]
        w.writerow([row.get(h, "") for h in header])
    return buf.getvalue()


# ---------- dedupe ----------

def dedupe(incoming, existing):
    """Split incoming into (unique, duplicates). Matches on email, then phone, then name."""
    by_email, by_phone, by_name = {}, {}, {}

    def index(c, cid):
        for e in c.get("emails") or []:
            by_email.setdefault(normalize_email(e), cid)
        for p in c.get("phones") or []:
            if normalize_phone(p):
                by_phone.setdefault(normalize_phone(p), cid)
        if normalize_name(c.get("name")):
            by_name.setdefault(normalize_name(c.get("name")), cid)

    for c in existing:
        index(c, c["id"])

    unique, duplicates = [], []
    for i, c in enumerate(incoming):
        match = next((by_email[normalize_email(e)] for e in c.get("emails") or []
                      if normalize_email(e) in by_email), None)
        if match is None:
            match = next((by_phone[normalize_phone(p)] for p in c.get("phones") or []
                          if normalize_phone(p) in by_phone), None)
        if match is None and normalize_name(c.get("name")):
            match = by_name.get(normalize_name(c.get("name")))
        if match is None:
            unique.append(c)
            index(c, c.get("id") or f"incoming:{i}")
        else:
            duplicates.append({"incoming": c, "existing_id": match})
    return unique, duplicates
