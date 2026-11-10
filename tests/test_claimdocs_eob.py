"""Offline EOB financial-column regressions, including the CMS sample layout.

Fixtures reproduce a fictional two-service table, not real patient records.
All model responses are mocked; no API calls or credentials are needed.
"""
from __future__ import annotations

import copy
import json
import socket
from pathlib import Path

import pytest
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

import app
from claimdocs_eob import _money, read_eob_tables, reconcile_eob, table_context
from claimdocs_ocr import prepare_document

HEADERS = ['Line\nNo.', 'Date of\nService', '3\nService\nDescrip-\ntion', 'Claim\nStatus',
           '4\nProvider\nCharges', '5\nAllowed\nCharges', 'Co\nPay', 'Deduct-\nible',
           'Coinsurance', '6\nPaid by\nInsurer', '7\nWhat\nYou\nOwe', '8\nRemark\nCode']
ROWS = [
    ['1', '3/20/22-\n3/20/22', 'Medical\ncare', 'Paid', '$31.60', '$2.15', '$0.00', '$0.00', '$0.00', '$2.15', '$0.00', 'PDC'],
    ['2', '3/20/22-\n3/20/22', 'Medical\ncare', 'Paid', '$375.00', '$118.12', '$35.00', '$0.00', '$0.00', '$83.12', '$35.00', 'PDC'],
    ['', '', '', 'Total', '$406.60', '$120.27', '$35.00', '$0.00', '$0.00', '$85.27', '$35.00', ''],
]
WRONG = {'claim_number': 'DEMO-EOB-1', 'patient_name': 'Fictional Patient',
         'provider_name': None, 'line_items': [
             {'description': 'Medical Care', 'service_date': '2022-03-20', 'charged_amount': 31.6,
              'allowed_amount': 2.15, 'paid_amount': 0, 'patient_responsibility': 0},
             {'description': 'Medical Care', 'service_date': '2022-03-20', 'charged_amount': 375,
              'allowed_amount': 118.12, 'paid_amount': 0, 'patient_responsibility': 0}],
         'total_charged': 406.6, 'total_allowed': 120.27, 'total_paid': 0,
         'total_patient_responsibility': 0}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('EOB verification must not open external sockets')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setenv('GROQ_API_KEY', 'offline-test-key')


def parsed(rows=None, headers=None):
    return {'tables': [{'page': 1, 'rows': [[None] * 12, headers or HEADERS, *(ROWS if rows is None else rows)]}]}


def synthetic_pdf(path):
    table = Table([HEADERS, *ROWS], colWidths=[30, 70, 75, 45, 65, 65, 45, 50, 65, 65, 50, 45])
    table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                               ('FONTSIZE', (0, 0), (-1, -1), 8),
                               ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=20, rightMargin=20).build([table])
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
        return json.dumps(WRONG)
    monkeypatch.setattr(OpenAICompatBackend, 'complete', complete)
    import tiktoken
    encoding = tiktoken.Encoding(name='offline-test-bytes', pat_str=r'(?s).',
        mergeable_ranks={bytes([i]): i for i in range(256)}, special_tokens={})
    monkeypatch.setattr(tiktoken, 'get_encoding', lambda name: encoding)
    return calls


def test_headers_map_correct_cells_instead_of_adjacent_zero_columns():
    table = read_eob_tables(parsed())[0]
    assert [(r['paid_amount'], r['patient_responsibility']) for r in table.rows] == [(2.15, 0), (83.12, 35)]
    assert table.totals[0]['paid_amount'] == 85.27
    assert table.totals[0]['patient_responsibility'] == 35
    assert table.rows[0]['service_date'] == '2022-03-20'
    context = table_context([table])
    assert '"paid_amount": 83.12' in context and 'printed_total_rows' in context


