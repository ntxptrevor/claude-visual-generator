from datetime import timedelta

import pytest

from admin_console.server import gate

calls = []
gate.register("test.kind", lambda payload, approver: calls.append((payload, approver)) or {"ok": True})


def stage():
    return gate.stage("test.kind", "Do a thing", {"x": 1}, "trevor@ntxpllc.com")


def test_stage_shape():
    s = stage()
    assert s["needs_approval"] is True and s["summary"] == "Do a thing"
    assert s["change_id"].startswith("CH-") and len(s["payload_digest"]) == 64
    assert s["payload_digest"] == gate.digest({"x": 1})


def test_approve_executes_once():
    calls.clear()
    s = stage()
    out = gate.approve(s["change_id"], "Alison@ntxpllc.com")
    assert out["result"] == {"ok": True} and calls == [({"x": 1}, "Alison@ntxpllc.com")]
    with pytest.raises(gate.GateError) as e:
        gate.approve(s["change_id"], "alison@ntxpllc.com")
    assert e.value.code == "not_found"


def test_non_owner_rejected_and_change_kept():
    s = stage()
    with pytest.raises(gate.GateError) as e:
        gate.approve(s["change_id"], "rosa.jimenez@ntxpllc.com")
    assert e.value.status == 403
    assert gate.approve(s["change_id"], "trevor@ntxpllc.com")["approved_by"] == "trevor@ntxpllc.com"


def test_expiry(monkeypatch):
    s = stage()
    real_now = gate.now()
    monkeypatch.setattr(gate, "now", lambda: real_now + timedelta(minutes=16))
    with pytest.raises(gate.GateError) as e:
        gate.approve(s["change_id"], "trevor@ntxpllc.com")
    assert e.value.code == "expired"


def test_digest_mismatch_tampered_payload():
    s = stage()
    gate._staged[s["change_id"]]["payload"]["x"] = 2
    with pytest.raises(gate.GateError) as e:
        gate.approve(s["change_id"], "trevor@ntxpllc.com")
    assert e.value.code == "digest_mismatch"


def test_digest_mismatch_expected():
    s = stage()
    with pytest.raises(gate.GateError) as e:
        gate.approve(s["change_id"], "trevor@ntxpllc.com", expected_digest="0" * 64)
    assert e.value.code == "digest_mismatch"


def test_approve_endpoint(client):
    r = client.post("/api/users/marcus.delgado@ntxpllc.com/action", json={"action": "suspend"})
    staged = r.json()
    assert staged["needs_approval"] and staged["change_id"]
    assert client.get("/api/approve").json()["pending"][0]["change_id"] == staged["change_id"]
    denied = client.post(f"/api/approve/{staged['change_id']}", headers={"X-Forwarded-Email": "marcus.delgado@ntxpllc.com"})
    assert denied.status_code == 403
    ok = client.post(f"/api/approve/{staged['change_id']}", json={"payload_digest": staged["payload_digest"]},
                     headers={"X-Forwarded-Email": "alison@ntxpllc.com"})
    assert ok.status_code == 200 and ok.json()["result"]["action"] == "suspend"
    assert client.post(f"/api/approve/{staged['change_id']}").status_code == 404


def test_owner_accounts_protected(client):
    r = client.post("/api/users/alison@ntxpllc.com/action", json={"action": "suspend"})
    assert r.status_code == 409
