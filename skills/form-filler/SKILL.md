---
name: form-filler
description: "FormFlow v2 — Autonomous AI form filler with JEV decision routing, Model Council inference, Google Sheets KB, NTXP Drive scanning, prewired workflows (legal, RFP, accounts), self-learning loop, and guided page-by-page approval GUI. Operates without user observation; gates only for approval."
skills: ntxp-model-router, ntxp-model-council, ntxp-change-gate, ntxp-folder-system
---

# FormFlow v2 — Autonomous Smart Form Filler

## Overview

FormFlow is an autonomous AI form-filling system that operates without user observation.
It builds an evolving Knowledge Base from NTXP's Google Drive, detects and fills PDF
forms using the cheapest-correct model via JEV routing, and gates only for minimal
human approval through a guided page-by-page scrolling GUI with highlighted fields.

### Architecture

```
                   ┌─────────────────┐
                   │   JEV (Referee)  │
                   │  Decision Tree   │
                   │  Confidence Gate  │
                   └────────┬────────┘
                            │ routes
        ┌───────────────────┼───────────────────┐
        │                   │                   │
  ┌─────▼─────┐     ┌──────▼──────┐     ┌──────▼──────┐
  │  Tier 0   │     │   Tier 1    │     │   Tier 2    │
  │ DeepSeek  │     │   Haiku     │     │  Sonnet/    │
  │ GLM Flash │     │  Gemini FL  │     │   Opus      │
  │ $0 regex  │     │ Simple KV   │     │ Ambiguous   │
  └─────┬─────┘     └──────┬──────┘     └──────┬──────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            │
                   ┌────────▼────────┐
                   │  Google Sheets  │
                   │   KB Database   │
                   │  (URL-visible)  │
                   └────────┬────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
        ┌─────▼─────┐ ┌────▼────┐ ┌──────▼──────┐
        │  Auto-Fill │ │ Sanity  │ │  Approval   │
        │  Engine    │ │ Check   │ │  GUI Gate   │
        └─────┬─────┘ └────┬────┘ └──────┬──────┘
              │             │             │
              └─────────────┼─────────────┘
                            │
                   ┌────────▼────────┐
                   │  Self-Learning  │
                   │     Loop        │
                   │  (corrections,  │
                   │   gap research) │
                   └─────────────────┘
```

### Core Capabilities
- **JEV Decision Tree**: Routes every task to cheapest-correct executor
- **Model Council Inference**: Council votes on ambiguous classifications
- **Google Sheets KB**: URL-accessible, admin-editable, cross-device
- **Autonomous Operation**: Watches Drive folders, auto-detects forms, auto-fills
- **Prewired Workflows**: Legal forms, RFP responses, new accounts, construction compliance
- **Guided Approval GUI**: Page-by-page scroll, filled fields highlighted, point-and-click edit
- **Drive KB Prefill**: Scans NTXP Drive for completed forms to seed KB
- **Self-Learning Loop**: Monitors corrections, researches gaps, consults Council

---

## Google Sheets KB Database

The KB lives in a Google Sheet shared across the organization — no Supabase, no env vars,
no server setup. Admins and project teams edit it directly at any time from any device.

**Sheet ID**: `1IZXlxLhPj4ZOgWC4m9dXPTd0b3rqJfoAwuW3d5Ih-Ug` (FormFlow KB — tabs KB, Sessions,
Learning, Workflows). Also stored in Model Council KB as `formflow_sheet_id`.

### Tab: `KB` (Knowledge Base)

| Column | Header | Description |
|--------|--------|-------------|
| A | `id` | Unique row ID (auto-generated UUID) |
| B | `category` | personal, contact, address, employment, education, financial, medical, legal, business, construction, other |
| C | `field_name` | Normalized snake_case field name |
| D | `field_value` | Current best value |
| E | `field_type` | text, date, email, phone, zip, ssn, ein, number, currency, checkbox |
| F | `confidence` | 0-100 score |
| G | `source` | Origin: wizard, drive_scan, manual, form_fill, ingestion |
| H | `alternates` | Pipe-delimited alternate values |
| I | `correction_count` | Times a human corrected this during approval |
| J | `last_corrected` | Date of last human correction |
| K | `correction_reason` | Last correction note |
| L | `created_at` | Row creation date |
| M | `updated_at` | Last update date |

