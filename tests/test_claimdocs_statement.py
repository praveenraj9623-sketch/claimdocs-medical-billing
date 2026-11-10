"""Fictional itemization regressions; source columns are checked offline."""
from __future__ import annotations

import copy
import hashlib
import json
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError
from reportlab.pdfgen import canvas

import app
from claimdocs_ocr import prepare_document
from claimdocs_statement import StatementSource, read_statement_source, reconcile_statement

WRONG = {'claim_number': 'DEMO-V100', 'patient_name': 'Fictional Patient',
         'provider_name': 'Example Clinician', 'date_of_service': None,
         'diagnosis_codes': ['261', 'I10'], 'total_charged': 612,
         'total_patient_responsibility': 538.56,
         'line_items': [
             {'description': 'Office visit', 'service_code': '99215', 'service_date': '2024-07-03', 'charged_amount': 462},
             {'description': 'Ciprofloxacin IV', 'service_code': 'J0744', 'service_date': '2024-07-03', 'charged_amount': 150}]}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Statement tests cannot open network sockets')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setenv('GROQ_API_KEY', 'offline-test-key')


def grid(pdf, x, y, widths, headers, body, bottom):
    xs = [x]
    for width in widths:
        xs.append(xs[-1] + width)
    for at in xs:
        pdf.line(at, y, at, bottom)
    header_bottom = y - 35
    for at in (y, header_bottom, bottom):
        pdf.line(x, at, xs[-1], at)
    pdf.setFont('Helvetica', 8)
    for index, text in enumerate(headers):
        for j, line in enumerate(text.split('\n')):
            pdf.drawString(xs[index] + 3, y - 11 - j * 9, line)
    # Deliberately no horizontal boundaries between body services: newline-
    # zipping would assign the only Dx/NDC value to the wrong first service.
    for baseline, values in body:
        for index, text in enumerate(values):
            for j, line in enumerate(text.split('\n')):
                pdf.drawString(xs[index] + 3, baseline - j * 10, line)


def statement_pdf(path):
    pdf = canvas.Canvas(str(path), pagesize=(842, 800))
    pdf.setFont('Helvetica', 10)
    pdf.drawString(30, 775, 'SYNTHETIC ITEMIZATION - NOT A BILL')
    pdf.drawString(30, 755, 'Itemization for account DEMO-V100 for Fictional Patient.')
    # The actual sample has a numeric account ID; the fixture additionally
    # proves that no numeric identifier or provider name is hard-coded.
    grid(pdf, 30, 730, [140, 120, 120, 120], ['Patient Name', 'Visit ID', 'Account Number', 'Visit Balance'],
         [(680, ['Fictional Patient', 'DEMO-V100', 'DEMO-V100', '$538.56'])], 665)
    headers = ['Date of\nService', 'NDC Code', 'Procedure\nCode', 'Procedure Description', 'Dx Code', 'Rev\nCode', 'Qty', 'Charge Amt']
    first = ['07/03/2024', '', '99215', 'Office visit\nWrapped description\nMore details', '', '261', '1', '$462.00']
    second = ['07/03/2024', '296165', 'J0744', 'Ciprofloxacin IV', 'I10', '334', '1', '$150.00']
    grid(pdf, 30, 620, [70, 65, 70, 200, 50, 50, 30, 70], headers, [(570, first), (525, second)], 510)
    pdf.drawString(30, 495, 'Total professional charges: $612.00')
    pdf.drawString(30, 465, 'Professional Payments and Adjustments')
    grid(pdf, 30, 450, [85, 360, 120], ['Date', 'Description', 'Amount'],
         [(400, ['07/08/24', 'Self-Pay Discount', '-$55.44']),
          (380, ['07/30/24', 'Self-Pay Discount', '-$18.00'])], 365)
    pdf.drawString(30, 345, 'Total professional payments and adjustments: -$73.44')
    pdf.drawString(30, 325, 'Visit Balance: $538.56')
    pdf.save()
    return path


@pytest.fixture
def source(tmp_path):
    path = statement_pdf(tmp_path / 'fictional_statement.pdf')
    prepared = prepare_document(path)
    return path, prepared, read_statement_source(path, prepared)


