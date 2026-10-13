"""JEV routing for the NTXP Admin Console.

Every analytics or search step asks route() which executor to use. Deterministic work
stays at Tier 0 ($0). Model work goes to the cheapest seat allowed for the data. Personnel
content (employee behaviour, messages between staff) is confidential: Ledger (DeepSeek)
and Mason (GLM) never see it, per the Model Council hard rules.
"""

TASKS = {
    # task: (tier, executor, est_cost_usd)
    "query_build":        (0, "rules", 0.0),
    "gmail_fetch":        (0, "gmail_api", 0.0),
    "drive_fetch":        (0, "drive_api", 0.0),
    "kpi_compute":        (0, "python", 0.0),
    "baseline_anomaly":   (0, "python_stats", 0.0),
    "classify_message":   (0, "lexicon", 0.0),
    "crosscheck_fetch":   (0, "source_apis", 0.0),
    "contact_dedupe":     (0, "python", 0.0),
    "guide_questions":    (1, "claude-haiku", 0.002),
    "rerank":             (1, "claude-haiku", 0.002),
    "classify_ambiguous": (1, "claude-haiku", 0.002),
    "volatility":         (1, "claude-haiku", 0.002),
    "trend_summary":      (1, "claude-haiku", 0.003),
    "report_write":       (2, "claude-sonnet", 0.015),
    "council_conclusion": (2, "council_run", 0.010),
    "notify_owner":       (2, "notify_then_act", 0.0),
    "message_external":   (3, "change_gate", 0.0),
    "account_change":     (3, "change_gate", 0.0),
    "bulk_delete":        (3, "change_gate", 0.0),
}

PERSONNEL_FORBIDDEN_SEATS = ("deepseek", "glm")
PERSONNEL_TASKS = {"classify_message", "classify_ambiguous", "volatility", "trend_summary",
                   "report_write", "council_conclusion", "rerank", "baseline_anomaly"}


def route(task, personnel=None, ambiguity=0):
    """Return the routing decision for a task.

    personnel defaults to True for tasks that touch staff behaviour or staff messages.
    ambiguity >= 2 bumps a Tier 0 classifier up to the Tier 1 model check.
    """
    if task not in TASKS:
        return {"task": task, "tier": 3, "executor": "change_gate", "cost": 0.0,
                "reason": "unknown task -> fail safe to Tier 3", "forbidden_seats": []}

    tier, executor, cost = TASKS[task]
    if task == "classify_message" and ambiguity >= 2:
        tier, executor, cost = TASKS["classify_ambiguous"]

    if personnel is None:
        personnel = task in PERSONNEL_TASKS

    decision = {"task": task, "tier": tier, "executor": executor, "cost": cost,
                "confidential": bool(personnel),
                "forbidden_seats": list(PERSONNEL_FORBIDDEN_SEATS) if personnel else []}
    if executor == "council_run":
        decision["council_args"] = {"confidential": bool(personnel),
                                    "category": "classification", "min_providers": 3}
    return decision


def stamp(decision):
    """The `jev` object every API response carries."""
    return {"tier": decision["tier"], "executor": decision["executor"],
            "cost": decision["cost"]}
