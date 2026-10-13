import datetime as dt

import pytest

from admin_console.analytics import classify, council, learning, store, util

from .conftest import NOW

FLAG = {"id": "FL-T-1", "person": "jake@ntxpllc.com", "kpi": "wait_complaints", "level": 3,
        "urgency": "high", "severity": "redflag", "confidence": 0.8,
        "summary": "External complaint not forwarded.",
        "evidence": [{"source": "gmail", "ref": "t1", "note": "x" * 500}],
        "crosscheck": {"status": "confirmed", "sources_checked": ["gmail"], "explanations": ["tracks"]}}


def answer(verdict):
    return lambda prompt: {"verdict": verdict, "conclusion": "Verify the punch walk schedule."}


def test_request_is_confidential_and_excludes_forbidden_seats():
    req = council.build_request(FLAG)
    assert req["confidential"] is True and req["category"] == "classification"
    assert req["min_providers"] >= 3
    assert {"deepseek", "glm"} <= set(req["forbidden_seats"])
    assert all(len(e["note"]) <= 200 for e in req["evidence"])
    assert req["ceiling_usd"] == 2.0


def test_no_providers_returns_none_for_human_review():
    assert council.conclude(FLAG) is None


def test_local_fallback_never_asks_deepseek_or_glm():
    asked = []
    for seat in ("anthropic", "xai", "openai", "deepseek", "glm"):
        council.PROVIDER_CALLS[seat] = (lambda s: (lambda p: asked.append(s) or
                                                   {"verdict": "supported", "conclusion": "ok"}))(seat)
    res = council.conclude(FLAG)
    assert res and set(res) == {"council_id", "agreement", "conclusion"}
    assert "deepseek" not in asked and "glm" not in asked
    assert res["agreement"] == 1.0


def test_local_fallback_agreement_and_minimum_three():
    council.PROVIDER_CALLS.update({"anthropic": answer("supported"), "xai": answer("supported"),
                                   "openai": answer("not_supported")})
    res = council.conclude(FLAG)
    assert res["agreement"] == pytest.approx(0.67, abs=0.01)
    assert res["conclusion"].startswith("Proposal (supported")
    council.PROVIDER_CALLS.pop("openai")
    assert council.conclude(FLAG) is None  # only two seats


def test_council_url_adapter_first(live, monkeypatch):
    monkeypatch.setenv("NTXP_COUNCIL_URL", "https://council.example/run")
    seen = {}

    def post(url, payload):
        seen.update(url=url, payload=payload)
        return {"council_id": "CR-77", "agreement": 0.8, "conclusion": "Supported."}
    council.POST = post
    res = council.conclude(FLAG)
    assert res == {"council_id": "CR-77", "agreement": 0.8, "conclusion": "Supported."}
    assert seen["payload"]["confidential"] is True and "deepseek" in seen["payload"]["forbidden_seats"]


def test_council_url_failure_falls_back(live, monkeypatch):
    monkeypatch.setenv("NTXP_COUNCIL_URL", "https://council.example/run")

    def boom(url, payload):
        raise OSError("down")
    council.POST = boom
    assert council.conclude(FLAG) is None


# --------------------------------------------------------------------------- learning

def _actions(kpi, action, n, start=0):
    for i in range(n):
        store.append("Interactions", {"id": f"IX-{kpi}-{action}-{start + i}",
                                      "at": util.iso(util.as_utc(NOW) - dt.timedelta(minutes=60 - i)),
                                      "actor": "alison@ntxpllc.com", "kind": "flag_action",
                                      "request_type": f"flag_{action}", "flag_id": f"F{i}",
                                      "action": action, "kpi": kpi, "level": 1})


def test_low_precision_makes_threshold_less_sensitive():
    store.ensure_schema()
    _actions("responsiveness_anomaly", "dismiss", 5)
    _actions("responsiveness_anomaly", "ack", 1)
    changes = learning.tune(NOW)
    (c,) = changes
    assert c["param"] == "z_minor" and c["before"] == 2.0 and c["after"] == 2.25
    assert classify.thresholds()["z_minor"] == 2.25
    # no new actions since the change -> no second nudge
    assert learning.tune(util.as_utc(NOW) + dt.timedelta(minutes=5)) == []


def test_owner_escalations_make_threshold_more_sensitive_within_bounds():
    store.ensure_schema()
    _actions("daily_report_quality", "escalate", 4)
    _actions("daily_report_quality", "ack", 2)
    (c,) = learning.tune(NOW)
    assert c["param"] == "quality_min" and c["after"] == pytest.approx(0.65)
    lo, hi, _, _ = classify.BOUNDS["quality_min"]
    assert lo <= c["after"] <= hi


def test_too_few_actions_no_change():
    store.ensure_schema()
    _actions("no_shows", "dismiss", 2)
    assert learning.tune(NOW) == []


def test_request_types_tracked():
    store.ensure_schema()
    learning.record_request("trevor@ntxpllc.com", "search", "unanswered jake", NOW)
    learning.record_request("trevor@ntxpllc.com", "search", "", NOW)
    learning.record_request("alison@ntxpllc.com", "report_view", "no_shows", NOW)
    counts = learning.request_types(NOW)
    assert counts["search"] == 2 and counts["report_view"] == 1
    assert store.query("Learning", {"kind": "request_types"})


def test_recurring_blocker_proposes_runbook_never_applied():
    store.ensure_schema()
    for i in range(3):
        store.log_change("analytics", "collectors", "failure", "jobtread", "HTTP 401")
    for i in range(2):
        store.log_change("analytics", "collectors", "failure", "plaud", "timeout")
    props = learning.blockers(NOW)
    assert len(props) == 1 and props[0]["status"] == "proposed"
    rb = store.rows("Runbook")
    assert rb[0]["workflow"].endswith("jobtread") and isinstance(rb[0]["steps"], list)
    assert store.query("Learning", {"kind": "blocker"})[0]["status"] == "proposed"
    assert learning.blockers(NOW) == []  # not re-proposed
