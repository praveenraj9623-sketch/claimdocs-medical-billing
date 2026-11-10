"""Bounded, CPU-only OCR for ClaimDocs input; no LLM or network calls.

Existing native text and table parsing are retained. Only pages without a
usable text layer (or with a sparse header over an image) need Tesseract.
The prepared result implements py-idp's Parser protocol, so all downstream
extraction, validation, correction and export steps keep their existing path.
"""
from __future__ import annotations

import math
import os
import shutil
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 10
MAX_IMAGE_PIXELS = 20_000_000
MAX_RENDER_PIXELS = 12_000_000
MAX_TEXT_CHARS = 200_000
OCR_PAGE_SECONDS = 20
OCR_DOCUMENT_SECONDS = 90
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
SUPPORTED_SUFFIXES = {".pdf", ".txt", *IMAGE_SUFFIXES}


@dataclass
class PreparedDocument:
    parsed: dict[str, Any]
    methods: dict[int, str]
    notes: list[str]

    @property
    def name(self):
        return self.parsed['metadata']['parser']

    def parse(self, path):
        # Already prepared before constructing the live backend. Parse failures
        # therefore cannot be swallowed by the library and trigger model calls.
        return self.parsed


def _remaining_timeout(started):
    remaining = OCR_DOCUMENT_SECONDS - (time.monotonic() - started)
    if remaining <= 0:
        raise ValueError("OCR exceeded the 90-second document limit. Split the scan into smaller files.")
    return min(OCR_PAGE_SECONDS, remaining)


def _ocr_text(image, started):
    import pytesseract
    from PIL import Image, ImageOps

    engine = shutil.which('tesseract')
    if not engine and os.name == 'nt':
        candidate = Path(os.environ.get('PROGRAMFILES', r'C:\Program Files')) / 'Tesseract-OCR' / 'tesseract.exe'
        if candidate.is_file():
            engine = str(candidate)
    if not engine:
        raise ValueError("OCR engine unavailable. Install Tesseract OCR locally; on Streamlit Cloud, rebuild with packages.txt. Text-based PDF and TXT still work.")
    pytesseract.pytesseract.tesseract_cmd = engine
    # EXIF orientation is applied by the image reader. Flatten transparency onto
    # white before grayscale conversion, so transparent scans remain readable.
    rgba = image.convert('RGBA')
    background = Image.new('RGBA', rgba.size, 'white')
    background.alpha_composite(rgba)
    gray = ImageOps.autocontrast(background.convert('L'))
    rgba.close()
    background.close()
    max_edge = max(gray.size)
    if max_edge < 1800:
        factor = min(2.0, 1800 / max_edge)
        resized = gray.resize((round(gray.width * factor), round(gray.height * factor)), Image.Resampling.LANCZOS)
        gray.close()
        gray = resized
    gray.thumbnail((4200, 4200), Image.Resampling.LANCZOS)
    try:
        text = pytesseract.image_to_string(gray, lang='eng', config='--psm 3 --dpi 300', timeout=_remaining_timeout(started))
    except pytesseract.TesseractNotFoundError:
        raise ValueError("OCR engine unavailable. Install Tesseract OCR and ensure it is on PATH.") from None
    except pytesseract.TesseractError:
        raise ValueError("OCR could not read this page. Confirm that Tesseract's English language data is installed, or upload a clearer scan.") from None
    except RuntimeError:
        raise ValueError("OCR timed out on a page. Upload a clearer or smaller scan; no claim record was created.") from None
    finally:
        gray.close()
    return text.strip()


def _finish(parsed, methods):
    text = parsed['text']
    if not text.strip():
        raise ValueError("No readable text was found. Use a clear, upright scan of printed English text or a text-based PDF/TXT.")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError("Extracted text exceeds this demo's 200,000-character limit. Split the document into smaller files.")
    ocr_pages = [page for page, method in methods.items() if method == 'tesseract-ocr']
    notes = []
    if ocr_pages:
        parsed['metadata']['parser'] = 'claimdocs-ocr'
        parsed['metadata']['ocr_pages'] = ocr_pages
        notes.append('Tesseract OCR was used on page(s) ' + ', '.join(map(str, ocr_pages)) + '. OCR can misread names, codes, dates and amounts; compare the record with the original scan before export.')
    empty_pages = [p['page'] for p in parsed['pages'] if not p['text'].strip()]
    if empty_pages:
        notes.append('No text was recognised on page(s) ' + ', '.join(map(str, empty_pages)) + '. These pages may be blank or unreadable; check the original document for missing content.')
    for page in parsed['pages']:
        page['reading_method'] = methods[page['page']]
    return PreparedDocument(parsed, methods, notes)


