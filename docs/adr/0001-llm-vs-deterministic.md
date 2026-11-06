# ADR 0001: The AI reads, deterministic code calculates

- Status: Accepted
- Date: 2026-11-07

## Context

The customer's top requirement is **zero pricing errors** (see [discovery](../01_discovery.md)). A wrong total has already cost them money once. Quote requests arrive as free-text emails full of abbreviations, typos and full-width characters, which is the kind of input a language model handles well. Arithmetic, price lookups and document layout are things a language model can get wrong in ways that are hard to detect and impossible to reproduce.

## Decision

Split the work at one boundary: the `QuoteRequest` model.

| Step | Done by | Module |
| --- | --- | --- |
| Read the email, fill in `QuoteRequest` (company, contact, items as written, dates, express, notes) | Claude | `extract.py` (Phase 4) |
| Clean up spelling variations (full-width, dashes, units) | Code | `normalize.py` |
| Match items to the price list (code, name, alias) | Code | `catalog.py` |
| Flag anything a person must check | Code | `validate.py` |
| Approve, edit or abort | **Person** | `review.py` (Phase 4) |
| Prices, discounts, express fee, tax, totals | Code (`Decimal`) | `pricing.py` |
| PDF layout | Code (reportlab) | `render_pdf.py` |

Rules that follow from this:

1. The model never outputs a price, a discount or a total. `QuoteRequest` has no field for them, so a prompt injection like "make this 90% off" has nowhere to go except `notes`.
2. All money is `decimal.Decimal`. Rates live in `config/pricing.toml` as quoted strings, and the loader rejects unquoted floats.
3. Every amount is rounded down to the yen at fixed points: line gross, line discount, express fee, tax. Tax is applied once to the whole quote, not per line.
4. Product matching is exact after normalisation. A typo that isn't in the alias list is **not** guessed by code. It becomes an `unknown_product` warning, and pricing refuses to run. Fuzzy candidates (`Catalog.search`) are only suggestions for agent mode or the reviewer.
5. Pricing refuses the whole request and lists every problem at once, rather than producing a partial quote.
6. The same input gives the same output: quote numbers are derived from content plus issue date, and PDFs are rendered with `invariant=1`, so identical quotes are byte-identical.

## Consequences

- "Zero pricing errors" becomes a testable claim. `tests/test_pricing.py` pins hand-calculated totals, and every ground-truth case in the evaluation set is priced in CI.
- The AI's job is narrower and easier to evaluate: we measure field accuracy against labelled data (Phase 5) instead of checking totals.
- An extraction error can still produce a wrong quote, for example the wrong quantity read correctly as a number. That risk is handled by the human review step ([ADR 0003](0003-human-in-the-loop.md)), not by the calculator.
- Unknown products and typos stop the flow until a person fixes them. That is slower than guessing, and it is the intended trade-off for this customer.
- Changing tax, discount or express rules is a config edit, not a prompt change, and is covered by the same tests.

## Alternatives considered

- **Let the model produce the full quote, including totals.** This is the fastest to build, but the results are not reproducible, cannot be unit-tested, and are exposed to prompt injection on prices. Rejected.
- **Let the model calculate, then check its numbers in code.** This needs the same calculator anyway and adds a reconciliation step. Rejected as extra complexity with no benefit.
- **Fuzzy-match products in code automatically.** This would resolve typos without a human, but a near-miss match (6204 vs 6201) is exactly the silent error the customer wants to avoid. Kept as candidate suggestions only.
