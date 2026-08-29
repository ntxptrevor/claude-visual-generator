# KB Setup Wizard — Artifact Template

Generate an interactive HTML artifact for the FormFlow Knowledge Base setup wizard.
This artifact walks the user through initial KB population via Q&A cards.

## Design Requirements

- **Page orientation**: Designed for responsive viewing (phone, iPad, laptop)
- **Headers**: Centered, full-width, bold
- **Labels**: Bold text for all field labels
- **Organization**: Bullet points and clear section labeling
- **Theme**: Professional blue (#1a365d primary, #2b6cb0 secondary, #38a169 accent)
- **Branding**: "FormFlow by NTXP LLC" footer

## Artifact Structure

The wizard artifact should include:

### Step Progress Bar
- Visual step indicator (1-6) showing current position
- Step labels: Personal → Contact → Address → Employment → Education → Business

### Q&A Card Layout
Each step presents a card with:
- **Category header** (centered, bold, colored)
- **Field inputs** stacked vertically:
  - Bold label above each input
  - Appropriate input type (text, date, email, tel, select)
  - Validation hint below input
  - Green checkmark when validated
- **Navigation**: Back / Next buttons, Skip option
- **Progress ring**: small completion indicator per step

### Standard Fields by Step

**Step 1 — Personal Information**
- Full Name (text, required)
- First Name (text, required)
- Last Name (text, required)
- Date of Birth (date)
- Gender (select: Male/Female/Non-binary/Prefer not to say)
- SSN (text, masked input, format: XXX-XX-XXXX)

**Step 2 — Contact Details**
- Email Address (email, required)
- Phone Number (tel)
- Alt Phone (tel)

**Step 3 — Address Information**
- Street Address (text)
- Apt/Suite (text)
- City (text)
- State (select, US states)
- ZIP Code (text, 5-digit validation)
- Country (text, default: United States)

**Step 4 — Employment**
- Employer/Company Name (text)
- Job Title (text)
- Department (text)
- Start Date (date)

**Step 5 — Education**
- School/University (text)
- Degree (text)
- Major/Field (text)
- Graduation Year (number, 4-digit)

**Step 6 — Business (Optional)**
- Business/Company Name (text)
- DBA/Trade Name (text)
- EIN/Tax ID (text)
- Business Type (select)

### Completion Summary
After all steps:
- Summary table of all entered values by category
- Edit button per row for corrections
- "Save to Knowledge Base" action button
- Total fields populated count with completion ring

## Output

The artifact outputs a JSON object to be consumed by the skill:
```json
{
  "entries": [
    {
      "category": "personal",
      "field_name": "full_name",
      "field_value": "John Doe",
      "field_type": "text",
      "confidence": 100,
      "source": "wizard"
    }
  ]
}
```
