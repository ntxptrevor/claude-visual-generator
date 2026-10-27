---
name: ntxp-form-fill
description: "NTXP Form Fill - NTXP LLC's form filler. Use whenever a form, questionnaire or bid/RFP package must be filled for NTXP: W-9, Conflict of Interest Questionnaire (CIQ), vendor or SAM registration, bid/proposal forms, insurance certificates, lien waivers, HUB/MBE forms, NDAs, credit applications, daily reports. Opens a guided review GUI with the live PDF, every field highlighted, field-by-field auto-scroll, page approve buttons, save/ignore prompts for manual edits, and a confidence score. Fills from the NTXP Form Fill Database (private Google Sheet synced to a local SQLite DB) and canonical answers (Exhibit A insurance/bonding, B W-9, C ACH), always enforcing the NTXP Tier 1 rules. Prices and signatures are never auto-filled; signatures, external sends and banking are Tier 3 owner approvals. Trigger on: fill this form, complete the W-9, do the CIQ, bid package, RFP forms, vendor registration, scan Drive for form answers, sync the form database."
version: 3.1.0
owner: NTXP
requires:
  skills: [ntxp-model-council, ntxp-model-router, ntxp-change-gate, ntxp-folder-system, ntxp-secrets-vault]
  tools: [python3]
provides: [ntxp-form-fill, ntxp-form-database-sync, ntxp-drive-proposals, ntxp-jev-confidence]
user-invocable: true
argument-hint: "[form | sync | scan | review]"
---

# NTXP Form Fill

Fills NTXP LLC's forms correctly, fast, with the owner in control of anything that matters.
Architecture contract and tool choices: **`ARCHITECTURE.md`** (same folder). Business rules: `CLAUDE.md`.

Command paths are from the repo root. In the Forge copy, the same scripts live in `scripts/` inside this skill folder.

---

## 1. TIER 1 RULES — NTXP Identity (owner directive, hard-coded)

These override the database, Drive scans, Council votes, model output and any source document.
Change them only on written direction from the owner.

| Rule | Value | Enforced in |
|---|---|---|
| **Owner of NTXP LLC** | Always **Alison Hopkins** (Owner) | `NTXP_IDENTITY` in `scripts/nff_signatures.py` |
| **Operations contact** | Always **Trevor Hopkins** | `NTXP_IDENTITY` |
| **Designated signatory** | Always **Alison Hopkins** (default signer) | `DESIGNATED_SIGNATORY`, `nff_jev.choose_value` |
| **Alternate signatory** | **Trevor Hopkins**, only when circumstances require; the circumstance is recorded | `verify_approval()` |
| **W-9 line 3a** | **S corporation** box only. Never the LLC box; LLC code blank | W-9 `fixed_values` / `never_fill` / `clear_fields` in `scripts/nff_workflow_registry.py` |
| **Business address** | **101 South Locust St Ste 605, Denton, TX 76201** | Tier 1 overrides; retired values block 405 S Elm St |
| **Business phone** | **469-248-7431** | Tier 1 overrides |

Never auto-filled (always the user): **prices and dollar bid amounts, signatures, initials, notary/jurat
blocks, yes/no legal certifications** (debarment, felony, conflict of interest, boycott), and **banking**.

---

## 2. Quick start (what the agent does)

1. **Sync the database** (fast, local): `python3 scripts/nff_sync.py --status`. If the last sync is older
   than today, sync (§4). Never fill from a stale DB on bid day.
2. **Open the guided GUI** on the blank form:
   `python3 scripts/nff_gui.py --pdf <blank.pdf> [--form-type w9|ciq|bid_form|...]`
   It detects and classifies every field, pre-fills from the DB (Tier 1 → canonical → KB), and opens the
   review view (§5). Give the user the printed URL if no browser opens.
3. The user reviews field by field (or approves whole pages), adds any missed field with the
   **Add field** / **Highlighter** tools, and answers each **Save to database / Ignore this time** card.
