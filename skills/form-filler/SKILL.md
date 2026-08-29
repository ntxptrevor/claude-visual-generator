---
name: form-filler
description: "FormFlow — Smart document form filler that builds an evolving Knowledge Base from PDF, Excel, and Word documents, then auto-fills PDF forms with intelligent field matching, conflict detection, and branded report output. Works cross-device via cloud DB."
---

# FormFlow — Smart Document Form Filler

## Overview

FormFlow is an AI-powered document form filling skill with two core components:

1. **Knowledge Base (KB)** — Ingests PDF, Excel, and Word documents, parses form field
   answers, stores them in an editable, evolving knowledge base persisted in Supabase
   for cross-device access (phone, iPad, laptop).

2. **Form Filler** — Detects form fields in PDF forms, auto-fills answers from the KB
   using fuzzy matching, flags contradictions, and generates branded completion reports.

Core capabilities:
- Setup wizard with Q&A cards for initial KB population
- Document ingestion via MCP file-source hooks (Google Drive, OneDrive, iCloud, local)
- Intelligent field detection (AcroForm + visual pattern recognition)
- Fuzzy matching with confidence scoring for KB-to-field mapping
- Conflict detection and resolution prompts
- Sanity checks (date, email, phone, ZIP, SSN format validation)
- Branded PDF/HTML report generation (8.5×11 portrait, centered headers)
- Cloud persistence via Supabase (cross-device, cross-session)

---

## User Input Schema

### Required Input

| Item | Description | Example |
|------|-------------|---------|
| Action | Which workflow to run | `setup`, `ingest`, `fill`, `report`, `kb-manage` |

### Optional Input

| Item | Description | Default |
|------|-------------|---------|
| Document Path | Path to PDF/Excel/Word file to ingest or fill | User prompted |
| KB Category Filter | Limit operations to specific KB category | All categories |
| Output Directory | Where to save filled forms and reports | `formflow_output/` |
| Supabase URL | Supabase project URL for cloud KB | Environment variable `SUPABASE_URL` |
| Supabase Key | Supabase anon/service key | Environment variable `SUPABASE_KEY` |

---

## KB Categories

| Category | Description | Example Fields |
|----------|-------------|----------------|
| `personal` | Personal Information | Name, DOB, SSN, Gender, Nationality |
| `contact` | Contact Details | Email, Phone, Fax, Website |
| `address` | Address Information | Street, City, State, ZIP, Country |
| `employment` | Employment & Work | Employer, Title, Department, Salary |
| `education` | Education & Training | School, Degree, GPA, Graduation Date |
| `financial` | Financial Information | Bank, Account, Routing, Income, EIN |
| `medical` | Medical & Health | Insurance, Policy, Allergies, Doctor |
| `legal` | Legal & Compliance | License, Permit, Case Number |
| `business` | Business Information | Company Name, DBA, Registered Agent |
| `other` | Other / Custom | Any user-defined fields |

---

## Workflow