@pytest.fixture
def fake_groq(monkeypatch):
    from idp.llm.backend import OpenAICompatBackend
    monkeypatch.setattr('idp.llm.backend._validate_base_url', lambda value, **kwargs: value)
    calls = []
    def complete(self, request):
        calls.append(request)
        if 'document classifier' in request.messages[0].content:
            return json.dumps({'label': 'other', 'confidence': 0.99})
        return json.dumps(WRONG)
    monkeypatch.setattr(OpenAICompatBackend, 'complete', complete)
    import tiktoken
    vocab = tiktoken.Encoding(name='offline-statement', pat_str=r'(?s).',
        mergeable_ranks={bytes([i]): i for i in range(256)}, special_tokens={})
    monkeypatch.setattr(tiktoken, 'get_encoding', lambda name: vocab)
    return calls


def candidate():
    return app.ClaimDocsClaim.model_validate(WRONG).model_dump(mode='json')


def test_native_geometry_keeps_blank_dx_and_ndc_in_their_actual_rows(source):
    _, _, found = source
    assert len(found.services) == 2
    first, second = found.services
    assert first['revenue_code'] == '261' and first['diagnosis_codes'] == [] and first['ndc_code'] is None
    assert second['revenue_code'] == '334' and second['diagnosis_codes'] == ['I10'] and second['ndc_code'] == '296165'
    assert first['quantity'] == second['quantity'] == 1
    assert [(a['amount'], a['date']) for a in found.adjustments] == [(-55.44, '2024-07-08'), (-18, '2024-07-30')]


def test_reconcile_keeps_identifiers_balances_and_discounts_separate(source):
    _, prepared, found = source
    raw = candidate()
    clean, evidence, _ = reconcile_statement(raw, found, prepared.parsed['text'])
    assert raw['claim_number'] == 'DEMO-V100' and raw['diagnosis_codes'] == ['261', 'I10']
    assert clean['claim_number'] is None and clean['visit_id'] == clean['account_number'] == 'DEMO-V100'
    assert clean['date_of_service'] == '2024-07-03' and clean['diagnosis_codes'] == ['I10']
    assert clean['visit_balance'] == 538.56 and clean['total_patient_responsibility'] is None
    assert clean['total_paid'] is None and clean['total_allowed'] is None
    assert clean['total_adjustments'] == -73.44 and len(clean['adjustments']) == 2
    assert clean['line_items'][0]['diagnosis_codes'] == []
    assert any(e['field'] == 'claim_number' and e['changed'] for e in evidence)
    assert any(e['field'] == 'line_items.1.ndc_code' and e['source']['page'] == 1 for e in evidence)


@pytest.mark.parametrize('label,field', [('Claim Number', 'claim_number'), ('Patient responsibility', 'total_patient_responsibility')])
def test_explicit_separate_source_labels_are_not_cleared(source, label, field):
    _, prepared, found = source
    clean, _, _ = reconcile_statement(candidate(), found, prepared.parsed['text'] + '\n' + label + ': DEMO-V100')
    assert clean[field] == candidate()[field]


def test_conflicting_identifier_candidates_are_not_automapped():
    found = StatementSource(facts=[{'field': 'visit_id', 'value': 'A'}, {'field': 'visit_id', 'value': 'B'}])
    clean, evidence, _ = reconcile_statement(candidate(), found, '')
    assert clean['visit_id'] is None and not any(e['field'] == 'visit_id' for e in evidence)


@pytest.mark.parametrize('change', ['duplicate', 'missing', 'wrong_charge', 'wrong_date'])
def test_uncertain_service_matches_do_not_change_codes_or_dates(source, change):
    _, prepared, found = source
    found = copy.deepcopy(found)
    if change == 'duplicate':
        found.services.append(copy.deepcopy(found.services[0]))
    elif change == 'missing':
        found.services.pop()
    elif change == 'wrong_charge':
        found.services[0]['charged_amount'] = 999
    else:
        found.services[0]['service_date'] = '2024-07-04'
    clean, _, notes = reconcile_statement(candidate(), found, prepared.parsed['text'])
    assert clean['diagnosis_codes'] == ['261', 'I10'] and clean['date_of_service'] is None
    assert any('did not match uniquely' in note for note in notes)