4. On **COMPLETED**, the GUI runs the JEV-1 review and shows the confidence score (never printed on the
   PDF). If nothing blocks, it exports the final PDF and prints `NFF_EXPORT: <path>`.
5. **Deliver the PDF in chat** for download (send the exported file to the user). If the user pressed
   **Stop and download**, deliver the `NFF_PROGRESS: <path>` file the same way.
6. **Push the change log**: `python3 scripts/nff_sync.py --push-changes` (live) or append the printed rows
   to the Sheet's **Change Log** tab with the Sheets connector, then `--mark-pushed <ids>`.
7. Signatures: only after the user clicks **Approve signature** in the GUI (hash-bound, Tier 3).
   Saving to Drive or sending to an agency is a separate Tier 3 approval.

Headless fallback (no GUI possible): `nff_workflow_registry.py --answers <type> --kb-json kb.json
--canonical-json canonical.json --output answers.json`, then `nff_fill_pdf.py`, then review with
`nff_jev.review` and show the result to the user before delivering.

---

## 3. The NTXP Form Fill Database

**Source of truth:** private Google Sheet **NTXP Form Fill Database**
`1KYFkZoEWNvbAYqZ0Vq4LOUPh9QM4MiIYyqPmDyIelQA`, in `! NTXP Knowledge Base / Admin Tools / NTXP Form Fill Skill`.

| Tab | Holds |
|---|---|
| `KB` | Reusable field answers (company, contacts, insurance agent, etc.) |
| `Canonical` | Owner-approved bid exhibits: **A** insurance/bonding, **B** W-9, **C** ACH, with source and status |
| `Workflows` | Prewired form types and field maps |
| `Change Log` | Every manual entry/edit, approved proposal and sync overwrite, with the **form field title** it came from |
| `Settings` | Scan folders, scan window, default font/size/color |
| `Sessions`, `Learning` | Fill history and learning events |

**Internal database:** SQLite at `NFF_HOME/nff.sqlite` (default `~/.ntxp/nff`). Chosen because it is the
fastest free embedded database, part of Python, transactional, and needs no server. It lives **outside
the repo** (this repo is public; the DB holds EIN and banking data). Schema in `ARCHITECTURE.md`.

Rules: the Sheet is edited by people; the DB is never edited by hand. Sync is **one way, Sheet → DB**,
and the Sheet always wins.

---

## 4. Sync and authentication

```bash
python3 scripts/nff_sync.py --status                 # last sync, row counts
python3 scripts/nff_sync.py --live                   # Sheet -> SQLite via Google API
python3 scripts/nff_sync.py --from-json sheet.json   # Sheet -> SQLite from connector output
python3 scripts/nff_sync.py --push-changes [--live]  # pending Change Log rows -> Sheet
```

What a sync does: reads `KB`, `Canonical`, `Workflows` and `Settings`; upserts by key; overwrites any
outdated DB entry with the Sheet value; deletes rows removed from the Sheet; writes a `sync_overwrite`
row to the change log for every value it replaced.

**Authentication (no tokens in this repo or skill, ever):**

| Path | Credential | How |
|---|---|---|
| Claude session with Google connectors (default) | The user's own Google sign-in through the claude.ai Sheets connector | Agent calls `mcp__Google_Sheets__get_values` on each tab, saves `{tab: values}` to a JSON file, runs `--from-json`. |
| Headless / scheduled | Service account with domain-wide delegation | Env vars `NTXP_GOOGLE_SA_KEY` (or `NTXP_GOOGLE_SA_EMAIL`) and `NTXP_GOOGLE_ADMIN_SUBJECT`, loaded from the **NTXP API Keys** vault (`ntxp-secrets-vault`), never pasted into chat or files. Setup: `scripts/google_workspace/README.md`. Then `--live`. |
| Sheet id | `NFF_SHEET_ID` env, default the id above | |

Run a sync at the start of every fill session and after any approved proposal.

---

## 5. Guided review GUI

