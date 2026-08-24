# Slice 0322: AG Generation Audit Quality Projection Wiring

## Scope

Wire the AG grounded response quality checkpoint into the generation audit
projection returned by `/admin/v1/generation-audit/generations/{cx_generation_id}`.

This slice does not change database schema, provider configuration, or
PostgreSQL smoke behavior. It exposes only compact, raw-safe quality status
metadata for AG operators and future dashboard wiring.

## Implemented

- Added `ag_generation_audit_grounded_response_quality_projection.v1`.
- Added `grounded_response_quality_projection`.
- Added top-level `grounded_response_quality` to
  `ag_generation_audit_projection.v1`.
- Projected:
  - gap audit schema version;
  - source CX audit schema version;
  - coverage status;
  - grounded response boundary status;
  - citation status;
  - source and projection issue counts;
  - issue codes;
  - lineage mismatches;
  - retrieval package and structured draft lineage;
  - raw-content redaction flags.
- Kept raw prompts, generated output, evidence/source text, provider endpoints,
  model paths, storage paths, and secrets out of the projection.

## Runtime Behavior

AG now computes the grounded response quality gap audit while assembling the
generation audit projection, then returns a compact summary under
`grounded_response_quality`.

Operators can distinguish:

```text
coverage_status: PASS | WARN | FAIL | NOT_REQUIRED | UNKNOWN
boundary_status: PASS | FAIL | NOT_REQUIRED | UNKNOWN
```

`coverage_status` describes whether AG has enough safe source metadata.
`boundary_status` mirrors the CX grounded response quality result when present.

Recommended next slice:

```text
Slice 0323: AG generation audit quality contract/schema hardening
```

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ag_generation_audit.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Observed targeted result:

```text
18 passed, 1 warning
```

Observed full quality gate:

```text
2195 passed, 1 warning
statement_coverage=98.53% threshold=95.00%
branch_coverage=95.42% threshold=85.00%
contract_validation=pass schemas=50 examples=82 negative_examples=59 openapi=7
```
