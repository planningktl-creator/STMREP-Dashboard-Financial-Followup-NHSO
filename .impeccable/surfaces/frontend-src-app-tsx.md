---
version: 1
slug: "frontend-src-app-tsx"
primary_target: "frontend/src/App.tsx"
related_targets: ["frontend/src/styles.css"]
---

# Financial case file

Mode: Operate. Audience: hospital 10929 reimbursement, finance and clinical review teams. Task: identify a case needing follow-up, inspect its evidence, and record a next action. Primary action: open a case file. Source completeness remains visible alongside amounts. All demonstration cases are explicitly synthetic.

## Direction contract

THESIS: A hospital case register with a financial evidence trail. Each case opens as a working file; the overview connects its HIS, REP and STM stages to the action queue.

OWN-WORLD: Cool white sheets on pale blue grey, petrol navigation, lavender folder tabs, amber review stamps. Square ledger rules, tabular figures, Thai workhorse type and wide row hit targets establish the register.

STORY: See the hospital scope and available snapshot, find the interrupted financial stage, inspect its source rows, then assign a team and next follow-up date.

FIRST VIEWPORT: A narrow left register index, scope/date line at top, prominent HIS → REP → STM evidence rail across the working area. Financial ledger below, with the follow-up queue beside it. The primary action is the clickable case row. A case drawer carries the same rail into the detailed file.

FORM: Case-file folder/register, grounded candidate 4, seed 1df2eadd. User confirmed light ground, legible tables and stage rail; code-first build. Signature interaction: selecting a stage filters the case register; opening a row continues that stage inside its evidence file.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
