"""Data shapes shared by every stage of the pipeline.

QuoteRequest is what the AI (or a human, or a JSON file) produces: raw facts from the email.
Quote is what the deterministic pricing code produces from it. Money is always Decimal.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LineItem(BaseModel):
    """One requested product, as written by the customer (code and/or name)."""

    product_code: str | None = None
    product_name: str | None = None
    quantity: int | None = None
    unit: str | None = None


class QuoteRequest(BaseModel):
    """Facts extracted from a request. `None` means "not stated" - never guessed."""

    is_quote_request: bool
    company_name: str | None = None
    contact_name: str | None = None
    items: list[LineItem] = Field(default_factory=list)
    requested_delivery_date: date | None = None
    express: bool = False
    # Free text the reviewer should see, including any instructions found in the email.
    # Notes are never acted on and never printed on the quote.
    notes: str | None = None


class QuoteLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_code: str
    name: str
    unit: str
    unit_price: Decimal
    quantity: int
    gross: Decimal  # unit_price * quantity
    discount: Decimal  # quantity discount for this line


class Quote(BaseModel):
    model_config = ConfigDict(frozen=True)

    quote_number: str
    issue_date: date
    valid_until: date
    company_name: str
    contact_name: str | None
    requested_delivery_date: date | None
    express: bool
    lines: list[QuoteLine]
    subtotal: Decimal  # sum of line gross amounts
    discount_total: Decimal
    express_fee: Decimal
    tax_rate: Decimal
    tax: Decimal
    total: Decimal
