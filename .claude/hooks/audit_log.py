#!/usr/bin/env python3
"""PostToolUse hook: append a one-line audit record for every mutating tool call.

Records the tool name, time and a SHA-256 digest of the input, never the input itself,
so the log can't leak message bodies or secrets. Log: .claude/audit/tool-audit.jsonl
(git-ignored; this repo is public).
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

READ_ONLY = re.compile(
    r"^(Read|Glob|Grep|WebSearch|WebFetch|ToolSearch|TaskGet|TaskList|ListAgents|"
    r"mcp__.*__(get|list|search|read|fetch|query|count|aggregate|inspect|describe|check|whoami)"
    r"[_-]?.*)$", re.IGNORECASE)


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return
    tool = event.get("tool_name", "")
    if READ_ONLY.match(tool):
        return
    payload = json.dumps(event.get("tool_input") or {}, sort_keys=True, default=str)
    record = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": event.get("session_id", ""),
        "tool": tool,
        "input_sha256": hashlib.sha256(payload.encode()).hexdigest()[:16],
        "remote": os.environ.get("CLAUDE_CODE_REMOTE") == "true",
    }
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR", "."))
    log = root / ".claude" / "audit" / "tool-audit.jsonl"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    main()
