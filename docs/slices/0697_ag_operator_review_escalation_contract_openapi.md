# Slice 0697: AG operator review escalation contract/OpenAPI hardening

## Intent

Freeze the public contract for persisted AG operator review escalation action
state before adding PostgreSQL smoke and privacy regression evidence.

## Scope

- Extend `operator_review_case.v1` with persisted escalation record, list, and
  action mutation response definitions.
- Add positive examples for escalation list and action mutation responses.
- Add a negative fixture that rejects raw notification payload leakage.
- Document the protected list/detail/action escalation endpoints in the AG
  OpenAPI surface.
- Keep persisted escalation action state separate from S69 escalation candidate
  projections.

## Decision

The S70 escalation action contract reuses the AG operator review case schema
family to preserve one canonical review-case boundary, while the route paths
remain explicit under `/admin/v1/operator-review/escalations`. The response
contract exposes only safe action state, hashes/previews, route links, and
redaction assertions.

## Verification

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
./scripts/quality/run_quality_gate.sh
```

## Result

AG escalation operators now have a schema-validated and OpenAPI-documented
surface for list, detail, and action mutation flows without exposing raw action
comments, notification payloads, external incident payloads, database URLs,
tokens, or idempotency keys.