```
[Phase 0: Environment Setup]
    |
    +-- Step 0-1. Python Environment
    |   +-- Verify Python 3.8+ available
    |   +-- Install required packages:
    |       pip install pdfplumber openpyxl python-docx PyPDF2 reportlab supabase
    |
    +-- Step 0-2. Supabase Connection
    |   +-- Check for SUPABASE_URL and SUPABASE_KEY environment variables
    |   +-- If not set, prompt user via Q&A card for credentials
    |   +-- Test connection and verify formflow_kb table exists
    |   +-- If table missing, run migration:
    |       python scripts/formflow_db_setup.py --migrate
    |
    +-- Step 0-3. MCP File Source Detection
        +-- Check available MCP connectors (Google Drive, OneDrive, iCloud, local)
        +-- List accessible file sources to user
        +-- Store available sources for document ingestion phase

[Phase 1: KB Setup Wizard]  (Action: setup)
    |
    +-- Step 1-1. Welcome & Q&A Cards
    |   +-- Present interactive setup wizard artifact
    |   +-- Walk user through standard questions by category:
    |       - Personal: Full name, DOB, SSN, Gender
    |       - Contact: Email, Phone, Address
    |       - Employment: Employer, Title, Start Date
    |       - Education: School, Degree, Year
    |       - Financial: Bank, Account (if applicable)
    |       - Business: Company name, EIN (if applicable)
    |   +-- Each card shows field name, input type, and validation hint
    |
    +-- Step 1-2. Initial KB Population
    |   +-- Validate all answers (format checks for dates, emails, phones, etc.)
    |   +-- Categorize entries automatically using field pattern matching
    |   +-- Save to Supabase formflow_kb table
    |   +-- Generate summary artifact showing KB contents
    |
    +-- Step 1-3. Document Ingestion Prompt
        +-- Ask user if they want to ingest existing documents
        +-- If yes, proceed to Phase 2
        +-- If no, mark setup complete

[Phase 2: Document Ingestion]  (Action: ingest)
    |
    +-- Step 2-1. Document Selection
    |   +-- Accept document path from user or MCP file browser
    |   +-- Supported formats: PDF (.pdf), Excel (.xlsx/.xls), Word (.docx)
    |   +-- Validate file exists and is readable
    |
    +-- Step 2-2. Document Parsing
    |   +-- Run Python parser script:
    |       python scripts/formflow_parse_document.py \
    |         --file [document_path] \
    |         --output-json [temp_output.json]
    |   +-- Parser extracts key-value pairs using:
    |       - PDF: pdfplumber for text + AcroForm field extraction
    |       - Excel: openpyxl for labeled row/column pairs
    |       - Word: python-docx for table cells and form controls
    |
    +-- Step 2-3. KB Merge & Conflict Resolution
    |   +-- Compare extracted fields against existing KB entries
    |   +-- For new fields: auto-add to appropriate category
    |   +-- For conflicting fields: present conflict resolution artifact
    |       - Show existing value vs. new value
    |       - Ask user to pick or enter corrected value
    |       - Option to keep both (mark one as alternate)
    |   +-- Save merged KB to Supabase
    |
    +-- Step 2-4. Ingestion Report
        +-- Display summary: fields added, updated, conflicts resolved
        +-- Show updated KB statistics by category

[Phase 3: Form Filling]  (Action: fill)
    |
    +-- Step 3-1. Form Analysis
    |   +-- Accept target PDF form path
    |   +-- Run field detection script:
    |       python scripts/formflow_detect_fields.py \
    |         --form [pdf_path] \
    |         --output-json [fields.json]
    |   +-- Detection methods:
    |       - AcroForm field extraction (named fields, types, positions)
    |       - Visual pattern recognition (label:blank line pairs)
    |       - Checkbox and radio button detection
    |
    +-- Step 3-2. KB Matching
    |   +-- Load current KB from Supabase
    |   +-- For each detected field:
    |       - Fuzzy match field name/label against KB entries
    |       - Score confidence (0-100): exact=100, fuzzy≥70=auto-fill, <70=prompt
    |   +-- Present matching preview artifact:
    |       - Green: high-confidence auto-fills
    |       - Yellow: medium-confidence (user confirm)
    |       - Red: no match (manual entry needed)
    |
    +-- Step 3-3. Interactive Fill Session
    |   +-- Present form-filling artifact with:
    |       - Auto-filled fields pre-populated
    |       - Inline edit for manual entries
    |       - Auto-advance after each answer (Enter=accept+next, Tab=skip)
    |       - Zoom to active field region
    |       - Progress ring showing completion percentage
    |   +-- New manual entries saved back to KB automatically
    |
    +-- Step 3-4. Sanity Checks
    |   +-- Run validation per page and per document:
    |       python scripts/formflow_sanity_check.py \
    |         --filled [filled_fields.json] \
    |         --kb [kb_snapshot.json]
    |   +-- Checks include:
    |       - Format validation (date, email, phone, ZIP, SSN patterns)
    |       - Cross-field consistency (e.g., age matches DOB, city matches ZIP)
    |       - Required field completeness
    |       - Duplicate/contradictory entries
    |   +-- Present issues to user for resolution
    |
    +-- Step 3-5. Form Output
        +-- Generate filled PDF:
            python scripts/formflow_fill_pdf.py \
              --form [original_pdf] \
              --answers [filled_fields.json] \
              --output [output_dir/filled_form.pdf]
        +-- Save to output directory
        +-- Offer to user via artifact download link

[Phase 4: Branded Report Generation]  (Action: report)
    |
    +-- Step 4-1. Report Data Assembly
    |   +-- Gather: KB statistics, fill session results, sanity check outcomes
    |   +-- Calculate: completion rate, confidence scores, issues resolved
    |
    +-- Step 4-2. Report Rendering
    |   +-- Generate branded PDF report:
    |       python scripts/formflow_generate_report.py \
    |         --session-data [session.json] \
    |         --output [output_dir/FormFlow_Report.pdf]
    |   +-- Report format (per organization standards):
    |       - 8.5 × 11 inch portrait orientation
    |       - Centered headers and titles (full width)
    |       - Bold text for section labels
    |       - Bullet points for organized information
    |       - Infographic section: completion ring, category breakdown chart
    |       - Color-coded status indicators
    |       - NTXP LLC branding footer
    |
    +-- Step 4-3. Report Delivery
        +-- Present report as artifact (interactive HTML version)
        +-- Provide downloadable PDF version
        +-- Save to Supabase for historical access

[Phase 5: KB Management]  (Action: kb-manage)
    |
    +-- Step 5-1. KB Browser
    |   +-- Present interactive KB artifact organized by category
    |   +-- Search, filter, and sort capabilities
    |
    +-- Step 5-2. CRUD Operations
    |   +-- Add new entries manually
    |   +-- Edit existing entries inline
    |   +-- Delete entries (with confirmation)
    |   +-- Merge duplicate entries
    |
    +-- Step 5-3. Import/Export
        +-- Export KB as JSON or CSV
        +-- Import KB from JSON backup
        +-- Sync status with Supabase
```

