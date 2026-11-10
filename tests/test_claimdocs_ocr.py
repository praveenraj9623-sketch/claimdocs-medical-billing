"""Synthetic OCR and workflow regressions; no external API requests."""
from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import app
import claimdocs_ocr as reader

# The library's default CI does not install the app's optional OCR stack.
# Install requirements.txt to include these app integration tests.
pytest.importorskip('pytesseract')
requires_tesseract = pytest.mark.skipif(not shutil.which('tesseract'), reason='Tesseract engine required for integration check')

TEXT = '''SYNTHETIC MEDICAL CLAIM
Claim number: DEMO-1001
Patient name: Alex Sample
Provider name: Demo EMS Services
Insurer name: Demo Health Plan
Date of service: 2026-10-20
Ambulance transport: 1100.00
Transport mileage: 400.00
Total charged: 1500.00
'''
EXTRACTION = {
    'claim_number': 'DEMO-1001', 'patient_name': 'Alex Sample',
    'provider_name': 'Demo EMS Services', 'insurer_name': 'Demo Health Plan',
    'date_of_service': '2026-10-20', 'diagnosis_codes': [],
    'line_items': [{'description': 'Ambulance transport', 'charged_amount': 1100.0},
                   {'description': 'Transport mileage', 'charged_amount': 400.0}],
    'total_charged': 1500.0,
}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('OCR verification must not open external sockets')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setenv('GROQ_API_KEY', 'offline-test-key')


@pytest.fixture
def image():
    pic = Image.new('RGB', (1400, 1800), 'white')
    font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    font = ImageFont.truetype(font_path, 32) if Path(font_path).exists() else ImageFont.load_default(size=32)
    ImageDraw.Draw(pic).multiline_text((60, 60), TEXT, font=font, fill='black', spacing=16)
    yield pic
    pic.close()


def native_pdf(path, text=TEXT):
    doc = canvas.Canvas(str(path))
    y = 790
    for line in text.splitlines():
        doc.drawString(45, y, line)
        y -= 20
    doc.save()
    return path


def mixed_pdf(path, image, sparse_header=False):
    doc = canvas.Canvas(str(path), pagesize=(672, 864))
    if not sparse_header:
        for i, line in enumerate(TEXT.splitlines()):
            doc.drawString(45, 810 - i * 20, line)
        doc.showPage()
    doc.drawImage(ImageReader(image), 0, 0, width=672, height=864)
    if sparse_header:
        doc.drawString(10, 850, 'Statement')
    doc.save()
    return path


@pytest.fixture
def fake_groq(monkeypatch):
    from idp.llm.backend import OpenAICompatBackend
    calls = []
    monkeypatch.setattr('idp.llm.backend._validate_base_url', lambda url, **kwargs: url)
    def complete(self, request):
        calls.append(request)
        if 'document classifier' in request.messages[0].content:
            return json.dumps({'label': 'other', 'confidence': 0.95})
        return json.dumps(EXTRACTION)
    monkeypatch.setattr(OpenAICompatBackend, 'complete', complete)
    # The tokenizer normally downloads its vocabulary on first use. A local
    # byte vocabulary exercises the same encode/decode interface offline;
    # token counts here are not a production-model token-budget benchmark.
    import tiktoken
    encoding = tiktoken.Encoding(name='offline-test-bytes', pat_str=r'(?s).',
        mergeable_ranks={bytes([i]): i for i in range(256)}, special_tokens={})
    monkeypatch.setattr(tiktoken, 'get_encoding', lambda name: encoding)
    return calls


def test_plain_text_uses_existing_parser_without_ocr(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, '_ocr_text', lambda *args: pytest.fail('TXT must not run OCR'))
    path = tmp_path / 'claim.txt'
    path.write_text(TEXT)
    prepared = reader.prepare_document(path)
    assert prepared.parsed['text'] == TEXT
    assert prepared.methods == {1: 'plain-text'}
    assert prepared.notes == []


