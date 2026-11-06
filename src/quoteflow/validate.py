"""Warnings shown to the reviewer before anything is priced.

Every issue blocks `--yes` (auto-approve). Some of them (unknown product, bad quantity,
unit mismatch) also make pricing refuse to run - see pricing.py.
Messages are in Japanese because the reviewers are the customer's sales reps.
"""

from datetime import date

from pydantic import BaseModel

from quoteflow.catalog import Catalog
from quoteflow.models import QuoteRequest
from quoteflow.normalize import normalize_unit

# Issues that make the request impossible to price correctly. The reviewer must fix these
# before approving; the rest ("確認") only need to be read.
BLOCKING_CODES = frozenset(
    {
        "not_quote_request",
        "missing_company",
        "no_items",
        "unknown_product",
        "missing_quantity",
        "non_positive_quantity",
        "unit_mismatch",
    }
)


class Issue(BaseModel):
    code: str
    message: str
    item_index: int | None = None  # 0-based index into request.items


def validate_request(
    request: QuoteRequest, catalog: Catalog, *, today: date | None = None
) -> list[Issue]:
    if not request.is_quote_request:
        return [Issue(code="not_quote_request", message="見積依頼ではないと判定されました。")]

    issues: list[Issue] = []

    def add(code: str, message: str, item_index: int | None = None) -> None:
        issues.append(Issue(code=code, message=message, item_index=item_index))

    if not request.company_name:
        add("missing_company", "会社名が読み取れません。")
    if not request.contact_name:
        add("missing_contact", "担当者名が読み取れません。")
    if not request.items:
        add("no_items", "品目がありません。")

    first_seen: dict[str, int] = {}
    for i, item in enumerate(request.items):
        label = f"品目{i + 1}"
        product = catalog.match(item).product
        if product is None:
            written = item.product_code or item.product_name or "(空欄)"
            add("unknown_product", f"{label}: 価格表にない商品です: {written}", i)
        else:
            if product.code in first_seen:
                other = first_seen[product.code] + 1
                add("duplicate_product", f"{label}: 品目{other}と同じ商品です ({product.code})", i)
            first_seen.setdefault(product.code, i)
            unit = normalize_unit(item.unit)
            if unit is not None and unit != product.unit:
                detail = f"依頼: {item.unit} / 価格表: {product.unit}"
                add("unit_mismatch", f"{label}: 単位が価格表と違います（{detail}）", i)

        if item.quantity is None:
            add("missing_quantity", f"{label}: 数量が読み取れません。", i)
        elif item.quantity <= 0:
            add("non_positive_quantity", f"{label}: 数量が0以下です ({item.quantity})", i)

    delivery = request.requested_delivery_date
    if today and delivery and delivery < today:
        add("delivery_date_in_past", f"希望納期が過去の日付です ({delivery})")
    if request.notes:
        # Notes may contain instructions from the email ("90% off"). A person must read them.
        add("notes_to_review", f"備考を確認してください: {request.notes}")
    return issues
