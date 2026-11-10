"""Preserve EOB column boundaries and reconcile only unambiguous native tables.

This is source transcription, not payer adjudication. No amounts are inferred
from arithmetic or from OCR text whose table structure is unavailable.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

AMOUNTS = ('charged_amount', 'allowed_amount', 'paid_amount', 'patient_responsibility')
TOTALS = dict(zip(AMOUNTS, ('total_charged', 'total_allowed', 'total_paid', 'total_patient_responsibility'), strict=True))
ALIASES = {
    'description': {'servicedescription', 'description', 'typeofservice'},
    'service_date': {'dateofservice', 'servicedate'},
    'charged_amount': {'providercharges', 'billedcharges', 'billedamount', 'chargedamount'},
    'allowed_amount': {'allowedcharges', 'allowedamount'},
    'paid_amount': {'paidbyinsurer', 'paidbyinsurance', 'planpaid', 'planliability', 'paidamount'},
    'patient_responsibility': {'whatyouowe', 'youowe', 'patientresponsibility'},
}


def _key(value):
    return re.sub(r'[^a-z]', '', str(value or '').lower())


def _money(value):
    """Blank stays unknown; accept a single printed currency amount only."""
    text = re.sub(r'\s+', '', '' if value is None else str(value)).replace('$', '')
    if not text:
        return None
    if not re.fullmatch(r'-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?', text):
        raise ValueError('Ambiguous amount cell')
    return float(Decimal(text.replace(',', '')))


def _date(value):
    text = re.sub(r'\s+', '', str(value or ''))
    # A same-day service range represents one date. Multi-day ranges remain
    # unknown; never choose an endpoint as if the range were a single date.
    parts = text.split('-') if '/' in text else [text]
    dates = []
    for part in parts:
        for fmt in ('%m/%d/%y', '%m/%d/%Y', '%Y-%m-%d'):
            try:
                dates.append(datetime.strptime(part, fmt).date().isoformat())
                break
            except ValueError:
                continue
        else:
            return None
    return dates[0] if dates and len(set(dates)) == 1 else None


@dataclass
class EOBTable:
    page: int
    table: int
    columns: dict
    rows: list[dict]
    totals: list[dict]


def read_eob_tables(parsed):
    """Require explicit, unique headers for every financial column and service.

    Merged group headings are ignored. No column-position assumptions or sample
    amounts are used. An incomplete/malformed data row rejects the table.
    """
    found = []
    for number, table in enumerate(parsed.get('tables', []), 1):
        raw_rows = table.get('rows') or []
        for header_index, header in enumerate(raw_rows):
            columns = {}
            duplicate = False
            for index, cell in enumerate(header):
                for field, aliases in ALIASES.items():
                    if _key(cell) in aliases:
                        duplicate |= field in columns
                        columns[field] = index
            if duplicate or not set((*AMOUNTS, 'description')).issubset(columns):
                continue
            rows, totals = [], []
            valid = True
            for row_index, raw in enumerate(raw_rows[header_index + 1:], header_index + 2):
                if not any(str(cell or '').strip() for cell in raw):
                    continue
                if len(raw) != len(header):
                    valid = False
                    break
                # Ignore a repeated identical header, e.g. continuation tables.
                if [_key(v) for v in raw] == [_key(v) for v in header]:
                    continue
                try:
                    values = {field: _money(raw[columns[field]]) for field in AMOUNTS}
                except (ValueError, InvalidOperation):
                    valid = False
                    break
                if all(value is None for value in values.values()):
                    valid = False
                    break
                is_total = any(_key(cell) in {'total', 'grandtotal', 'claimtotal'}
                               for index, cell in enumerate(raw) if index not in [columns[f] for f in AMOUNTS])
                description = ' '.join(str(raw[columns['description']] or '').split())
                record = {'row': row_index, 'description': description,
                          'service_date': _date(raw[columns['service_date']]) if 'service_date' in columns else None,
                          **values}
                if is_total:
                    totals.append(record)
                elif description and values['charged_amount'] is not None:
                    rows.append(record)
                else:
                    valid = False
                    break
            if valid and rows:
                found.append(EOBTable(table.get('page'), number,
                    {field: ' '.join(str(header[index]).split()) for field, index in columns.items()}, rows, totals))
            break
    return found


def table_context(tables):
    """Named source cells stay inside the existing untrusted document boundary."""
    if not tables:
        return ''
    content = [{'page': t.page, 'table': t.table, 'printed_columns': t.columns,
                'service_rows': t.rows, 'printed_total_rows': t.totals} for t in tables]
    return '\n\nNative PDF EOB table cells (source data; not extra service rows):\n' + json.dumps(content, ensure_ascii=False)


def reconcile_eob(claim, tables):
    """Copy printed amounts only after a unique, complete one-to-one row match.

    Match description + charge, and service date when both are known. Multiple
    candidate tables, duplicate indistinguishable rows, omitted/extra services
    or malformed cells never trigger automatic replacement. Evidence records
    both the model value and the printed cell; users still review the source.
    """
    clean = copy.deepcopy(claim)
    lines = clean.get('line_items') or []
    candidates = []
    for table in tables:
        if len(table.rows) != len(lines) or not lines:
            continue
        matched = []
        for line in lines:
            hits = [row for row in table.rows
                    if _key(row['description']) == _key(line.get('description'))
                    and row['charged_amount'] == line.get('charged_amount')
                    and not (row['service_date'] and line.get('service_date')
                             and row['service_date'] != line['service_date'])]
            if len(hits) != 1:
                break
            matched.append(hits[0])
        if len(matched) == len(lines) and len({row['row'] for row in matched}) == len(lines):
            candidates.append((table, matched))
    if len(candidates) != 1:
        notes = ['EOB table amounts could not be matched uniquely to every extracted service row. Compare all payment and patient-responsibility amounts with the original PDF.'] if tables else []
        return clean, [], notes
    table, matched = candidates[0]
    evidence = []
    for index, (line, row) in enumerate(zip(lines, matched, strict=True)):
        for field in AMOUNTS:
            value = row[field]
            evidence.append({'field': f'line_items.{index}.{field}', 'page': table.page,
                             'table': table.table, 'row': row['row'], 'column': table.columns[field],
                             'model_value': line.get(field), 'source_value': value,
                             'changed': line.get(field) != value})
            line[field] = value
    # A printed total is never manufactured by summing service rows. Totals
    # are used only when a single matching table and a single total row exist.
    if len(table.totals) == 1:
        row = table.totals[0]
        for field, total_field in TOTALS.items():
            evidence.append({'field': total_field, 'page': table.page, 'table': table.table,
                             'row': row['row'], 'column': table.columns[field],
                             'model_value': clean.get(total_field), 'source_value': row[field],
                             'changed': clean.get(total_field) != row[field]})
            clean[total_field] = row[field]
    changes = sum(entry['changed'] for entry in evidence)
    note = f'Checked EOB amounts against named native PDF table cells; corrected {changes} model value(s). Original model values and source-cell locations are retained in the JSON export. Human source review is still required.'
    notes = [note]
    if len(table.totals) > 1:
        notes.append('Multiple printed EOB total rows were found; totals were not automatically replaced. Compare each claim total with the source.')
    return clean, evidence, notes
