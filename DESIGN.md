---
name: "STMREP"
description: "A light hospital case register with a financial evidence trail."
colors:
  petrol: "#12474f"
  paper: "#fff"
  ground: "#f2f5f8"
  ink: "#213a43"
  muted: "#60747f"
  rule: "#dce4eb"
  soft-surface: "#f7f9fc"
  field-rule: "#c8d4de"
  secondary-rule: "#cbd8e1"
  secondary-ink: "#234b58"
  lavender: "#eae6f5"
  folder-ground: "#f0f3f7"
  folder-ink: "#5b4d79"
  active-nav: "#f0f5f6"
  nav-label: "#c6d9dc"
  good-ground: "#e8f2ec"
  good-ink: "#3a7757"
  review-ground: "#fcf2e4"
  review-ink: "#875719"
  bad-ground: "#fae8e9"
  bad-ink: "#a8494e"
  focus: "#488dac"
  his: "#bdd0dc"
  rep: "#659aa3"
  stm: "#a7a0c5"
typography:
  display:
    fontFamily: "'Noto Sans Thai', Tahoma, sans-serif"
    fontSize: "38px"
    fontWeight: 700
    lineHeight: 1.5
    letterSpacing: "-.6px"
  headline:
    fontFamily: "'Noto Sans Thai', Tahoma, sans-serif"
    fontSize: "28px"
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: "-.6px"
  title:
    fontFamily: "'Noto Sans Thai', Tahoma, sans-serif"
    fontSize: "16px"
    fontWeight: 700
    lineHeight: 1.45
  body:
    fontFamily: "'Noto Sans Thai', Tahoma, sans-serif"
    fontSize: "12px"
    lineHeight: 1.6
  label:
    fontFamily: "'Noto Sans Thai', Tahoma, sans-serif"
    fontSize: "13px"
    fontWeight: 500
  button:
    fontFamily: "'Noto Sans Thai', Tahoma, sans-serif"
    fontSize: "13px"
    fontWeight: 600
  table-label:
    fontFamily: "'Noto Sans Thai', Tahoma, sans-serif"
    fontSize: "10px"
    fontWeight: 500
  number:
    fontFamily: "'Noto Sans Thai', Tahoma, sans-serif"
    fontSize: "20px"
    fontWeight: 600
  code:
    fontFamily: "Consolas, monospace"
    fontSize: "12px"
rounded:
  square: "0"
  stamp: "3px"
  label: "4px"
  utility: "5px"
  panel: "6px"
  folder-top: "7px 7px 0 0"
  drawer: "8px 0 0 8px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  sheet: "20px"
  section: "24px"
  page: "32px"
components:
  button-primary:
    backgroundColor: "{colors.petrol}"
    textColor: "{colors.paper}"
    typography: "{typography.button}"
    rounded: "{rounded.panel}"
    padding: "9px 14px"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.secondary-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.panel}"
    padding: "9px 14px"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "8px 11px"
  navigation:
    textColor: "{colors.nav-label}"
    rounded: "{rounded.utility}"
    padding: "11px 12px"
  navigation-active:
    backgroundColor: "{colors.active-nav}"
    textColor: "{colors.petrol}"
    rounded: "{rounded.utility}"
    padding: "11px 12px"
  badge-good:
    backgroundColor: "{colors.good-ground}"
    textColor: "{colors.good-ink}"
    rounded: "{rounded.label}"
    padding: "4px 8px"
  badge-review:
    backgroundColor: "{colors.review-ground}"
    textColor: "{colors.review-ink}"
    rounded: "{rounded.label}"
    padding: "4px 8px"
  badge-bad:
    backgroundColor: "{colors.bad-ground}"
    textColor: "{colors.bad-ink}"
    rounded: "{rounded.label}"
    padding: "4px 8px"
  sheet:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.panel}"
  folder-tab:
    backgroundColor: "{colors.folder-ground}"
    rounded: "{rounded.folder-top}"
    padding: "9px 15px"
  folder-tab-selected:
    backgroundColor: "{colors.lavender}"
    textColor: "{colors.folder-ink}"
    rounded: "{rounded.folder-top}"
    padding: "9px 15px"
  evidence-rail:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.square}"
---

# Design System: STMREP

## Overview

**Creative North Star: "The Financial Case Register"**

STMREP uses the user's chosen light case file and register world. Cool white working sheets sit on a pale blue grey ground, with a petrol register index and lavender folder tabs. The material is practical and calm: thin ledger rules, compact Thai text and aligned figures make dense financial evidence easy to scan.

A case keeps its HIS → REP → STM identity from the overview into its working file. Source, date, coverage and uncertainty remain legible beside the amounts. Thai operational wording and visible controls support staff who inspect records and record the next action.

**Key Characteristics:**