---

## File Structure

```
claude-visual-generator/
├── skills/
│   └── form-filler/
│       ├── SKILL.md                          ← This file
│       └── assets/
│           └── output_template/
│               ├── kb_wizard_template.md      ← Artifact template: setup wizard
│               ├── form_fill_template.md      ← Artifact template: form filler UI
│               ├── conflict_resolution_template.md  ← Artifact template: conflicts
│               └── report_template.md         ← Artifact template: branded report
├── scripts/
│   ├── formflow_db_setup.py                  ← Supabase migration & DB setup
│   ├── formflow_parse_document.py            ← Document parser (PDF/Excel/Word)
│   ├── formflow_detect_fields.py             ← PDF form field detection
│   ├── formflow_fill_pdf.py                  ← PDF form filling & output
│   ├── formflow_sanity_check.py              ← Validation & sanity checks
│   └── formflow_generate_report.py           ← Branded report generator
```

---

## MCP Integration Hooks

FormFlow leverages MCP connectors for document access across platforms:

| Source | MCP Server | Usage |
|--------|-----------|-------|
| Google Drive | `google-drive` | Browse and fetch documents from Google Drive |
| OneDrive | `onedrive` | Access Microsoft OneDrive files |
| iCloud | `icloud` | Pull documents from Apple iCloud Drive |
| Local Files | `filesystem` | Access local filesystem documents |
| Supabase | `supabase` | Cloud KB storage and retrieval |

The skill checks for available MCP connectors at Phase 0 and presents
accessible file sources during document ingestion.

---

## Supabase Schema

The KB uses two tables in Supabase for cloud persistence:

### Table: `formflow_kb`

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid (PK) | Unique entry identifier |
| `user_email` | text | Owner email for multi-user isolation |
| `category` | text | KB category (personal, contact, etc.) |
| `field_name` | text | Normalized field name |
| `field_value` | text | Current value |
| `field_type` | text | Data type hint (text, date, email, phone, etc.) |
| `confidence` | integer | Confidence score 0-100 |
| `source` | text | Origin document or manual entry |
| `alternates` | jsonb | Array of alternate values with sources |
| `created_at` | timestamptz | Creation timestamp |
| `updated_at` | timestamptz | Last update timestamp |

### Table: `formflow_sessions`

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid (PK) | Session identifier |
| `user_email` | text | Owner email |
| `form_name` | text | Name of filled form |
| `fields_total` | integer | Total fields detected |
| `fields_filled` | integer | Fields successfully filled |
| `confidence_avg` | real | Average confidence score |
| `issues` | jsonb | Array of sanity check issues |
| `created_at` | timestamptz | Session timestamp |

---

## Output Format

All reports and artifacts follow organization standards:
- **Page size**: 8.5 × 11 inch portrait orientation
- **Headers**: Centered, full-width, bold
- **Body**: Bold labels, bullet points for organized information
- **Infographics**: Completion rings, category breakdowns, status indicators
- **Branding**: Professional design with consistent color scheme
