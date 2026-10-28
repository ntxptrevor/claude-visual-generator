#!/usr/bin/env python3
"""PreToolUse hook: force an owner approval prompt for NTXP Tier 3 actions.

Sessions on this repo run with permission prompts off, so this hook is the
safety net for anything external, destructive, financial, public or bulk.
"""

import json
import re
import sys

TIER3_TOOLS = [
    (r"^mcp__Gmail__(send_message|reply|forward|create_draft|trash_|delete_)", "sends or deletes email"),
    (r"^mcp__iCloud_MCP__(send_email|reply_email|m365_send_email|m365_reply_email|send_message|"
     r"teams_send|whatsapp_send|signal_|zalo_send|delete_)", "sends a message or deletes data"),
    (r"^mcp__Slack__slack_(send_message|schedule_message)", "posts to Slack"),
    (r"^mcp__Quo__(send-message|send-bulk-messages|send-group-message)", "sends a text message"),
    (r"^mcp__Twilio__", "uses the phone/SMS system"),
    (r"^mcp__Google_Drive__(trash_file|share_file)", "deletes or shares a Drive file"),
    (r"^mcp__Google_Calendar__(delete_event|respond_to_event)", "changes a calendar commitment"),
    (r"^mcp__Intuit_QuickBooks__qbo_(sales_(send|delete|create)|payroll_(create|update|save)|"
     r"catalog_create|contact_create)", "changes accounting or payroll"),
    (r"^mcp__Hostinger_Connector__(execute|multi-execute)", "changes hosting, DNS or a server"),
    (r"^mcp__Vercel__(create|delete|update|buy|patch|put|replace|assign|request|start|"
     r"approve|complete|cancel|pause|unpause|upload|add|edit)", "changes a Vercel deployment or domain"),
    (r"^mcp__Cloudflare_Developer_Platform__.*_(create|delete|update|edit)", "changes Cloudflare resources"),
    (r"^mcp__Supabase__(apply_migration|execute_sql|delete|create|deploy|merge|reset|pause|restore)",
     "changes a database or project"),
    (r"^mcp__GoDaddy__", "touches domains"),
    (r"^mcp__Zapier__(execute_zapier_write_action|run_workflow|publish|delete|enable|update)",
     "runs or changes an automation"),
    (r"^mcp__Lightfield__write_to_lightfield", "writes to the CRM"),
    (r"^mcp__GovTribe__(Delete|Send|Create_Teaming|Withdraw|Respond)", "changes a GovTribe record or message"),
    (r"^mcp__HubSpot__manage_", "changes marketing content"),
    (r"^mcp__Claude_Code_Remote__(create_trigger|update_trigger|delete_trigger|fire_trigger|send_later)",
     "schedules or fires automation"),
]

TIER3_BASH = [
    (r"\bgit\s+push\b[^\n]*(--force|-f\b|--force-with-lease)", "force-pushes git history"),
    (r"\bgit\s+(reset\s+--hard|clean\s+-[a-z]*f|branch\s+-D)", "discards git work"),
    (r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r", "recursively deletes files"),
    (r"\bgcloud\b[^\n]*\b(delete|remove-iam-policy-binding|disable)\b", "deletes or disables a Google Cloud resource"),
    (r"\bgcloud\b[^\n]*\bkeys\s+create\b", "creates a service-account key"),
    (r"\bcurl\b[^\n]*api\.openphone\.com[^\n]*messages", "sends a text message"),
    (r"\b(nff|formflow)_signatures\.py\b[^\n]*--apply\b", "stamps a signature"),
    (r"\bnff_gui\.py\b[^\n]*--export-signed\b", "stamps a signature"),
]


def decide(tool_name, tool_input):
    for pattern, why in TIER3_TOOLS:
        if re.search(pattern, tool_name):
            return why
    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        for pattern, why in TIER3_BASH:
            if re.search(pattern, command):
                return why
    return None


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return
    why = decide(event.get("tool_name", ""), event.get("tool_input") or {})
    if not why:
        return
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": (
            f"NTXP Tier 3: this {why}. Owner approval is required before it runs "
            f"(CLAUDE.md, ntxp-change-gate)."),
    }}))


if __name__ == "__main__":
    main()
