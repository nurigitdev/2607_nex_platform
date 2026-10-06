# Slice 1377: AG Cross-Service Trace Client and Aggregation

## Goal

Replace the remaining cross-service read design with typed, authenticated,
metadata-only service API clients before the protected AG route is switched in
Slice 1378.

## Implementation

- Added one typed HTTP client contract for OA, AE, CX, and MO trace sources.
- TEST_MOCK outbound claims now carry both `service:call` and
  `operations:read`; signed profiles still require operator-supplied OA tokens.
- Strictly validate every source response against the canonical service,
  trace, stage, summary, and private-payload boundary before aggregation.
- Aggregate healthy sources in timestamp order while representing timeout,
  transport, authorization, 5xx, missing-client, and contract failures as
  per-source `DEGRADED` or `UNAVAILABLE` state.
- Keep diagnostics metadata-only: service id, bounded error code, retryability,
  and optional HTTP status. Response bodies, URLs, tokens, and private details
  are never copied into the projection or diagnostics.
- Extended the AG E2E schema for model-agnostic model revision, deployment,
  route, and provider mode metadata already admitted by the shared contract.

The old AG route remains behaviorally unchanged in this Slice. Slice 1378
wires the new aggregator and durable AG audit evidence together so the response
contract changes only once. No database or remote provider is required here.

## Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-ag \
  --test tests/test_nex_runtime_cross_service_trace.py \
  --test tests/test_nex_ag_cross_service_trace.py \
  --test tests/test_ag_cross_service_trace_aggregation_contract.py \
  --coverage-target services/nex-ag/nex_ag/cross_service_trace.py \
  --coverage-target scripts/smoke/run_ag_cross_service_trace_aggregation_contract.py \
  --smoke scripts/smoke/run_ag_cross_service_trace_aggregation_contract.py
```

Expected deterministic evidence is `checks=12/12`, `sources=3/4`, `stages=3`,
`diagnostics=1`, and `next=1378`.

Observed evidence:

- AG Slice Gate: `2499 passed`; statement `98.88%`, branch `96.48%`.
- AG trace client/aggregator statement and branch coverage: `100%`.
- Aggregation evidence runner statement and branch coverage: `100%`.
- Contract validation: `166` schemas, `228` examples, `196` negative examples,
  and `7` OpenAPI documents.
- Deterministic evidence: `checks=12/12`, `sources=3/4`, `stages=3`,
  `diagnostics=1`, `next=1378`.