`scripts/nff_gui.py` (Python stdlib web server on 127.0.0.1 with a per-session token) +
`assets/gui/` (plain HTML/CSS/JS, no frameworks, works offline). Pages are rendered with **pypdfium2**;
the final PDF is written with **pypdf** + **reportlab**.

**What the user sees**
- The live document, every field outlined and color-coded: **green** auto-filled, **amber** needs review,
  **red** empty/manual, **blue** added by the user, a check when approved.
- **Start review**: auto-scrolls field by field, centering each field and opening its editor.
  Enter/Space accept and go next, Shift+Enter back, Esc stop.
- **LAST PAGE** (bottom left) and **NEXT PAGE** (bottom right): approve or re-open a whole page at once
  for simple documents.
- **Add field**: drag a box around anything the AI missed and pick its type.
- **Highlighter**: draws straight lines only (snaps to horizontal, vertical, 45°).
- **Color picker** and size control for the selected field. Default everywhere: **Arial 11 pt, black,
  regular** (Helvetica, the Arial-metric PDF font, unless an Arial TTF is installed).
- **Save to database / Ignore this time** card whenever a manual edit changes an auto-filled answer.
- **Scan Drive** (§6), **Stop and download** (always visible, saves progress), **COMPLETED** flag,
  review panel and **confidence score** (screen only, never printed).

**Field types**

| Type | Behavior |
|---|---|
| One-word text | Single line |
| Paragraph text | Multi-line, wraps on export |
| Date | Date picker → `MM/DD/YYYY` |
| Person | Name; owner/signer fields default to Tier 1 people |
| Address | Multi-line; NTXP address from Tier 1 |
| Phone | Auto-formats `(469) 248-7431` |
| Email | Validated |
| Dollar amount | Accounting format `$1,234.00`, negatives `($1,234.00)`; never auto-filled for prices |
| Checkmark ✓ / X mark | Toggles |
| Initials | Editable; default from the signer |
| Signature | Editable (typed or drawn); stamped only after Tier 3 approval |
| Highlighter | Straight-line, semi-transparent |

### 5a. Live view and construction markups

Every saved change (from this window, another window, a script or an agent) shows in the open GUI at
once. The page image stays static and every overlay sits on a vector layer in PDF user space, so a
change patches only that mark. The **LIVE** badge turns gray (RECONNECTING) if the event stream drops.

- **Markup** tool: cloud, rectangle (bounding box), ellipse, arrow, line, polyline, ink, text callout,
  area and stamp. Drag on the page, or click a mark and press Delete; the color picker recolors it.
- Marks follow `ntxp-pdf-markups-and-redlines` (core/invariants.md): redline red `#FF0000`, core
  opacity at most 0.80, a 0.30 halo at 3x width under line-based marks, areas 0.30 fill, bold opaque
  bounding boxes, one-sided outward clouds, centered red text, dotted demolition.
- **Stamps** (APPROVED, APPROVED AS NOTED, REVISE AND RESUBMIT, REJECTED, FOR RECORD ONLY, NOT
  REVIEWED, VOID) are attestations. Like signatures, they show as a preview but reach a PDF only
  after the Tier 3 approval, and the stamp reviewer must be the approved signer (Alison Hopkins by
  default; Trevor Hopkins only with a stated circumstance).