def test_native_pdf_preserves_existing_text_and_tables(tmp_path, monkeypatch):
    from idp.parse.parser import PdfPlumberParser
    monkeypatch.setattr(reader, '_ocr_text', lambda *args: pytest.fail('Native text must not run OCR'))
    path = native_pdf(tmp_path / 'native.pdf')
    expected = PdfPlumberParser().parse(path)
    actual = reader.prepare_document(path)
    assert actual.parsed['text'] == expected['text']
    assert actual.parsed['tables'] == expected['tables']
    assert actual.methods == {1: 'pdf-text'}


@pytest.mark.parametrize('suffix', ['.png', '.jpg', '.tiff'])
@requires_tesseract
def test_real_tesseract_reads_synthetic_image(tmp_path, image, suffix):
    assert shutil.which('tesseract'), 'Install the documented OCR engine for this integration test'
    path = tmp_path / ('claim' + suffix)
    image.save(path, compression='tiff_lzw')
    result = reader.prepare_document(path)
    text = result.parsed['text']
    assert 'DEMO-1001' in text and 'Alex Sample' in text and '1500.00' in text
    assert result.methods == {1: 'tesseract-ocr'}
    assert 'OCR can misread' in result.notes[0]


@requires_tesseract
def test_real_ocr_scanned_pdf_has_original_page_number(tmp_path, image):
    path = tmp_path / 'scanned.pdf'
    image.save(path, 'PDF', resolution=150)
    result = reader.prepare_document(path)
    assert result.methods == {1: 'tesseract-ocr'}
    assert result.parsed['pages'][0]['page'] == 1
    assert '1500.00' in result.parsed['pages'][0]['text']


@requires_tesseract
def test_mixed_pdf_keeps_native_and_scanned_pages(tmp_path, image):
    result = reader.prepare_document(mixed_pdf(tmp_path / 'mixed.pdf', image))
    assert result.methods == {1: 'pdf-text', 2: 'tesseract-ocr'}
    assert all('DEMO-1001' in p['text'] for p in result.parsed['pages'])
    assert 'page(s) 2.' in result.notes[0]


@requires_tesseract
def test_sparse_native_header_does_not_hide_scanned_body(tmp_path, image):
    result = reader.prepare_document(mixed_pdf(tmp_path / 'header.pdf', image, sparse_header=True))
    assert result.methods[1] == 'tesseract-ocr'
    assert '1500.00' in result.parsed['text']


@requires_tesseract
def test_multipage_tiff_preserves_all_frames(tmp_path, image):
    path = tmp_path / 'claim.tiff'
    image.save(path, save_all=True, append_images=[image], compression='tiff_lzw')
    result = reader.prepare_document(path)
    assert list(result.methods) == [1, 2]
    assert all('1500.00' in p['text'] for p in result.parsed['pages'])


@requires_tesseract
def test_exif_orientation_is_applied_before_ocr(tmp_path, image):
    rotated = image.rotate(90, expand=True)
    path = tmp_path / 'oriented.jpg'
    exif = rotated.getexif()
    exif[274] = 6
    rotated.save(path, exif=exif)
    rotated.close()
    result = reader.prepare_document(path)
    assert 'DEMO-1001' in result.parsed['text']


@pytest.mark.parametrize('filename,data', [('invalid.pdf', b'not a PDF'), ('invalid.png', b'not an image'), ('empty.txt', b'  '), ('file.exe', b'bad')])
def test_bad_input_fails_before_backend_creation(monkeypatch, filename, data):
    monkeypatch.setattr(app, 'make_backend', lambda *args: pytest.fail('Invalid input must not create a live backend'))
    with pytest.raises(ValueError):
        app.extract_claim(data, filename, 'unused', 'unused')


def test_missing_engine_has_actionable_error_before_backend(tmp_path, image, monkeypatch):
    path = tmp_path / 'claim.png'
    image.save(path)
    monkeypatch.setattr(reader.shutil, 'which', lambda name: None)
    monkeypatch.setattr(app, 'make_backend', lambda *args: pytest.fail('No backend call on OCR failure'))
    with pytest.raises(ValueError, match='OCR engine unavailable'):
        app.extract_claim(path.read_bytes(), path.name, 'unused', 'unused')


