# ADR 0002: Structured outputs for extraction, checked in a fixed order

- Status: Accepted
- Date: 2026-11-07

## Context

Extraction turns a free-text email into a `QuoteRequest` ([ADR 0001](0001-llm-vs-deterministic.md)). The output has to be machine-readable every time, and every way the call can fail has to be detected and reported, not guessed around. The ways it can fail are: the model refuses, the output is cut off, the network is down, or the JSON is malformed.

The versions are checked against the installed SDK (`anthropic` 2.6.0) and the official model list (2026-11).

## Decision

1. **One call, structured outputs.** The request sets `output_config.format` to a JSON schema built from the pydantic model: `anthropic.transform_schema(QuoteRequest.model_json_schema())`. The schema and the code share one source of truth, and the field descriptions in `models.py` double as instructions to the model.
2. **`messages.create`, not `messages.parse`.** `parse()` validates the JSON inside the SDK call. If the output was cut off at `max_tokens`, it fails with a validation error before we can see why. We call `create()` and check in this order:
   1. `stop_reason == "refusal"`: error `refusal`, with `stop_details.category` logged
   2. `stop_reason == "max_tokens"`: error `max_tokens`
   3. any other non-`end_turn` stop: error `unexpected_stop`
   4. only then validate the text with pydantic: error `invalid_output` on failure
3. **Network errors use the SDK's retry.** The SDK retries connection errors, 408, 409, 429 and 5xx with exponential backoff. `QUOTEFLOW_MAX_RETRIES` and `QUOTEFLOW_TIMEOUT_SECONDS` control the retry count and the per-attempt timeout. After the last retry the error becomes `connection_error` or `api_error`. We do not add our own retry loop.
4. **Prompt-injection defence is structural first, then instructed.**
   - The schema has no field for prices, discounts or totals.
   - The email is wrapped in `<email>` tags, and any tag in the text is escaped so it cannot close the wrapper.
   - The system prompt says the email is untrusted data, and that instructions found in it are copied verbatim into `notes`.
   - `notes` always raises a review warning, so a person reads it ([ADR 0003](0003-human-in-the-loop.md)).
5. **Model choice is configuration.** The default is `claude-opus-5-5`, set by `QUOTEFLOW_MODEL`. Effort is set explicitly (`QUOTEFLOW_EFFORT`, default `medium`, which is also that model's default). Phase 5 compares it with `claude-haiku-5-5` on the evaluation set. For models that support it, the server-side refusal fallback (`fallbacks: "default"`) is on, and it can be turned off with `QUOTEFLOW_REFUSAL_FALLBACK=false`. The model that actually answered is logged.
6. **The API call is a function.** `extract()` takes a `send(params) -> message` function. The same code path runs live (`live_sender`), from saved responses (`replay_sender`), or live while saving (`recording_sender`). Saved responses are keyed by a hash of model, system prompt, messages and schema. Changing the prompt therefore makes old recordings miss loudly (`missing_fixture`) instead of replaying stale answers.

## Consequences

- Tests and CI cover every failure mode with plain functions as fakes, so they need no network, API key or HTTP mocking library.
- `make demo` runs end to end without a key, using stand-in responses that are clearly labelled `"source": "stand-in"`. `make record` replaces them with real ones.
- Every prompt change requires re-recording the evaluation fixtures. This is intended: the evaluation must always describe the prompt that ships.
- Using `create()` means validating the JSON ourselves (one `model_validate_json` call). That is a small cost for knowing *why* a call failed.

## Alternatives considered

- **Forced tool use to get JSON.** On the current models a forced `tool_choice` is rejected, and structured outputs is the documented way to get schema-shaped output. Rejected.
- **Free-text JSON with "respond only in JSON" in the prompt.** Nothing guarantees the shape, so it needs repair logic. Rejected.
- **`messages.parse()`.** Less code, but it hides the stop reason on truncation. Rejected for the reason above.
