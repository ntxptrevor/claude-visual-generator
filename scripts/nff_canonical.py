#!/usr/bin/env python3
"""
NTXP Form Filler canonical answers and JEV answer determination.

Canonical answers are the owner-approved values that forms reuse (bonding,
insurance, W-9, ACH, contacts). For any field, several candidate values may
exist: a Tier 1 rule, an exhibit the owner approved, an executed third-party
document (a broker's COI, a signed W-9), a KB row, or a Drive scan. JEV picks
the correct one deterministically (Tier 0, $0) and escalates only when it
cannot:

  1. Tier 1 rule exists for the field     -> that value, always.
  2. Value is retired                     -> never used.
  3. One normalized value clearly wins    -> canonical (score = source rank,
     recency, agreement between sources).
  4. Top two disagree and both are strong -> Tier 3: owner decides. Never a
     council vote for banking, tax-ID or insurance values.
Banking fields (ACH) are always confidential: they never go to a model, are
masked in logs, and a form that uses them needs Tier 3 approval to fill.

Usage:
    python nff_canonical.py --determine candidates.json
"""

import argparse
import json
import re
import sys
from datetime import date, datetime

from nff_signatures import NTXP_IDENTITY, TIER1_FIELD_OVERRIDES

CANONICAL_HEADERS = [
    "answer_id", "exhibit", "category", "field_name", "field_value", "source_kind",
    "source_title", "source_ref", "source_date", "status", "verified_by",
    "verified_at", "notes",
]

SOURCE_RANK = {
    "tier1": 100,          # CLAUDE.md owner directive
    "owner_canonical": 90,  # an exhibit the owner approved as canonical
    "executed_doc": 80,    # signed/issued third-party document (COI, signed W-9, bond letter)
    "company_doc": 70,     # NTXP-issued summary or letter
    "kb_manual": 60,       # typed into the KB by a person
    "drive_scan": 40,
    "learned": 20,
}

CONFIDENTIAL_CATEGORIES = {"banking", "tax_id"}
NO_COUNCIL_CATEGORIES = {"banking", "tax_id", "insurance", "bonding"}
CLEAR_MARGIN = 15
STALE_DAYS = 400


def normalize(value):
    v = str(value).strip().lower()
    v = re.sub(r"[\s,.$]+", " ", v).strip()
    digits = re.sub(r"\D", "", v)
    return digits if digits and len(digits) >= 0.6 * len(v.replace(" ", "")) else v


def mask(value, category):
    s = str(value)
    if category in CONFIDENTIAL_CATEGORIES and len(s) > 4:
        return "•" * (len(s) - 4) + s[-4:]
    return s


def _age_days(d):
    if not d:
        return None
    try:
        return (date.today() - datetime.strptime(str(d)[:10], "%Y-%m-%d").date()).days
    except ValueError:
        return None


def _score(c):
    rank = SOURCE_RANK.get(c.get("source_kind"), 0)
    age = _age_days(c.get("source_date"))
    recency = 0 if age is None else max(0, 10 - age // 30)
    return rank + recency


def determine(field_name, candidates, category="other", retired=()):
    """Pick the correct value for one field. Returns a decision dict.

    candidates: [{"field_value", "source_kind", "source_title", "source_ref", "source_date"}]
    """
    if field_name in TIER1_FIELD_OVERRIDES:
        return {"field_name": field_name, "value": NTXP_IDENTITY[TIER1_FIELD_OVERRIDES[field_name]],
                "status": "canonical", "jev_tier": 0, "basis": "Tier 1 rule (CLAUDE.md)",
                "rejected": [c for c in candidates
                             if normalize(c["field_value"]) != normalize(NTXP_IDENTITY[TIER1_FIELD_OVERRIDES[field_name]])]}

    retired_norm = {normalize(r) for r in retired}
    live = [c for c in candidates if normalize(c["field_value"]) not in retired_norm]
    dropped = [c for c in candidates if normalize(c["field_value"]) in retired_norm]

    if not live:
        return {"field_name": field_name, "value": None, "status": "missing", "jev_tier": 3,
                "basis": "no usable source - owner must supply", "rejected": dropped}

    groups = {}
    for c in live:
        g = groups.setdefault(normalize(c["field_value"]), {"value": c["field_value"], "sources": [], "score": 0})
        g["sources"].append(c)
        g["score"] = max(g["score"], _score(c))
    for g in groups.values():
        g["score"] += 5 * (len(g["sources"]) - 1)
    ranked = sorted(groups.values(), key=lambda g: g["score"], reverse=True)
    best = ranked[0]

    stale = all((_age_days(c.get("source_date")) or 0) > STALE_DAYS for c in best["sources"])
    if len(ranked) > 1 and best["score"] - ranked[1]["score"] < CLEAR_MARGIN:
        return {"field_name": field_name, "value": None, "status": "conflict", "jev_tier": 3,
                "basis": "sources disagree - owner decides"
                         + ("" if category in NO_COUNCIL_CATEGORIES else " (council may advise)"),
                "candidates": [{"value": mask(g["value"], category), "score": g["score"],
                                "sources": [s.get("source_title") for s in g["sources"]]} for g in ranked],
                "rejected": dropped}

    return {"field_name": field_name, "value": best["value"],
            "status": "stale" if stale else "canonical",
            "jev_tier": 3 if category in CONFIDENTIAL_CATEGORIES else 0,
            "basis": f"{best['sources'][0].get('source_kind')}: {best['sources'][0].get('source_title')}"
                     + (f" (+{len(best['sources']) - 1} agreeing)" if len(best["sources"]) > 1 else ""),
            "rejected": dropped + [s for g in ranked[1:] for s in g["sources"]]}


def determine_all(candidates_by_field, categories=None, retired=None):
    categories, retired = categories or {}, retired or {}
    return {f: determine(f, cands, categories.get(f, "other"), retired.get(f, ()))
            for f, cands in candidates_by_field.items()}


def canonical_values(decisions):
    """{field: value} for fields JEV settled; conflicts and missing values are left out."""
    return {f: d["value"] for f, d in decisions.items() if d["status"] in ("canonical", "stale")}


def main():
    p = argparse.ArgumentParser(description="NTXP Form Filler canonical answers (JEV determination)")
    p.add_argument("--determine", required=True,
                   help='JSON {"candidates": {field: [...]}, "categories": {...}, "retired": {...}}')
    a = p.parse_args()
    data = json.load(open(a.determine))
    decisions = determine_all(data["candidates"], data.get("categories"), data.get("retired"))
    for f, d in decisions.items():
        cat = (data.get("categories") or {}).get(f, "other")
        if d.get("value") is not None:
            d["value"] = mask(d["value"], cat)
    print(json.dumps(decisions, indent=2, default=str))


if __name__ == "__main__":
    sys.exit(main())