def _prepare_pdf(path):
    import pdfplumber

    from idp.parse.parser import PdfPlumberParser

    with pdfplumber.open(path) as pdf:
        if not pdf.pages or len(pdf.pages) > MAX_PAGES:
            raise ValueError("For this demo, upload a PDF of 1 to 10 pages.")
        # Use the same library parser for existing text and table extraction.
        parsed = PdfPlumberParser().parse(path)
        scan_pages = []
        for index, page in enumerate(pdf.pages):
            native = parsed['pages'][index]['text']
            sparse = sum(c.isalnum() for c in native) < 80
            has_marks = any(page.objects.values())
            if (not native.strip() and has_marks) or (sparse and page.images):
                scan_pages.append(index)
    methods = {p['page']: 'pdf-text' for p in parsed['pages']}
    if scan_pages:
        import pypdfium2 as pdfium
        started = time.monotonic()
        document = pdfium.PdfDocument(str(path))
        try:
            for index in scan_pages:
                _remaining_timeout(started)
                page = document[index]
                try:
                    width, height = page.get_size()
                    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                        raise ValueError("The PDF has an invalid page size.")
                    scale = min(300 / 72, math.sqrt(MAX_RENDER_PIXELS / (width * height)), 4200 / max(width, height))
                    bitmap = page.render(scale=scale)
                    try:
                        image = bitmap.to_pil()
                        try:
                            text = _ocr_text(image, started)
                        finally:
                            image.close()
                    finally:
                        bitmap.close()
                    native = parsed['pages'][index]['text']
                    # An unreadable scan with a sparse selectable header must not
                    # become an apparently successful header-only extraction.
                    if not text and native.strip():
                        raise ValueError(f"OCR found no readable text on scanned page {index + 1}. Upload a clearer scan; no partial record was created.")
                    parsed['pages'][index]['text'] = text
                    methods[index + 1] = 'tesseract-ocr'
                finally:
                    page.close()
        finally:
            document.close()
        # Tables from these pages describe the sparse native layer, not the OCR
        # text. Do not expose them as if OCR had preserved the original grid.
        parsed['tables'] = [t for t in parsed['tables'] if t['page'] not in {i + 1 for i in scan_pages}]
        parsed['text'] = '\n\n'.join(p['text'] for p in parsed['pages'])
    return _finish(parsed, methods)


def _prepare_image(path):
    from PIL import Image, ImageOps, UnidentifiedImageError

    pages = []
    methods = {}
    started = time.monotonic()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as source:
                frames = getattr(source, 'n_frames', 1)
                if frames > MAX_PAGES:
                    raise ValueError("For this demo, upload an image/TIFF of at most 10 pages.")
                for index in range(frames):
                    source.seek(index)
                    if source.width * source.height > MAX_IMAGE_PIXELS:
                        raise ValueError("An image page exceeds the 20-megapixel limit. Resize it before upload.")
                    image = ImageOps.exif_transpose(source)
                    try:
                        text = _ocr_text(image, started)
                    finally:
                        image.close()
                    pages.append({'page': index + 1, 'text': text, 'image_path': None})
                    methods[index + 1] = 'tesseract-ocr'
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ValueError("The image is too large to process safely. Resize it before upload.") from None
    except (UnidentifiedImageError, OSError, EOFError):
        raise ValueError("The image is damaged or unsupported. Upload a valid PNG, JPEG or TIFF.") from None
    parsed = {'text': '\n\n'.join(p['text'] for p in pages), 'pages': pages, 'tables': [], 'metadata': {'parser': 'claimdocs-ocr', 'size': path.stat().st_size}}
    return _finish(parsed, methods)


def prepare_document(path):
    """Prepare text or bounded OCR pages before any live model request."""
    from idp.parse.parser import PlainTextParser

    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("Choose a PDF, TXT, PNG, JPEG or TIFF document.")
    if not path.stat().st_size or path.stat().st_size > MAX_BYTES:
        raise ValueError("Choose a non-empty document under 5 MB.")
    if suffix == '.txt':
        if not path.read_bytes().decode('utf-8-sig', errors='replace').strip():
            raise ValueError("The text document is empty.")
        parsed = PlainTextParser().parse(path)
        return _finish(parsed, {p['page']: 'plain-text' for p in parsed['pages']})
    if suffix in IMAGE_SUFFIXES:
        return _prepare_image(path)
    try:
        return _prepare_pdf(path)
    except ValueError:
        raise
    except Exception:
        # No original parser exception, file path or native-library diagnostics
        # are surfaced to the UI. There is no retry with partial data.
        raise ValueError("The PDF could not be read. Use an unencrypted, undamaged PDF or export its pages as PNG/JPEG.") from None
