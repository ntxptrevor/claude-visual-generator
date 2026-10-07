#!/usr/bin/env python3
"""
FormFlow Parallel Subagent Orchestrator

Plans fan-out of independent FormFlow work to parallel subagents, each sized
to the cheapest intelligence that can do it correctly, while keeping shared
state (the Google Sheets KB, Drive outputs) corruption-free.

Safety model (single-writer):
  - Workers are READ-ONLY against shared state. They return proposed changes
    (JSON "change sets"), never write to the KB or Drive directly.
  - One coordinator merges change sets, de-duplicates, detects conflicts, and
    performs every write serially, in one batch per tab.
  - Each change set carries the KB revision it was computed against; if the
    KB moved since, the coordinator re-validates before applying.
  - Signatures and confidential content never fan out to non-Claude seats.

Usage (CLI):
    python formflow_orchestrator.py --plan drive_scan --items 40
    python formflow_orchestrator.py --plan batch_fill --items 6
    python formflow_orchestrator.py --merge a.json b.json c.json
    python formflow_orchestrator.py --agents
"""

import argparse
import hashlib
import json
import sys


AGENT_PROFILES = {
    "scout": {
        "subagent_type": "Explore",
        "model": "haiku",
        "intelligence": "low",
        "use_for": ["list Drive files", "filename classification", "locate blank forms"],
        "can_see_confidential": True,
        "writes": False,
    },
    "extractor": {
        "subagent_type": "general-purpose",
        "model": "haiku",
        "intelligence": "low",
        "use_for": ["read one document", "regex/AcroForm field extraction"],
        "can_see_confidential": True,
        "writes": False,
    },
    "matcher": {
        "subagent_type": "general-purpose",
        "model": "sonnet",
        "intelligence": "medium",
        "use_for": ["map form fields to KB", "ambiguous labels", "complex layouts"],
        "can_see_confidential": True,
        "writes": False,
    },
    "reviewer": {
        "subagent_type": "general-purpose",
        "model": "opus",
        "intelligence": "high",
        "use_for": ["contradiction analysis", "client-facing sanity review",
                    "learning-loop reclassification"],
        "can_see_confidential": True,
        "writes": False,
    },
    "council": {
        "subagent_type": "council_run",
        "model": "council",
        "intelligence": "multi",
        "use_for": ["3-provider vote on non-confidential classification"],
        "can_see_confidential": False,
        "writes": False,
    },
}

COORDINATOR = {
    "role": "coordinator",
    "who": "main Claude session",
    "writes": True,
    "responsibilities": [
        "fan out work and collect change sets",
        "merge, de-duplicate and detect conflicts",
        "apply all KB/Drive writes serially",
        "present approval GUI and run every change gate",
        "apply signatures only after Tier 3 approval",
    ],
}

MAX_PARALLEL = 6
BATCH_SIZE = {"scout": 25, "extractor": 5, "matcher": 3, "reviewer": 1}

PLANS = {
    "drive_scan": [
        ("scout", "List and classify candidate files in each scan location"),
        ("extractor", "Read a batch of files and return extracted KB field proposals"),
    ],
    "batch_fill": [
        ("extractor", "Detect fields on one blank form"),
        ("matcher", "Map that form's fields to KB values with confidence"),
    ],
    "learning_loop": [
        ("extractor", "Compute correction / auto-fill stats per form type"),
        ("reviewer", "Analyze flagged fields and propose fixes"),
    ],
}

NEVER_PARALLEL = [
    "KB writes (append/update/delete rows)",
    "Drive saves, moves, renames",
    "Signature application",
    "Change-gate approvals",
]


def pick_agent(task_kind, confidential=False, ambiguity=0):
    if task_kind in ("list", "classify_filename"):
        name = "scout"
    elif task_kind in ("extract", "parse"):
        name = "extractor" if ambiguity < 2 else "matcher"
    elif task_kind in ("match",):
        name = "matcher" if ambiguity < 3 else "reviewer"
    elif task_kind in ("vote",):
        name = "reviewer" if confidential else "council"
    else:
        name = "reviewer"

    if confidential and not AGENT_PROFILES[name]["can_see_confidential"]:
        name = "reviewer"
    return name, AGENT_PROFILES[name]