- **Programmatic control** (`scripts/nff_live.py`, reads the running session's owner-only `gui.json`):
  ```bash
  python3 scripts/nff_live.py cloud --page 1 --rect 96 128 268 232 --text "Clarify head height"
  python3 scripts/nff_live.py import rfi_manifest.v3.json          # ntxp-pdf-markups-and-redlines
  python3 scripts/nff_live.py stamp --page 1 --rect 400 640 590 740 --status "APPROVED AS NOTED"
  python3 scripts/nff_live.py field f3 "NTXP LLC"
  python3 scripts/nff_live.py snapshot --page 1 --out page1.png    # PNG with overlays, no browser
  python3 scripts/nff_live.py watch                                 # print live change events
  ```
  Coordinates are PDF points from the page's top-left corner (the v3 manifest convention).
- Open a construction set the same way as a form: `python3 scripts/nff_gui.py --pdf A101_set.pdf`.
  Count tags and dimension proofs still render through `ntxp-pdf-markups-and-redlines`; the live view
  skips them on import and reports them.

---

## 6. Manual Drive scan → proposed database additions

Button **Scan Drive** in the GUI, or `python3 scripts/nff_scan.py --live` / `--from-manifest FILE`.

1. Reviews recently added or changed files in **`! Company Documents - Do Not Edit`**.
2. Moves to **`!Active Bids / !Done`** (closed/submitted bids; there is no "Closed" folder under
   `!Active Bids` — change `closed_bids_folder_id` in the Sheet's Settings tab if one is created) and
   parses the **final** RFP response in each recent bid plus the project knowledge-base files.
3. Builds a **one-page checklist** of proposed additions and edits to the database, each line with an
   **unchecked** checkbox. Nothing is added until the user checks the line and clicks **Apply approved**.
   Tier 1 fields, retired values and prices are never proposed; banking proposals are marked Tier 3.
4. Approved lines are written to the Sheet (Canonical or KB tab) and the Change Log, then synced to SQLite.

Without service-account credentials, the agent runs the scan itself: list and read the files with the
Google Drive connector, write a manifest (`[{id,title,mimeType,modifiedTime,folder,text}]`), run
`--from-manifest`, show the checklist, then `--apply <ids>` for the lines the user checked.

---

## 7. JEV-1 layer — deterministic choices, probabilities, document and browser control

`scripts/nff_jev.py` is the single decision layer.

| Job | How |
|---|---|
| Deterministic choices | Tier 1 → canonical (`nff_canonical`) → KB → manual. Never-autofill list above. |
| Field classification | Rules on label, nearby text and box shape; below 0.6 confidence, an open-source local referee (**Qwen2.5-7B-Instruct via Ollama**, Apache-2.0, data stays on the machine), else Claude Haiku, else ask the user. |
| Probabilities | Per-field reliability **Beta(1 + accepted, 1 + corrected)** learned from every review, blended with the source prior; exact 90% interval. |
| Form confidence | Geometric mean of field confidences × coverage × compliance; any blocking failure caps it at 50%. **Shown to the user, never printed on the document.** |
| Document control | Detect, classify, fill, flatten, export; hash-bound signature gate. |
| Browser control | Optional Playwright plan for portal forms; every submit is Tier 3. |
| Completion review | Deterministic compliance checks (Tier 1 identity, retired values, required blanks, formats, signature approval, contradictions with canonical answers) + an AI interpretation review (Claude Sonnet if `ANTHROPIC_API_KEY`, otherwise the Claude session reviews the saved packet). |

Why this design: deterministic rules decide everything that has a right answer; a calibrated Bayesian
model turns real review outcomes into honest probabilities; a model is consulted only for genuinely
ambiguous labels. No model ever decides a price, a signature or a legal certification.

---

## 8. Multi-model optimizations (Claude, Grok and the Model Council)

The Form Filler runs on any host. Route by `ntxp-model-router`; hard rule: **personnel, owner, bid,
pricing, banking and credential content never go to DeepSeek (Ledger) or GLM (Mason).**

| Model / seat | Use it for | How to prompt it | Never |
|---|---|---|---|
| **Claude** (Opus/Sonnet: orchestration, review; Haiku: label tie-breaks) | Running this skill end to end, the completion review, anything client-facing | XML-tagged sections (`<form>`, `<kb>`, `<rules>`); give the Tier 1 table verbatim; ask for JSON matching the field schema; prompt-cache the Tier 1 + canonical block | — |
| **Grok** (Vector) | Researching an unfamiliar agency form (what a field means, current form revision) with live search | One question per call, ask for cited sources and a one-line answer; send labels only, no NTXP values | Filling values; seeing banking/EIN |
| **ChatGPT / Astra** (Torque) | Second-opinion interpretation of an ambiguous form section | Strict JSON schema output, short context (the section + labels), temperature 0 | Seeing banking or pricing |
| **Gemini** | Long scanned RFP packages: locating the pages that contain forms | Send page images/text, ask for page numbers and form titles only | Field values |
| **Perplexity** (Compass) | Public facts (agency addresses, statute references on a CIQ) | Ask for the source URL with each fact | NTXP data |
| **DeepSeek / GLM** | Non-confidential bulk text cleanup only (e.g. normalizing public form labels) | Labels only | Any NTXP value, owner, bid, pricing, personnel or credential content |
| **Local Qwen2.5 (Ollama)** | Offline field-type tie-breaks | Strict JSON schema, 3 s timeout | — |

Cost levers: Tier 0 code handles ~95% of a typical form at $0; cache the Tier 1 + canonical prompt block;
batch label classification in one call; council only for disagreements, within the $2/task ceiling.

---

## 9. Canonical answers

The `Canonical` tab holds the owner-approved exhibits. `scripts/nff_canonical.py` picks each field's
value: Tier 1 wins; retired values never win; otherwise owner-approved exhibit > executed third-party
document (broker COI, signed W-9, bond letter) > NTXP summary > KB > Drive scan, weighted by agreement
and recency. Close disagreements go to the owner; insurance, bonding, tax-ID and banking conflicts
never go to a council vote. Banking values are masked in logs and need Tier 3 approval to fill.

---

## 10. Signatures (designated signatory, always Tier 3)

- Default signer **Alison Hopkins**; **Trevor Hopkins** only with a stated circumstance; nobody else.
- The GUI's **Approve signature** creates an approval bound to the exact document hash; any later edit
  voids it. Notary and jurat blocks are never stamped.
- Every request, approval and stamp is logged.

---

## 11. Prewired workflows

| Category | Forms (save location) |
|---|---|
| Legal & compliance | W-9 (!Company Documents), W-4/I-9 (employee folder), NDA (2.1), COI (2.7), lien waiver (2.8), HUB/MBE (13.x), CIQ (!Active Bids) |
| RFP & bids | SAM registration, vendor registration (!Company Documents), bid form, subcontractor prequalification, capability statement |
| Accounts & admin | Bank account, credit application, business license, software signup (!Company Documents) |
| Construction | Daily report (10.2), safety checklist (11.x), punch list (10.1), inspection request (11.x) |

Field maps live in `scripts/nff_workflow_registry.py` (official W-9 by AcroForm id; CIQ by fixed overlay).

---

## 12. Parallel subagents (single writer)

Workers are read-only and return change sets; only the main session writes to the Sheet, the DB, Drive
or a PDF. Confidential forms never go to non-Claude seats. Plans: `scripts/nff_orchestrator.py`.

---

## 13. Files

```
.claude/skills/ntxp-form-fill/
  SKILL.md, ARCHITECTURE.md, assets/gui/ (index.html, app.css, app.js), assets/output_template/
scripts/
  nff_gui.py, nff_render.py          guided GUI server, page render, PDF export
  nff_markup.py, nff_live.py          live markup layer (NTXP rules, v3 import), live CLI client
  nff_db.py, nff_sync.py, nff_scan.py SQLite DB, Sheet->DB sync, Drive scan + checklist
  nff_jev.py                          JEV-1 layer (choices, probabilities, review, confidence)
  nff_canonical.py, nff_workflow_registry.py, nff_signatures.py
  nff_detect_fields.py, nff_fill_pdf.py, nff_sanity_check.py, nff_generate_report.py
  nff_drive_scanner.py, nff_learning_loop.py, nff_orchestrator.py, nff_jev_router.py, nff_sheets_db.py
  google_workspace/ntxp_google_access.py
```

Dependencies: `pip install pypdf pypdfium2 reportlab pdfplumber` (optional: `python-docx openpyxl
google-auth google-api-python-client playwright`).