### Tab: `Sessions` (Fill History)

| Column | Header | Description |
|--------|--------|-------------|
| A | `session_id` | UUID |
| B | `form_name` | Name of the form filled |
| C | `form_type` | Workflow type: legal, rfp, account, construction, general |
| D | `fields_total` | Total fields detected |
| E | `fields_auto` | Fields auto-filled (no correction) |
| F | `fields_corrected` | Fields human-corrected |
| G | `confidence_avg` | Average confidence |
| H | `model_used` | Which model did inference |
| I | `cost` | Estimated cost of this fill |
| J | `duration_sec` | Seconds to complete |
| K | `source_path` | Where the blank form came from |
| L | `output_path` | Where the filled form was saved |
| M | `timestamp` | ISO datetime |

### Tab: `Learning` (Self-Learning Log)

| Column | Header | Description |
|--------|--------|-------------|
| A | `id` | UUID |
| B | `event_type` | correction, gap_found, research_done, council_consult, field_reclassified |
| C | `field_name` | Affected field |
| D | `detail` | What happened |
| E | `action_taken` | What the loop did |
| F | `model_used` | Which model handled it |
| G | `timestamp` | ISO datetime |

### Tab: `Workflows` (Prewired Form Types)

Pre-populated with known form templates and their field maps. See Prewired Workflows below.

---

## JEV Decision Tree

JEV (the Model Council referee) governs every routing decision. The decision tree
scores each FormFlow subtask and dispatches to the cheapest executor that will
produce a correct result.

### Routing Rules (enforced, not advisory)

```
[JEV Decision: Form Type Classification]
    │
    ├── Filename/metadata matches a prewired workflow?
    │   YES → deterministic route, $0 (regex + lookup table)
    │   NO  → score ambiguity
    │         ├── ambiguity=0 (clear title like "W-9", "I-9")
    │         │   → Tier 0: regex classifier, $0
    │         ├── ambiguity=1-2 (needs content skim)
    │         │   → Tier 1: DeepSeek/Haiku, ~$0.001
    │         └── ambiguity=3 (novel form, unclear purpose)
    │             → Tier 2: council_route, ~$0.01

[JEV Decision: Field Extraction]
    │
    ├── AcroForm fields present?
    │   YES → deterministic extraction, $0 (pypdf only)
    │   NO  → visual extraction needed
    │         ├── Simple key:value layout
    │         │   → Tier 0: regex + pdfplumber, $0
    │         ├── Complex tables/nested layout
    │         │   → Tier 1: Haiku/Gemini Flash, ~$0.002
    │         └── Handwritten/scanned/ambiguous
    │             → Tier 2: Sonnet with OCR, ~$0.01

[JEV Decision: KB Matching Confidence]
    │
    ├── Exact field_name match in KB?
    │   YES, confidence ≥ 95 → auto-fill, no gate
    │   YES, confidence 70-94 → auto-fill, Tier 1 gate (batch approve)
    │   YES, confidence < 70  → present in GUI, Tier 2 gate
    │   NO match → manual entry in GUI, save to KB after
    │
    ├── Contradicts existing KB value?
    │   → Tier 3 gate: explain + wait (change-gate protocol)
    │
    └── Cross-field consistency failure?
        → Tier 2 gate: notify-then-act with flag

[JEV Decision: Where to Save Filled Form]
    │
    ├── Form type matches NTXP folder system?
    │   legal/compliance → project folder 13.3 (HUB/MBE Forms)
    │   insurance cert   → project folder 2.7 (Insurance & Bonds)
    │   lien waiver      → project folder 2.8 (Lien Waivers)
    │   submittal form   → project folder 5.x
    │   RFP response     → !Active Bids/[project]
    │   account/vendor   → !Company Documents/Registrations
    │   general          → user-specified or prompted
    │
    └── No match → ask user, save answer as workflow for next time
```

### JEV Cost Savings Matrix

