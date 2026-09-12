# Slice 0687: AG operator review case SLA/escalation contract and OpenAPI hardening

## Intent

Freeze the S69 SLA/escalation API contract so client and smoke-test work can
depend on stable response shapes.

## Scope

- Extend `operator_review_case_workbench.v1.schema.json` with SLA policy,
  aging, and escalation response variants.
- Add positive examples for the three S69 read-model responses.
- Add negative examples for raw prompt, raw case comment, and notification
  payload leakage.
- Document `/sla-policy`, `/aging`, and `/escalations` in
  `nex-ag.openapi.yaml`.
- Register all new examples in the contract indexes.

## Decision

The S69 contract remains read-model-only. It validates safe references,
thresholds, runbook ids, summaries, paths, and redaction flags, while rejecting
raw prompt/case/comment material and outbound notification payload exposure.

## Verification

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
```

## Result

Contract validation passed for schemas, examples, negative examples, and OpenAPI
specs.
