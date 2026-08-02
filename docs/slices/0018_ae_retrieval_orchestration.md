# Slice 0018 AE Retrieval Orchestration

Status: Implemented.

Backlog candidate: `S2-008` AE retrieval orchestration route.

Requirement coverage: `AE-RETRIEVAL-001`, `AE-CX-001`, `TRACE-PLAT-001`,
`CONTRACT-AE-001`.

## Scope

Slice 0018 lets AE API call CX retrieval without starting generation:

- `POST /api/v1/retrieval/contexts` accepts an AE user message and retrieval
  options.
- AE builds the CX retrieval request package with trace ID, actor reference,
  chat document ID, document scope, top-k, source preview, neighbor flag, and
  purpose.
- AE calls CX `POST /api/v1/retrieval/context` through a service-token-bearing
  client.
- AE stores a retrieval interaction record with CX package ID/hash, status,
  evidence count, best score, confidence bucket, warnings, and no-answer reason.
- `GET /api/v1/retrieval/contexts/{retrieval_interaction_id}` reads the stored
  record.

This slice keeps retrieval orchestration separate from chat generation. Slice
0019 can use this record/package boundary to assemble grounded chat.

## Contract Artifacts

- `contracts/schemas/service/nex_ae_api/retrieval_interaction.v1.schema.json`
- `contracts/examples/retrieval/ae_retrieval_interaction.mock_success.json`
- `contracts/tests/negative/retrieval/ae_retrieval_interaction.raw_user_message_leak.json`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover CX payload mapping, default retrieval options, bad
request rejection, CX failure propagation, no-answer mapping, endpoint auth,
readback, and HTTP service-token forwarding.
