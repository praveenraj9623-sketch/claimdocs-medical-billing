# Upstream py-idp examples

> These inherited library examples are separate from [ClaimDocs](../README.md). Mock outputs and receipt/invoice benchmarks do not establish medical-claim accuracy. The browser app uses the configured Groq path; provider-specific examples are optional.

# Examples

Copy-pasteable scripts that demonstrate py-idp's main use cases. Run any
of them with `python examples/NN_name.py` — most work offline with the
in-tree MockBackend.

| # | script | what it shows | API key needed? |
|---|---|---|---|
| 01 | [`pipeline_minimal.py`](01_pipeline_minimal.py) | the smallest possible end-to-end pipeline run | no |
| 02 | [`anthropic.py`](02_anthropic.py) | Anthropic Claude 3.5 Sonnet for vision-capable invoice extraction | yes (`ANTHROPIC_API_KEY`) |
| 03 | [`china_qwen.py`](03_china_qwen.py) | Qwen via DashScope — one of the 8 China-LLM providers built in | yes (`DASHSCOPE_API_KEY`) |
| 04 | [`hitl_loop.py`](04_hitl_loop.py) | programmatic HITL feedback loop: human reviews → policy update → faster runs | no |
| 05 | [`batch.py`](05_batch.py) | batch-process multiple documents and save JSON output | no |

Standalone scripts (not numbered; more specialized):

- [`benchmark_cord.py`](benchmark_cord.py) — reproducible 5-receipt CORD-style benchmark with per-field precision/recall/F1.
- [`discover_schema_sample.py`](discover_schema_sample.py) — end-to-end AI-driven schema discovery from a generated PDF.
- [`contract.py`](contract.py) — extract a Contract schema (uses the in-tree sample).

## Pattern

Every numbered example follows the same shape:

1. **Try the real backend.** If the API key is set, use it.
2. **Fall back gracefully.** If the key is missing or the package isn't installed, fall back to `MockBackend` so the script still runs offline.
3. **Print informative output.** `pretty_print_result()` shows schema, classification, timings, extraction, confidence (with low-confidence fields marked), and validation outcome.
4. **End with a one-line note.** Explains what you would have seen with a real backend.

This means every example is runnable in a clean venv with no credentials — the visitor sees the full pipeline anatomy even when their LLM call would 401.

## Adding a new example

1. Pick a `NN_` number that doesn't conflict (check the existing numbered scripts before choosing the next number).
2. Add the AGPL-3.0 + commercial SPDX header at the top (the boilerplate from the existing examples).
3. Add the `logging.getLogger("idp").setLevel(logging.CRITICAL)` line so the offline output is readable.
4. End the script with a one-line `print()` note explaining the MockBackend limitation when applicable.
5. Update this README's table.
