"""Price list loading and product matching. No AI here: lookups are exact after normalisation."""

import csv
import difflib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from quoteflow.models import LineItem
from quoteflow.normalize import normalize_code, normalize_name

MatchMethod = Literal["code", "name", "alias"]


@dataclass(frozen=True)
class Product:
    code: str
    name: str
    aliases: tuple[str, ...]
    unit: str
    unit_price: Decimal
    category: str


@dataclass(frozen=True)
class Match:
    product: Product | None
    method: MatchMethod | None = None


class CatalogError(ValueError):
    """The price list file is malformed."""


class Catalog:
    def __init__(self, products: list[Product]) -> None:
        self.products = products
        self._by_code: dict[str, Product] = {}
        self._by_name: dict[str, tuple[Product, MatchMethod]] = {}
        for p in products:
            self._add_key(self._by_code, normalize_code(p.code), p.code)
            self._by_code[normalize_code(p.code)] = p
            self._add_key(self._by_name, normalize_name(p.name), p.name)
            self._by_name[normalize_name(p.name)] = (p, "name")
            for alias in p.aliases:
                self._add_key(self._by_name, normalize_name(alias), alias)
                self._by_name[normalize_name(alias)] = (p, "alias")

    @staticmethod
    def _add_key(index: Mapping[str, object], key: str, label: str) -> None:
        # An ambiguous key would make matching depend on file order, so refuse it outright.
        if key in index:
            raise CatalogError(f"duplicate code/name/alias in price list: {label!r}")

    @classmethod
    def load(cls, path: Path) -> "Catalog":
        products = []
        with path.open(encoding="utf-8", newline="") as f:
            for line_no, row in enumerate(csv.DictReader(f), start=2):
                try:
                    price = Decimal(row["unit_price"])
                except (InvalidOperation, KeyError) as e:
                    raise CatalogError(f"{path}:{line_no}: invalid unit_price") from e
                if price < 0:
                    raise CatalogError(f"{path}:{line_no}: unit_price must not be negative")
                aliases = tuple(a.strip() for a in row["aliases"].split("|") if a.strip())
                products.append(
                    Product(
                        code=row["product_code"],
                        name=row["name"],
                        aliases=aliases,
                        unit=row["unit"],
                        unit_price=price,
                        category=row["category"],
                    )
                )
        return cls(products)

    def get(self, code: str) -> Product | None:
        """Exact lookup by product code (after normalisation)."""
        return self._by_code.get(normalize_code(code))

    def match(self, item: LineItem) -> Match:
        """Find the product for a line item: by code first, then by official name or alias.

        Customers sometimes put a name in the code column or vice versa, so both fields
        are tried against both indexes.
        """
        texts = [t for t in (item.product_code, item.product_name) if t and t.strip()]
        for text in texts:
            product = self._by_code.get(normalize_code(text))
            if product:
                return Match(product, "code")
        for text in texts:
            hit = self._by_name.get(normalize_name(text))
            if hit:
                return Match(*hit)
        return Match(None)

    def search(self, query: str, limit: int = 5) -> list[tuple[Product, float]]:
        """Fuzzy search for candidates (typos, partial names). Used by agent mode and MCP.

        Returns (product, similarity 0..1), best first. Still deterministic: no AI involved.
        """
        q = normalize_name(query)
        scored = []
        for p in self.products:
            keys = [normalize_name(p.code), normalize_name(p.name), *map(normalize_name, p.aliases)]
            score = max(difflib.SequenceMatcher(None, q, k).ratio() for k in keys)
            scored.append((p, round(score, 3)))
        scored.sort(key=lambda pair: (-pair[1], pair[0].code))
        return [pair for pair in scored[:limit] if pair[1] > 0]
