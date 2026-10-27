# P9-S11: AE AgentResult Safe WA Projection

## Scope

P9-S11 exposes the exact canonical AE `AgentResult` as bounded evidence for
NeX-WA without returning structured result content or any raw response text.
It reuses `ae_agent_result`, `ae_result_delivery`, and `ae_agent_execution`;
there is no migration and no duplicate WA-owned identity store.

## Boundary

```text
GET /internal/v1/wa-sources/agent-results/{result_id}
caller = nex-wa
audience = nex-ae-api
scopes = service:call + work:source:read
tenant = X-NeX-Tenant-Id
```

The projection is tenant exact and contains only identities, statuses, hashes,
bounded references, WorkItem/Claim/Assignment lineage, and the authoritative
execution/delivery completion barrier. Both pre-ACK and post-ACK states are
visible so P9-S17 can make the admission decision; P9-S11 does not itself
create WorkEvidence.

## Verification

Focused tests cover project-neutral IA, claimed background Agent lineage,
pre/post ACK state, missing scope, wrong caller, cross-tenant lookup, source
unavailability, lineage drift, and raw-content exclusion. Contract validation
includes `wa_agent_result_source_projection.v1` and its acknowledged example.

```text
S11 focused tests         = 13 passed
NeX-AE Slice Gate         = 5,568 passed, 44 skipped
AE statement coverage     = 97.35%
AE branch coverage        = 95.69%
projection statement      = 100.00%
projection branch         = 100.00%
contract validation       = 215 schemas / 279 examples / 235 negatives / 10 OpenAPI
ruff                      = PASS
```

The first Slice Gate detected that changing the frozen AE OpenAPI version from
`1.7.0` would invalidate nine existing contract baselines. The new internal
route is therefore additive within the established version, avoiding unrelated
contract churn while retaining explicit schema and operation coverage.