def test_multiple_service_dates_do_not_create_one_overall_date(source):
    _, prepared, found = source
    found.services[1]['service_date'] = '2024-07-04'
    claim = candidate()
    claim['line_items'][1]['service_date'] = '2024-07-04'
    clean, _, _ = reconcile_statement(claim, found, prepared.parsed['text'])
    assert clean['date_of_service'] is None


def test_adjustments_are_not_inferred_when_printed_total_disagrees(source):
    _, prepared, found = source
    found.adjustments[0]['amount'] = -1
    clean, _, notes = reconcile_statement(candidate(), found, prepared.parsed['text'])
    assert clean['adjustments'] == [] and clean['total_paid'] is None
    assert any('do not reconcile' in note for note in notes)


def test_old_records_and_missing_new_fields_remain_valid():
    clean = app.ClaimDocsClaim.model_validate({'line_items': [{'charged_amount': 12}]}).model_dump()
    assert clean['visit_id'] is None and clean['adjustments'] == []
    assert clean['line_items'][0]['diagnosis_codes'] == []
    assert clean['line_items'][0]['quantity'] is None


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf')])
def test_invalid_quantities_fail_schema_validation(value):
    with pytest.raises(ValidationError):
        app.ClaimDocsLineItem(quantity=value)


def test_adjustments_accept_signed_amounts_but_reject_nonfinite_values():
    assert app.ClaimDocsAdjustment(amount=-55.44).amount == -55.44
    with pytest.raises(ValidationError):
        app.ClaimDocsAdjustment(amount=float('nan'))
    claim = candidate()
    claim.update(adjustments=[{'amount': -10}], total_adjustments=-20, visit_balance=538.56)
    assert any(row['Check'] == 'Adjustments' and row['Level'] == 'Error' for row in app.findings(claim))
    assert any(row['Check'] == 'Visit balance' for row in app.findings(claim))


def test_actual_pipeline_repairs_the_reported_statement_failure(source, fake_groq):
    path, _, _ = source
    result = app.extract_claim(path.read_bytes(), path.name, 'offline-test-key', 'openai/gpt-oss-20b')
    clean = result['current']
    assert clean['claim_number'] is None and clean['visit_id'] == 'DEMO-V100'
    assert clean['diagnosis_codes'] == ['I10'] and clean['line_items'][0]['revenue_code'] == '261'
    assert clean['total_paid'] is None and clean['visit_balance'] == 538.56
    assert clean['total_patient_responsibility'] is None
    assert sum(a['amount'] for a in clean['adjustments']) == -73.44
    assert result['model_extraction']['claim_number'] == 'DEMO-V100'
    assert result['model_extraction']['diagnosis_codes'] == ['261', 'I10']
    assert result['source_statement_checks'] and 1 <= len(fake_groq) <= 2
    request = next(m.content for req in fake_groq for m in req.messages if m.content.startswith('Extract data'))
    assert request.index('<document>') < request.index('Named native statement cells') < request.rindex('</document>')


def test_review_save_keeps_new_fields_and_does_not_call_groq_again(source, fake_groq):
    from streamlit.testing.v1 import AppTest
    path, _, _ = source
    result = app.extract_claim(path.read_bytes(), path.name, 'offline-test-key', 'openai/gpt-oss-20b')
    result['filename'] = 'synthetic_medical_claim.txt'
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=30)
    at.session_state['source_id'] = hashlib.sha256(app.SAMPLE.encode() + result['filename'].encode()).hexdigest()
    at.session_state['claim_result'] = result
    at.run()
    assert not at.exception
    assert next(t for t in at.text_input if t.label == 'Visit ID').value == 'DEMO-V100'
    before = len(fake_groq)
    next(b for b in at.button if b.label == 'Save reviewed record').click().run()
    assert not at.exception
    saved = at.session_state['claim_result']['current']
    assert saved['line_items'][1]['ndc_code'] == '296165'
    assert saved['line_items'][1]['diagnosis_codes'] == ['I10']
    assert saved['line_items'][0]['diagnosis_codes'] == []
    assert saved['adjustments'][0]['amount'] == -55.44
    assert at.session_state['claim_result']['reviewed'] and len(fake_groq) == before
    assert len(at.get('download_button')) == 2
