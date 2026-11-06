# ADR 0003: A person approves every quote; automation only removes typing

- Status: Accepted
- Date: 2026-11-07

## Context

The sales team said a person must see every quote before it reaches a customer ([discovery](../01_discovery.md)). Extraction can be wrong in ways no code can detect, such as a quantity misread as a different valid number. Emails may also contain instructions aimed at the system. The target is still 3 minutes per quote, down from 15, so the review step has to be fast.

## Decision

1. **Review sits between extraction and pricing.** `review.py` shows the extracted request, how each item matched the price list, and every warning. The reviewer then chooses **approve**, **edit** or **abort**. Nothing is priced and no PDF is written before approval.
2. **Two kinds of warning.**
   - **[要修正] (must fix):** `not_quote_request`, `missing_company`, `no_items`, `unknown_product`, `missing_quantity`, `non_positive_quantity`, `unit_mismatch`. Approval is refused until these are fixed, because the quote would be wrong or impossible.
   - **[確認] (read):** `missing_contact`, `duplicate_product`, `delivery_date_in_past`, `notes_to_review`. The reviewer may approve after reading them.
3. **Edit means editing the extracted data, not the quote.** The reviewer edits the `QuoteRequest` JSON in their editor. It is re-validated and shown again. Prices are never editable by hand: they always come from the price list and `config/pricing.toml`.
4. **`--yes` only for clean requests.** Auto-approval is refused when there is *any* warning, including notes. A prompt injection therefore always reaches a person.
5. **Sending stays manual.** QuoteFlow writes a PDF. The rep attaches and sends it.
6. **The Excel request form skips the AI**, not the review. The fixed cells are read by code (`inputs.py`), then go through the same validation and review.

## Consequences

- Wrong extractions cost a few seconds of the reviewer's attention instead of a wrong quote. The evaluation (Phase 5) measures how often that attention is needed.
- Typos that are not in the alias list block approval until the reviewer types the right code. This is slower than auto-matching, and it is deliberate: a near-miss product is the costliest error.
- Each run's log line records the outcome (`completed`, `aborted`, `needs_review`, `failed`) and the warning codes. This shows which warnings occur most often and which aliases or rules to add.
- The review UI is a terminal prompt. A web form would be friendlier, but it is out of scope for this engagement.

## Alternatives considered

- **Fully automatic with a confidence threshold.** This would need calibrated confidence the model does not give, and the customer explicitly rejected unattended quotes. Rejected.
- **Review the finished PDF instead of the data.** Mistakes are harder to spot in a rendered document, and a fix would mean regenerating everything. Rejected.
