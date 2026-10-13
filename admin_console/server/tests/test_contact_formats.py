from pathlib import Path

import pytest

from admin_console.server import contact_formats as cf

SAMPLES = Path(__file__).parent / "samples"


def load(name):
    return cf.parse((SAMPLES / name).read_bytes())


@pytest.mark.parametrize("name,fmt", [("vcard3.vcf", "vcf"), ("vcard4.vcf", "vcf"),
                                      ("google_legacy.csv", "google_csv"), ("google_new.csv", "google_csv"),
                                      ("outlook.csv", "outlook_csv"), ("generic.csv", "csv")])
def test_detect(name, fmt):
    assert cf.detect_format(cf.decode((SAMPLES / name).read_bytes())) == fmt


def test_vcard3_multiple_folded_typed():
    fmt, cs = load("vcard3.vcf")
    assert fmt == "vcf" and len(cs) == 3
    b = cs[0]
    assert (b["name"], b["given"], b["family"]) == ("Brenda Walsh", "Brenda", "Walsh")
    assert b["emails"] == ["bwalsh@dentonisd.example.org"]
    assert b["phones"] == ["(940) 555-0142", "+1 940 555 0199"]
    assert b["org"] == "Denton ISD (example)" and b["title"] == "Construction Manager"
    assert b["address"] == "1307 N Locust St, Denton, TX 76201, USA"
    assert b["notes"] == "Prefers calls before 9am.\nGate code 4471 (ask at front desk)"
    assert b["labels"] == ["Owners", "Denton ISD"]


def test_vcard_quoted_printable_and_bare_params():
    _, cs = load("vcard3.vcf")
    j = cs[1]
    assert j["name"] == "José Peña" and j["family"] == "Peña" and j["given"] == "José"
    assert j["phones"] == ["214-555-0111"] and j["emails"] == ["jose@penaconcrete.example.com"]
    assert j["notes"] == "Concrete sub. Long note that is softbroken across lines."


def test_vcard_grouped_property():
    _, cs = load("vcard3.vcf")
    assert cs[2]["emails"] == ["luis@ortegaelectric.example.com"] and cs[2]["org"] == "Ortega Electric (example)"


def test_vcard4_uri_and_quoted_types():
    _, cs = load("vcard4.vcf")
    g = cs[0]
    assert g["phones"] == ["+1-972-555-0110"] and g["emails"] == ["glin@suretypartners.example.com"]
    assert g["address"] == "5800 Granite Pkwy, Plano, TX 75024, USA" and g["labels"] == ["Surety"]
    assert (cs[1]["given"], cs[1]["family"]) == ("Kevin", "Chen")


def test_vcard_escapes_and_lf_only():
    text = "BEGIN:VCARD\nVERSION:3.0\nFN:A\\, B\nORG:Smith\; Sons;Div\nNOTE:x\\ny\nEND:VCARD\n"
    c = cf.parse_vcard(text)[0]
    assert c["name"] == "A, B" and c["org"] == "Smith; Sons" and c["notes"] == "x\ny"


def test_google_legacy():
    fmt, cs = load("google_legacy.csv")
    assert fmt == "google_csv" and len(cs) == 2
    b = cs[0]
    assert b["emails"] == ["bwalsh@dentonisd.example.org", "brenda.w@example.net"]
    assert b["phones"] == ["940-555-0142", "940-555-0199"]
    assert b["labels"] == ["Owners"] and b["address"] == "1307 N Locust St, Denton, TX 76201"
    assert cs[1]["labels"] == [] and cs[1]["title"] == "Estimator"


def test_google_new():
    _, cs = load("google_new.csv")
    g, k = cs
    assert g["address"] == "5800 Granite Pkwy, Plano, TX 75024, USA" and g["notes"] == "Bonding contact"
    assert k["name"] == "Kevin J Chen" and k["family"] == "Chen"
    assert k["phones"] == ["817-555-0177", "817-555-0100"] and k["labels"] == ["Architects", "Denton"]


def test_outlook():
    fmt, cs = load("outlook.csv")
    r = cs[0]
    assert fmt == "outlook_csv"
    assert r["name"] == "Rachel Moore" and r["title"] == "Chief Estimator"
    assert r["emails"] == ["rmoore@lonestarmech.example.com", "estimating@lonestarmech.example.com"]
    assert r["phones"] == ["(817) 555-0163", "817-555-0164"]
    assert r["address"] == "4100 Industrial Blvd, Fort Worth, TX 76106, United States"
    assert r["labels"] == ["Subcontractors", "HVAC"]
    assert cs[1]["phones"] == ["469-555-0121"]


