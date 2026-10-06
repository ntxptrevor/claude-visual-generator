#!/usr/bin/env python3
"""
FormFlow Self-Learning Loop

Monitors skill usage, seeks ways to fill DB gaps, corrects fields/types
that commonly need human correction, and consults the Model Council.

Triggers:
  - correction_count > 3: Flag field for review
  - correction_count > 5: Council consult for reclassification
  - Form type < 60% auto-fill rate: Research that form type
  - New form type encountered: Add to Workflows tab
  - KB field unused 90+ days: Flag as potentially stale
  - KB contradiction (2+ sources disagree): Council vote

Usage (as library):
    from formflow_learning_loop import LearningLoop
    loop = LearningLoop(kb_entries, session_entries, learning_entries)
    actions = loop.analyze()
    loop.apply_actions(actions)

Usage (CLI):
    python formflow_learning_loop.py --analyze --kb kb.json --sessions sessions.json
    python formflow_learning_loop.py --digest --format json
"""

import argparse
import json
import sys
from datetime import datetime, timedelta


CORRECTION_THRESHOLD_REVIEW = 3
CORRECTION_THRESHOLD_COUNCIL = 5
AUTO_FILL_RATE_THRESHOLD = 60.0
STALE_DAYS_THRESHOLD = 90
MIN_SESSIONS_FOR_STATS = 2


def analyze_corrections(kb_entries):
    """Find fields with high correction counts that need attention."""
    actions = []

    for entry in kb_entries:
        corrections = int(entry.get("correction_count", 0))
        field_name = entry.get("field_name", "")
        field_type = entry.get("field_type", "text")

        if corrections >= CORRECTION_THRESHOLD_COUNCIL:
            actions.append({
                "action": "council_consult",
                "priority": "high",
                "field_name": field_name,
                "correction_count": corrections,
                "current_type": field_type,
                "current_value": entry.get("field_value", ""),
                "detail": f"Field '{field_name}' corrected {corrections} times. "
                         f"Current type: {field_type}. Consider reclassification.",
                "council_category": "classification",
                "jev_tier": 2
            })
        elif corrections >= CORRECTION_THRESHOLD_REVIEW:
            actions.append({
                "action": "flag_for_review",
                "priority": "medium",
                "field_name": field_name,
                "correction_count": corrections,
                "current_type": field_type,
                "current_value": entry.get("field_value", ""),
                "detail": f"Field '{field_name}' corrected {corrections} times. "
                         f"May need type or value adjustment.",
                "jev_tier": 1
            })

    return actions


def analyze_auto_fill_rates(session_entries):
    """Find form types with poor auto-fill rates that need more KB coverage."""
    actions = []

    by_type = {}
    for session in session_entries:
        form_type = session.get("form_type", "general")
        total = int(session.get("fields_total", 0))
        auto = int(session.get("fields_auto", 0))

        if total == 0:
            continue

        if form_type not in by_type:
            by_type[form_type] = {"total_fields": 0, "auto_fields": 0, "count": 0}
        by_type[form_type]["total_fields"] += total
        by_type[form_type]["auto_fields"] += auto
        by_type[form_type]["count"] += 1

    for form_type, stats in by_type.items():
        if stats["count"] < MIN_SESSIONS_FOR_STATS:
            continue

        rate = (stats["auto_fields"] / stats["total_fields"]) * 100 if stats["total_fields"] > 0 else 0

        if rate < AUTO_FILL_RATE_THRESHOLD:
            actions.append({
                "action": "research_form_type",
                "priority": "medium",
                "form_type": form_type,
                "auto_fill_rate": round(rate, 1),
                "session_count": stats["count"],
                "detail": f"Form type '{form_type}' has {rate:.1f}% auto-fill rate "
                         f"across {stats['count']} sessions. Research missing fields.",
                "jev_tier": 1
            })

    return actions


