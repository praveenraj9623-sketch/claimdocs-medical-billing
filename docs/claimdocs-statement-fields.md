# Itemized statement fields and source checks

## Purpose

An itemization can contain a Visit ID, account number, revenue codes, service charges, discounts and a visit balance without containing an insurance claim number or adjudicated patient responsibility. These meanings must remain distinct. A language model can fill the requested JSON schema with valid types while still confusing those meanings or shifting codes across blank table cells.

## Schema and interface

The app's custom schemas now add:

- Claim/statement: `visit_id`, `account_number`, `visit_balance`, `adjustments` and `total_adjustments`.
- Service: `revenue_code`, `ndc_code`, `quantity` and `diagnosis_codes` alongside existing service code, description, date and financial fields.
- Each payment/adjustment entry: `date`, `description`, signed `amount`. Negative self-pay discounts do not become insurer payments or negative service charges.

Old records remain valid because the new fields are optional/default empty. Quantities must be finite and non-negative; signed adjustment amounts and balances must be finite. Printed codes remain strings, including leading zeros. Code format or factual correctness is not established by these type checks.

The same three tabs, extraction button, review/save flow and JSON/service-line CSV remain. New fields and columns are visible/editable. Line diagnoses use comma-separated text in the editor and lists in JSON. The full adjustment list is editable and included in JSON; service CSV repeats statement balance/adjustment totals but does not pretend that each discount belongs to a particular service. Saving never reruns the model or reapplies source corrections over human edits.

## Reading and reconciliation

1. Groq still runs the configurable extraction LLM (default `openai/gpt-oss-20b`). Its prompt distinguishes procedure, diagnosis, revenue and NDC columns, Visit ID versus claim number, visit balance versus patient responsibility, and discounts versus insurer payments.
2. Existing OCR and native PDF parsing are retained. `claimdocs_statement.py` reads explicit native table headers and, for recognised service grids, uses printed currency baselines to locate row bands. Codes/dates/quantities must align with the same amount baseline; wrapped descriptions can span the band. It does not zip newline-split columns, because blank cells would shift subsequent rows.
3. Missing columns are not evidence that a model value is absent. Existing columns with an empty cell retain null/empty-list meaning. Malformed amount tokens or a row without the required date/service-code anchors reject that grid for automatic service matching.
4. Source context stays inside the existing untrusted `<document>` boundary. It repeats source cells, not extra services. Combined text/context retains the 200,000-character pre-model bound.
5. Codes and dates are copied only after a complete, unique service-code/charge/date match across source and model rows. No unmatched service is invented. Every known service date must agree before a single overall service date is used. Claim-level diagnoses come from the matched Dx cells, excluding values printed only in revenue cells.
6. Unique printed Visit ID/account/balance values are recorded separately. A claim number equal to a visit/account identifier is cleared only if no explicit claim-number label exists. A total patient-responsibility candidate equal to a Visit Balance is cleared only when the source has no explicit patient-responsibility/amount-due label; the printed balance stays in `visit_balance`.
7. Native adjustment rows replace the candidate adjustment list only when their signed sum matches an explicitly printed payments/adjustments total. The printed total is not inferred from the list. Row/total inconsistency is flagged.
8. `model_extraction` retains the initial schema-valid model candidate. `source_statement_checks` retains field paths, before/after values and source coordinates/labels. The existing `source_amount_checks` handles supported EOB financial tables separately. JSON keeps both; human review is still necessary.

## Verification and limitations

Offline fixtures recreate a fictional itemization with two services, a blank first-row diagnosis/NDC, revenue codes, wrapped description, two discounts and an account balance. Tests deliberately mock the incorrect claim-ID, diagnosis and patient-responsibility candidate and check source corrections, ambiguity refusal, multiple dates, signed amounts, schema compatibility and Streamlit save/export availability. External sockets are blocked. There are no additional reconciliation API calls, model comparisons or paid/live requests in verification.

The supplied Mayo sample is checked locally without publishing its file. Expected source interpretation: two charges 462.00 and 150.00 (total 612.00), revenue codes 261/334, only the second row's diagnosis I10 and NDC 296165, discounts -55.44/-18.00 (total -73.44), visit balance 538.56, service date 2024-07-03, and a Visit ID/account rather than an explicit claim number. The document says it is an itemization, not a bill. These are sample transcription checks, not medical coding advice or payer validation.

This is a bounded native-grid reader, not a universal layout engine. Borderless, rotated, complex merged, malformed or OCR-only tables may need manual corrections. Conflicting identifiers, ambiguous rows, missing cells and unsupported source labels do not justify guessing. Groq output remains a draft, and no field-accuracy, throughput, payment verification or claim-acceptance result is established.
