from admin_console import config
from admin_console.server import contacts

LABEL = config.SHARED_CONTACTS_LABEL


def ws(cid, labels, name="X"):
    return {"id": cid, "source": "workspace", "name": name, "given": "", "family": "", "emails": [f"{name}@x.com"],
            "phones": [], "org": "", "title": "", "address": "", "notes": "", "labels": labels,
            "owner_user": cid[3:].split(":")[0]}


def test_row_contact_round_trip():
    row = {"id": "shared:sc-1", "name": "A B", "given": "A", "family": "B", "emails": "a@x.com|b@x.com",
           "phones": "1|2", "org": "O", "title": "T", "address": "", "notes": "", "labels": "L1|L2",
           "owner_user": "trevor@ntxpllc.com", "source_ref": "", "updated": ""}
    c = contacts.row_to_contact(row)
    assert c["emails"] == ["a@x.com", "b@x.com"] and c["shared"] and c["source"] == "shared"
    back = contacts.contact_to_row(c)
    assert back["id"] == "shared:sc-1" and back["labels"] == "L1|L2"
    assert contacts.row_to_contact({**row, "id": "sc-9"})["id"] == "shared:sc-9"


def test_person_to_contact():
    person = {"resourceName": "people/c42", "etag": "e",
              "names": [{"displayName": "Luis Ortega", "givenName": "Luis", "familyName": "Ortega"}],
              "emailAddresses": [{"value": "luis@o.com"}], "phoneNumbers": [{"value": "214"}],
              "organizations": [{"name": "Ortega Electric", "title": "Estimator"}],
              "memberships": [{"contactGroupMembership": {"contactGroupResourceName": "contactGroups/abc"}}],
              "metadata": {"sources": [{"updateTime": "2026-10-01T00:00:00Z"}]}}
    c = contacts.person_to_contact(person, "workspace", "trevor@ntxpllc.com", {"contactGroups/abc": LABEL})
    assert c["id"] == "ws:trevor@ntxpllc.com:people/c42" and c["shared"] is True
    assert c["labels"] == [LABEL] and c["org"] == "Ortega Electric" and c["updated"].startswith("2026-10-01")


def test_contact_to_person_mask():
    body, mask = contacts.contact_to_person({"title": "PM", "org": "NTXP", "phones": ["1"], "notes": "n"})
    assert mask == "phoneNumbers,organizations,biographies"
    assert body["organizations"] == [{"name": "NTXP", "title": "PM"}]


def test_plan_sync_adds_updates_removes_and_respects_failed_users():
    workspace = [ws("ws:a@ntxpllc.com:people/c1", [LABEL, "Owners"], "Ann"),
                 ws("ws:a@ntxpllc.com:people/c2", [LABEL], "Ben"),
                 ws("ws:a@ntxpllc.com:people/c3", [], "Cal")]
    rows = [{"id": "shared:sc-1", "name": "Old Ann", "source_ref": "ws:a@ntxpllc.com:people/c1", "labels": ""},
            {"id": "shared:sc-3", "name": "Cal", "source_ref": "ws:a@ntxpllc.com:people/c3", "labels": ""},
            {"id": "shared:sc-4", "name": "Gone user", "source_ref": "ws:b@ntxpllc.com:people/c9", "labels": ""},
            {"id": "shared:sc-5", "name": "Manual", "source_ref": "", "labels": ""}]
    out, added, removed = contacts.plan_sync(workspace, rows, {"a@ntxpllc.com"})
    assert (added, removed) == (1, 1)
    by_id = {r["id"]: r for r in out}
    assert by_id["shared:sc-1"]["name"] == "Ann" and by_id["shared:sc-1"]["labels"] == "Owners"
    assert "shared:sc-3" not in by_id and "shared:sc-4" in by_id and "shared:sc-5" in by_id
    new = [r for r in out if r["source_ref"] == "ws:a@ntxpllc.com:people/c2"][0]
    assert new["id"].startswith("shared:sc-") and LABEL not in new["labels"]


def test_clean_fields():
    assert contacts._clean_fields({"emails": "a@x.com, b@x.com", "title": 5}) == \
        {"emails": ["a@x.com", "b@x.com"], "title": "5"}