| Task | Without JEV | With JEV | Savings |
|------|-------------|----------|---------|
| Form type classification | Sonnet $0.015 | Regex $0 | 100% |
| AcroForm field extraction | API call $0.01 | pypdf $0 | 100% |
| Simple KV text parsing | Sonnet $0.015 | DeepSeek $0.001 | 93% |
| KB field matching | API call $0.01 | Local fuzzy $0 | 100% |
| Confidence scoring | Sonnet $0.015 | 3-model council $0.006 | 60% |
| File destination routing | User prompt (time) | Folder system lookup $0 | N/A (speed) |

---

## Prewired Workflows

Each workflow has pre-mapped field-to-KB bindings, known form layouts, and
deterministic save locations. JEV routes these at Tier 0 (regex match on filename
or form title) — zero inference cost.

### Legal & Compliance Forms

| Form | Fields Auto-Mapped | Save Location |
|------|-------------------|---------------|
| W-9 (Tax ID) | business_name, ein, address, ssn, tax_classification | !Company Documents |
| W-4 (Withholding) | full_name, ssn, address, filing_status | Employee folder |
| I-9 (Employment) | full_name, dob, ssn, citizenship, address | Employee folder |
| NDA | company_name, signer_name, signer_title, date | Project 2.1 |
| Insurance Certificate | company_name, policy_number, agent, limits | Project 2.7 |
| Lien Waiver | company_name, project_name, amount, date | Project 2.8 |
| HUB/MBE Certification | company_name, cert_type, cert_number, expiry | Project 13.1 |

### RFP & Bid Responses

| Form | Fields Auto-Mapped | Save Location |
|------|-------------------|---------------|
| SAM Registration | company_name, duns, cage, ein, naics, address | !Company Documents |
| Capability Statement | company_name, services, past_performance, certs | !Active Bids |
| Vendor Registration | company_name, ein, contact, insurance, bonding | !Company Documents |
| Bid Form | project_name, bid_amount, addenda_ack, bond_info | Project 4.1 |
| Subcontractor Prequalification | company_name, bonding_capacity, experience | Project 4.3 |

### New Account & Admin

| Form | Fields Auto-Mapped | Save Location |
|------|-------------------|---------------|
| Bank Account Application | company_name, ein, authorized_signers, address | !Company Documents |
| Credit Application | company_name, duns, trade_references, financials | !Company Documents |
| Business License | company_name, address, license_type, jurisdiction | !Company Documents |
| Software/Platform Signup | company_name, admin_email, admin_name, phone | !Company Documents |

### Construction Project

| Form | Fields Auto-Mapped | Save Location |
|------|-------------------|---------------|
| Daily Report | project_name, date, weather, manpower, activities | Project 10.2 |
| Safety Checklist | project_name, date, inspector, items | Project 11.x |
| Punch List Item | project_name, location, description, responsible | Project 10.1 |
| Inspection Request | project_name, type, date_requested, scope | Project 11.x |

---

## Autonomous Operation

FormFlow operates without user observation. It is designed to:

### Smart Form Discovery
1. **Watch folders**: Monitor Drive locations where blank forms typically arrive:
   - `!Active Bids/` — new RFP packages
   - `!Active Projects/*/9 - Received by Client/` — owner-issued forms
   - `!Company Documents/Inbox/` — admin forms
2. **Auto-detect**: When a new PDF appears, classify it (JEV Tier 0-1)
3. **Auto-fill**: Match fields against KB, fill at highest possible confidence
4. **Auto-save**: Route filled form to correct NTXP folder location

### Smart File Destination
The skill uses `ntxp-folder-system` to determine where filled forms go:
- Maps form type → NTXP folder number (see Prewired Workflows above)
- Falls back to content-based classification if form type is unknown
- Logs the decision for future routing (self-learning)

### Minimal Human Approval Gating

Approval uses the `ntxp-change-gate` three-tier system mapped to confidence:

| Confidence | Gate Tier | User Experience |
|------------|-----------|-----------------|
| ≥ 95% | Tier 1 (batch) | Auto-filled. Grouped for one-click batch approve |
| 70-94% | Tier 2 (notify) | Highlighted yellow in GUI. Auto-proceeds unless objected |
| < 70% | GUI prompt | Highlighted red. Requires point-and-click entry |
| Contradiction | Tier 3 (explain+wait) | Side-by-side comparison. Hard stop until resolved |