def analyze_contradictions(kb_entries):
    """Find fields where multiple sources disagree on the value."""
    actions = []

    by_field = {}
    for entry in kb_entries:
        field_name = entry.get("field_name", "")
        if field_name not in by_field:
            by_field[field_name] = []
        by_field[field_name].append(entry)

    for field_name, entries in by_field.items():
        if len(entries) < 2:
            continue

        values = set()
        for e in entries:
            val = e.get("field_value", "").strip().lower()
            if val:
                values.add(val)
            alts = e.get("alternates", "")
            for alt in alts.split("|"):
                alt = alt.strip().lower()
                if alt:
                    values.add(alt)

        if len(values) > 1:
            entries_detail = []
            for e in entries:
                entries_detail.append({
                    "value": e.get("field_value", ""),
                    "source": e.get("source", ""),
                    "confidence": int(e.get("confidence", 0))
                })

            actions.append({
                "action": "resolve_contradiction",
                "priority": "high",
                "field_name": field_name,
                "conflicting_values": list(values),
                "entries": entries_detail,
                "detail": f"Field '{field_name}' has {len(values)} conflicting values: "
                         f"{', '.join(values)}",
                "council_category": "methodology",
                "jev_tier": 2
            })

    return actions


def analyze_stale_fields(kb_entries, reference_date=None):
    """Find KB fields that haven't been used or updated in a long time."""
    actions = []

    if reference_date is None:
        reference_date = datetime.utcnow()

    threshold_date = reference_date - timedelta(days=STALE_DAYS_THRESHOLD)

    for entry in kb_entries:
        updated = entry.get("updated_at", "")
        if not updated:
            continue

        try:
            updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00").replace("+00:00", ""))
        except (ValueError, TypeError):
            continue

        if updated_dt < threshold_date:
            actions.append({
                "action": "flag_stale",
                "priority": "low",
                "field_name": entry.get("field_name", ""),
                "last_updated": updated,
                "days_stale": (reference_date - updated_dt).days,
                "current_value": entry.get("field_value", ""),
                "detail": f"Field '{entry.get('field_name')}' not updated in "
                         f"{(reference_date - updated_dt).days} days. "
                         f"May need verification.",
                "jev_tier": 0
            })

    return actions


def analyze_type_mismatches(kb_entries):
    """Detect fields where the stored type doesn't match the value pattern."""
    import re
    actions = []

    type_patterns = {
        "date": r"^\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}$",
        "email": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
        "phone": r"^\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}$",
        "zip": r"^\d{5}(-\d{4})?$",
        "ssn": r"^\d{3}-?\d{2}-?\d{4}$",
        "ein": r"^\d{2}-?\d{7}$",
        "number": r"^\d+$",
        "currency": r"^\$?[\d,]+\.?\d{0,2}$",
    }

    for entry in kb_entries:
        value = entry.get("field_value", "").strip()
        stored_type = entry.get("field_type", "text")

        if not value or stored_type == "text":
            continue

        expected_pattern = type_patterns.get(stored_type)
        if expected_pattern and not re.match(expected_pattern, value):
            detected_type = "text"
            for type_name, pattern in type_patterns.items():
                if re.match(pattern, value):
                    detected_type = type_name
                    break

            if detected_type != stored_type:
                actions.append({
                    "action": "reclassify_type",
                    "priority": "medium",
                    "field_name": entry.get("field_name", ""),
                    "stored_type": stored_type,
                    "detected_type": detected_type,
                    "value": value,
                    "detail": f"Field '{entry.get('field_name')}' stored as '{stored_type}' "
                             f"but value '{value}' looks like '{detected_type}'.",
                    "jev_tier": 1
                })

    return actions


def analyze_new_form_types(session_entries, workflow_entries):
    """Detect form types seen in sessions but not in the Workflows tab."""
    actions = []

    known_types = set()
    for wf in workflow_entries:
        known_types.add(wf.get("form_type", ""))

    session_types = {}
    for session in session_entries:
        ft = session.get("form_type", "")
        if ft and ft not in known_types and ft != "general":
            session_types[ft] = session_types.get(ft, 0) + 1

    for ft, count in session_types.items():
        if count >= 2:
            actions.append({
                "action": "add_workflow",
                "priority": "medium",
                "form_type": ft,
                "session_count": count,
                "detail": f"Form type '{ft}' seen {count} times but has no prewired workflow. "
                         f"Consider adding field mappings.",
                "jev_tier": 1
            })

    return actions


