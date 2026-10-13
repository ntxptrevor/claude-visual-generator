# Conflict Resolution — Artifact Template

Generate an interactive HTML artifact for resolving KB conflicts during
document ingestion or form filling.

## Design Requirements

- **Page orientation**: Responsive (phone, iPad, laptop)
- **Headers**: Centered, full-width, bold
- **Labels**: Bold text with clear visual distinction
- **Organization**: Side-by-side comparison with color coding
- **Theme**: Warning amber (#d69e2e) for conflicts, blue/green for resolved
- **Branding**: "FormFlow by NTXP LLC" footer

## Artifact Structure

### Conflict Summary Header
- "X Conflicts Found" (centered, bold, amber warning color)
- Conflict count badge
- "Resolve All" and "Skip All" action buttons

### Conflict Card (repeated per conflict)

Each card contains:

**Field Identity**
- Field name (bold, large)
- Category tag (e.g., "Personal", "Contact")
- Source document name

**Side-by-Side Comparison**
| | Existing KB Value | New Value |
|---|---|---|
| Value | Current stored value | Newly extracted value |
| Source | Original document name | Current document name |
| Confidence | 95% | 85% |
| Last Updated | 2024-01-15 | Today |

**Resolution Options** (radio buttons):
1. **Keep Existing** — Retain current KB value (default if higher confidence)
2. **Use New Value** — Replace KB with new value
3. **Keep Both** — Store new as alternate value
4. **Enter Custom** — Type a corrected value (shows text input when selected)

**Quick Actions**:
- "Apply same choice to similar fields" checkbox
- "Add note" expandable text area

### Resolution Summary
After resolving all conflicts:
- Table of all decisions made
- Count: Kept existing / Used new / Custom / Both
- "Apply Changes" confirmation button
- "Undo All" safety button

## Output

```json
{
  "resolutions": [
    {
      "field_name": "phone",
      "action": "use_new",
      "old_value": "555-0100",
      "new_value": "555-0199",
      "note": "Updated phone number"
    }
  ],
  "summary": {
    "kept_existing": 3,
    "used_new": 5,
    "custom": 1,
    "kept_both": 2
  }
}
```
