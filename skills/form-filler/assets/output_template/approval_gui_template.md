# Guided Approval GUI — Artifact Template

Generate an interactive HTML artifact for the FormFlow page-by-page approval GUI.
This artifact presents filled form fields for review with confidence-based highlighting,
point-and-click editing, and minimal approval gating.

## Design Requirements (Organization Standards — MANDATORY)

- **Page size**: 8.5 × 11 inch portrait orientation (scrollable pages)
- **Headers and titles**: Centered, full-width, bold
- **Body text**: Bold labels for field names, bullet points for organized info
- **Infographics**: Progress bar, completion ring, confidence meters
- **Design**: Professional, clean layout with NTXP branding
- **Branding**: "FormFlow by NTXP LLC" footer on every page

## Color Palette

| Role | Color | CSS Variable | Usage |
|------|-------|-------------|-------|
| Primary | #1a365d | --ff-primary | Headers, main text |
| Secondary | #2b6cb0 | --ff-secondary | Subheaders, links |
| Auto-filled (≥95%) | #e6ffed | --ff-auto-bg | Green tint background |
| Auto-filled badge | #38a169 | --ff-auto-badge | Green badge text |
| Review (70-94%) | #fffce6 | --ff-review-bg | Yellow tint background |
| Review badge | #d69e2e | --ff-review-badge | Yellow badge text |
| Manual (<70%) | #ffe6e6 | --ff-manual-bg | Red tint background |
| Manual badge | #e53e3e | --ff-manual-badge | Red badge text |
| Contradiction | #f0e6ff | --ff-conflict-bg | Purple tint background |
| Contradiction badge | #805ad5 | --ff-conflict-badge | Purple badge text |
| Background | #f7fafc | --ff-bg | Section backgrounds |
| Text | #2d3748 | --ff-text | Body text |

## Artifact Structure

### Top Header (Sticky)
- **Form name** (centered, bold, large, primary color)
- **Page indicator**: "Page X of Y"
- **Completion stat**: "XX% Auto-Filled"
- **Progress bar**: Full-width, showing fields_done / fields_total
  - Green fill for auto-filled fields
  - Yellow fill for review-needed fields
  - Gray for unfilled

### Page Container (Scrollable)

Each page of the form maps to a scrollable section. Fields are displayed
in document order, each in a bordered card:

```
┌─────────────────────────────────────────────────────────┐
│  FIELD CARD                                             │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─ [BADGE] ─────────────── [FIELD LABEL] ────────────┐│
│  │                                                     ││
│  │  ┌─────────────────────────────────────────────┐    ││
│  │  │ [VALUE or INPUT]                    [Edit]  │    ││
│  │  └─────────────────────────────────────────────┘    ││
│  │                                                     ││
│  │  KB Match: field_name (XX%) · Source: wizard        ││
│  │  ⚠ Alternate: "other value" (source, XX%)          ││
│  │                                                     ││
│  └─────────────────────── background: var(--bg) ──────┘│
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Field Card States

**State 1: Auto-Filled (≥95% confidence)**
- Background: `--ff-auto-bg` (#e6ffed green tint)
- Badge: `✓ AUTO` in green
- Value displayed as read-only text (click to edit)
- No action required — scrolling past = accepted
- KB match info shown in small text below

**State 2: Review (70-94% confidence)**
- Background: `--ff-review-bg` (#fffce6 yellow tint)
- Badge: `⚠ REVIEW` in amber
- Value displayed as editable input (pre-filled)
- Alternates shown if available
- "Confirm" button on right side

**State 3: Manual (<70% confidence)**
- Background: `--ff-manual-bg` (#ffe6e6 red tint)
- Badge: `✗ MANUAL` in red
- Empty input or dropdown with KB suggestions
- Must enter value to proceed
- For select/dropdown fields: show KB-suggested options first

**State 4: Contradiction**
- Background: `--ff-conflict-bg` (#f0e6ff purple tint)
- Badge: `⚡ CONFLICT` in purple
- Side-by-side comparison of conflicting values
- Must resolve before proceeding
- Resolution options: Keep A / Keep B / Enter New / Keep Both

### Point-and-Click Editing

Interactive editing behaviors:
1. **Click any field value** → Switches to inline edit mode
   - Text fields: input replaces display text
   - Date fields: date picker appears
   - Select fields: dropdown opens with KB suggestions first
   - Phone/SSN/EIN: masked input with format validation
2. **Click [Edit] button** → Expanded editor opens
   - Shows all KB alternates for that field
   - Shows source and confidence for each alternate
   - "Use this value" button next to each alternate
3. **After editing**:
   - New value saved to KB with `source: form_fill`
   - `correction_count` incremented for self-learning
   - Field card background updates to green (confirmed)
4. **Keyboard shortcuts**:
   - Enter: Confirm field and advance to next
   - Tab: Skip field and advance
   - Escape: Cancel edit, revert to original

### Page Navigation (Sticky Bottom Bar)

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│  [← Prev Page]  [Approve All on Page ✓]  [Next Page →] │
│                                                         │
│              [Approve Entire Form ✓✓]                   │
│                                                         │
│  Fields: 12/15 done  ·  Corrections: 2  ·  Cost: $0.003│
│                                                         │
└─────────────────────────────────────────────────────────┘
```

- **Approve All on Page**: Accepts all auto/review fields on current page
- **Approve Entire Form**: Accepts all remaining fields across all pages
- **Field counter**: Real-time count of completed fields
- **Correction counter**: How many fields were edited (for learning loop)
- **Cost indicator**: Running JEV cost estimate

### Completion Summary

After all fields are approved:
1. Summary table of all field values with sources
2. Sanity check results (any issues flagged)
3. Save location (from JEV routing)
4. "Generate Filled PDF" action button
5. "Generate Report" action button
6. "Save to Drive" action button (with folder path shown)

## Output

The artifact outputs filled field data as JSON:
```json
{
  "form_name": "W-9 Tax Information",
  "form_type": "w9",
  "pages": [
    {
      "page_number": 1,
      "fields": [
        {
          "field_name": "business_name",
          "field_label_raw": "Name (as shown on your income tax return)",
          "field_value": "NTXP LLC",
          "field_type": "text",
          "confidence": 99,
          "source": "kb",
          "state": "auto",
          "accepted": true,
          "was_edited": false
        }
      ]
    }
  ],
  "summary": {
    "total_fields": 15,
    "auto_filled": 11,
    "review_filled": 2,
    "manual_filled": 1,
    "conflicts_resolved": 1,
    "corrections_made": 2,
    "completion_pct": 100,
    "avg_confidence": 89,
    "jev_cost": 0.003
  },
  "save_location": "!Company Documents",
  "save_location_folder": "NTXP folder system"
}
```
