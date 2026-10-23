# Branded Report — Artifact Template

Generate a branded HTML artifact for the FormFlow completion report.
This report follows organization formatting standards for professional output.

## Design Requirements (Organization Standards — MANDATORY)

- **Page size**: 8.5 × 11 inch portrait orientation
- **Headers and titles**: Centered, full-width
- **Body text**: Bold text for labels, bullet points for organized information
- **Infographics**: Completion rings, category breakdown charts, status indicators
- **Design**: Professional, clean layout with consistent color scheme
- **Branding**: "FormFlow by NTXP LLC" footer on every page/section

## Color Palette

| Role | Color | Usage |
|------|-------|-------|
| Primary | #1a365d | Headers, main text |
| Secondary | #2b6cb0 | Subheaders, links |
| Accent | #38a169 | Success, completion |
| Warning | #d69e2e | Warnings, medium confidence |
| Error | #e53e3e | Errors, low confidence |
| Background | #f7fafc | Section backgrounds |
| Text | #2d3748 | Body text |

## Report Sections

### 1. Title Block (Centered)
- **"FormFlow Completion Report"** — Large, bold, primary color
- Form name — Medium, secondary color
- Date/time generated
- Horizontal rule

### 2. Executive Summary (Bulleted)
- **Total Fields Detected**: X
- **Fields Successfully Filled**: Y
- **Completion Rate**: Z% (with inline colored indicator)
- **Average Confidence Score**: N%
- **Issues Requiring Attention**: N
- **Fill Method Used**: AcroForm / Overlay / Auto

### 3. Completion Infographic (Centered)
- Large completion ring (SVG/Canvas)
  - Green ring if ≥80%, amber if ≥50%, red if <50%
  - Percentage in center, bold
  - "Complete" label below
- Category breakdown horizontal bar chart
  - One bar per KB category with field counts
  - Color-coded by category

### 4. Issues & Warnings Table
- Column headers: **Severity** | **Field** | **Issue Description**
- Rows sorted by severity (errors first)
- Color-coded severity badges:
  - Red: Error (blocking)
  - Amber: Warning (review needed)
  - Blue: Info (advisory)

### 5. Filled Fields Detail Table
- Column headers: **Field** | **Value** | **Confidence** | **Source**
- Confidence column color-coded:
  - Green text ≥90%
  - Amber text 70-89%
  - Red text <70%
- Source shows "KB", "Manual", or document name
- Maximum 40 rows per page

### 6. JEV Cost & Model Usage Summary
- **Total Cost**: $X.XXX for this fill session
- **Models Used**: List of models invoked with call count
- **JEV Routing Breakdown** (horizontal bar chart):
  - Tier 0 (regex/local): XX tasks — $0
  - Tier 1 (cheap model): XX tasks — $X.XXX
  - Tier 2 (full model/council): XX tasks — $X.XXX
- **Cost Savings**: "JEV saved $X.XX vs. sending all tasks to Sonnet"

### 7. KB Statistics Section
- Total entries by category (bulleted list with counts)
- Recently added entries (last 10)
- Data source breakdown pie chart
- **Learning Loop Status**:
  - Fields flagged for review: X
  - Auto-fill rate trend (last 5 sessions)
  - High-correction fields (correction_count ≥ 3)

### 8. Footer (Centered, Every Section)
- "FormFlow Report • Generated [date] • NTXP LLC"
- Page indicator

## Output

The artifact renders as a self-contained HTML page styled for 8.5×11 viewing,
with print-friendly CSS. Also generates a matching PDF via the Python report
generator script.
