# Slice 1146: MO provider retry capability wiring

## Goal

Activate bounded retry policy for live embedding, reranking, and generation
execution, then run the S115 fifth-Slice Checkpoint Gate.

## Result

- All three remote execution paths now resolve their capability policy and call
  the retry transport decorator.
- Embedding and reranking retry transient connection/status failures within
  their three-attempt budgets. Generation retries a pre-response connection
  failure within its two-attempt budget.
- Ambiguous generation read timeout remains single-attempt.
- Injected requesters keep retry semantics but replace wall-clock sleep with a
  no-op, keeping fault-injection regression deterministic and fast.
- This Slice adds no database table and does not require live DGX access.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_retry_wiring.py
./.venv/bin/python scripts/smoke/run_mo_provider_retry_wiring.py --summary
scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_mo_provider_retry_wiring.py \
  --coverage-target services/nex-mo/nex_mo/remote_provider.py \
  --smoke scripts/smoke/run_mo_provider_retry_wiring.py
```

## Quality Evidence

- Focused MO/CX compatibility regression: `92 passed` before checkpoint.
- The first Checkpoint Gate found two legacy fake responses without a
  `headers` attribute. Retry-After was corrected to remain an optional response
  protocol element; the focused compatibility recheck passed `18/18`.
- Final Checkpoint Gate: `8,657 passed`, `6` protected skips.
- Coverage: statement `98.74%`, branch `96.90%`; changed remote-provider scope
  reached statement `99.34%` and branch `99.43%`.
- Contract validation remained `119/177/145/7`.
- Retry wiring smoke recovered all three capabilities and kept ambiguous
  generation timeout at one attempt (`4/4` checks).
