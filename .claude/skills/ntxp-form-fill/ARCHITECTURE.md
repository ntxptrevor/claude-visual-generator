# NTXP Form Fill — Architecture Contract (v3)

Single source of truth for the components below. Change this file first, then the code.
Python 3.10+. Repo root on `sys.path`; scripts live in `scripts/`, the GUI front end in
`.claude/skills/ntxp-form-fill/assets/gui/`.

## Tool choices (decided)

| Need | Choice | Why |
|---|---|---|
| Internal database | **SQLite** (Python stdlib `sqlite3`, WAL mode) | Fastest free embedded DB, zero install, single file, transactional. |
| Source of truth | Private Google Sheet **NTXP Form Fill Database** (`1KYFkZoEWNvbAYqZ0Vq4LOUPh9QM4MiIYyqPmDyIelQA`) in `! NTXP Knowledge Base / Admin Tools / NTXP Form Fill Skill` | Owner-editable; synced **one way** Sheet → SQLite. |
| PDF page render (live view) | **pypdfium2** (PDFium, Apache-2.0/BSD) | Fast, permissive license, pip wheel, no system deps. |
| PDF read/write, AcroForm | **pypdf** | Already used; pure Python. |
| Text/marks overlay, final output | **reportlab** | Already used; built-in Helvetica (metric-equivalent to Arial). |
| GUI server | Python stdlib **`http.server`** (`ThreadingHTTPServer`) | No Flask/FastAPI dependency. |
| GUI front end | Vanilla HTML/CSS/JS, no frameworks, no CDN | Works offline; nothing to install. |
| JEV-1 layer | Deterministic rules + **Beta-Binomial** per-field reliability (pure Python) | Explainable, calibrated, no model download. |
| Optional open-source referee | **Qwen2.5-7B-Instruct** via **Ollama** (`http://127.0.0.1:11434`, Apache-2.0) | Local tie-breaker for ambiguous labels; data never leaves the machine. Off unless reachable. |
| Browser control | **Playwright** (optional) | Only for portal forms; never required for PDF filling. |

## Paths

- `NFF_HOME` (default `~/.ntxp/nff`): `nff.sqlite`, `sessions/<session_id>/` (working PDFs, page PNGs, state JSON), `proposals/`, `exports/`.
- Never write the database or session files inside the repo (it is public; the DB holds EIN and banking data). `.gitignore` covers `.ntxp/`.

## SQLite schema (`scripts/nff_db.py` owns it)

```
kb_fields(field_name PK, category, field_value, field_type, confidence INT, source, alternates,
          correction_count INT, updated_at, sheet_row INT)
canonical(answer_id PK, exhibit, category, field_name, field_value, source_kind, source_title,
          source_ref, source_date, status, verified_by, verified_at, notes, sheet_row INT)
workflows(workflow_id PK, form_type, form_pattern, field_map_json, save_location, jev_tier)
change_log(id PK AUTOINCREMENT, logged_at, field_name, form_field_title, form_name, old_value,
           new_value, action, decision, user, session_id, notes, pushed_to_sheet INT DEFAULT 0)
field_outcomes(id PK AUTOINCREMENT, field_name, source_kind, accepted INT, at)   -- JEV learning
proposals(proposal_id PK, created_at, field_name, proposed_value, current_value, category,
          evidence, source_title, source_ref, status)  -- status: pending|approved|rejected
sync_state(key PK, value)  -- last_sync_at, last_sheet_revision, rows_per_tab
```

`nff_db.py` public API (others import only these):
```
connect(path=None) -> sqlite3.Connection           # creates schema, WAL
kb_values(conn) -> dict[field_name, value]
canonical_rows(conn) -> list[dict]
record_change(conn, **change_log_fields) -> int
record_outcome(conn, field_name, source_kind, accepted: bool)
outcome_counts(conn, field_name) -> (accepted, corrected)
add_proposals(conn, rows) / list_proposals(conn, status="pending") / set_proposal_status(conn, ids, status)
pending_sheet_changes(conn) -> list[dict]; mark_pushed(conn, ids)
```

## Sheet ↔ DB sync (`scripts/nff_sync.py`)

