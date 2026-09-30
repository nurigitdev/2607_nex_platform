# Slice 1142: MO provider resilience and retry boundary

## Goal

Freeze the S115 ownership, retry safety, and delivery sequence before changing
remote provider execution behavior.

## Result

- S115 owns bounded retries within one logical embedding, reranking, or
  generation request. It does not create a background retry queue.
- Embedding and reranking allow at most three attempts. Generation allows at
  most two attempts and does not replay ambiguous read/write timeout or
  malformed-response failures.
- Retry delay uses bounded exponential full jitter with injectable sleep and
  jitter sources. A valid `Retry-After` delta may be honored only within the
  policy cap.
- Existing safe failure classification, provider telemetry, and readiness
  boundaries remain the integration points.
- Restart-safe aggregate telemetry remains S116. GPU/runtime observability
  remains S117. S115 adds no database table and requires no DGX call.

## Planned Slices

1. Slice 1143: retry policy and refined failure taxonomy.
2. Slice 1144: deterministic bounded retry executor.
3. Slice 1145: remote HTTP transport integration.
4. Slice 1146: capability policy wiring and checkpoint gate.
5. Slice 1147: retry-attempt telemetry projection.
6. Slice 1148: readiness and resilience composition.
7. Slice 1149: deterministic fault-injection HTTP smoke.
8. Slice 1150: resilience contract and API hardening.
9. Slice 1151: S115 closure and Full Gate.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_resilience_boundary.py
./.venv/bin/python \
  scripts/smoke/run_mo_provider_resilience_boundary.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_resilience_boundary.py \
  --coverage-target services/nex-mo/nex_mo/provider_resilience_boundary.py \
  --smoke scripts/smoke/run_mo_provider_resilience_boundary.py
```

## Quality Evidence

- Focused regression: `4 passed`.
- Slice Gate: `455 passed`, `1` protected PostgreSQL skip.
- Coverage: statement `99.68%`, branch `98.73%`, changed scope `100%/100%`.
- Contract validation: `119` schemas, `177` positive examples, `145` negative
  examples, and `7` OpenAPI documents.
- Boundary evidence: `6/6` boundaries, three capability policies, zero issues.
