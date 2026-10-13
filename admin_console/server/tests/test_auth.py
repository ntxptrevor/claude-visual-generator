import pytest


def test_missing_header_outside_demo_is_403(prod_client):
    r = prod_client.get("/api/me")
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"


def test_non_owner_is_403(prod_client):
    r = prod_client.get("/api/me", headers={"X-Forwarded-Email": "marcus.delgado@ntxpllc.com"})
    assert r.status_code == 403
    assert set(r.json()) == {"error", "code"}


def test_non_owner_is_403_even_in_demo(client):
    assert client.get("/api/health", headers={"X-Forwarded-Email": "someone@gmail.com"}).status_code == 403


@pytest.mark.parametrize("email,name", [("Trevor@NTXPLLC.com", "Trevor Hopkins"),
                                        ("alison@ntxpllc.com", "Alison Hopkins"),
                                        ("  ALISON@ntxpllc.com ", "Alison Hopkins")])
def test_owners_allowed_case_insensitive(prod_client, email, name):
    r = prod_client.get("/api/me", headers={"X-Forwarded-Email": email})
    assert r.status_code == 200
    assert r.json() == {"email": email.strip().lower(), "name": name, "role": "owner"}


def test_demo_missing_header_is_trevor(client):
    assert client.get("/api/me").json()["email"] == "trevor@ntxpllc.com"


def test_other_identity_headers_ignored(prod_client):
    r = prod_client.get("/api/me", headers={"X-Forwarded-User": "trevor@ntxpllc.com",
                                            "X-Auth-Request-Email": "trevor@ntxpllc.com"})
    assert r.status_code == 403


def test_non_api_paths_not_gated(prod_client):
    assert prod_client.get("/").status_code in (200, 404)