---

## Guided Approval GUI (Artifact)

The approval artifact presents a **page-by-page scrolling view** of the filled form.
The user scrolls through at their own pace — no action needed for approved fields.

### Visual Design

```
┌─────────────────────────────────────────────────────────┐
│           FormFlow — W-9 Tax Information                │
│           Page 1 of 2  ·  87% Auto-Filled              │
│     ████████████████████████░░░░  Progress: 13/15       │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─ FIELD 1 ──────────────────────────── ✓ AUTO ──────┐ │
│  │  Name (as shown on tax return)                      │ │
│  │  ┌──────────────────────────────────────────────┐   │ │
│  │  │ NTXP LLC                              [Edit] │   │ │
│  │  └──────────────────────────────────────────────┘   │ │
│  │  KB Match: business_name (99%) · Source: wizard     │ │
│  └─────────────────────────── background: #e6ffed ────┘ │
│                                                         │
│  ┌─ FIELD 2 ──────────────────────────── ⚠ REVIEW ───┐ │
│  │  Business name / disregarded entity name            │ │
│  │  ┌──────────────────────────────────────────────┐   │ │
│  │  │ NTXP Professional LLC             ✏️ [Edit]  │   │ │
│  │  └──────────────────────────────────────────────┘   │ │
│  │  KB Match: dba_name (78%) · Source: drive_scan      │ │
│  │  ⚠ Alternate: "NTXP LLC" (wizard, 99%)             │ │
│  └─────────────────────────── background: #fffce6 ────┘ │
│                                                         │
│  ┌─ FIELD 3 ──────────────────────────── ✗ MANUAL ───┐ │
│  │  Federal tax classification                         │ │
│  │  ┌──────────────────────────────────────────────┐   │ │
│  │  │ [Select: C Corp / S Corp / LLC / ...]        │   │ │
│  │  └──────────────────────────────────────────────┘   │ │
│  │  No KB match · Click to enter                       │ │
│  └─────────────────────────── background: #ffe6e6 ────┘ │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  [← Prev Page]  [Approve All on Page ✓]  [Next Page →] │
│                  [Approve Entire Form]                   │
└─────────────────────────────────────────────────────────┘
```

### Field Highlighting Colors

| State | Background | Badge | Meaning |
|-------|-----------|-------|---------|
| Auto-filled (≥95%) | `#e6ffed` (green tint) | ✓ AUTO | No action needed |
| Review (70-94%) | `#fffce6` (yellow tint) | ⚠ REVIEW | Click to confirm or edit |
| Manual (<70%) | `#ffe6e6` (red tint) | ✗ MANUAL | Must enter value |
| Contradiction | `#f0e6ff` (purple tint) | ⚡ CONFLICT | Must resolve |

### Point-and-Click Editing
- Click any field value → inline edit mode
- Click [Edit] button → expanded editor with KB alternates shown
- Dropdown fields show KB-suggested options first
- After editing, value saved to KB with `source: form_fill`
- Correction increments `correction_count` for self-learning

---

## Signatures (Owner-Only, Always Tier 3)

FormFlow can stamp a signature block (name, title, date) onto a filled form, but only
under these rules, enforced in `scripts/formflow_signatures.py` and `route_signature()`
in `scripts/formflow_jev_router.py`:

- **Authorized signers**: **Trevor Hopkins (Owner)** and **Alison Hopkins (Owner)**. Nobody
  else. Any other name is denied outright, and no gate is offered.
- **Always Tier 3**: every signature application is explain-and-wait. Confidence, form
  type, prior approvals and batch "Approve All" never skip this step.
- **Approval happens inside Claude before the document leaves NTXP.** The filled, unsigned
  PDF is generated first; the signature is applied only after explicit approval; only
  then is the document saved to its external-facing location or sent.
- **One approval, one document.** Approval covers the exact document, signer and fields
  shown. If any field changes after approval, approval is void and must be re-obtained.
