# Slice 0659: AG operator review case workbench privacy regression

## Intent

Lock the S66 case workbench privacy boundary after the queue, detail, timeline,
contract, and PostgreSQL smoke surfaces are in place.

## Scope

- Add `scripts/smoke/run_ag_operator_review_case_workbench_privacy_regression.py`.
- Build a mock-first unsafe case fixture that deliberately injects raw action
  comments, raw prompts, generation output, source text, storage paths, provider
  keys, service tokens, database URLs, and idempotency keys into records/events.
- Drive protected AG routes for:
  - case queue
  - case workbench detail
  - case timeline
  - operations dashboard
  - issue candidates
- Verify the public payloads expose only safe refs, hashes, redaction flags,
  and operational-event metadata.
- Update the Slice 0651 S66 plan to reflect the actual sequence:
  - Slice 0657 contract/OpenAPI hardening
  - Slice 0658 PostgreSQL smoke evidence
  - Slice 0659 privacy regression

## Boundary

- No database migration or new table.
- No live PostgreSQL dependency; this is a deterministic in-memory regression.
- Raw action and resolution text must not appear in the evidence payload.
- Timeline remains `service_operational_events` metadata-first and does not add
  a case action history table.

## Evidence

```bash
./.venv/bin/python scripts/smoke/run_ag_operator_review_case_workbench_privacy_regression.py --summary
```

Result:

```text
ag_operator_review_case_workbench_privacy_regression=pass surfaces=5 forbidden_labels=11
```

## Verification

- Targeted privacy regression tests.
- Full quality gate.
