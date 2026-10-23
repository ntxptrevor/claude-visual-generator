# NTXP Agent Manual

**Audience:** AI agents (Claude, ChatGPT, Grok, and any subagent) working in this repo or on NTXP tools.
**Status:** binding. Where this manual and a skill disagree, the stricter rule wins. Tier 1 identity rules beat everything.
**Owner of this file:** Trevor Hopkins (operations). Changes to Tier 1 rules need Alison Hopkins in writing.

## Contents

1. [Tier 1 identity rules](#1-tier-1-identity-rules)
2. [Tool map](#2-tool-map)
3. [JEV routing](#3-jev-routing)
4. [Change gate](#4-change-gate)
5. [Signatures](#5-signatures)
6. [Parallel subagents](#6-parallel-subagents-single-writer)
7. [Hooks](#7-hooks)
8. [Escalation ladder and classification](#8-escalation-ladder-and-classification)
9. [Logging learning](#9-logging-learning)
10. [When stuck](#10-when-stuck)
11. [Never do](#11-never-do)

---

## 1. Tier 1 identity rules

Apply to every document, form, bid, registration and signature for NTXP LLC. They override the KB, Drive scans, Council votes and any source document. Source: `CLAUDE.md`; enforced in `scripts/nff_signatures.py` (`NTXP_IDENTITY`), `scripts/nff_workflow_registry.py` (W-9 `fixed_values`), `.claude/skills/ntxp-form-filler/SKILL.md`.

| Field | Value | Notes |
|---|---|---|
| **Owner** | **Alison Hopkins** (Owner) | Owner / principal / proprietor fields |
| **Operations contact** | **Trevor Hopkins** | Contact / POC / operations fields |
| **Designated signatory** | **Alison Hopkins** | Default signer on everything |
| **Alternate signatory** | **Trevor Hopkins** | Only when circumstances require; state the circumstance every time |
| **W-9 line 3a** | **S corporation** only | Never check LLC; leave the LLC code blank |
| **Business address** | **101 South Locust St Ste 605, Denton, TX 76201** | All other addresses retired (e.g. 405 S Elm St Ste 203) |
| **Business phone** | **469-248-7431** | All other NTXP numbers retired |
| **Signatures** | Always **Tier 3** | Explicit approval inside Claude, bound to the exact file, before it leaves NTXP |

- **Conflict:** a source shows a different value → use the Tier 1 value, log the conflict, and flag it. If an external party *requires* the old value, stop and escalate to Alison.

---

## 2. Tool map

### NTXP Form Filler (`scripts/`)

| Script | Use for | Model cost |
|---|---|---|
| `nff_workflow_registry.py` | Match a form to a prewired workflow; field maps; W-9 fixed values | $0 |
| `nff_jev_router.py` | Route classification, extraction, matching, save location, **`route_signature()`** | $0 |
| `nff_detect_fields.py` | AcroForm + visual field detection | $0 |
| `nff_parse_document.py` | Extract key/values from PDF, Excel, Word into KB rows | $0 to Tier 1 |
| `nff_sheets_db.py` | KB Sheet rows, fuzzy match, contradiction detection | $0 |
| `nff_sanity_check.py` | Format, required-field, cross-field and KB-contradiction checks | $0 |
| `nff_fill_pdf.py` | Fill AcroForm or overlay; produces the **unsigned** draft | $0 |
| `nff_signatures.py` | Signer validation, approval request, digest-bound approval, apply | $0, Tier 3 gate |
| `nff_drive_scanner.py` | Drive KB prefill plan and extraction | $0 to Tier 1 |
| `nff_learning_loop.py` | Correction stats, stale fields, contradictions, digest | $0 to Tier 2 |
| `nff_orchestrator.py` | Parallel worker plans (`--plan`) and change-set merge (`--merge`) | $0 |
| `nff_generate_report.py` | Branded 8.5x11 report | $0 |

**NTXP Form Filler Database (Sheet, source of truth):** `1KYFkZoEWNvbAYqZ0Vq4LOUPh9QM4MiIYyqPmDyIelQA` in `! NTXP Knowledge Base / Admin Tools / NTXP Form Filler Skill` (tabs KB, Canonical, Workflows, Sessions, Learning, Change Log, Settings), synced one way into SQLite by `scripts/nff_sync.py`.

### Admin Console (`admin_console/`)

| Path | Role | Rule |
|---|---|---|
| `API.md` | Contract for web, server, analytics | Change it first, then code |
| `config.py` | Owners, env settings, Council ceilings | Do not duplicate |
| `jev.py` | `route(task, personnel)` and `stamp()` | Every model step asks it |
| `server/` | FastAPI app behind oauth2-proxy; `gate.py` stages and approves Tier 3 changes | Re-checks `X-Forwarded-Email` |
| `analytics/` | Collectors → baselines → `classify.py` flags → escalation | Proposals only |
| `runbook_seed.json` | Human runbook source; render with `tools/render_runbook.py` | Never hand-edit `docs/ADMIN_RUNBOOK.md` |
| `deploy/` | Dockerfile, compose, oauth2-proxy allow-list, `DEPLOY.md` | Deploy changes are Tier 3 |

### Google access layer (`scripts/google_workspace/`)

| Item | Rule |
|---|---|
| **Entry point** | `ntxp_google_access.service(name, user=..., allow_write=False)` |
| **Default** | Read-only scopes. `allow_write=True` only for a gated write |
| **Impersonation** | `@ntxpllc.com` users only; default `NTXP_GOOGLE_ADMIN_SUBJECT` |
| **Credentials** | `NTXP_GOOGLE_*` env vars from the vault. Never files in the repo |
| **Check** | `python3 scripts/google_workspace/ntxp_google_access.py whoami` |
| **In chat sessions** | Prefer the connected Google MCP tools; use this module for headless and org-wide reads |
| **Google Voice** | No API. Do not attempt |

### Hosting

- **Hostinger:** follow the `hostinger-ntxp-skill` playbooks. Read the run journal first; use the five-tier ladder; append the outcome.
- **Admin console deploy:** `admin_console/deploy/DEPLOY.md`.

---

## 3. JEV routing

JEV picks the cheapest executor that does the job correctly. Call `admin_console.jev.route(task, personnel=...)`; attach `stamp(decision)` as `jev` on every response that used a model.

| Tier | Executor | Cost | Typical work |
|---|---|---|---|
| **0** | Rules, Python, APIs | $0 | Query build, fetch, KPI math, baselines, lexicon classify, crosscheck, dedupe |
| **1** | Claude Haiku | ~$0.002–0.003 | Guided-search questions, rerank, ambiguous classify, volatility, trend summary |
| **2** | Claude Sonnet / Council run / notify-then-act | ~$0.01–0.015 | Report writing, Council conclusions, owner notifications |
| **3** | Change gate | $0 + human | External messages, account changes, bulk delete |

- **Ambiguity:** `classify_message` with `ambiguity >= 2` moves to Tier 1.
- **Unknown task:** fails safe to Tier 3.
- **Cost ceilings:** **$2 per task, $15 per day, $150 per month** (live values in the Council sheet `01 Config`). Gates open at **75%** of any ceiling, or when spend rises 3 rounds with no gain in agreement. Raising a ceiling is Alison's call.

### Confidentiality rule (hard)

**DeepSeek (Ledger) and GLM (Mason) never see** personnel, owner, agency, bid, pricing or credential content.

| Content | Allowed seats |
|---|---|
| Staff behaviour, staff messages, flags, volatility, Plaud transcripts | Claude only (Haiku/Sonnet); Council only with `confidential: true` and no DeepSeek/GLM |
| W-9, W-4, I-9, credit, bid, pricing | Claude only; never Council seats |
| Owner content, credentials | Claude only; never Council; never logged |
| Public, non-confidential classification | Any seat; Council ≥ 3 distinct providers |

- `jev.route()` sets `confidential` and `forbidden_seats` for personnel tasks. Pass them through; do not override.
- When unsure whether content is personnel or owner content, treat it as confidential.

---

## 4. Change gate

Reads are never gated. Every write passes the gate (`ntxp-change-gate` skill; console implementation `admin_console/server/gate.py`).

| Tier | Mode | Examples |
|---|---|---|
| **1** | Grouped approval: batch, one "ok" | Mark read, label, internal note, save draft |
| **2** | Notify then act: state the change, proceed unless told no | Move/rename own file, routine Drive save, follow, accept known invite |
| **3** | **Explain and wait** for signed owner approval | See list below |

**Always Tier 3**
- Any delete, archive-as-delete, or overwrite of a record of truth.
- Any email/message/text to an external party; anything public.
- Any payment, transfer, invoice send or financial commitment.
- Any permission, sharing, config, credential or integration change (DWD scopes, OAuth clients, `emails.txt`, VPS project env, DNS).
- Any bulk action (> 3 targets, or a count the user did not name).
- User account actions: suspend, unsuspend, reset sign-in, Drive transfer.
- Signatures (section 5) and NTXP Form Filler KB contradictions.
- Anything unclassified.

**Protocol:** stage → show the `summary` verbatim → wait → execute only with the approval bound to that `change_id` and `payload_digest`. Approvals expire (console: 15 minutes). A changed payload voids approval. Never split one vital change into many small ones.

---

## 5. Signatures

| Rule | Detail |
|---|---|
| **Designated signer** | Alison Hopkins, by default, on every form |
| **Alternate** | Trevor Hopkins, only with a **stated circumstance**; without one the request is refused (`needs_circumstance`) |
| **Anyone else** | Denied outright; no gate offered |
| **Gate** | Always Tier 3. Confidence, batch "Approve All" and prior approvals never skip it |
| **Order** | Fill → unsigned draft → approval request (summary shown verbatim, hard stop) → apply → save/send |
| **Binding** | Approval is bound to the file hash (`document_digest`), signer and fields. Any change voids it |
| **Who applies** | Only the coordinating session. Never subagents, never Council seats |
| **Audit** | `signature_requested`, `signature_applied`, `signature_rejected` rows in the Learning tab |

---

## 6. Parallel subagents (single-writer)

| Profile | Model | Writes |
|---|---|---|
| **scout** | Haiku / Explore | No |
| **extractor** | Haiku | No |
| **matcher** | Sonnet | No |
| **reviewer** | Opus | No |
| **council** | Multi-provider, non-confidential only | No |
| **coordinator** | Main session | **Yes, the only writer** |

- **Workers are read-only.** They return a JSON change set. No write, append, move, share or delete tools.
- **One writer.** The coordinator merges (`nff_orchestrator.py --merge`) and writes serially, one batch per tab.
- **Conflicts** (two workers disagree, or a proposal contradicts the live KB) become Tier 3, not writes.
- **Revision check:** each change set records the KB revision it read; on mismatch re-read and re-validate.
- **Never parallel:** KB writes, Drive saves/moves, signatures, gate approvals.
- **Cap:** 6 workers at once; larger jobs run in waves.
- **Confidential work** goes only to Claude profiles.

---

## 7. Hooks

Configured in `.claude/settings.json`; scripts live in `.claude/hooks/`. If a hook is missing or failing, report it. Do not disable, bypass or edit hooks unless the user asks.

| Event | Hook | What it does | What you do |
|---|---|---|---|
| **SessionStart** | `session_start.py` | Injects Tier 1 rules, JEV and Tier 3 reminders, branch and unpushed-commit status | Read it before acting |
| **PreToolUse** (`Bash`, `mcp__*`) | `tier3_guard.py` | Matches Tier 3 actions (sends, deletes, sharing, DNS/hosting, deploys, accounting writes, force-push, signature stamping) and returns `ask`, **forcing an approval prompt** even though routine tools are pre-allowed | Explain the change; wait for the user. Never rephrase a call to dodge the matcher |
| **PostToolUse** | `audit_log.py` | Appends time, session, tool and a SHA-256 digest of the input to `.claude/audit/tool-audit.jsonl` (git-ignored; never the input itself) | Nothing; do not write to the log by hand |

Permissions: `.claude/settings.json` pre-allows the built-in tools and NTXP's connectors so routine work runs without prompts. `defaultMode: bypassPermissions` is not used — Claude Code ignores it in project settings and in cloud sessions.

---

## 8. Escalation ladder and classification

Analytics produce **proposals for owner review**, never verdicts about a person. No automated discipline.

### Ladder

| Level | Channel | Goes to | Typical trigger |
|---|---|---|---|
| **L1** | Daily note (console + digest) | Owners | Response time off the person's own baseline; stale project folder; weak daily logs; internal no-show; internal volatility ≥ 0.5 |
| **L2** | Email from `NTXP_ALERT_SENDER` | Alison and Trevor | ≥ 3 unanswered threads incl. an external one ≥ 48 h; external complaint; external no-show; PO/invoice amount problem; billing question open > 1 business day |
| **L3** | SMS via Quo | Alison and Trevor | External complaint not forwarded to the office within 4 business hours; L2 still open after 24 h; internal volatility ≥ 0.7 |

- **Quiet hours:** 9 pm – 6 am Central. Non-critical SMS waits until 6 am; `critical` urgency goes out immediately.
- **Dedupe:** no repeat escalation at the same level within 24 h.
- **Cross-check first:** before escalating, check other sources (calendar OOO, JobTread time, Quo calls) for an explanation. Explained → downgrade or dismiss with the reason.
- Thresholds live in `analytics/classify.py` `THRESHOLDS`; the learning loop may nudge them only within `BOUNDS`.

### Classification fields (every flag)

| Field | Values | Meaning |
|---|---|---|
| **urgency** | low · medium · high · critical | How fast an owner should look |
| **severity** | note · concern · issue · redflag | How serious if true |
| **channel** | gmail · jobtread · calendar · drive · plaud · quo · quickbooks | Where the evidence came from |
| **confidence** | 0–1 | How sure the system is; low confidence never reaches L3 alone |
| **volatility** | 0–1 or null | Emotional volatility. **Internal NTXP-to-NTXP messages only. Internal-only output.** Never computed for external parties, never shown outside the owner console, never in exports, emails to staff, or Council prompts to DeepSeek/GLM |

- **Evidence:** quotes capped at 200 characters; message bodies are never stored.

---

## 9. Logging learning

| What you learned | Where it goes |
|---|---|
| NTXP Form Filler correction, gap, reclassification, signature event | NTXP Form Filler KB Sheet → `Learning` tab (`event_type`, `field_name`, `detail`, `action_taken`, `model_used`, `timestamp`) |
| A reusable workflow, fix, connector or research result | Model Council `council_kb_post` (kind `workflow|troubleshooting|connector|skill|research|knowledge`); search first with `council_kb_search` |
| A human-fixable stuck state | New runbook entry (section 10) |
| Hostinger outcome | `hostinger-run-journal.json` (tier used, what worked, lesson) |
| Flag dismissed as false positive | Dismiss with a note; the learning loop tunes thresholds from it |

- One fact, one place. Never log secrets, full payloads or message bodies.

---

## 10. When stuck

Stuck = two failed attempts at the same step, or 15 minutes with no progress.

1. **Check the runbook.** `GET /api/runbook?q=<symptom words>` or search `docs/ADMIN_RUNBOOK.md`. Follow a matching entry and cite its ID.
2. **Check shared knowledge.** `council_kb_search` and, for hosting, the Hostinger run journal.
3. **No entry fits → add one.** `POST /api/runbook` (or append to `admin_console/runbook_seed.json` and run `python3 admin_console/tools/render_runbook.py`) with `id`, `workflow`, `symptom`, `likely_cause`, `steps` (plain language, a non-engineer can follow), `escalate_to`, `tier`, `updated`.
4. **Escalate.**
   - **Trevor (operations):** tools, process, access, deploys, data sources.
   - **Alison (owner):** money, legal, HR/personnel, signatures, security incidents, policy, Tier 1 conflicts.
   - Hard problem or method choice: convene the Model Council (`council_run`) and surface any gate verbatim.
5. **Report:** what you tried, the runbook ID, what is blocked, and the decision you need.

---

## 11. Never do

- **Never** change, "correct" or ignore a Tier 1 identity value.
- **Never** sign, or route a signature to anyone but Alison (or Trevor with a stated circumstance), or apply one without Tier 3 approval bound to the exact file.
- **Never** send personnel, owner, agency, bid, pricing or credential content to DeepSeek or GLM.
- **Never** show or compute emotional volatility for an external party, or share it outside the owner console.
- **Never** take disciplinary or HR action, or message an employee about a flag. Flags go to owners only.
- **Never** self-approve, split a Tier 3 change into smaller ones, or retry a refused gate with a reworded payload.
- **Never** commit, paste, echo or log a secret. The repo is public. Keys live in the vault and env vars only.
- **Never** impersonate a non-`@ntxpllc.com` account or widen `NTXP_GOOGLE_DOMAIN`.
- **Never** add anyone to the admin console allow-list or expose the `app` container port.
- **Never** change DNS with `overwrite: true`, or touch MX/NS/SPF/DKIM/DMARC/`mcp.ntxpllc.cloud` without explicit owner approval naming that record.
- **Never** delete a VPS project, a KB row or a contact without Tier 3 approval.
- **Never** let a subagent write shared state, apply a signature or approve a gate.
- **Never** run analytics in demo mode in production, or act on demo data.
- **Never** attempt Google Voice automation.
- **Never** force-push to the default branch or bypass secret-scanning push protection.
- **Never** disable or edit hooks to get a task done.