- **Never delegated.** Subagents and Council seats never receive signature requests or
  apply signatures; only the coordinating session does.
- **Audited.** Every request, approval, rejection and application is logged to the
  `Learning` tab (`event_type: signature_requested | signature_applied | signature_rejected`).

### Signature Step (Phase 3, Step 3-6b)

```
[Step 3-6b. Signature (only if form type needs one)]
    │
    +── formflow_signatures.check_form_needs_signature(form_type)
    +── detect_signature_fields(form_fields)
    +── Ask which owner signs (Trevor or Alison). Never assume.
    +── generate_approval_request(...) → show summary verbatim, HARD STOP
    │     Options: Approve / Reject / Edit fields first
    +── On Approve: build_signature_data(signer) → refill PDF → audit row
    +── On Reject: log rejection, keep unsigned draft in staging
```

Form types that need a signature: W-9, W-4, I-9, NDA, lien waiver, bid form, credit
application, vendor registration, SAM registration, subcontractor prequalification and
insurance certificate forms. The registry marks them `needs_signature: true`.

---

## Parallel Subagents (Single-Writer Model)

FormFlow fans out independent work to parallel subagents sized to the task, so large
jobs (Drive scans, multi-form packages, learning-loop analysis) finish fast. Plans come
from `scripts/formflow_orchestrator.py`.

### Agent Profiles

| Profile | Intelligence | Used For | Writes? |
|---|---|---|---|
| **scout** | Low (Haiku, Explore) | List Drive files, classify filenames, locate blank forms | No |
| **extractor** | Low (Haiku) | Read one document, regex/AcroForm extraction | No |
| **matcher** | Medium (Sonnet) | Map form fields to KB, ambiguous labels, complex layouts | No |
| **reviewer** | High (Opus) | Contradictions, client-facing review, reclassification | No |
| **council** | Multi-provider | 3-provider vote on **non-confidential** classification only | No |
| **coordinator** | Main session | Merge, gate, write, sign | **Yes (only writer)** |

JEV picks the profile: deterministic work stays at Tier 0 in-process; only work
that actually needs a model is handed to a subagent, at the cheapest profile that works.

### Corruption Safeguards

1. **Workers are read-only.** Every worker prompt carries the worker contract: no tool
   that writes, appends, moves, shares or deletes. Workers return a JSON **change set**.
2. **Single writer.** The coordinator merges change sets
   (`merge_change_sets`) and performs every KB/Drive write serially, one batch per tab.
3. **No silent overwrites.** Two workers proposing different values for one field, or a
   proposal that contradicts the live KB, becomes a Tier 3 conflict, not a write.
4. **Revision check.** Each change set records the KB revision it read; if revisions
   differ, the coordinator re-reads the KB and re-validates before applying.
5. **Never parallel:** KB writes, Drive saves/moves, signature application, gate approvals.
6. **Confidentiality.** W-9/W-4/I-9/credit/bid content never goes to Council seats;
   Ledger (DeepSeek) and Mason (GLM) never see it.
7. **Concurrency cap.** At most 6 workers at once; larger jobs run in waves.

### Standard Fan-Out Plans

| Job | Stage 1 | Stage 2 |
|---|---|---|
| `drive_scan` | scouts (25 files each) list + classify | extractors (5 files each) propose KB rows |
| `batch_fill` | extractor per form detects fields | matcher per form proposes values |
| `learning_loop` | extractor computes stats | reviewer analyzes flagged fields |

```bash
python scripts/formflow_orchestrator.py --plan drive_scan --items 40
python scripts/formflow_orchestrator.py --merge w1.json w2.json --kb-json kb.json
```

---

## Drive KB Prefill (Phase 0 Bootstrap)

On first run, FormFlow scans NTXP's Google Drive to seed the KB from completed documents.

### Scan Locations (NTXP Folder System)

| Drive Location | Document Types | Expected Fields |
|---|---|---|
| `!Company Documents/` | Registrations, licenses, insurance certs | company_name, ein, address, phone, email |
| `!Active Projects/*/2.1` | Contracts, NTP letters | company_name, project contacts, addresses |
| `!Active Projects/*/2.7` | Insurance certificates | policy_numbers, agent, limits, expiry |
| `!Active Projects/*/13.x` | HUB/MBE certifications | cert_type, cert_number, ethnicity, expiry |
| `!Active Bids/` | RFP responses, bid forms | company_name, DUNS, CAGE, NAICS, capabilities |

