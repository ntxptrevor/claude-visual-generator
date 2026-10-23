#!/usr/bin/env python3
"""SessionStart hook: load NTXP operating context into every session on this repo."""

import json
import os
import subprocess

CONTEXT = """NTXP session context (from .claude/hooks/session_start.py):
- Tier 1 identity rules are in CLAUDE.md: owner Alison Hopkins; operations contact Trevor Hopkins;
  designated signatory Alison (Trevor only with a stated circumstance); W-9 = S corporation box only;
  address 101 South Locust St Ste 605, Denton, TX 76201; phone 469-248-7431.
- Agent manual: docs/AGENT_MANUAL.md. Stuck? Search docs/ADMIN_RUNBOOK.md (or /api/runbook) first.
- JEV routing: admin_console/jev.py and scripts/nff_jev_router.py. Tier 0 deterministic first;
  personnel, owner, bid, pricing and credential content never go to DeepSeek or GLM.
- Tier 3 (external sends, deletes, sharing, money, DNS/hosting, signatures, bulk) always needs explicit
  owner approval. The PreToolUse hook (.claude/hooks/tier3_guard.py) forces a prompt for these.
- Parallel subagents are read-only; the main session is the single writer.
- This repo is PUBLIC: never commit keys, tokens, EINs of others, or employee data.
- Admin console: admin_console/ (API contract API.md; run NTXP_ADMIN_DEMO=1 uvicorn admin_console.server.app:app)."""


def git(*args):
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def main():
    lines = [CONTEXT]
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch:
        lines.append(f"- Current branch: {branch}.")
    unpushed = git("log", "--oneline", "@{u}..HEAD")
    if unpushed:
        lines.append(f"- Unpushed commits: {len(unpushed.splitlines())}. Push before the session ends.")
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        lines.append("- Cloud session: the container is temporary; commit and push anything worth keeping.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                             "additionalContext": "\n".join(lines)}}))


if __name__ == "__main__":
    main()
