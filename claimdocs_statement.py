"""Source-backed statement fields, separate from insurance adjudication.

Only native PDF grids with explicit headers and aligned currency anchors are
used for deterministic service checks. Unsupported layouts remain reviewable
model candidates. No network requests or payer-rule inference happen here.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from claimdocs_eob import _date, _key, _money

HEADERS = {
    'service_date': {'dateofservice', 'servicedate'},
    'service_code': {'procedurecode', 'cptcode', 'hcpcscode'},
    'description': {'proceduredescription', 'servicedescription', 'description'},
    'charged_amount': {'chargeamt', 'chargeamount', 'chargedamount', 'billedamount'},
    'revenue_code': {'revcode', 'revenuecode'},
    'ndc_code': {'ndccode', 'ndc'},
    'diagnosis_codes': {'dxcode', 'diagnosiscode'},
    'quantity': {'qty', 'quantity', 'units'},
}
ID_HEADERS = {'visitid': 'visit_id', 'accountnumber': 'account_number', 'accountno': 'account_number',
              'claimnumber': 'claim_number', 'claimid': 'claim_number', 'visitbalance': 'visit_balance'}


@dataclass
class StatementSource:
    facts: list[dict] = field(default_factory=list)
    services: list[dict] = field(default_factory=list)
    adjustments: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _one_value(source, name):
    values = [entry['value'] for entry in source.facts if entry['field'] == name]
    distinct = {json.dumps(value, sort_keys=True) for value in values}
    return values[0] if len(distinct) == 1 else None


def _column_text(page, box, top, bottom):
    if box is None:
        return ''
    words = page.crop(box).extract_words()
    return ' '.join(word['text'] for word in words if top <= (word['top'] + word['bottom']) / 2 < bottom)


def _aligned_rows(page, table, header_index, columns, amount_field):
    """Currency cell baselines define row bands; require matching date/code.

    Never zip newline-delimited cells: a blank diagnosis/NDC cell would shift
    all later codes. Coordinates preserve those blanks instead.
    """
    output = []
    for row_index in range(header_index + 1, len(table.rows)):
        cells = table.rows[row_index].cells
        if len(cells) <= max(columns.values()) or cells[columns[amount_field]] is None:
            continue
        box = cells[columns[amount_field]]
        anchors = page.crop(box).extract_words()
        if any(not re.fullmatch(r'-?\$[\d,]+\.\d{2}', word['text']) for word in anchors):
            return []
        for index, anchor in enumerate(anchors):
            baseline = (anchor['top'] + anchor['bottom']) / 2
            # Description may wrap until the next amount baseline; codes,
            # dates and quantities must align with this amount's baseline.
            next_top = anchors[index + 1]['top'] if index + 1 < len(anchors) else box[3]
            values = {}
            for name, column in columns.items():
                tolerance = max(3, (anchor['bottom'] - anchor['top']) / 2 + 1)
                top, bottom = baseline - tolerance, baseline + tolerance
                if name == 'description':
                    top, bottom = anchor['top'] - 1, next_top - 1
                values[name] = _column_text(page, cells[column], top, bottom)
            try:
                values[amount_field] = _money(anchor['text'])
                values['service_date'] = _date(values.get('service_date'))
                if not values['service_date'] or not values.get('description'):
                    return []
                if amount_field == 'charged_amount':
                    if not re.fullmatch(r'[A-Za-z0-9]+', values.get('service_code', '')):
                        return []
                    for name in ('revenue_code', 'ndc_code'):
                        if name in columns:
                            values[name] = values.get(name) or None
                    if 'diagnosis_codes' in columns:
                        diagnosis = values.get('diagnosis_codes', '')
                        values['diagnosis_codes'] = [code for code in re.split(r'[,;\s]+', diagnosis) if code]
                    if 'quantity' in columns:
                        quantity = values.get('quantity', '')
                        values['quantity'] = _money(quantity) if quantity else None
                values['source'] = {'page': page.page_number, 'row': row_index + 1,
                                    'bbox': list(box), 'amount_baseline': baseline}
                output.append(values)
            except ValueError:
                # Keep malformed/unclear rows out of automatic reconciliation.
                return []
    return output


def read_statement_source(path, prepared):
    source = StatementSource()
    # These table values retain their header boundaries even where plain text
    # places identifiers on the following line or mixes them with addresses.
    for number, table in enumerate(prepared.parsed.get('tables', []), 1):
        rows = table.get('rows') or []
        for header_index, header in enumerate(rows):
            names = [_key(cell) for cell in header]
            for row_index, row in enumerate(rows[header_index + 1:], header_index + 2):
                if len(row) != len(header):
                    continue
                for index, name in enumerate(names):
                    if name not in ID_HEADERS or names.count(name) != 1:
                        continue
                    text = ' '.join(str(row[index] or '').split())
                    try:
                        value = _money(text) if name == 'visitbalance' else text
                    except ValueError:
                        continue
                    if value not in ('', None) and (name == 'visitbalance' or re.fullmatch(r'[A-Za-z0-9_-]+', text)):
                        source.facts.append({'field': ID_HEADERS[name], 'value': value,
                            'page': table.get('page'), 'table': number, 'row': row_index, 'column': str(header[index])})
    text = prepared.parsed['text']
    # Only literal labels are recognised, never a generic number elsewhere.
    for match in re.finditer(r'\b(?:for\s+account|account\s+(?:number|no\.?))\s*[:#]?\s*(\d{4,})\b', text, re.I):
        source.facts.append({'field': 'account_number', 'value': match[1], 'source_label': match[0]})
    for line in text.splitlines():
        match = re.fullmatch(r'\s*(Total\s+(?:professional\s+)?(?:payments\s+and\s+adjustments|adjustments|discounts))\s*:\s*(-?\$[\d,]+\.\d{2})\s*', line, re.I)
        if match:
            source.facts.append({'field': 'total_adjustments', 'value': _money(match[2]), 'source_label': match[1]})
    if Path(path).suffix.lower() != '.pdf':
        return source
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            if prepared.methods.get(page.page_number) != 'pdf-text':
                continue
            for number, table in enumerate(page.find_tables(), 1):
                rows = table.extract()
                for header_index, header in enumerate(rows):
                    columns = {}
                    duplicate = False
                    for index, cell in enumerate(header):
                        for name, aliases in HEADERS.items():
                            if _key(cell) in aliases:
                                if name in columns:
                                    duplicate = True
                                columns[name] = index
                    if duplicate:
                        continue
                    required = {'service_date', 'service_code', 'charged_amount', 'description'}
                    if required.issubset(columns):
                        records = _aligned_rows(page, table, header_index, columns, 'charged_amount')
                        for record in records:
                            record['source']['table'] = number
                        source.services.extend(records)
                        break
                    names = [_key(cell) for cell in header]
                    if names == ['date', 'description', 'amount']:
                        records = _aligned_rows(page, table, header_index,
                            {'service_date': 0, 'description': 1, 'amount': 2}, 'amount')
                        for record in records:
                            record['source']['table'] = number
                            record['date'] = record.pop('service_date')
                        source.adjustments.extend(records)
                        break
    return source


def statement_context(source):
    if not any((source.facts, source.services, source.adjustments)):
        return ''
    return '\n\nNamed native statement cells (source data, not extra services):\n' + json.dumps({
        'labelled_fields': source.facts, 'service_rows': source.services,
        'payments_and_adjustments': source.adjustments}, ensure_ascii=False)


def reconcile_statement(claim, source, original_text):
    clean = copy.deepcopy(claim)
    checks, notes = [], list(source.notes)

    def set_value(target, name, value, field_path, evidence):
        checks.append({'field': field_path, 'model_value': target.get(name), 'source_value': value,
                       'changed': target.get(name) != value, 'source': evidence})
        target[name] = value

    for name in ('visit_id', 'account_number', 'visit_balance', 'total_adjustments'):
        value = _one_value(source, name)
        if value is not None:
            set_value(clean, name, value, name, [e for e in source.facts if e['field'] == name])
    # The same number can legitimately be both a visit and a claim number.
    # Clear a mislabel only when no explicit Claim Number/ID label is present.
    explicit_claim = re.search(r'\bclaim\s*(?:number|no\.?|id)\b|\bclaim\s*#', original_text, re.I)
    if not explicit_claim and clean.get('claim_number') and clean['claim_number'] in {clean.get('visit_id'), clean.get('account_number')}:
        set_value(clean, 'claim_number', None, 'claim_number', 'Source labels this identifier as Visit ID/account, not claim number.')
    balance = _one_value(source, 'visit_balance')
    explicit_owed = re.search(r'patient\s+(?:responsibility|balance|amount\s+due)|what\s+you\s+owe|amount\s+(?:you\s+)?owe|balance\s+due|amount\s+due', original_text, re.I)
    if balance is not None and not explicit_owed and clean.get('total_patient_responsibility') == balance:
        set_value(clean, 'total_patient_responsibility', None, 'total_patient_responsibility',
                  'Printed Visit Balance is kept separately; no patient-responsibility label was found.')
    lines = clean.get('line_items') or []
    matches = []
    if source.services and len(source.services) == len(lines):
        for line in lines:
            hits = [row for row in source.services if row['service_code'] == line.get('service_code')
                    and row['charged_amount'] == line.get('charged_amount')
                    and (not line.get('service_date') or row['service_date'] == line['service_date'])]
            if len(hits) != 1:
                break
            matches.append(hits[0])
    if matches and len(matches) == len(lines) and len({id(row) for row in matches}) == len(matches):
        for index, (line, row) in enumerate(zip(lines, matches, strict=True)):
            for name in ('service_date', 'revenue_code', 'ndc_code', 'quantity', 'diagnosis_codes'):
                # Only copy a field when its column actually exists. An absent
                # column isn't proof that the model's value is unsupported.
                if name in row:
                    set_value(line, name, row[name], f'line_items.{index}.{name}', row['source'])
        dates = {row['service_date'] for row in matches}
        set_value(clean, 'date_of_service', next(iter(dates)) if len(dates) == 1 else None,
                  'date_of_service', 'Dates on all uniquely matched native service rows.')
        if all('diagnosis_codes' in row for row in matches):
            diagnoses = list(dict.fromkeys(code for row in matches for code in row['diagnosis_codes']))
            set_value(clean, 'diagnosis_codes', diagnoses, 'diagnosis_codes',
                      'Dx Code cells on every uniquely matched native service row; revenue codes excluded.')
    elif source.services:
        notes.append('Native statement services did not match uniquely; review service dates, diagnosis/revenue/NDC codes and quantities against the PDF.')
    # Use a complete adjustment list only when its sum equals the explicit
    # printed adjustment total. Discounts never populate insurer-paid fields.
    total = _one_value(source, 'total_adjustments')
    if source.adjustments and total is not None:
        from decimal import Decimal
        summed = sum(Decimal(str(row['amount'])) for row in source.adjustments)
        if summed == Decimal(str(total)):
            adjustments = [{key: row[key] for key in ('date', 'description', 'amount')} for row in source.adjustments]
            set_value(clean, 'adjustments', adjustments, 'adjustments', [row['source'] for row in source.adjustments])
        else:
            notes.append('Native adjustment rows do not reconcile to the printed total; review discounts and payments separately.')
    if checks:
        notes.append('Statement fields were checked against labelled native PDF cells. Visit balances and discounts are separate from insurer payments; source checks and original model values are retained in JSON.')
    return clean, checks, notes