One way, Sheet → SQLite, Sheet wins. Each run: read tabs `KB`, `Canonical`, `Workflows`; upsert
by key; rows changed vs DB overwrite the DB and write a `change_log` row (`action=sync_overwrite`);
rows deleted on the Sheet are removed from the DB. Inputs (any one):
- `--live`: Google Sheets API through `scripts/google_workspace/ntxp_google_access.py`
  (credentials only from env `NTXP_GOOGLE_SA_KEY`/`NTXP_GOOGLE_SA_EMAIL` + `NTXP_GOOGLE_ADMIN_SUBJECT`;
  tokens are never stored in the repo or the skill).
- `--from-json FILE`: `{tab: [[header...], [row...]]}` produced by the Sheets MCP `get_values` (agent path).
- `--from-csv-dir DIR`: one CSV per tab.
Manual GUI edits never write the DB directly as truth: they append to `change_log` and to the
Sheet's **Change Log** tab (`--push-changes` sends pending rows via API, or prints them for the
agent to append with the Sheets MCP). The Sheet's KB/Canonical rows are then updated by the owner
or by an approved proposal, and the next sync brings them into SQLite.

Sheet tab `Change Log` headers (exact order):
`logged_at, field_name, form_field_title, form_name, old_value, new_value, action, decision, user, session_id, notes`
`action`: manual_entry | manual_edit | approved_proposal | sync_overwrite.
`decision`: saved | ignored | n/a.

Sheet tab `Settings` (key, value): `company_docs_folder_id`, `closed_bids_folder_id`, `scan_recent_days`,
`default_font`, `default_size`, `default_color`.

## Manual scan (`scripts/nff_scan.py`)

1. `! Company Documents - Do Not Edit` (`1MBEgq8tlfCvJdeTqG6lGtrFaXKuvISM9`): files modified in the
   last `scan_recent_days` (default 30).
2. `!Active Bids / !Done` (`1rs1P8FuhQamouFRDv29f9hIR1rmKqKfs`) — closed/submitted bids (there is no
   "Closed" folder; configurable in Settings): recent bid folders; in each, pick the final RFP
   response (newest file whose name matches `final|submitted|executed|signed|response`), plus any
   project knowledge-base files (`*Knowledge Base*`, `*KB*`, `*.json` dossiers).
3. Extract candidate field values (reuse `nff_drive_scanner.extract_fields_from_text` +
   `nff_canonical.determine`), compare with the DB, and emit proposals (new field / changed value /
   conflict). Tier 1 fields and retired values are never proposed.
4. Output: proposals stored in SQLite + a one-page checklist (HTML for the GUI, PDF via reportlab),
   every line with an unchecked checkbox. Nothing is added until the user checks the line and clicks
   **Apply approved**; approved lines go to the Sheet (Canonical or KB tab) and the Change Log
   (`action=approved_proposal`), then a sync pulls them into SQLite.
Drive access: `--live` via the access layer, or `--from-manifest FILE` (JSON list of
`{id,title,mimeType,modifiedTime,folder,text}` the agent built with the Drive MCP).

## JEV-1 layer (`scripts/nff_jev.py`)

One layer, four jobs:
1. **Deterministic choices**: Tier 1 → canonical (`nff_canonical.determine`) → KB → manual.
   Prices, signatures, initials, notary blocks and yes/no legal certifications are never auto-filled.
2. **Probabilities**: per-field reliability `Beta(1 + accepted, 1 + corrected)` from `field_outcomes`
   blended with the source rank prior; field confidence = posterior mean × source weight × match
   score. Form confidence = geometric mean of filled-field confidences × coverage penalty
   (required fields left blank) × check penalty (failed compliance checks). Reported with a 90%
   interval. **Shown in the GUI only; never printed on the PDF.**
3. **Document control**: field detection, classification into the field types below, fill, flatten,
   export, and the hash-bound signature gate (`nff_signatures`).
4. **Browser control** (optional, Playwright): portal forms only, Tier 3 for any submit.
Optional referee: ambiguous label → Ollama `qwen2.5:7b-instruct` if reachable, else Tier 1 Claude
model if `ANTHROPIC_API_KEY`, else manual. Never DeepSeek/GLM for NTXP content.

Public API:
```
classify_field(label, page_text_near, rect) -> {"type", "confidence"}
choose_value(field_name, field_type, kb, canonical) -> {"value", "source", "confidence", "basis"}
field_confidence(conn, field_name, source_kind, match_score) -> float
form_confidence(fields, checks) -> {"score", "low", "high", "drivers"}
review(session_state, conn) -> {"checks": [...], "issues": [...], "confidence": {...}}
```

