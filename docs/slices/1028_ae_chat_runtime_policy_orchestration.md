# Slice 1028: AE Chat Runtime Policy Orchestration

## Goal

Wire exact intent, prompt, template, runtime policy, and generation-policy
package resolution into durable AE workspace chat execution.

## Implementation

- Resolve runtime policy after owner/workspace admission and before retrieval or
  generation dispatch.
- Render the selected active prompt binding and persist its hash-only user
  lineage event.
- Derive retrieval necessity from the resolved execution mode, including
  deterministic summary/document intent.
- Attach the metadata-only generation-policy package and package hash to the CX
  request.
- Persist policy snapshot, prompt binding, render-event reference, and policy
  package in the existing chat `generation_summary` JSON across completed,
  no-answer, rejected, and failed states.
- Preserve legacy builder compatibility when no policy context is supplied.

## Decisions

- AE persists the decision package; CX still owns provider-facing prompt
  assembly and MO still owns provider runtime.
- Policy errors fail before CX generation. A failure after PENDING preserves the
  resolved policy lineage for restart/debugging.
- No new table, PostgreSQL smoke, or remote provider is required in this Slice.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_nex_ae_chat_runtime_policy.py \
  --coverage-target services/nex-ae-api/nex_ae_api/chat.py \
  --coverage-target services/nex-ae-api/nex_ae_api/generation_policy.py \
  --smoke scripts/smoke/run_ae_chat_runtime_policy.py
```

## Observed Evidence

- Slice Gate: PASS (`2074 passed`; statement `97.87%`, branch `95.65%`).
- Target coverage: `chat.py` statement `97.61%`, branch `98.24%`;
  `generation_policy.py` statement/branch `100.00%`.
- Contract validation: PASS (`93` schemas, `147` examples, `110` negative
  examples, `7` OpenAPI documents).
- AE chat runtime-policy smoke: PASS (`13/13` checks).