### Scan Strategy (JEV-Optimized)

1. **List files** via `mcp__Google_Drive__search_files` — no inference cost
2. **Filter by type**: PDF, DOCX, XLSX only — regex on filename, $0
3. **Classify**: JEV routes each file name through Tier 0 regex first
4. **Parse cheapest-first**: Only invoke model inference on files regex can't parse
5. **Deduplicate**: Fuzzy-match extracted values against KB before inserting
6. **Log**: Every scan result goes to the Learning tab

Expected first-scan yield: 50-200 KB entries from a typical NTXP Drive.

---

## Self-Learning Loop

A background process that continuously improves KB accuracy and coverage.

### Triggers

| Trigger | Action | JEV Tier |
|---------|--------|----------|
| `correction_count > 3` on a field | Flag field for review, research correct value | Tier 1 |
| `correction_count > 5` on a field | Council consult for field reclassification | council_run |
| Form type has < 60% auto-fill rate | Research that form type, add missing fields | Tier 1-2 |
| New form type encountered | Add to Workflows tab, map common fields | council_route |
| KB field unused for 90+ days | Flag as potentially stale, suggest verification | Tier 0 |
| KB contradiction detected (2+ sources disagree) | Council vote on correct value | council_run |

### Learning Actions

```
[Self-Learning Loop]
    │
    ├── Monitor
    │   +── Read Sessions tab: which fields get corrected most?
    │   +── Read Learning tab: what gaps have been found?
    │   +── Check correction_count across KB
    │
    ├── Research (JEV routes to cheapest model)
    │   +── For high-correction fields:
    │   │   - Check if field_type is wrong (e.g., "date" parsed as "text")
    │   │   - Check if field_name normalization is off
    │   │   - Check if alternates list needs updating
    │   +── For low-coverage form types:
    │   │   - Scan Drive for more examples of that form type
    │   │   - Extract additional field patterns
    │   │   - Add to Workflows tab prewired mappings
    │   +── For stale fields:
    │       - Check if source document has been updated
    │       - Flag for human verification
    │
    ├── Correct (requires approval per change-gate)
    │   +── Reclassify field_type → Tier 1 gate
    │   +── Update field_value from research → Tier 2 gate
    │   +── Add new prewired workflow → Tier 2 gate
    │   +── Delete/merge duplicate KB entries → Tier 3 gate
    │
    └── Report
        +── Post findings to Council KB (council_kb_post)
        +── Update Learning tab
        +── Generate weekly learning digest (branded report)
```

### Model Council Integration

The self-learning loop consults the Model Council for:

1. **Field reclassification**: "Is 'Tax Classification' a dropdown, text, or checkbox?"
   → `council_run` with `category: classification`, 3+ model vote
2. **Value disambiguation**: "Company registered as 'NTXP LLC' in W-9 but 'NTXP Professional LLC' in SAM — which is canonical?"
   → `council_run` with `category: methodology`, gates for Trevor's approval
3. **Workflow expansion**: "We've seen 5 similar forms from DISD. Should we add a 'DISD Vendor' prewired workflow?"
   → `council_route` to cheapest model for pattern analysis, gate for approval

---

## Workflow Phases