def test_generic_semicolon_sniffing():
    fmt, cs = load("generic.csv")
    assert fmt == "csv" and len(cs) == 2
    a = cs[0]
    assert a["name"] == "Amy Fowler" and a["emails"] == ["amy@fowlerglass.example.com"]
    assert a["phones"] == ["469-555-0188"] and a["org"] == "Fowler Glass (example)" and a["title"] == "PM"
    assert a["labels"] == ["Glazing", "Subcontractors"]


def test_generic_finds_unlabelled_email_column():
    _, cs = cf.parse("Who,Contact Info\nPat Lee,pat@lee.example.com\n")
    assert cs[0]["emails"] == ["pat@lee.example.com"]


def test_explicit_format_and_unknown():
    assert cf.parse((SAMPLES / "outlook.csv").read_bytes(), "outlook_csv")[0] == "outlook_csv"
    with pytest.raises(ValueError):
        cf.parse("a,b\n1,2\n", "xml")


def test_utf16_and_bom():
    fmt, cs = cf.parse("﻿First Name,Last Name,E-mail Address\nAna,Diaz,ana@x.example.com\n".encode("utf-16"))
    assert fmt == "outlook_csv" and cs[0]["emails"] == ["ana@x.example.com"]


def test_export_layout():
    out = cf.export_google_csv([cf.new_contact(name="Grace Lin", emails=["a@x.com", "b@x.com"], phones=["1"],
                                               org="S", title="AE", labels=["Surety", "Bonds"], address="1 Main")])
    header, row = out.splitlines()[:2]
    cols = header.split(",")
    assert cols[:3] == ["First Name", "Middle Name", "Last Name"]
    assert cols[cols.index("Labels")] == "Labels"
    assert ["E-mail 1 - Label", "E-mail 1 - Value", "E-mail 2 - Label", "E-mail 2 - Value",
            "Phone 1 - Label", "Phone 1 - Value"] == cols[17:23]
    assert "Organization Name" in cols and "Organization Title" in cols and "Notes" in cols
    values = dict(zip(cols, row.split(",")))
    assert values["First Name"] == "Grace" and values["Last Name"] == "Lin"
    assert values["Labels"] == "Surety ::: Bonds" and values["E-mail 2 - Value"] == "b@x.com"
    assert out.endswith("\r\n")


@pytest.mark.parametrize("name", ["vcard3.vcf", "vcard4.vcf", "google_legacy.csv", "google_new.csv",
                                  "outlook.csv", "generic.csv"])
def test_round_trip(name):
    _, original = load(name)
    fmt, back = cf.parse(cf.export_google_csv(original))
    assert fmt == "google_csv" and len(back) == len(original)
    for a, b in zip(original, back):
        for field in ("given", "family", "emails", "phones", "org", "title", "address", "notes", "labels"):
            assert a[field] == b[field], (name, field)


def test_normalizers():
    assert cf.normalize_phone("+1 (940) 555-0142") == "9405550142" == cf.normalize_phone("940.555.0142")
    assert cf.normalize_phone("12") == ""
    assert cf.normalize_email(" Bob@X.COM ") == "bob@x.com"
    assert cf.normalize_name("Walsh, Brenda") == cf.normalize_name("brenda walsh")


def test_dedupe_priority_and_within_file():
    existing = [cf.new_contact(id="e1", name="Brenda Walsh", emails=["bwalsh@d.org"]),
                cf.new_contact(id="e2", name="Someone", phones=["940-555-0142"]),
                cf.new_contact(id="e3", name="Kevin Chen")]
    incoming = [cf.new_contact(id="i0", name="B. Walsh", emails=["BWALSH@d.org"]),
                cf.new_contact(id="i1", name="Other", phones=["+1 940 555 0142"]),
                cf.new_contact(id="i2", name="Chen, Kevin"),
                cf.new_contact(id="i3", name="New Person", emails=["new@x.com"]),
                cf.new_contact(id="i4", name="New Person Dup", emails=["new@x.com"])]
    unique, dupes = cf.dedupe(incoming, existing)
    assert [c["id"] for c in unique] == ["i3"]
    assert [(d["incoming"]["id"], d["existing_id"]) for d in dupes] == [
        ("i0", "e1"), ("i1", "e2"), ("i2", "e3"), ("i4", "i3")]