def test_reconciliation_retains_model_values_and_explicit_real_zero():
    before = copy.deepcopy(WRONG)
    clean, evidence, notes = reconcile_eob(WRONG, read_eob_tables(parsed()))
    assert before == WRONG
    assert [r['paid_amount'] for r in clean['line_items']] == [2.15, 83.12]
    assert [r['patient_responsibility'] for r in clean['line_items']] == [0, 35]
    assert clean['total_paid'] == 85.27 and clean['total_patient_responsibility'] == 35
    check = next(e for e in evidence if e['field'] == 'line_items.1.paid_amount')
    assert check['model_value'] == 0 and check['source_value'] == 83.12
    assert check['page'] == 1 and check['row'] == 4 and check['column'] == '6 Paid by Insurer'
    assert 'corrected 5 model value(s)' in notes[0]
    assert not any(r['Level'] == 'Error' for r in app.findings(clean))


def test_column_order_does_not_determine_mapping():
    order = [0, 1, 2, 3, 9, 10, 8, 7, 6, 5, 4, 11]
    shuffled = [[r[i] for i in order] for r in [HEADERS, *ROWS]]
    table = read_eob_tables({'tables': [{'page': 7, 'rows': shuffled}]})[0]
    assert table.rows[1]['paid_amount'] == 83.12
    assert table.rows[1]['patient_responsibility'] == 35
    assert table.page == 7


@pytest.mark.parametrize('change', ['missing_header', 'duplicate_header', 'bad_money', 'unequal_row'])
def test_ambiguous_or_malformed_table_is_not_used(change):
    data = parsed(rows=copy.deepcopy(ROWS), headers=HEADERS.copy())
    rows = data['tables'][0]['rows']
    if change == 'missing_header':
        rows[1][9] = 'Unlabelled amount'
    elif change == 'duplicate_header':
        rows[1][7] = rows[1][9]
    elif change == 'bad_money':
        rows[3][9] = '$83.I2'
    else:
        rows[3].pop()
    assert read_eob_tables(data) == []
    assert reconcile_eob(WRONG, [])[0] == WRONG


@pytest.mark.parametrize('change', ['extra_line', 'missing_line', 'different_charge', 'different_date', 'duplicate_rows', 'multiple_tables'])
def test_no_unique_full_row_match_does_not_override_model(change):
    claim = copy.deepcopy(WRONG)
    tables = read_eob_tables(parsed())
    if change == 'extra_line':
        claim['line_items'].append(copy.deepcopy(claim['line_items'][0]))
    elif change == 'missing_line':
        claim['line_items'].pop()
    elif change == 'different_charge':
        claim['line_items'][0]['charged_amount'] = 99
    elif change == 'different_date':
        claim['line_items'][0]['service_date'] = '2022-03-21'
    elif change == 'duplicate_rows':
        tables[0].rows[1] = copy.deepcopy(tables[0].rows[0])
        tables[0].rows[1]['row'] = 4
        claim['line_items'][1] = copy.deepcopy(claim['line_items'][0])
    else:
        tables.append(copy.deepcopy(tables[0]))
    clean, evidence, notes = reconcile_eob(claim, tables)
    assert clean == claim and evidence == []
    assert 'could not be matched uniquely' in notes[0]


def test_blank_payment_is_unknown_and_totals_are_not_inferred():
    rows = copy.deepcopy(ROWS[:2])
    rows[0][9] = ''
    clean, evidence, _ = reconcile_eob(WRONG, read_eob_tables(parsed(rows)))
    assert clean['line_items'][0]['paid_amount'] is None
    assert clean['line_items'][1]['paid_amount'] == 83.12
    # No printed total row: leave the model total as a candidate and flag its
    # incomplete line reconciliation rather than derive an invented total.
    assert clean['total_paid'] == 0
    assert not any(e['field'] == 'total_paid' for e in evidence)
    assert any(r['Check'] == 'Paid total' and r['Level'] == 'Review' for r in app.findings(clean))


@pytest.mark.parametrize('field,total,label', [('paid_amount', 'total_paid', 'Paid total'),
    ('patient_responsibility', 'total_patient_responsibility', 'Patient responsibility total'),
    ('allowed_amount', 'total_allowed', 'Allowed total')])