def test_ocr_timeout_does_not_create_partial_claim(tmp_path, image, monkeypatch):
    import pytesseract
    path = tmp_path / 'claim.png'
    image.save(path)
    def timeout(*args, **kwargs):
        raise RuntimeError('timeout')
    monkeypatch.setattr(reader.shutil, 'which', lambda name: 'mock-tesseract')
    monkeypatch.setattr(pytesseract, 'image_to_string', timeout)
    monkeypatch.setattr(app, 'make_backend', lambda *args: pytest.fail('No backend call on OCR timeout'))
    with pytest.raises(ValueError, match='OCR timed out'):
        app.extract_claim(path.read_bytes(), path.name, 'unused', 'unused')


@requires_tesseract
def test_blank_image_does_not_create_a_record(tmp_path, monkeypatch):
    path = tmp_path / 'blank.png'
    Image.new('RGB', (600, 800), 'white').save(path)
    monkeypatch.setattr(app, 'make_backend', lambda *args: pytest.fail('No backend call on empty OCR'))
    with pytest.raises(ValueError, match='No readable text'):
        app.extract_claim(path.read_bytes(), path.name, 'unused', 'unused')


def test_pixel_limit_precedes_ocr(tmp_path, image, monkeypatch):
    path = tmp_path / 'claim.png'
    image.save(path)
    monkeypatch.setattr(reader, 'MAX_IMAGE_PIXELS', 10)
    monkeypatch.setattr(reader, '_ocr_text', lambda *args: pytest.fail('Oversized images must not reach OCR'))
    with pytest.raises(ValueError, match='20-megapixel'):
        reader.prepare_document(path)


def test_pdf_page_limit_precedes_ocr(tmp_path, monkeypatch):
    path = tmp_path / 'many.pdf'
    pdf = canvas.Canvas(str(path))
    for _ in range(11):
        pdf.drawString(20, 30, 'Page')
        pdf.showPage()
    pdf.save()
    monkeypatch.setattr(reader, '_ocr_text', lambda *args: pytest.fail('Page limit must be checked first'))
    with pytest.raises(ValueError, match='1 to 10 pages'):
        reader.prepare_document(path)


def test_file_size_limit_precedes_ocr(tmp_path, monkeypatch):
    path = tmp_path / 'large.png'
    path.write_bytes(b'x' * (reader.MAX_BYTES + 1))
    with pytest.raises(ValueError, match='under 5 MB'):
        reader.prepare_document(path)


def test_document_timeout_is_bounded(monkeypatch):
    monkeypatch.setattr(reader.time, 'monotonic', lambda: 91)
    with pytest.raises(ValueError, match='90-second'):
        reader._remaining_timeout(0)


@pytest.mark.parametrize('suffix', ['.txt', '.pdf', '.png'])
def test_actual_pipeline_keeps_schema_and_source_review(tmp_path, image, fake_groq, suffix):
    if suffix == '.png' and not shutil.which('tesseract'):
        pytest.skip('Tesseract engine required for PNG integration')
    path = tmp_path / ('claim' + suffix)
    if suffix == '.txt':
        path.write_text(TEXT)
    elif suffix == '.pdf':
        native_pdf(path)
    else:
        image.save(path)
    result = app.extract_claim(path.read_bytes(), path.name, 'offline-test-key', 'openai/gpt-oss-20b')
    assert result['original']['claim_number'] == 'DEMO-1001'
    assert result['current']['total_charged'] == 1500
    assert result['current']['line_items'][1]['charged_amount'] == 400
    assert result['current']['total_paid'] is None
    assert result['reviewed'] is False
    assert result['calls'] == len(fake_groq)
    assert all('DEMO-1001' in page['text'] for page in result['pages'])
    assert bool(result['input_processing']['ocr_engine']) == (suffix == '.png')
    assert result['seconds'] >= result['input_processing']['seconds']


def test_review_save_and_export_remain_available_without_more_model_calls(fake_groq):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=30).run()
    assert not at.exception
    next(b for b in at.button if b.label == 'Extract claim details').click().run()
    assert not at.exception
    before = len(fake_groq)
    next(b for b in at.button if b.label == 'Save reviewed record').click().run()
    assert not at.exception
    assert at.session_state['claim_result']['reviewed']
    assert at.session_state['claim_result']['current']['total_charged'] == 1500
    assert len(fake_groq) == before
    assert len(at.get('download_button')) == 2
