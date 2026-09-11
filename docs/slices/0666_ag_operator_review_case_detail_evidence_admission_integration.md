# Slice 0666: AG operator review case detail evidence/admission integration

## Intent

Make the operator review case workbench detail payload point operators to the
new evidence-link and action-admission surfaces without inlining raw evidence or
duplicating the authoritative mutation route.

## Scope

- Extend `GET /admin/v1/operator-review/cases/{case_id}/workbench-detail` with
  lightweight `evidence_links` and `action_admission` sections.
- Reuse the target-scoped operator note and redacted evidence export stores
  already used by the evidence-link route.
- Keep full evidence-link items on
  `GET /admin/v1/operator-review/cases/{case_id}/evidence-links`.
- Keep action mutation authority on
  `POST /admin/v1/operator-review/cases/{case_id}/actions`.

## Behavior

- When note/export stores are configured, workbench detail returns evidence
  summary counts and source status.
- When only one evidence source is configured, the summary reports `PARTIAL`.
- When no evidence source is configured, the summary reports `NOT_CONFIGURED`.
- The detail response includes links to the evidence-link and action-admission
  routes while leaving both detailed payloads un-inlined.

## Privacy Guard

The integrated detail surface keeps raw notes, raw evidence bodies, raw case
comments, raw action comments, raw resolution comments, prompts, generation
output, source text, storage paths, provider payloads, database URLs, tokens,
idempotency keys, and raw metadata payloads out of the response.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

Regression coverage verifies pure projection output, service-level evidence
source status handling, protected route integration, action-admission summary
exposure, route links, and raw payload leak prevention.
