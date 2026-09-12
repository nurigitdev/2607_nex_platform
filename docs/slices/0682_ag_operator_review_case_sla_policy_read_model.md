# Slice 0682: AG operator review case SLA policy read model

## Intent

Add the first S69 SLA/escalation read model: a metadata-only SLA policy
projection for operator review cases.

## Scope

- Add `ag_operator_review_case_sla_policy.v1`.
- Define default priority rules for `LOW`, `MEDIUM`, `HIGH`, and `URGENT`.
- Keep notification delivery, external incident sync, and escalation persistence
  deferred/read-model-first.
- Add a service wrapper for future protected route wiring.
- Do not add a new table or outbound delivery behavior.

## Decision

The SLA policy is configuration-shaped read-model data owned by `nex-ag`.
Thresholds are deterministic and safe to expose to AG operators because they do
not include raw case comments, prompts, source text, provider payloads, storage
paths, database URLs, service tokens, idempotency keys, or metadata payloads.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
```

## Result

The targeted tests cover SLA policy shape, priority thresholds, reason mappings,
redaction flags, path templates, and service wrapper behavior.
