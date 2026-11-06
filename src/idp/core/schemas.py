# py-idp: general-purpose, AI-enabled Intelligent Document Processing.
# Copyright (c) 2026 Royce.
#
# Licensed under the GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)
# with the following addition: a commercial license is also available for organizations
# that wish to embed py-idp in proprietary products / hosted SaaS without the AGPL
# copyleft obligations. See LICENSE and LICENSE-COMMERCIAL at the repo root, or
# contact <roycelam@umich.edu> for terms.
#
# This Source Code Form is subject to the terms of the AGPL-3.0-or-later.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Built-in example schemas that ship with py-idp.

Users can supply their own Pydantic models; these are reference implementations.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class LineItem(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float
    total: float


class Invoice(BaseModel):
    """Standard invoice extraction schema.

    Minimal required fields chosen from real-world IDP requirements:
    an invoice that lacks an ID, vendor identity, or a total isn't an
    invoice we can route or pay. Everything else is optional because
    partial extractions from weaker LLMs are still useful.
    """

    # --- required for a usable invoice ---
    invoice_number: str
    vendor_name: str
    total_amount: float
    # --- everything else stays optional (partial extraction is fine) ---
    invoice_date: str | None = None
    due_date: str | None = None
    vendor_address: str | None = None
    customer_name: str | None = None
    customer_address: str | None = None
    subtotal: float | None = None
    tax_amount: float | None = None
    currency: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)


class ContractParty(BaseModel):
    name: str
    role: str | None = None  # e.g., "Licensor", "Licensee"


class Contract(BaseModel):
    """Basic contract extraction schema.

    Title is required: a contract without a title is unidentifiable.
    Parties and effective dates are optional — partial extraction still
    surfaces what was found for downstream HITL review.
    """

    title: str
    effective_date: str | None = None
    expiration_date: str | None = None
    parties: list[ContractParty] = Field(default_factory=list)
    governing_law: str | None = None
    total_value: float | None = None
    currency: str | None = None
    key_obligations: list[str] = Field(default_factory=list)


class BankTransaction(BaseModel):
    date: str
    description: str
    amount: float
    balance: float | None = None


class BankStatement(BaseModel):
    """Bank statement extraction schema.

    Account holder is required — a statement without an identified
    account holder is unactionable. Transactions and balances are
    optional and may be partially extracted.
    """

    account_holder: str
    account_number_last4: str | None = None
    statement_period_start: str | None = None
    statement_period_end: str | None = None
    opening_balance: float | None = None
    closing_balance: float | None = None
    transactions: list[BankTransaction] = Field(default_factory=list)


class ReceiptLineItem(BaseModel):
    """One line on a receipt (CORD-style)."""

    description: str
    quantity: float = 1.0
    unit_price: float
    total: float


class Receipt(BaseModel):
    """Receipt extraction schema (CORD: Consolidated Receipt Dataset shape).

    `merchant_name` is required (a receipt without an identified merchant
    is unactionable). Other fields are optional and may be partially
    extracted — handwritten or faded receipts often miss subtotals, tips,
    or tax.
    """

    merchant_name: str
    date: str | None = None
    time: str | None = None
    line_items: list[ReceiptLineItem] = Field(default_factory=list)
    subtotal: float | None = None
    tax_amount: float | None = None
    tip_amount: float | None = None
    total: float | None = None
    payment_method: str | None = None
    credit_card_last4: str | None = None


class W2LineItem(BaseModel):
    description: str
    amount: float


class W2(BaseModel):
    """W-2 wage and tax statement (US IRS)."""
    employee_name: str
    employee_ssn_last4: str | None = None
    employer_name: str
    employer_ein: str | None = None
    tax_year: int | None = None
    wages_tips_compensation: float | None = None
    federal_income_tax_withheld: float | None = None
    social_security_wages: float | None = None
    social_security_tax_withheld: float | None = None
    medicare_wages: float | None = None
    medicare_tax_withheld: float | None = None


class IDCard(BaseModel):
    """Generic ID card or driver's license extraction."""
    document_type: str  # e.g. "Driver's License", "Passport", "State ID"
    full_name: str
    date_of_birth: str | None = None
    sex: str | None = None
    id_number: str | None = None  # license #, passport #, etc.
    issuing_authority: str | None = None  # e.g. "California DMV", "US State Department"
    issue_date: str | None = None
    expiration_date: str | None = None
    address: str | None = None
    nationality: str | None = None


class MedicalClaimLineItem(BaseModel):
    service_code: str | None = None  # CPT/HCPCS code
    description: str
    service_date: str | None = None
    charged_amount: float
    allowed_amount: float | None = None
    paid_amount: float | None = None
    patient_responsibility: float | None = None


class MedicalClaim(BaseModel):
    """Medical insurance claim (CMS-1500 / UB-04 style)."""
    claim_number: str | None = None
    patient_name: str
    patient_dob: str | None = None
    patient_member_id: str | None = None
    insurer_name: str | None = None
    provider_name: str
    provider_npi: str | None = None
    date_of_service: str | None = None
    diagnosis_codes: list[str] = Field(default_factory=list)  # ICD-10
    line_items: list[MedicalClaimLineItem] = Field(default_factory=list)
    total_charged: float | None = None
    total_allowed: float | None = None
    total_paid: float | None = None
    total_patient_responsibility: float | None = None

    @field_validator("diagnosis_codes", mode="before")
    @classmethod
    def normalize_missing_diagnosis_codes(cls, value):
        """Missing extracted codes become an empty list."""
        return [] if value is None else value


SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {
    "Invoice": Invoice,
    "Contract": Contract,
    "BankStatement": BankStatement,
    "Receipt": Receipt,
    "W2": W2,
    "IDCard": IDCard,
    "MedicalClaim": MedicalClaim,
}


def get_schema(name: str) -> type[BaseModel]:
    if name not in SCHEMA_REGISTRY:
        raise KeyError(
            f"Unknown schema '{name}'. Available: {list(SCHEMA_REGISTRY)} "
            "or pass your own Pydantic model to extract()."
        )
    return SCHEMA_REGISTRY[name]
