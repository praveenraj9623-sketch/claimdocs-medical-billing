# ClaimDocs - Billing Document Intelligence

[Live demo](https://praveen-claimdocs.streamlit.app/) · [Source](https://github.com/praveenraj9623-sketch/claimdocs-medical-billing)

Turn synthetic billing documents into structured records that a reviewer can inspect, correct and export. Built with Python, Streamlit, Groq, Pydantic and pdfplumber on the py-idp foundation.

## Problem and user outcome

Billing staff need named claim fields and service lines instead of manually copying a document. ClaimDocs produces an editable first draft, highlights missing or inconsistent information, and preserves the source for comparison. Staff-time savings and real-world extraction accuracy have not been measured.

## How it works

1. Choose **Try a sample** or upload a supported PDF, TXT or image.
2. Validate the input; read native PDF/TXT text, or recognise scanned pages and supported images with local Tesseract OCR.
3. Send the document and billing instructions to the configured Groq model.
4. Validate candidate fields with Pydantic; for supported native EOB tables, check amounts against uniquely matched source cells. Show financial-total and missing-field checks.
5. Review source text, edit the stored record, and download JSON or service-line CSV.

Review edits reuse the extracted record without another model call. Exports do not submit or approve an insurance claim, and are not protected by ClaimVoice's separate mandatory approval gate.

## Supported scope

- Text-based or scanned **PDF**, **TXT**, **PNG**, **JPEG** and **TIFF**. Limits: **5 MB**, **10 PDF/TIFF pages**, **20 megapixels per uploaded image page** and **200,000 extracted characters**.
- Claim, patient, provider, insurer, diagnosis and service-line fields, with distinct charged, allowed, paid and patient-responsibility amounts.
- Missing facts remain unknown. Null is not zero; no extracted diagnosis is not proof that no diagnosis exists.
- Schema validation, decimal amount-consistency checks, source review and correction.
- Native EOB tables with explicit service, charged, allowed, insurer-paid and patient-responsibility columns retain named cells in the extraction input. When every service row matches uniquely, printed amounts replace conflicting model values, with both versions and cell locations preserved in JSON. Ambiguous matches stay flagged for review. Printed totals are not inferred by adding rows. See [EOB amount handling](docs/claimdocs-eob-amounts.md).

OCR supports clear, upright printed English text. PDF pages retain their page numbers: native text is reused, while pages without a usable text layer or with a sparse header over an image use Tesseract. EXIF orientation is honoured for image uploads. OCR is bounded to 20 seconds per page and 90 seconds per document. Recognition can misread codes, names, dates, tables and decimal amounts; human source comparison remains required. Handwriting, arbitrary rotation, damaged scans and accurate reconstruction of every EOB/table layout are not guaranteed. Input limits are not a concurrency or throughput benchmark.

## Models and tools

| Component | Actual role |
|---|---|
| Groq API | Hosted language-model inference |
| `openai/gpt-oss-20b` | Default extraction model; override with `GROQ_MODEL` |
| py-idp | Reused document/pipeline foundation |
| pdfplumber | Preserve the existing native PDF text/table-reading path |
| Tesseract / pytesseract | Local CPU recognition of scanned English text; no OCR API key |
| PDFium / Pillow | Bounded PDF page rendering, image reading and preprocessing |
| Pydantic | Field types and constraints; not factual truth verification |
| pandas / Decimal | Service-line tables and amount handling |
| Streamlit | Interface, per-session state, review and export |

The model is a practical configurable starting point for a key-based hosted demo. Hosting inference through Groq avoids loading a large LLM on the Streamlit host. GPT-OSS has open weights under Apache 2.0; **Groq's hosted service is separate**, with its own availability, quotas and pricing. No comparison establishes this as the best extraction model. This app does not fine-tune an LLM or implement a policy-retrieval RAG workflow.

## Run locally - Python 3.11 / PowerShell

```powershell
git clone https://github.com/praveenraj9623-sketch/claimdocs-medical-billing.git
Set-Location claimdocs-medical-billing
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

For scans, install the **Tesseract OCR application plus English language data**, and make `tesseract --version` work in the same terminal. Windows installations under `Program Files/Tesseract-OCR` are also detected. Python packages alone do not install the engine. On Streamlit Cloud, the included root `packages.txt` installs it automatically when the app rebuilds. Native text input remains independent of the OCR engine.

Create `.streamlit/secrets.toml` locally, or paste these top-level values into Streamlit Community Cloud's Secrets settings:

```toml
GROQ_API_KEY = "your-key-here"
GROQ_MODEL = "openai/gpt-oss-20b"
```

Keep real credentials out of Git and screenshots. The app also supports a root `.env`; inspect `make_backend` in [app.py](app.py) for the actual configuration precedence. For Community Cloud, select `app.py` as the entrypoint and keep the repository dependency files intact.

## Demo and evaluation

Use the built-in synthetic sample, extract, compare the two service lines with the source, inspect findings, edit a field and export. Extraction makes real Groq requests when configured; merely having a key is not evidence of success.

The OCR update adds real-Tesseract synthetic fixture checks and an offline extraction/review/export regression suite; Groq responses and the token vocabulary are replaced with offline test fixtures in those tests. See [OCR implementation and verification](docs/claimdocs-ocr.md). A clean fixture check is not an OCR accuracy benchmark.

**There is no ClaimDocs-specific field-accuracy benchmark.** Sample smoke checks are not an accuracy study. The inherited py-idp invoice/receipt scores, including its 0.96 field F1, are upstream results and must not be presented as this adaptation's performance. The receipt fixtures and notebooks below exercise the upstream library, not medical-claim accuracy.

## Repository guide

- [app.py](app.py): billing interface, schema handling, checks, correction and export.
- [claimdocs_ocr.py](claimdocs_ocr.py): bounded app-specific input preparation and OCR.
- [packages.txt](packages.txt): Streamlit Cloud system OCR dependencies.
- [src/idp](src/idp): inherited processing library and compatibility changes.
- [examples](examples/README.md): optional upstream examples; some use mocks or other providers.
- [Receipt fixtures](src/idp/eval/datasets/cord/README.md): inherited evaluation material, not a ClaimDocs benchmark.
- [中文说明](README.zh-CN.md) / [繁體中文說明](README.zh-TW.md): adaptation scope and links.

## Limitations and safe demonstration

Use fictional documents only. OCR runs on the app server. Configured extraction then sends the resulting document text to Groq. Session state is not durable enterprise storage. Schema-valid output can still contain incorrect facts; a reviewer must compare it with the source. No real claim submission, payment verification, production load result or established HIPAA compliance is provided.

## Foundation and licence

This adaptation extends [rollroyces/py-idp](https://github.com/rollroyces/py-idp). Billing-specific interface, schema/nullable-field handling, amount checks, correction/export, bounded OCR input preparation and compatibility work are adaptation contributions; the underlying library remains attributed to its upstream authors. Preserve [LICENSE](LICENSE), [LICENSE-AGPL](LICENSE-AGPL), [LICENSE-COMMERCIAL](LICENSE-COMMERCIAL) and applicable dataset notices. See the licence files for the upstream AGPL/commercial terms; this cleanup does not relicense the code.
