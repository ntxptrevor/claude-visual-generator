import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import formflow_canonical as can  # noqa: E402
import formflow_workflow_registry as reg  # noqa: E402

COI = {"source_kind": "executed_doc", "source_title": "ACORD 25 #44236304", "source_date": "2026-08-03"}
SCAN = {"source_kind": "drive_scan", "source_title": "old scan", "source_date": "2026-01-01"}
OWNER = {"source_kind": "owner_canonical", "source_title": "Exhibit A", "source_date": "2026-10-13"}


def c(value, base):
    return dict(base, field_value=value)


def test_tier1_field_always_wins():
    d = can.determine("street_address", [c("405 S Elm St Ste 203", COI)])
    assert d["value"] == "101 South Locust St Ste 605" and d["jev_tier"] == 0
    assert d["rejected"][0]["source_title"] == "ACORD 25 #44236304"


def test_agreeing_sources_become_canonical():
    d = can.determine("gl_policy_number", [c("BBD6499", COI), c("bbd6499", SCAN)], "insurance")
    assert d["status"] == "canonical" and d["value"] == "BBD6499" and d["jev_tier"] == 0


def test_higher_ranked_source_wins_clearly():
    d = can.determine("umbrella_limit", [c("$5,000,000", OWNER), c("$2,000,000", SCAN)], "insurance")
    assert d["value"] == "$5,000,000"


def test_close_conflict_goes_to_owner_never_council_for_insurance():
    d = can.determine("gl_aggregate_limit", [c("$2,000,000", COI), c("$4,000,000", dict(COI, source_title="other COI"))],
                      "insurance")
    assert d["status"] == "conflict" and d["jev_tier"] == 3 and "council" not in d["basis"]


def test_retired_values_are_never_chosen():
    d = can.determine("mailing_address", [c("405 S Elm St Ste 203", COI)], retired=["405 S Elm St Ste 203"])
    assert d["status"] == "missing" and d["value"] is None


def test_banking_is_confidential_and_masked():
    d = can.determine("ach_account_number", [c("123456789012", OWNER)], "banking")
    assert d["jev_tier"] == 3
    assert can.mask(d["value"], "banking") == "••••••••9012"


def test_canonical_feeds_answers_but_tier1_still_wins():
    decisions = can.determine_all(
        {"ein": [c("87-2033276", OWNER)], "phone": [c("940-000-0000", OWNER)]})
    canon = can.canonical_values(decisions)
    values, sources = reg.resolve_kb_values({"ein": "11-1111111"}, canon)
    assert values["ein"] == "87-2033276" and sources["ein"] == "canonical"
    assert values["phone"] == "469-248-7431" and sources["phone"] == "tier1"
