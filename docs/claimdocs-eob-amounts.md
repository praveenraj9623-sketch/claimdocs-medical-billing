# ClaimDocs EOB financial-column handling

## Observed issue

The supplied CMS educational EOB contains readable native text and a table with multi-line headers. pdfplumber captures the correct cells, but py-idp's extraction stage forwards only the flattened `raw_text`, discarding the separate parsed tables. In the reported output, insurer-paid and patient-responsibility service values were returned as zero. Pydantic permits legitimate zero amounts; the existing app only reconciled charged amounts, so it did not catch wrong payment-column values. The exact internal reason the model selected those zeros cannot be reconstructed from the screenshot alone.

The sample's printed cells are:

| Service | Charged | Allowed | Paid by insurer | What you owe |
|---|---:|---:|---:|---:|
| 1 | 31.60 | 2.15 | 2.15 | 0.00 |
| 2 | 375.00 | 118.12 | 83.12 | 35.00 |
| Printed total | 406.60 | 120.27 | 85.27 | 35.00 |

These are educational example amounts, not real patient/payment verification. The document says an EOB is not a bill. Empty provider/insurer names remain unknown and masked identifiers remain review findings.

## Fix and scope

- App-specific `claimdocs_eob.py` recognises explicit, unique headers for service description and all four financial columns. Normalisation handles spaces, line breaks, numbered callouts and the split `Descrip-tion` header. No amount, provider or CMS filename is hard-coded into the implementation.
- The named table cells are included **inside the existing untrusted document boundary** sent to Groq. Prompt guidance distinguishes copay/deductible/coinsurance from insurer-paid and patient-owed columns and prohibits duplicate service rows from the repeated table context.
- A deterministic source check requires a complete, unique one-to-one match of service descriptions and charged amounts, with service dates checked where both sides are known. Only a single matching table can change amounts. Duplicated indistinguishable rows, extra/missing services, ambiguous headers, malformed amounts and competing tables do not trigger automatic replacement.
- For a matched table, source amounts replace conflicting model amounts. A blank amount remains null and an explicit printed zero remains zero. A single printed total row supplies totals; totals are never calculated as a substitute for missing printed totals.
- The result keeps the initial model candidate in `model_extraction`; `source_amount_checks` retains field path, page, table, row, source column, model value, source value and change status. `original_extraction` is the initial source-reconciled record; `reviewed_extraction` reflects subsequent human edits. The internal pipeline report retains its original model candidate and adds `reconciled_extraction` separately. Pipeline confidence values are not recalculated or presented as confidence in the source correction.
- Financial consistency checks now cover charged, allowed, paid and patient-responsibility sums against known printed totals. Incomplete line amounts produce a review finding rather than assuming zero.
- The existing screen layout and workflow remain. Printed totals are displayed beneath service lines, all four totals are editable, and CSV includes them. Saving edits still makes no model calls and does not rerun automatic source reconciliation.
- The Groq model, key setup, upstream library, OCR engine, licences and submission/review semantics are unchanged. No additional API requests are introduced by the source check.

## Limits

Native table extraction can still be imperfect. Source alignment is a transcription aid, not a guarantee of factual correctness, actual insurance payment or claim acceptance. It does not reconstruct grids from Tesseract-only OCR, resolve every multi-page/merged-cell layout, infer missing services, or treat patient responsibility as an immediately unpaid balance. Non-matching layouts continue through model extraction and require manual comparison. All documents still require human review.

## Offline verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_claimdocs_eob.py tests/test_claimdocs_ocr.py tests/test_parser_router.py tests/test_pipeline_construction.py tests/test_new_schemas.py tests/test_validator_edge_cases.py -q
```

New regression tests recreate the sample's financial table and deliberately mock the incorrect zero-payment model response. They exercise the real PDF parser and pipeline, source reconciliation, column reordering, missing/ambiguous cells, duplicate rows, competing tables, zero/null distinction, all financial totals, and Streamlit review/save/export availability. Model requests and tokenizer vocabulary are mocked; external sockets are blocked. The actual supplied PDF is also inspected locally without a model call. These checks are not a field-accuracy benchmark or a live Groq re-run.

Verification: 94 targeted tests passed (26 new EOB regressions and the 68 existing targeted OCR/parser/schema/pipeline checks). The exact supplied PDF also produced insurer-paid totals of 85.27 and patient responsibility of 35.00 through the real pipeline with a mocked incorrect zero-amount response. The complete inherited suite and live Groq responses were not rerun.