## Field types (GUI + export)

`text_word` (one word), `text_paragraph` (multi-line wrap), `date` (MM/DD/YYYY), `person`,
`address` (multi-line), `phone` ((###) ###-#### for US), `email`, `currency` (accounting format
`$1,234.00`, negatives `($1,234.00)`), `checkmark` (✓), `x_mark` (X), `initials` (user-editable,
default from signer), `signature` (user-editable: typed or drawn; Tier 3 approval at export),
`highlight` (straight lines only, snapped horizontal/vertical/45°; semi-transparent).
Default style everywhere: **Arial 11 pt, black (#000000), regular** (rendered with Helvetica, the
Arial-metric standard PDF font, unless an Arial/Liberation Sans TTF is present). The color picker
changes the selected field's color only.

## GUI server (`scripts/nff_gui.py`)

`python3 scripts/nff_gui.py --pdf blank.pdf [--form-type w9] [--port 8765]` opens the browser.
HTTP JSON API (same origin, bound to 127.0.0.1, random session token in the URL):
```
GET  /api/session                 -> state: pages[{n,w,h,img}], fields[...], confidence, flags
GET  /api/page/<n>.png            -> rendered page (pypdfium2, 2x scale)
POST /api/field  {id, value, style?}           -> updates; if value != auto value → returns {"ask_save": true}
POST /api/field/save-decision {id, decision}   -> saved|ignored; writes change_log (+ Sheet push queue)
POST /api/field/add {page, rect, type}         -> user-drawn field (missed by AI)
POST /api/page/approve {page}  /api/page/reopen {page}
POST /api/review                  -> JEV review + confidence
POST /api/signature/approve {signer, circumstance?} -> hash-bound approval record
POST /api/export {final: bool}    -> writes PDF to NFF_HOME/exports; returns path
POST /api/stop                    -> saves progress PDF + state, returns path
POST /api/scan  /GET /api/proposals  /POST /api/proposals/apply {ids}
POST /api/markup {kind, page, rect|start+end|points, text?, color?, origin?}  -> live markup
POST /api/markup/update {id, ...}  /api/markup/delete {id}
POST /api/markups/import {manifest, replace?}   -> ntxp-pdf-markups-and-redlines v2/v3 manifest
GET  /api/events?since=REV        -> text/event-stream; one "change" event per saved revision
GET  /api/page/<n>/live.png       -> page with every overlay applied (stamps/signatures after Tier 3)
```

### Live view design (reverse-engineered from pdf.js with the REA skill)

`rea-open-source-stack` tier 0 (`rea-agents analyze-javascript-application`) mapped pdf.js 4.10
(Apache-2.0): `display/annotation_storage.js`, `display/draw_layer.js`, `display/editor/*`,
`web/pdf_page_view.js`. The pieces that make its edits live, and how this GUI uses them:

| pdf.js | NTXP Form Fill |
|---|---|
| Page canvas rendered once; annotations in separate layers | Page PNG rendered once; fields (DOM) and markups (SVG) are overlays |
| `DrawLayer` SVG with page-relative boxes; `updateProperties` patches attributes | Markup SVG uses a PDF user-space `viewBox` with a y-flip, so resizing never redraws |
| `AnnotationStorage.setValue` diffs and fires `onSetModified` only on a real change | `Session.save()` bumps `rev` and wakes waiting streams; the client diffs by id and re-renders only what changed |
| `serialize()` + worker writes appearance streams on save | `nff_markup.draw` writes vector marks with reportlab at export; the live view never flattens |

Session state: `markups[]` (bottom-left PDF points, like fields and highlights) and `rev`. A markup's
geometry and style are part of `digest()`, so any change voids a signature approval. Programmatic
clients use `scripts/nff_live.py` (reads `<session>/gui.json`, mode 0600, removed on exit).
Front end: live page view with every field highlighted by state (auto/review/manual/user-added),
auto-scroll that steps field by field (Space/Enter = accept & next, Esc = stop), **LAST PAGE** bottom
left and **NEXT PAGE** bottom right (approve or re-open whole pages), toolbar (field types, highlighter,
color picker, font size), save/ignore pop-up card when a manual edit differs from the auto value,
**Completed** flag when every field is approved, AI review + confidence panel (not printed),
**Stop and download** overlay button always visible, **Scan Drive** button opening the proposals
checklist.