- Light working sheets with a petrol navigation index.
- Lavender folder tabs and amber review stamps.
- Compact Thai typography, tabular figures and ruled tables.
- HIS → REP → STM labels carried into the case file.
- Flat working surfaces with structural depth for the modal file.

This record is extracted from the shipped `frontend/src/styles.css`, `frontend/src/App.tsx` and `frontend/src/api.ts`. The frontmatter owns the reusable primitives; the sidecar owns motion, responsive thresholds, actual shadows and component previews.

## Colors

The palette pairs cool paper and petrol with lavender filing cues and readable status stamps.

### Primary

- **Petrol:** Navigation ground, primary actions, links and the top rule of the evidence rail. This is the main identity accent.
- **Evidence Teal:** REP series in the monthly comparison.

### Secondary

- **Folder Lavender:** Selected file tabs and filing context.
- **Statement Lavender:** STM series in the monthly comparison.
- **Folder Ink:** Text on selected lavender tabs.

### Tertiary

- **Amber Review:** Review stamp text on pale amber paper.
- **Verified Green:** Matched, complete and resolved stamp text on pale green paper.
- **Exception Rose:** Rejected and failed stamp text on pale rose paper.

### Neutral

- **Cool Paper / Pale Blue Grey:** Working sheets and the surrounding ground.
- **Register Ink / Muted Ink:** Main text and secondary evidence text. Muted Ink also appears in table headers, empty-state copy and field placeholders.
- **Ledger Rule / Field Rule / Secondary Rule:** Thin sheet dividers, field strokes and secondary action strokes.
- **Soft Surface / Folder Ground:** Table headings, file headings, form groups and unselected folder tabs.
- **Active Navigation Paper / Navigation Label:** Selected navigation fill and labels on petrol.
- **Secondary Ink:** Secondary actions on white.
- **HIS Blue:** HIS series in the monthly comparison.
- **Focus Blue:** The visible keyboard outline for interactive elements.

### Named Rules

**The Stage Identity Rule.** Keep HIS, REP and STM explicitly named. Use the existing HIS blue, REP teal and STM lavender together when comparing their series.

**The Status Stamp Rule.** Pair each status color with a readable status label. Amber signals review, green signals matched or completed work, and rose signals a rejected or failed result.

## Typography

**Display Font:** Noto Sans Thai, with Tahoma and sans-serif fallbacks.
**Body Font:** The same Thai stack throughout the working register.
**Label/Mono Font:** Consolas, with a monospace fallback, for technical source identifiers.

**Character:** A single Thai workhorse family keeps the evidence and controls cohesive. Bold headings and tabular numbers establish hierarchy without adding a second display voice. The CSS names Noto Sans Thai; availability determines whether its fallback is used.

### Hierarchy

- **Display:** The login introduction; reduces to 31px below the medium threshold and 30px on small screens.
- **Headline:** Main page headings; reduces to 25px below the medium threshold and 23px on small screens.
- **Title:** Sheet headings; reduces to 15px on small screens. The general section heading uses 18px, and file headings use 26px.
- **Body:** The table body role. Supporting prose generally uses 12–14px with more open line spacing.
- **Label:** Form labels. Buttons use the same size with the stronger button weight.
- **Table Label:** Table headings and compact metadata. They remain readable Muted Ink on Soft Surface.
- **Number:** Financial ledger amounts. Evidence rail amounts use 23px at the default desktop width; file amounts use 17px.
- **Code:** Table, source and field identifiers; allow long identifiers to wrap.

### Named Rules

**The Aligned Figures Rule.** Use tabular numerals for amounts, counts and strong figures. Right-align financial table columns and keep the monetary unit secondary to its amount.

## Layout

The desktop workspace has a fixed petrol index (222px), a top bar (63px) and a main container capped at 1660px. Main content uses 28px top padding and the page spacing token horizontally. Ordinary sheets use the sheet spacing token for much of their horizontal content, with thin rules between rows.

The overview grid pairs a flexible ledger with a queue column of 275–330px and a 20px gap. At 1600px and above, the queue becomes 350px and the evidence rail gains space. At 1200px and below, the register index becomes 194px and content gutters narrow to 22px.

At 980px and below, the overview becomes one column; the queue briefly uses a two-column arrangement, and scope filters wrap. At 760px and below, the index becomes a static header with horizontally scrolling navigation. Main gutters become 16px, the evidence rail stacks vertically, scope filters use two columns with full-width fiscal year and snapshot fields, and form groups become one column.

Tables retain their column structure inside horizontal scrolling wrappers. Case rows keep a prominent case link with a minimum 42px target height. The modal file fills the height of the viewport, opens from the right at up to 960px / 95vw, and becomes full width on small screens. File amounts change from three columns to two.

## Elevation & Depth

