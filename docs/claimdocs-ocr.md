# ClaimDocs OCR input support

This change is confined to app input preparation and its deployment dependencies. It does not change the Groq model, extraction instructions, Pydantic schemas, amount checks or review/save logic. The existing screen layout and JSON/CSV downloads remain; supported-file labels and per-page OCR provenance are updated.

## Reading path

1. Retain the 5 MB upload limit. Reject invalid or excessive inputs before constructing the live backend.
2. TXT uses the existing `PlainTextParser`. PDF uses the existing `PdfPlumberParser` for native text and tables.
3. Pages with drawing/image content but no text, or an image plus fewer than 80 native alphanumeric characters, use bounded PDFium rendering and Tesseract English recognition. Genuinely blank pages do not require OCR. This heuristic cannot identify every incomplete or corrupt hidden text layer.
4. PNG/JPEG/TIFF use Pillow, EXIF orientation, white transparency flattening and grayscale/autocontrast. TIFF page numbers are retained. EXIF correction is not arbitrary scan rotation/deskew.
5. A prepared parser feeds the same py-idp pipeline. No image is sent to an OCR API; recognised text subsequently goes to the configured Groq model on extraction.
6. Source text, notes and exported `input_processing` metadata identify which pages used OCR. The processing-time metric includes input preparation.

Tesseract can join or reorder table columns and confuse characters or decimal points. No character/field accuracy benchmark is claimed. Verify extracted codes, dates, amounts and names against the original scan; schema validity does not establish factual correctness.

## Resource bounds and failure behaviour

- Upload: 5 MB. PDF/TIFF: 10 pages. Uploaded image: 20 megapixels per page.
- Rendered PDF page: at most 12 megapixels and 4,200 pixels on the longest side.
- OCR: at most 20 seconds per page and 90 seconds across a document; pages run sequentially.
- Extracted text: at most 200,000 characters; oversized input is rejected rather than truncated.
- Missing engine, corrupt data, OCR failure/timeout and wholly unreadable input fail before a live backend is constructed. No fallback silently accepts a failed OCR page as a validated claim.
- A page on which recognition produces no text can be genuinely blank or unreadable. If other pages are readable, this is explicitly reported in processing notes; verify the original for omitted content. An image-backed page with a native header but no OCR text fails rather than exporting the header alone.

## Dependencies

Python dependencies are in `requirements.txt`: `pytesseract`, `Pillow` and `pypdfium2`. The included root `packages.txt` lists `tesseract-ocr` and `tesseract-ocr-eng` for Streamlit Community Cloud's system-package installation.

Local users must separately install Tesseract with English language data and check `tesseract --version`. No new credential or secret is needed; existing Groq configuration stays the same.

References: [Streamlit dependency setup](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies), [pytesseract](https://github.com/madmaze/pytesseract), [Tesseract image-quality guidance](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html).

## Verification

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pytest pytest-asyncio reportlab
.\.venv\Scripts\python.exe -m pytest tests/test_claimdocs_ocr.py -q
```

The OCR tests generate fictional printed claims locally. They exercise real Tesseract on PNG, JPEG, TIFF, scanned PDFs, mixed native/scanned PDFs and EXIF-oriented images; they also cover limits, blank/corrupt files, absent engine and timeouts. Pipeline and Streamlit regression tests use mocked Groq responses and a deterministic byte-token vocabulary, with external socket connections blocked. No paid API request is needed for these checks. This is verification on fixtures, not a medical-document accuracy or load benchmark.

Local verification: 68 targeted tests passed (25 OCR/app regression cases plus 43 parser, pipeline-construction, schema and validator cases), using Python 3.12 and Tesseract 5.5. New OCR/test files passed Ruff; dependency and whitespace checks passed. The full inherited suite and paid/live Groq calls were not rerun.