def run_full_analysis(kb_entries, session_entries, learning_entries=None,
                      workflow_entries=None):
    """Run all analysis checks and return prioritized action list."""
    all_actions = []

    all_actions.extend(analyze_corrections(kb_entries))
    all_actions.extend(analyze_auto_fill_rates(session_entries))
    all_actions.extend(analyze_contradictions(kb_entries))
    all_actions.extend(analyze_stale_fields(kb_entries))
    all_actions.extend(analyze_type_mismatches(kb_entries))

    if workflow_entries is not None:
        all_actions.extend(analyze_new_form_types(session_entries, workflow_entries))

    priority_order = {"high": 0, "medium": 1, "low": 2}
    all_actions.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 3))

    return all_actions


def generate_digest(actions):
    """Generate a human-readable digest of learning loop findings."""
    if not actions:
        return {
            "summary": "No learning actions needed. KB is in good shape.",
            "action_count": 0,
            "by_priority": {"high": 0, "medium": 0, "low": 0},
            "by_action": {},
            "estimated_cost": "$0"
        }

    by_priority = {"high": 0, "medium": 0, "low": 0}
    by_action = {}
    cost_estimate = 0.0

    for action in actions:
        p = action.get("priority", "low")
        a = action.get("action", "unknown")
        by_priority[p] = by_priority.get(p, 0) + 1
        by_action[a] = by_action.get(a, 0) + 1

        tier = action.get("jev_tier", 0)
        if tier == 0:
            cost_estimate += 0
        elif tier == 1:
            cost_estimate += 0.001
        elif tier == 2:
            cost_estimate += 0.01

    return {
        "summary": f"{len(actions)} learning actions found: "
                  f"{by_priority.get('high', 0)} high, "
                  f"{by_priority.get('medium', 0)} medium, "
                  f"{by_priority.get('low', 0)} low priority.",
        "action_count": len(actions),
        "by_priority": by_priority,
        "by_action": by_action,
        "estimated_cost": f"${cost_estimate:.3f}",
        "actions": actions
    }


def build_learning_rows(actions):
    """Convert actions into Learning tab rows for logging."""
    rows = []
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    for action in actions:
        import uuid
        row = [
            str(uuid.uuid4())[:12],
            action.get("action", "unknown"),
            action.get("field_name", action.get("form_type", "")),
            action.get("detail", ""),
            "",
            "",
            now
        ]
        rows.append(row)

    return rows


def main():
    parser = argparse.ArgumentParser(description="FormFlow Self-Learning Loop")
    parser.add_argument("--analyze", action="store_true", help="Run full analysis")
    parser.add_argument("--digest", action="store_true", help="Generate digest")
    parser.add_argument("--kb", type=str, help="Path to KB entries JSON")
    parser.add_argument("--sessions", type=str, help="Path to session entries JSON")
    parser.add_argument("--workflows", type=str, default=None, help="Path to workflow entries JSON")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    args = parser.parse_args()

    kb_entries = []
    session_entries = []
    workflow_entries = []

    if args.kb:
        with open(args.kb) as f:
            kb_entries = json.load(f)

    if args.sessions:
        with open(args.sessions) as f:
            session_entries = json.load(f)

    if args.workflows:
        with open(args.workflows) as f:
            workflow_entries = json.load(f)

    if args.analyze or args.digest:
        actions = run_full_analysis(kb_entries, session_entries,
                                    workflow_entries=workflow_entries or None)

        if args.digest:
            digest = generate_digest(actions)
            if args.format == "json":
                print(json.dumps(digest, indent=2))
            else:
                print(f"\n{'='*50}")
                print(f"  FormFlow Learning Loop Digest")
                print(f"{'='*50}")
                print(f"\n  {digest['summary']}")
                print(f"  Estimated cost: {digest['estimated_cost']}")
                print()
                for action in actions:
                    priority_marker = {"high": "!!!", "medium": "!!", "low": "!"}.get(
                        action.get("priority", "low"), "")
                    print(f"  [{priority_marker}] {action.get('action')}: "
                          f"{action.get('detail', '')[:80]}")
        else:
            if args.format == "json":
                print(json.dumps(actions, indent=2))
            else:
                print(f"\n{len(actions)} actions found.")
                for i, action in enumerate(actions, 1):
                    print(f"\n  {i}. [{action['priority'].upper()}] {action['action']}")
                    print(f"     {action.get('detail', '')}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
