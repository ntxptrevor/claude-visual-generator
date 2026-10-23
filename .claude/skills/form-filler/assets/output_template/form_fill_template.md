# Form Filler UI — Artifact Template

Generate an interactive HTML artifact for the FormFlow form filling session.
This artifact presents detected form fields with KB matches for review and filling.

## Design Requirements

- **Page orientation**: Responsive (phone, iPad, laptop)
- **Headers**: Centered, full-width, bold
- **Labels**: Bold text for field names
- **Organization**: Color-coded confidence indicators, bullet points
- **Theme**: Professional blue/green (#1a365d, #38a169 accent)
- **Branding**: "FormFlow by NTXP LLC" footer

## Artifact Structure

### Header Section
- Form name (centered, bold, large)
- Total fields count and completion progress ring
- Timestamp

### Field List with Confidence Indicators

Each field row includes:
- **Confidence badge** (left side):
  - Green (≥90%): High confidence auto-fill
  - Yellow (70-89%): Medium confidence, user confirm
  - Orange (50-69%): Low confidence, needs review
  - Red (<50%): No match, manual entry required
- **Field name** (bold label)
- **Suggested value** from KB (or empty input for manual)
- **Source indicator**: "KB", "manual", or KB category tag
- **Action buttons**: Accept ✓ / Edit ✏️ / Skip →

### Interaction Model
- Enter key: Accept current value and advance to next field
- Tab key: Skip field and advance
- Click to edit: Opens inline edit mode
- Auto-scroll: Viewport scrolls to active field
- Progress updates in real-time

### Status Bar (sticky bottom)
- Fields completed: X / Y
- Completion ring (animated)
- "Run Sanity Check" button (when all fields done)
- "Generate Report" button

### Conflict Modal
When a field value contradicts KB:
- Side-by-side comparison (existing KB value vs. new value)
- Radio options: Keep KB / Use New / Enter Different
- "Apply to all similar" checkbox
- Explanation text area

## Output

The artifact outputs filled field data:
```json
{
  "form_name": "W-9 Tax Form",
  "fields": [
    {
      "field_name": "taxpayer_name",
      "field_name_raw": "Name (as shown on your income tax return)",
      "field_value": "John Doe",
      "field_type": "text",
      "confidence": 95,
      "source": "kb",
      "accepted": true
    }
  ],
  "completion_pct": 92,
  "conflicts_resolved": 2
}
```
