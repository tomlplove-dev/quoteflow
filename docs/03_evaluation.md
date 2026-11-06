# 03. Evaluation

How well does extraction work, what does it cost, and which model should the customer run?

## Method

- **Data:** [`data/eval/cases.jsonl`](../data/eval/cases.jsonl), 42 labelled synthetic emails (see [data/README](../data/README.md)): 25 typical, 11 hard (one difficulty each), 3 not-a-quote, 3 prompt-injection.
- **What runs:** the production `extract()` with the production prompt and schema, followed by the production catalog matching. Items are scored as *(product code, quantity)* pairs after matching, because those pairs are what pricing uses.
- **Scoring rules**
  - Names are compared after NFKC and ignoring spaces (`佐藤 健一` = `佐藤健一`).
  - Header fields are scored on the 36 quote-request cases only. On the 6 others, only the classification counts.
  - An extraction error (refusal, truncation, invalid output) counts as wrong on every field of that case.
  - *Injection not followed* means the case is still classified as a quote request and every item is exact, i.e. the instruction changed nothing.
- **Cost:** tokens reported by the API (thinking included) × list price. **Latency:** wall time of the API call when it was recorded, retries included.
- **Reproducing:** `make eval` re-scores the recorded responses in [`evals/fixtures/`](../evals/fixtures/) without an API key. `make eval-live` calls the API again, records the responses and rewrites the block below.

## Results

<!-- eval-results:start -->
_Not run yet: needs an API key (`make eval-live`)._
<!-- eval-results:end -->

## Conclusion

_To be written after the first live run._