```
[Phase 0: Bootstrap & Environment]
    │
    +── Step 0-1. Google Sheets KB
    │   +── Check for existing FormFlow KB sheet (council_kb_search "formflow_sheet_id")
    │   +── If not found: create via mcp__Google_Drive__create_file
    │   │   - Create tabs: KB, Sessions, Learning, Workflows
    │   │   - Write headers to each tab
    │   │   - Share with NTXP team (read/write)
    │   │   - Store sheet ID in Council KB
    │   +── If found: verify tab structure, add missing columns if upgraded
    │
    +── Step 0-2. Python Environment
    │   +── Verify Python 3.8+
    │   +── pip install pdfplumber openpyxl python-docx pypdf reportlab
    │
    +── Step 0-3. JEV Wire-In
    │   +── Call council_env (register this surface)
    │   +── council_kb_search "formflow" (reuse existing workflows/fixes)
    │   +── Load prewired workflow field maps from Workflows tab
    │
    +── Step 0-4. Drive KB Prefill (first run only)
    │   +── Scan NTXP Drive locations (see Drive KB Prefill above)
    │   +── Parse documents cheapest-first per JEV routing
    │   +── Populate KB tab with extracted fields
    │   +── Log scan results to Learning tab
    │
    +── Step 0-5. MCP Source Detection
        +── Detect available: Google Drive, OneDrive, iCloud, local filesystem
        +── List file sources for user

[Phase 1: KB Setup Wizard]  (Action: setup)
    │
    +── Step 1-1. Present Q&A wizard artifact (see assets/output_template/kb_wizard_template.md)
    │   +── Pre-populate any fields already in KB from Drive scan
    │   +── Walk through categories: Personal → Contact → Address → Employment →
    │       Education → Business → Construction (NTXP-specific)
    │
    +── Step 1-2. Validate and save to Google Sheets KB tab
    │   +── Format validation via JEV Tier 0 (regex, $0)
    │   +── Append rows via mcp__Google_Sheets__append_values
    │
    +── Step 1-3. Offer document ingestion → Phase 2

[Phase 2: Document Ingestion]  (Action: ingest)
    │
    +── Step 2-1. Document selection (user path, Drive browse, or auto-detected)
    │
    +── Step 2-2. JEV-routed parsing
    │   +── JEV scores document complexity:
    │   │   - Has AcroForm? → pypdf only, $0
    │   │   - Simple text KV? → regex + pdfplumber, $0
    │   │   - Complex layout? → Tier 1 model, ~$0.002
    │   │   - Scanned/handwritten? → Tier 2 model with OCR, ~$0.01
    │   +── Run: python scripts/formflow_parse_document.py
    │
    +── Step 2-3. KB merge with conflict resolution
    │   +── New fields → auto-add (Tier 1 gate: batch approve)
    │   +── Conflicts → present resolution artifact (Tier 3 gate)
    │   +── Write to KB tab via mcp__Google_Sheets__update_values
    │
    +── Step 2-4. Log to Sessions tab

[Phase 3: Form Filling]  (Action: fill)
    │
    +── Step 3-1. Form classification (JEV decision tree)
    │   +── Check prewired workflows first (Tier 0, regex, $0)
    │   +── Fall back to content-based classification
    │   +── Determine save location via ntxp-folder-system
    │
    +── Step 3-2. Field detection
    │   +── python scripts/formflow_detect_fields.py
    │   +── JEV routes: AcroForm=$0, visual=Tier 0-1
    │
    +── Step 3-3. KB matching and confidence scoring
    │   +── Read KB tab via mcp__Google_Sheets__get_values
    │   +── Fuzzy match field names (local, $0)
    │   +── For ambiguous matches: council_route to cheapest model
    │   +── For contradictions: council_run for vote
    │
    +── Step 3-4. Present Guided Approval GUI artifact
    │   +── Page-by-page scrolling view
    │   +── Fields color-coded by confidence (green/yellow/red/purple)
    │   +── Point-and-click editing on any field
    │   +── "Approve Page" and "Approve All" buttons
    │   +── Corrections saved to KB with correction_count++
    │
    +── Step 3-5. Sanity checks
    │   +── python scripts/formflow_sanity_check.py
    │   +── Present issues in GUI for resolution
    │
    +── Step 3-6. Generate filled PDF (unsigned draft)
    │   +── python scripts/formflow_fill_pdf.py
    │
    +── Step 3-6b. Signature (see Signatures section; always Tier 3)
    │
    +── Step 3-7. Save
    │   +── Save to JEV-determined Drive location
    │   +── Change-gate: Tier 2 for routine saves, Tier 3 for client-facing

[Phase 4: Branded Report]  (Action: report)
    │
    +── Same as before: branded PDF/HTML per organization standards
    │   (8.5×11 portrait, centered headers, bold labels, infographics)
    +── Additionally: include JEV cost summary, model usage, learning stats
    +── Log to Sessions tab

[Phase 5: KB Management]  (Action: kb-manage)
    │
    +── KB tab is directly editable in Google Sheets by admins
    +── Skill provides: search, filter, merge duplicates, export
    +── Learning tab visible for monitoring self-learning activity

[Phase 6: Self-Learning Loop]  (Action: learn — or runs automatically)
    │
    +── See Self-Learning Loop section above
    +── Triggered after every fill session, or on schedule
    +── Posts findings to Model Council KB
```

