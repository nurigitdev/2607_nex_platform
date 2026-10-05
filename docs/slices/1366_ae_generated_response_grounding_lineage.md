# Slice 1366: AE Generated-Response Grounding Lineage

## Goal

Persist the exact CX grounding, citation-validation, and bounded-repair lineage
with the AE owner-scoped generated response, reject incomplete grounded READY
handoffs before private content storage, and run the fifth-Slice Checkpoint
Gate.

## Implementation

- Added a metadata-only `cx_grounding_lineage` projection to AE generated
  response lineage while retaining read compatibility with pre-Slice 1366 v1
  records that do not contain the optional field.
- AE now accepts grounded response content only when the CX READY handoff has a
  validated citation workflow and exact retrieval package, evidence binding,
  evidence count, repair attempt, and provider prompt-transition lineage.
- Missing, malformed, private-evidence-bearing, or drifted CX lineage fails
  before AE private payload storage and chat-record persistence.
- Non-grounded responses retain `NOT_REQUIRED` semantics and persist a null
  grounding lineage.
- Hardened the generated-response, owner response, chat interaction, and
  OpenAPI contracts without adding a table or copying private evidence into
  PostgreSQL, public APIs, or operations evidence.
- The Checkpoint Gate exposed and corrected two older regression-fixture
  drifts: S136 contract inventory snapshots and S1363 retrieval-package SQLite
  columns.

## Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-ae-api \
  --test tests/test_ae_grounded_response_lineage.py \
  --test tests/test_ae_generated_response_contracts.py \
  --test tests/test_ae_async_chat_refresh.py \
  --test tests/test_nex_ae_generated_response_lineage.py \
  --test tests/test_nex_ae_generated_response_handoff.py \
  --coverage-target scripts/smoke/run_ae_grounded_response_lineage.py \
  --smoke scripts/smoke/run_ae_grounded_response_lineage.py

scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_ae_grounded_response_lineage.py \
  --test tests/test_ae_generated_response_contracts.py \
  --test tests/test_ae_async_chat_refresh.py \
  --test tests/test_nex_ae_generated_response_lineage.py \
  --test tests/test_nex_ae_generated_response_handoff.py \
  --coverage-target scripts/smoke/run_ae_grounded_response_lineage.py \
  --smoke scripts/smoke/run_ae_grounded_response_lineage.py
```

Observed evidence:

- focused lineage, handoff, refresh, contract, and evidence suite: `74 passed`
- changed lineage and handoff modules: `100%` statement/branch coverage
- Slice Gate: `2,858 passed`, `5 skipped`, statement `98.36%`, branch `96.30%`
- Checkpoint Gate: `10,955 passed`, `30 skipped`, statement `98.92%`, branch
  `97.31%`
- contract validation: `162` schemas, `221` examples, `189` negative
  examples, and `7` OpenAPI documents
- deterministic AE grounding-lineage evidence: `10/10` checks

The skipped tests are protected PostgreSQL/live-provider opt-in suites. This
Slice is deterministic and does not require a database or remote provider;
protected S137 PostgreSQL and live generation evidence remains assigned to
Slice 1370. Slice 1367 may now admit artifacts only from this verified AE
response lineage.
