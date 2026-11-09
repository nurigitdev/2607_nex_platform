# MyBee Phase-1 S0-02: Golden A V1 Regression Baseline

## Scope

S0-02 freezes the existing VoucherDraft and Golden A compatibility boundary
before additive MyBee accounting implementation begins.

## Result

```text
focused deterministic regression = 53 passed
protected live cases              = 2 skipped by explicit admission guards
functional failures               = 0
runtime code changed              = NO
database schema changed           = NO
```

The canonical evidence is recorded in
`docs/mybee_phase1/baselines/v1_regression_results.md`.

## Guardrail

Any later MyBee Slice touching EOS finance, approval, AE NSL execution,
idempotency, outbox, or result publication must rerun this baseline. Protected
PostgreSQL/provider acceptance must be rerun at the next environment-dependent
checkpoint rather than converting an explicit skip into a pass claim.