---

## Hooks & Automation

### Session Start Hook
On session start, if the user's request involves forms, documents, or registrations:
1. Wire in JEV (council_env)
2. Load KB sheet
3. Check for pending learning actions

### Drive Watch Hook
When configured as a scheduled task:
1. Poll watched Drive folders for new PDFs
2. Auto-classify, auto-fill, save draft to staging folder
3. Notify user via Slack/email with approval GUI link

### Post-Fill Hook
After every form fill:
1. Log to Sessions tab
2. Run self-learning check on corrected fields
3. Update correction_count in KB
4. If correction_count crossed threshold → queue learning action

---

## File Structure

```
claude-visual-generator/
├── skills/
│   └── form-filler/
│       ├── SKILL.md                                    ← This file
│       └── assets/
│           └── output_template/
│               ├── kb_wizard_template.md                ← Setup wizard Q&A
│               ├── approval_gui_template.md             ← Page-by-page approval GUI
│               ├── conflict_resolution_template.md      ← Conflict resolution
│               └── report_template.md                   ← Branded report
├── scripts/
│   ├── formflow_sheets_db.py                           ← Google Sheets KB operations
│   ├── formflow_parse_document.py                      ← Document parser (PDF/Excel/Word)
│   ├── formflow_detect_fields.py                       ← PDF form field detection
│   ├── formflow_fill_pdf.py                            ← PDF form filling & output
│   ├── formflow_sanity_check.py                        ← Validation & sanity checks
│   ├── formflow_generate_report.py                     ← Branded report generator
│   ├── formflow_drive_scanner.py                       ← Drive KB prefill scanner
│   ├── formflow_learning_loop.py                       ← Self-learning engine
│   ├── formflow_jev_router.py                          ← JEV decision tree implementation
│   ├── formflow_workflow_registry.py                   ← Prewired workflow field maps
│   ├── formflow_signatures.py                          ← Owner-only signatures, Tier 3 gate
│   └── formflow_orchestrator.py                        ← Parallel subagent plans + merge
```

---

## Model Usage Summary

| Operation | Model (JEV Tier) | Est. Cost | Speed |
|-----------|-----------------|-----------|-------|
| Form type classification (known) | Regex (Tier 0) | $0 | <1ms |
| Form type classification (unknown) | DeepSeek/Haiku (Tier 1) | $0.001 | ~1s |
| AcroForm field extraction | pypdf (Tier 0) | $0 | <1s |
| Visual field extraction (simple) | Regex + pdfplumber (Tier 0) | $0 | ~2s |
| Visual field extraction (complex) | Haiku/Gemini Flash (Tier 1) | $0.002 | ~3s |
| KB fuzzy matching | Local difflib (Tier 0) | $0 | <1s |
| Ambiguous match resolution | Council 3-vote (Tier 2) | $0.006 | ~5s |
| Sanity check | Python script (Tier 0) | $0 | <1s |
| Report generation | reportlab (Tier 0) | $0 | ~2s |
| Self-learning research | DeepSeek (Tier 1) | $0.001 | ~3s |
| Field reclassification | Council run (Tier 2) | $0.01 | ~10s |

**Typical full form fill**: 15 fields × mostly Tier 0 = **~$0.003 total**, ~15 seconds

---

## Output Format

All reports and artifacts follow organization standards:
- **Page size**: 8.5 × 11 inch portrait orientation
- **Headers**: Centered, full-width, bold
- **Body**: Bold labels, bullet points for organized information
- **Infographics**: Completion rings, category breakdowns, cost/speed meters
- **Branding**: NTXP LLC footer, professional color scheme
