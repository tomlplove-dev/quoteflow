"""Quote calculation. Pure Python and Decimal only - the AI never touches money.

Order of calculation (all amounts rounded down to the yen):
  1. line gross      = unit price x quantity
  2. line discount   = gross x discount rate, when quantity >= min quantity
  3. subtotal        = sum of line gross
  4. express fee     = subtotal x express rate, when express is requested
  5. taxable amount  = subtotal - discounts + express fee
  6. tax             = taxable amount x tax rate (once per quote)
  7. total           = taxable amount + tax
"""

import hashlib
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal

from quoteflow.catalog import Catalog, Product
from quoteflow.config import PricingRules
from quoteflow.models import Quote, QuoteLine, QuoteRequest
from quoteflow.normalize import normalize_unit

ZERO = Decimal("0")


class PricingError(ValueError):
    """The request cannot be priced as it is. The message lists every problem found."""


def floor_yen(amount: Decimal) -> Decimal:
    """Round down to a whole yen (1円未満切り捨て)."""
    return amount.quantize(Decimal("1"), rounding=ROUND_DOWN)


def price_line(product: Product, quantity: int, rules: PricingRules) -> QuoteLine:
    gross = floor_yen(product.unit_price * quantity)
    discount = ZERO
    if quantity >= rules.discount_min_quantity:
        discount = floor_yen(gross * rules.discount_rate)
    return QuoteLine(
        product_code=product.code,
        name=product.name,
        unit=product.unit,
        unit_price=product.unit_price,
        quantity=quantity,
        gross=gross,
        discount=discount,
    )


def make_quote_number(request: QuoteRequest, issue_date: date) -> str:
    """Deterministic quote number: same request + same date -> same number.

    A production system would use the customer's own numbering sequence; this keeps
    the demo and the tests reproducible without a database.
    """
    digest = hashlib.sha256(request.model_dump_json().encode("utf-8")).hexdigest()
    return f"Q-{issue_date:%Y%m%d}-{digest[:6].upper()}"


def calculate_quote(
    request: QuoteRequest,
    catalog: Catalog,
    rules: PricingRules,
    *,
    issue_date: date,
    quote_number: str | None = None,
) -> Quote:
    problems: list[str] = []
    if not request.is_quote_request:
        problems.append("見積依頼ではありません")
    if not request.company_name:
        problems.append("会社名がありません")
    if not request.items:
        problems.append("品目がありません")

    priced: list[tuple[Product, int]] = []
    for i, item in enumerate(request.items, start=1):
        product = catalog.match(item).product
        if product is None:
            problems.append(
                f"品目{i}: 価格表にない商品です ({item.product_code or item.product_name})"
            )
            continue
        if item.quantity is None or item.quantity <= 0:
            problems.append(f"品目{i}: 数量が正しくありません ({item.quantity})")
            continue
        unit = normalize_unit(item.unit)
        if unit is not None and unit != product.unit:
            problems.append(f"品目{i}: 単位が価格表と違います ({item.unit} / {product.unit})")
            continue
        priced.append((product, item.quantity))

    if problems:
        raise PricingError("見積を計算できません: " + "; ".join(problems))
    assert request.company_name is not None  # checked above; narrows the type for mypy

    lines = [price_line(product, quantity, rules) for product, quantity in priced]
    subtotal = sum((line.gross for line in lines), ZERO)
    discount_total = sum((line.discount for line in lines), ZERO)
    express_fee = floor_yen(subtotal * rules.express_rate) if request.express else ZERO
    taxable = subtotal - discount_total + express_fee
    tax = floor_yen(taxable * rules.tax_rate)

    return Quote(
        quote_number=quote_number or make_quote_number(request, issue_date),
        issue_date=issue_date,
        valid_until=issue_date + timedelta(days=rules.validity_days),
        company_name=request.company_name,
        contact_name=request.contact_name,
        requested_delivery_date=request.requested_delivery_date,
        express=request.express,
        lines=lines,
        subtotal=subtotal,
        discount_total=discount_total,
        express_fee=express_fee,
        tax_rate=rules.tax_rate,
        tax=tax,
        total=taxable + tax,
    )
