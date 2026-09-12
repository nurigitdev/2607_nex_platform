# Slice 0675: AG operator review case closure packet foundation

## Intent

Assemble redaction-safe closure packets for the S68 operator review case
decision lifecycle before exposing a protected route.

## Scope

- Add `ag_operator_review_case_closure_packet.v1` as an internal read-model
  schema version constant.
- Combine safe case refs, resolution hash, timeline summary, action
  outcome summary/items, and evidence-link refs into one packet.
- Derive closure readiness from closed status, terminal action evidence,
  resolution hash, and evidence-link presence.
- Keep closure packets read-model-only; no closure table is introduced.
- Add service-level wrapper logic so route wiring can remain small in the next
  slice.

## Decision

Closure packets remain AG-owned read models over `ag_op_cases`,
`service_operational_events`, `ag_op_notes`, and `ag_ev_exports`. The packet is
safe for operator review and debugging surfaces because it excludes raw case
comments, raw action/resolution text, raw note/export bodies, prompts, provider
payloads, local storage paths, database URLs, service tokens, idempotency keys,
and raw metadata payloads. Resolution previews are also excluded because short
previews can still be indistinguishable from raw operator text in a closure
packet.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
```

## Result

The targeted tests cover closure-ready packets, open/blocked packets, service
wrapper wiring, terminal action evidence, evidence-link refs, and raw payload
redaction.