Ordinary sheets, scope controls, ledger rows and the evidence rail use border and tonal layering. They have no applied box shadow. Depth is structural at the login sheet and the modal case file. The unused root shadow declaration is not an elevation token.

### Shadow Vocabulary

- **Login sheet:** `box-shadow: 0 10px 35px #1c435710`; a faint separation for the entry form.
- **Case file:** `box-shadow: -12px 0 60px #13293533`; right-side file depth over a `#233c5266` backdrop.

### Named Rules

**The Sheet Depth Rule.** Keep working sheets and ledger rows flat. Reserve the implemented shadows for the entry form and the modal file.

State changes use a brief background and border-color transition (0.16s), plus a subtle hover brightness change. The loading icon rotates at 1.2s with linear easing. Reduced motion disables animations and transitions.

## Shapes

Controls and sheets share gently curved panel corners. Small stamps, badges and utility controls use the tighter corner steps. File tabs have rounded upper corners with a straight baseline. The evidence rail and login sheet retain square outlines with a petrol top rule.

The desktop case file rounds only its left edge; the small-screen file has square corners. Borders are thin (1px). Circles are reserved for connection, status and timeline points. Charts use a small rounded top on each bar.

## Components

### Buttons

Compact, clear actions with a minimum 40px height.

- **Primary:** Petrol with white text, panel corners and the frontmatter padding.
- **Secondary:** White with Secondary Ink and a Secondary Rule stroke.
- **Hover / Focus:** Subtle brightness reduction on enabled hover; a 3px Focus Blue outline with 3px offset.
- **Disabled:** Half opacity and the unavailable cursor.
- **Icon action:** A transparent 38px square utility control, with a pale hover fill and an accessible name.

### Chips

Readable status stamps carry the result in text.

- **Style:** Pale good, review or bad ground with its corresponding status ink; label corners; 10px text with 1.5 line height.
- **State:** The shipped Badge component maps matched, complete and resolved to green; rejected and failed to rose; remaining statuses to amber.
- **Care stamp:** A smaller ruled OPD / IPD marker accompanies a case.

### Cards / Containers

Working sheets behave like sections of a register.

- **Corner Style:** Panel corners, except the square evidence rail and entry sheet.
- **Background:** Cool Paper; Soft Surface for file headings and action form groups.
- **Shadow Strategy:** Apply the Sheet Depth Rule.
- **Border:** A thin Ledger Rule stroke.
- **Internal Padding:** Sheet headers use 18px 20px 15px; body patterns use the sheet rhythm and ruled rows rather than an extra nested card.

### Inputs / Fields

White, stroked controls with permanent labels.

- **Style:** Field Rule stroke, panel corners, minimum 40px height and frontmatter padding. Scope controls are denser at 36px.
- **Focus:** The shared Focus Blue outline remains visible outside the field.
- **Search:** An integrated search icon and an unbordered input inside a single ruled shell.
- **Long Text:** Textareas start at 85px and resize vertically.
- **Error:** Readable error notices sit near the affected form. Preserve the source control and alert semantics.

### Navigation

The petrol register index uses compact left-aligned labels and inline SVG icons. The current destination becomes a light paper row with petrol text and stronger weight, and exposes `aria-current="page"`. On small screens, the same destinations form a horizontally scrolling row.

### Folder Tabs and Case File

The tabs use a shared baseline, lavender selected fill and a visible keyboard outline. The case file is a native modal dialog named by its visible case heading. Its tablist uses selected state, roving tab stops, ArrowLeft / ArrowRight / Home / End navigation and a labelled tab panel. Keep these semantics with the visual pattern.

### Evidence Rail and Ledger

The HIS → REP → STM rail joins source labels, quantities and context in a square ruled sheet. Each stage opens the corresponding case group. The detailed file repeats the stage labels with reached or pending indicators.

The ledger uses ruled rows, left-hand descriptions and secondary source hints, with right-hand tabular amounts and small unit labels. Money uses Thai locale formatting and two decimal places. Missing amounts display an em dash; they retain their unknown meaning.

## Do's and Don'ts

### Do:

- **Do** retain light working sheets, petrol navigation and lavender filing cues.
- **Do** use the Stage Identity Rule for comparisons and case evidence.
- **Do** use the Aligned Figures Rule for monetary columns and ledger values.
- **Do** keep source, date, coverage and unknown values visible beside financial observations.
- **Do** retain visible focus outlines and the native modal and tab semantics.
- **Do** preserve table structure with horizontal scrolling on small screens.

### Don't:

- **Don't** use a status color without its readable label.
- **Don't** replace missing financial evidence with zero.
- **Don't** merge HIS charges, REP compensation, STM statements and cash evidence into one unnamed amount.
- **Don't** add shadows to ordinary working sheets or ledger rows.
- **Don't** replace the folder tab baseline or square evidence rail with uniformly pill-shaped containers.
