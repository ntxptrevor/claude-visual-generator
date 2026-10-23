import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nff_jev as jev  # noqa: E402


@pytest.fixture(autouse=True)
def no_network(monkeypatch, tmp_path):
    """Every test runs offline: any HTTP call fails unless a test installs a fake."""
    def refuse(*a, **k):
        raise ConnectionError("network disabled in tests")
    monkeypatch.setattr(jev, "HTTP_POST", refuse)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("NFF_HOME", str(tmp_path / "nff"))


# ------------------------------------------------------------------ classify_field

@pytest.mark.parametrize("label,expected", [
    ("Company Name", "text_word"),
    ("Federal EIN", "text_word"),
    ("Describe your experience with similar projects", "text_paragraph"),
    ("Date", "date"),
    ("Date of Signature", "date"),
    ("Printed Name of Authorized Representative", "person"),
    ("Contact Name", "person"),
    ("Mailing Address", "address"),
    ("City, State, ZIP", "address"),
    ("Telephone", "phone"),
    ("Fax No.", "phone"),
    ("E-mail", "email"),
    ("Total Base Bid Amount", "currency"),
    ("Check one: Yes / No", "checkmark"),
    ("Place an X in the box that applies", "x_mark"),
    ("Initials", "initials"),
    ("Authorized Signature", "signature"),
    ("Highlight the applicable section", "highlight"),
])
def test_classify_typical_labels(label, expected):
    r = jev.classify_field(label)
    assert r["type"] == expected, r
    assert r["confidence"] >= 0.6
    assert r["type"] in jev.FIELD_TYPES


def test_classify_geometry():
    assert jev.classify_field("", rect=[100, 100, 110, 110])["type"] == "checkmark"
    assert jev.classify_field("Remarks", rect=[50, 100, 500, 220])["type"] == "text_paragraph"
    assert jev.classify_field("Name", rect={"x": 0, "y": 0, "w": 400, "h": 90})["type"] == "text_paragraph"


def test_classify_ambiguous_uses_ollama_then_falls_back(monkeypatch):
    calls = []

    def fake(url, payload, headers, timeout):
        calls.append((url, payload.get("model"), timeout))
        return {"message": {"content": json.dumps({"type": "date", "confidence": 0.95})}}
    monkeypatch.setattr(jev, "HTTP_POST", fake)
    r = jev.classify_field("Blank 7")
    assert r["type"] == "date" and r["referee"].startswith("ollama")
    assert r["confidence"] <= 0.85
    assert calls[0][0].endswith("/api/chat") and calls[0][1] == "qwen2.5:7b-instruct" and calls[0][2] == 3


