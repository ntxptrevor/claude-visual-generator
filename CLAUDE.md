# CLAUDE.md

## TIER 1 RULES — NTXP Identity (owner directive, 2026-10-07)

Apply to every document, form, bid, registration and signature produced for NTXP LLC.
They override KB values, Drive scans, Council votes and any source document. Change them
only on written direction from the owner.

- **Owner of NTXP LLC** is always listed as **Alison Hopkins** (Owner).
- **Operations contact** is always **Trevor Hopkins**.
- **Designated signatory** for NTXP LLC is always **Alison Hopkins**.
- **Trevor Hopkins** has designated signing authority but uses it only when circumstances
  require. State the circumstance whenever his signature is proposed.
- **W-9 line 3a**: check **S corporation** only. Do not check the LLC box; leave the LLC
  tax-classification code blank.
- **Business address**: 101 South Locust St Ste 605, Denton, TX 76201. Every other address
  is retired (e.g. 405 S Elm St Ste 203) and must not be used.
- **Business phone**: 469-248-7431. All other NTXP phone numbers are retired.
- **Signatures** are always a Tier 3 gate: explicit approval inside Claude, bound to the
  exact file, before the document leaves NTXP.

These rules are hard-coded in `scripts/formflow_signatures.py` (`NTXP_IDENTITY`),
`scripts/formflow_workflow_registry.py` (W-9 `fixed_values`), and
`skills/form-filler/SKILL.md` (Tier 1 Rules section). The FormFlow KB Sheet
(`1IZXlxLhPj4ZOgWC4m9dXPTd0b3rqJfoAwuW3d5Ih-Ug`) carries the same values.