def test_each_financial_total_is_checked(field, total, label):
    claim = copy.deepcopy(WRONG)
    claim[total] = 90
    for item in claim['line_items']:
        item[field] = 0
    assert any(r['Level'] == 'Error' and r['Check'] == label for r in app.findings(claim))


@pytest.mark.parametrize('value,expected', [('0', 0), (0, 0), ('$0.00', 0), ('', None), (None, None), ('$1,234.56', 1234.56)])
def test_money_distinguishes_printed_zero_and_blank(value, expected):
    assert _money(value) == expected


def test_native_pdf_pipeline_corrects_the_reported_zero_payment_failure(tmp_path, fake_groq):
    path = synthetic_pdf(tmp_path / 'synthetic_eob.pdf')
    result = app.extract_claim(path.read_bytes(), path.name, 'offline-test-key', 'openai/gpt-oss-20b')
    claim = result['current']
    assert claim['total_charged'] == 406.6 and claim['total_allowed'] == 120.27
    assert claim['total_paid'] == 85.27 and claim['total_patient_responsibility'] == 35
    assert claim['line_items'][0]['paid_amount'] == 2.15
    assert claim['line_items'][1]['paid_amount'] == 83.12
    assert claim['line_items'][1]['patient_responsibility'] == 35
    assert len(claim['line_items']) == 2
    assert result['model_extraction']['line_items'][1]['paid_amount'] == 0
    assert result['source_amount_checks'] and result['report']['reconciled_extraction'] == claim
    assert result['input_processing']['ocr_engine'] is None
    extracting = [m.content for req in fake_groq for m in req.messages if m.content.startswith('Extract data')]
    assert len(extracting) == 1 and 'Native PDF EOB table cells' in extracting[0]
    assert extracting[0].index('<document>') < extracting[0].index('Native PDF EOB table cells') < extracting[0].rindex('</document>')
    assert len(fake_groq) == 2  # Same classify + extract path; no reconciliation API call.


def test_native_pdf_parser_finds_the_recreated_multiline_headers(tmp_path):
    prepared = prepare_document(synthetic_pdf(tmp_path / 'synthetic_eob.pdf'))
    table = read_eob_tables(prepared.parsed)[0]
    assert table.rows[1]['paid_amount'] == 83.12
    assert table.totals[0]['charged_amount'] == 406.6


def test_review_and_exports_preserve_source_checks_without_more_model_calls(tmp_path, fake_groq):
    from streamlit.testing.v1 import AppTest
    path = synthetic_pdf(tmp_path / 'synthetic_eob.pdf')
    result = app.extract_claim(path.read_bytes(), path.name, 'offline-test-key', 'openai/gpt-oss-20b')
    # Reuse the built-in source fingerprint solely to render this prepared
    # result in AppTest, whose file-uploader interaction is not supported.
    import hashlib
    result['filename'] = 'synthetic_medical_claim.txt'
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=30)
    at.session_state['source_id'] = hashlib.sha256(app.SAMPLE.encode() + result['filename'].encode()).hexdigest()
    at.session_state['claim_result'] = result
    at.run()
    assert not at.exception
    assert any('Paid by insurer: $85.27' in c.value for c in at.caption)
    assert next(n for n in at.number_input if n.label == 'Total paid by insurer (USD)').value == 85.27
    calls = len(fake_groq)
    next(n for n in at.number_input if n.label == 'Total paid by insurer (USD)').set_value(84)
    next(b for b in at.button if b.label == 'Save reviewed record').click().run()
    assert not at.exception and at.session_state['claim_result']['reviewed']
    assert at.session_state['claim_result']['current']['total_paid'] == 84
    assert at.session_state['claim_result']['model_extraction']['total_paid'] == 0
    assert at.session_state['claim_result']['source_amount_checks'] == result['source_amount_checks']
    assert len(fake_groq) == calls and len(at.get('download_button')) == 2