def test_classify_falls_back_to_haiku_when_ollama_down(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    seen = []

    def fake(url, payload, headers, timeout):
        seen.append(url)
        if "11434" in url:
            raise ConnectionError("ollama down")
        assert payload["model"] == "claude-haiku-4-5-20251001"
        assert "123456789" not in json.dumps(payload)  # long digit runs are masked
        return {"content": [{"type": "text", "text": '{"type": "phone", "confidence": 0.7}'}]}
    monkeypatch.setattr(jev, "HTTP_POST", fake)
    r = jev.classify_field("Blank 7", page_text_near="ref 123456789")
    assert r["type"] == "phone" and "haiku" in r["referee"]
    assert seen[-1] == jev.ANTHROPIC_URL


def test_classify_no_referee_returns_rule_result():
    r = jev.classify_field("Blank 7")
    assert r["referee"] == "rules" and r["type"] == "text_word" and r["confidence"] < 0.6


def test_blocked_hosts_never_called(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "https://api.deepseek.com")
    called = []
    monkeypatch.setattr(jev, "HTTP_POST", lambda *a: called.append(a))
    jev.classify_field("Blank 7")
    assert called == []


# ------------------------------------------------------------------ choose_value

STALE_KB = {"company_name": "NTXP Professional LLC", "street_address": "405 S Elm St Ste 203",
            "phone": "(214) 555-0000", "owner_name": "Trevor Hopkins", "signer_name": "Trevor Hopkins",
            "naics": "236220", "bid_amount": "$125,000.00", "license_no": "405 S Elm St Ste 203"}


@pytest.mark.parametrize("field,expected", [
    ("company_name", "NTXP LLC"), ("street_address", "101 South Locust St Ste 605"),
    ("phone", "469-248-7431"), ("owner_name", "Alison Hopkins"), ("signer_name", "Alison Hopkins"),
    ("tax_classification", "S corporation"),
])
def test_choose_value_tier1_beats_stale_kb(field, expected):
    r = jev.choose_value(field, "text_word", STALE_KB, {field: "something else"})
    assert r["value"] == expected and r["source"] == "tier1" and r["autofill"]
    assert r["confidence"] >= 0.98


@pytest.mark.parametrize("field,ftype,label", [
    ("bid_amount", "currency", "Total Base Bid"),
    ("alt_1", "text_word", "Alternate No. 1 price"),
    ("unit_price", "text_word", ""),
    ("owner_signature", "signature", "Signature"),
    ("init_p2", "initials", "Initials"),
    ("q4", "checkmark", "Has the firm been debarred or suspended? Yes / No"),
    ("q5", "checkmark", "Has any officer been convicted of a felony?"),
    ("ciq_7", "checkmark", "Conflict of Interest disclosure"),
    ("israel", "checkmark", "Company does not boycott Israel"),
    ("notary_block", "text_paragraph", "Subscribed and sworn to before me, Notary Public"),
    ("bank_routing", "text_word", "Bank routing number"),
])
def test_choose_value_never_autofills_user_only_fields(field, ftype, label):
    kb = {field: "123", "bid_amount": "$125,000.00"}
    canonical = {field: "No"}
    r = jev.choose_value(field, ftype, kb, canonical, label=label)
    assert r["autofill"] is False and r["value"] is None and r["source"] == "manual"


def test_choose_value_signature_suggests_designated_signer():
    r = jev.choose_value("owner_signature", "signature", STALE_KB, {})
    assert r["suggested"] == "Alison Hopkins" and r["value"] is None
    assert jev.choose_value("init", "initials", {}, {})["suggested"] == "AH"


def test_choose_value_canonical_then_kb_then_manual():
    canon = {"naics": [{"field_value": "238990", "source_kind": "owner_canonical", "source_title": "Exhibit A",
                        "source_date": None}]}
    r = jev.choose_value("naics", "text_word", STALE_KB, canon)
    assert r["value"] == "238990" and r["source"] == "canonical"
    r = jev.choose_value("naics", "text_word", STALE_KB, {})
    assert r["value"] == "236220" and r["source"] == "kb"
    assert jev.choose_value("uei", "text_word", STALE_KB, {})["source"] == "manual"
    # Retired value in the KB is never used.
    r = jev.choose_value("license_no", "text_word", STALE_KB, {})
    assert r["value"] is None and "retired" in r["basis"]


def test_choose_value_canonical_conflict_goes_to_owner():
    canon = {"insurer": [
        {"field_value": "Acme Mutual", "source_kind": "executed_doc", "source_title": "COI 2026"},
        {"field_value": "Zeta Casualty", "source_kind": "executed_doc", "source_title": "COI 2026b"}]}
    r = jev.choose_value("insurer", "text_word", {}, canon)
    assert r["autofill"] is False and r["value"] is None


# ------------------------------------------------------------------ probabilities

def test_beta_cdf_known_values():
    assert jev.beta_cdf(0.5, 1, 1) == pytest.approx(0.5)
    for x in (0.1, 0.3, 0.7):
        assert jev.beta_cdf(x, 2, 2) == pytest.approx(3 * x**2 - 2 * x**3, abs=1e-10)
        assert jev.beta_cdf(x, 10, 2) == pytest.approx(x**10 * (11 - 10 * x), abs=1e-10)


def test_beta_quantile_inverts_cdf():
    q = jev.beta_quantile(0.05, 10, 2)
    assert q**10 * (11 - 10 * q) == pytest.approx(0.05, abs=1e-8)
    assert jev.beta_quantile(0.5, 3, 3) == pytest.approx(0.5, abs=1e-8)


def test_field_confidence_9_accepted_1_corrected():
    c = jev.field_confidence((9, 1), "ein", "owner_canonical", 1.0)
    d = c.as_dict()
    assert d["posterior_mean"] == pytest.approx(10 / 12)          # Beta(10, 2)
    # Blended with prior 0.90 at strength 4: Beta(10 + 3.6, 2 + 0.4)
    assert d["alpha"] == pytest.approx(13.6) and d["beta"] == pytest.approx(2.4)
    assert float(c) == pytest.approx(13.6 / 16, abs=1e-4)
    assert c.low < float(c) < c.high <= 1.0
    lo = jev.beta_quantile(0.05, 13.6, 2.4)
    assert c.low == pytest.approx(lo, abs=1e-4)


def test_field_confidence_inputs_and_match_score():
    full = jev.field_confidence(lambda f: (9, 1), "x", "kb_manual", 1.0)
    half = jev.field_confidence({"x": (9, 1)}, "x", "kb_manual", 0.5)
    assert float(half) == pytest.approx(float(full) / 2, abs=1e-3)
    assert half.low <= float(half) <= half.high
    fresh_kb = jev.field_confidence(None, "x", "kb", 1.0)
    fresh_canon = jev.field_confidence(None, "x", "canonical", 1.0)
    assert float(fresh_canon) > float(fresh_kb)
    many_corrections = jev.field_confidence((0, 20), "x", "owner_canonical", 1.0)
    assert float(many_corrections) < 0.3
    assert float(jev.field_confidence((0, 0), "phone", "tier1")) == pytest.approx(0.99)


def test_field_confidence_with_sqlite_conn(monkeypatch):
    import sqlite3
    import types
    fake_db = types.SimpleNamespace(outcome_counts=lambda conn, name: (9, 1))
    monkeypatch.setitem(sys.modules, "nff_db", fake_db)
    c = jev.field_confidence(sqlite3.connect(":memory:"), "ein", "owner_canonical", 1.0)
    assert c.as_dict()["accepted"] == 9


def _fields(conf=0.9, n=4):
    return [{"name": f"f{i}", "value": "v", "confidence": conf, "low": conf - 0.1, "high": conf + 0.05,
             "required": True} for i in range(n)]


def test_form_confidence_geometric_mean_and_caps():
    base = jev.form_confidence(_fields(), [{"id": "a", "passed": True, "blocking": True}])
    assert base["score"] == pytest.approx(0.9) and base["low"] <= base["score"] <= base["high"]
    capped = jev.form_confidence(_fields(0.99), [{"id": "tier1.x", "passed": False, "blocking": True,
                                                  "message": "wrong address"}])
    assert capped["score"] <= 0.5 and capped["high"] <= 0.5
    assert any("wrong address" in d for d in capped["drivers"])
    blank = _fields() + [{"name": "uei", "label": "UEI", "value": "", "required": True}]
    dropped = jev.form_confidence(blank, [])
    assert dropped["score"] < base["score"]
    assert any("UEI" in d for d in dropped["drivers"])
    mixed = [{"name": "a", "value": "x", "confidence": 0.4}, {"name": "b", "value": "x", "confidence": 0.9}]
    assert jev.form_confidence(mixed, [])["score"] == pytest.approx((0.4 * 0.9) ** 0.5, abs=1e-4)
    assert "never be printed" in jev.form_confidence.__doc__


# ------------------------------------------------------------------ review

def _state(**over):
    s = {"session_id": "t1", "form_type": "vendor_registration", "fields": [
        {"kb_field": "company_name", "label": "Company", "value": "NTXP LLC", "source": "tier1"},
        {"kb_field": "street_address", "label": "Address", "value": "101 South Locust St Ste 605", "source": "tier1"},
        {"kb_field": "phone", "label": "Phone", "type": "phone", "value": "469-248-7431", "source": "tier1"},
        {"kb_field": "signer_name", "label": "Printed name", "value": "Alison Hopkins", "source": "tier1"},
        {"kb_field": "email", "label": "Email", "type": "email", "value": "trevor@ntxpllc.com", "source": "kb"},
    ]}
    s.update(over)
    return s


def test_review_clean_form_passes():
    r = jev.review(_state())
    blocking = [c for c in r["checks"] if c["blocking"] and not c["passed"]]
    assert blocking == [], blocking
    assert r["confidence"]["score"] > 0.5


def test_review_flags_retired_address_and_wrong_signer():
    st = _state()
    st["fields"][1]["value"] = "405 S Elm St Ste 203"
    st["fields"][3]["value"] = "Bob Smith"
    st["fields"].append({"kb_field": "mailing_note", "label": "Remit to", "value": "405 South Elm St, Denton"})
    r = jev.review(st)
    failed = {c["id"] for c in r["checks"] if not c["passed"]}
    assert "tier1.street_address" in failed and "retired.street_address" in failed
    assert "retired.mailing_note" in failed and "tier1.signer" in failed
    assert r["confidence"]["score"] <= 0.5


def test_review_alternate_signer_needs_circumstance():
    st = _state()
    st["fields"][3]["value"] = "Trevor Hopkins"
    r = jev.review(st)
    assert any(c["id"] == "tier1.signer" and not c["passed"] for c in r["checks"])
    st["approvals"] = [{"decision": "approve", "signer": "Trevor Hopkins", "circumstance": "Owner traveling",
                        "request_id": "r1", "approved_by": "Alison Hopkins"}]
    r = jev.review(st)
    assert all(c["passed"] for c in r["checks"] if c["id"] == "tier1.signer")


def test_review_w9_requires_s_corp_only():
    st = _state(form_type="w9")
    st["fields"] += [{"name": "c1_1[2]", "value": "/3"}, {"name": "c1_1[5]", "value": "/6"}]
    assert any(c["id"] == "tier1.w9_scorp" and not c["passed"] for c in jev.review(st)["checks"])
    st["fields"][-1]["value"] = "/Off"
    assert any(c["id"] == "tier1.w9_scorp" and c["passed"] for c in jev.review(st)["checks"])


def test_review_signature_needs_approval_and_prices_must_be_user_entered():
    st = _state()
    st["fields"] += [
        {"name": "sig", "label": "Signature", "type": "signature", "value": "Alison Hopkins"},
        {"name": "bid_amount", "label": "Total Base Bid", "type": "currency", "value": "$10,000.00", "source": "kb"},
        {"name": "debarred", "label": "Debarred? Yes/No", "type": "checkmark", "value": "No", "source": "canonical"},
        {"name": "bid_date", "label": "Date", "type": "date", "value": "2026-10-23", "source": "kb"},
        {"name": "uei", "label": "UEI", "value": "", "required": True},
    ]
    r = jev.review(st)
    failed = {c["id"]: c for c in r["checks"] if not c["passed"]}
    assert "signature.sig" in failed and "user_only.bid_amount" in failed and "user_only.debarred" in failed
    assert "format.bid_date" in failed and not failed["format.bid_date"]["blocking"]
    assert "required.uei" in failed
    st["fields"][-4]["user_entered"] = True
    st["approvals"] = [{"decision": "approve", "signer": "Alison Hopkins", "request_id": "r", "approved_by": "Alison Hopkins"}]
    failed = {c["id"] for c in jev.review(st)["checks"] if not c["passed"]}
    assert "signature.sig" not in failed and "user_only.bid_amount" not in failed


def test_review_canonical_contradiction_is_advisory():
    st = _state(canonical={"naics": "236220"})
    st["fields"].append({"kb_field": "naics", "label": "NAICS", "value": "238990", "source": "kb"})
    c = next(c for c in jev.review(st)["checks"] if c["id"] == "canonical.naics")
    assert not c["passed"] and not c["blocking"]


def test_review_without_key_writes_packet_with_masked_banking(tmp_path):
    st = _state(session_dir=str(tmp_path / "s1"))
    st["fields"].append({"kb_field": "bank_account", "label": "Bank account number", "value": "000123456789"})
    r = jev.review(st)
    q = next(c for c in r["checks"] if c["id"] == "ai_review.queued")
    assert q["advisory"] and "queued for the Claude session" in q["message"]
    packet = (tmp_path / "s1" / "review_packet.json").read_text()
    assert "000123456789" not in packet and "6789" in packet


def test_review_with_key_merges_ai_advisories(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    sent = {}

    def fake(url, payload, headers, timeout):
        sent.update(payload)
        return {"content": [{"type": "text", "text": json.dumps(
            {"advisories": [{"field": "email", "message": "Bid contact should be the estimator"}]})}]}
    monkeypatch.setattr(jev, "HTTP_POST", fake)
    st = _state()
    st["fields"].append({"kb_field": "routing_number", "label": "ACH routing", "value": "111000025"})
    r = jev.review(st)
    assert sent["model"] == "claude-sonnet-5" and "111000025" not in json.dumps(sent)
    ai = [c for c in r["checks"] if c["id"].startswith("ai_review.")]
    assert ai and all(not c["blocking"] for c in ai)
    assert r["confidence"]["blocking_failures"] == 0


# ------------------------------------------------------------------ portal plan

def test_portal_fill_plan_marks_submit_tier3():
    plan = jev.portal_fill_plan("https://vendor.example.gov", [
        {"selector": "#company", "value": "NTXP LLC"},
        {"selector": "#bid", "label": "Bid amount", "type": "currency", "value": "$1.00"},
        {"selector": "button#submit", "action": "click", "label": "Submit"},
    ])
    assert plan["executed"] is False and plan["steps"][0]["action"] == "goto"
    assert plan["steps"][1]["value"] == "NTXP LLC"
    assert plan["steps"][2]["action"] == "pause_for_user" and "value" not in plan["steps"][2]
    assert plan["steps"][3]["tier"] == 3 and plan["steps"][3]["requires_approval"]
    assert plan["tier3_steps"] == [3]