def plan(job, item_count, confidential=False):
    if job not in PLANS:
        raise ValueError(f"Unknown job '{job}'. Choose from {sorted(PLANS)}")

    stages = []
    for agent_name, description in PLANS[job]:
        if confidential and not AGENT_PROFILES[agent_name]["can_see_confidential"]:
            agent_name = "reviewer"
        per = BATCH_SIZE.get(agent_name, 1)
        batches = max(1, -(-item_count // per))
        waves = -(-batches // MAX_PARALLEL)
        stages.append({
            "agent": agent_name,
            "profile": AGENT_PROFILES[agent_name],
            "task": description,
            "items_per_agent": per,
            "agents_total": batches,
            "parallel_waves": waves,
            "max_concurrent": min(batches, MAX_PARALLEL),
        })

    return {
        "job": job,
        "items": item_count,
        "confidential": confidential,
        "stages": stages,
        "coordinator": COORDINATOR,
        "never_parallel": NEVER_PARALLEL,
        "worker_contract": worker_contract(),
    }


def worker_contract():
    return {
        "instructions": (
            "You are a READ-ONLY FormFlow worker. Do not call any tool that "
            "writes, appends, updates, moves, shares or deletes. Return only "
            "a JSON change set in the schema below."
        ),
        "change_set_schema": {
            "worker_id": "string",
            "kb_revision": "revision id of the KB you read",
            "source": "file id or form name",
            "proposals": [{
                "op": "add|update|alternate",
                "field_name": "snake_case",
                "field_value": "string",
                "category": "business|contact|address|...",
                "field_type": "text|date|phone|...",
                "confidence": "0-100",
                "evidence": "short quote from the source",
            }],
        },
    }


def _key(p):
    return p["field_name"].strip().lower()


def merge_change_sets(change_sets, kb_entries=None):
    """Merge worker change sets into one serial write plan.

    Identical proposals collapse (highest confidence wins). Differing values
    for the same field become a conflict for the Tier 3 gate instead of a
    silent overwrite. Values that contradict the live KB are also conflicts.
    """
    kb, retired = {}, set()
    for e in kb_entries or []:
        name = e["field_name"].lower()
        if name.startswith("retired:"):
            retired.add((name[len("retired:"):], e.get("field_value", "").strip().lower()))
        else:
            kb[name] = e
    by_field = {}
    revisions = set()
    retired_hits = []

    for cs in change_sets:
        revisions.add(cs.get("kb_revision"))
        for p in cs.get("proposals", []):
            p = dict(p, _source=cs.get("source"), _worker=cs.get("worker_id"))
            if (_key(p), str(p["field_value"]).strip().lower()) in retired:
                retired_hits.append({"field_name": _key(p), "value": p["field_value"],
                                     "source": p["_source"]})
                continue
            by_field.setdefault(_key(p), []).append(p)

    writes, conflicts, skipped = [], [], []
    for field, props in by_field.items():
        values = {}
        for p in props:
            v = str(p["field_value"]).strip()
            if v not in values or int(p.get("confidence", 0)) > int(values[v].get("confidence", 0)):
                values[v] = p

        if len(values) > 1:
            conflicts.append({"field_name": field, "candidates": list(values.values()),
                              "gate_tier": 3})
            continue

        (value, best), = values.items()
        existing = kb.get(field)
        if existing and existing.get("field_value", "").strip().lower() == value.lower():
            skipped.append({"field_name": field, "reason": "already in KB"})
        elif existing:
            conflicts.append({"field_name": field, "candidates": [best],
                              "existing": existing.get("field_value"), "gate_tier": 3})
        else:
            writes.append(best)

    return {
        "writes": writes,
        "conflicts": conflicts,
        "skipped": skipped,
        "retired_rejected": retired_hits,
        "stale_revision": len(revisions - {None}) > 1,
        "write_digest": hashlib.sha256(
            json.dumps(writes, sort_keys=True).encode()).hexdigest()[:16],
    }


def main():
    parser = argparse.ArgumentParser(description="FormFlow Parallel Orchestrator")
    parser.add_argument("--plan", choices=sorted(PLANS))
    parser.add_argument("--items", type=int, default=10)
    parser.add_argument("--confidential", action="store_true")
    parser.add_argument("--merge", nargs="+", help="Worker change-set JSON files")
    parser.add_argument("--kb-json", help="Current KB entries JSON for conflict checks")
    parser.add_argument("--agents", action="store_true")
    args = parser.parse_args()

    if args.agents:
        print(json.dumps({"agents": AGENT_PROFILES, "coordinator": COORDINATOR,
                          "never_parallel": NEVER_PARALLEL}, indent=2))
    elif args.plan:
        print(json.dumps(plan(args.plan, args.items, args.confidential), indent=2))
    elif args.merge:
        sets = []
        for path in args.merge:
            with open(path) as f:
                sets.append(json.load(f))
        kb = None
        if args.kb_json:
            with open(args.kb_json) as f:
                kb = json.load(f)
        print(json.dumps(merge_change_sets(sets, kb), indent=2))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
