# Slice 1115: MO provider response normalization extraction

## Goal

Separate provider response validation and canonical MO response projection from
remote HTTP execution without changing caller-visible behavior.

## Result

- Generation, embedding, and reranking normalization now live in
  `nex_mo.provider_normalization`.
- `nex_mo.remote_provider` preserves the established normalizer exports.
- OpenAI-compatible and legacy embedding response shapes remain supported.
- Usage fallback, deterministic generation IDs, finish reasons, rerank sorting,
  and malformed-response failure semantics remain compatible.
- The normalization module has no HTTP client dependency and creates no table.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_provider_normalization_extraction.py \
  tests/test_nex_mo_remote_provider.py \
  --cov=nex_mo.provider_normalization \
  --cov=run_mo_provider_normalization_extraction \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_mo_provider_normalization_extraction.py --summary
```
