# Product

<!-- impeccable:product-schema 1 -->

## Platform
web

## Stack
Confirmed in approved plan: React/TypeScript, Python/FastAPI, PostgreSQL 17 and a Python worker. Private hospital deployment; BMS Session API reads HIS, the existing REP–STM importer writes statement data.

## Users
Hospital 10929 executives, reimbursement staff and case reviewers. They need annual visibility, case comparisons and an actionable follow-up queue.

## Product Purpose
Use HIS patients and encounters as denominators, connect them to claims and report rounds, and find missing submissions, missing responses, financial differences and pending appeals.

## Positioning
Every financial observation carries its source and coverage: HIS charges, submitted money, REP compensation, STM amount, cash receipt and item costs stay distinct.

## Operating Context
Thai hospital, OPD and IPD, Thai fiscal year October–September. BMS sessions verified for 10929 authorize reading and uploading. Uploads are XLS; records retain archive, revision and checkpoint history.

## Capabilities and Constraints
Staff identity integration is deferred. No HOSxP writes or automatic claim submissions. Cost semantics, payer rules, actual submission/appeal timestamps and cash evidence must be verified before dependent measures are certified. Forecasting follows completeness validation. Demo evidence must be visibly synthetic.

## Evidence on Hand
HOSxP schema JSON and Obsidian metadata, two CMI SQL references, instrument SQL, CMI Dashboard and IPD Compensation Dashboard source, and the working REP–STM importer. No active BMS session was provided for live HIS acceptance.

## Product Principles
- Count patients, encounters and claims separately.
- Missing evidence is unknown, not zero or failure.
- Make source, date and coverage visible.
- Every total drills through to the records that contributed.
- Use Thai operational wording and accessible controls.
