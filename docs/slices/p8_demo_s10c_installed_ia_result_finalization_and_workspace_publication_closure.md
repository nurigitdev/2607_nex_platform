# P8-DEMO-S10C: Installed IA Result Finalization and Workspace Publication Closure

## Outcome

The installed Chairman Demo IA path now completes the existing P5/P6/P8
execution lifecycle after controlled WRITE verification. This Slice adds no
parallel result model and no replacement worker.

```text
RESULT_VERIFY
-> SqlAlchemyP5PlanFinalizationService
-> immutable AgentResult
-> pending WORKSPACE_RESULT delivery
-> owner-scoped workspace activity
-> delivery ACK
-> AgentExecution SUCCEEDED / FINALIZE
```

The installed bounded worker invokes the closer after each worker cycle. A
restart can therefore resume either `RESULT_VERIFY` or `RESULT_PUBLISH`
without replaying the voucher commit.

## Persistence Decision

The source audit found that the required durable boundaries already exist:

```text
ae_agent_result           immutable finalized result and lineage
ae_result_delivery        WORKSPACE_RESULT publication state and ACK
ae_workspace_activities   owner-scoped reference-only workspace projection
ae_agent_execution        canonical lifecycle state and phase
```

No migration is added. Publication uses a deterministic workspace activity
identifier derived from the delivery operation ID. An acknowledged replay
validates the existing projection and terminal execution state instead of
inserting another activity, AgentResult, delivery, or voucher.

The AgentResult records an EOS BusinessOperation as a business reference.
Raw prompts and raw result payloads are not copied into the workspace read
model.

## Owner-Scoped Read Boundary

AE API now provides:

```text
GET /api/v1/chat/interactions/{interaction_id}/agent-result
```

The query constrains tenant, authenticated browser user, workspace owner, and
interaction inside the database query. Service identities are rejected from
this browser-owner route, and absent or cross-owner results both return the
same not-found response.

AE Web retains semantic-planning interaction lineage, renders a pending Agent
result state for compiled requests, and polls the same-origin authenticated
route until the result is published. The rendered projection contains state,
business references, and external references only.

## Restart and Replay Guarantees

The regression matrix verifies:

- one finalization and publication when starting at `RESULT_VERIFY`;
- publication-only recovery when starting at `RESULT_PUBLISH`;
- exact replay after ACK performs no mutation;
- owner-lineage drift, invalid delivery state, and tampered projection fail
  closed;
- a second installed runtime cycle creates no duplicate AgentResult,
  delivery, workspace activity, EOS BusinessOperation, or voucher;
- finalization preserves the existing result and delivery uniqueness keys.

## Protected PostgreSQL Evidence

The protected runner used the actual test databases and the existing signed
trust/runtime path:

```text
AE database               = nex_ae_user@nex_ae_test
WC database               = nex_wc_user@nex_wc_test
EOS database              = nex_eos_user@nex_eos_test
OA database               = nex_oa_user@nex_oa_test
checks                    = 8 / 8 PASS
AgentResult               = 1
WORKSPACE_RESULT delivery = 1 ACKNOWLEDGED
workspace activity        = 1
execution terminal state  = SUCCEEDED / FINALIZE
replay mutation           = 0
```

The runner cleans its tenant-scoped fixtures. Remote generation, embedding,
and reranking providers are not required for this lifecycle closure.

Evidence is recorded in ignored runtime reports:

- `reports/deployment/p8-demo-s10c-installed-result-closure.json`
- `reports/quality/p8-demo-s10c-slice.coverage.json`

## Regression and Coverage

```text
focused Python regression = 24 passed
AE Web regression         = 393 passed
Slice Gate                = 5,550 passed / 44 protected skips
statement coverage        = 97.34%
branch coverage           = 95.67%
contract validation       = PASS (207 schemas / 271 examples / 231 negative / 9 OpenAPI)
```

## Closure

P8-DEMO-S10C is complete. The installed IA path now finalizes, publishes,
acknowledges, and exposes an owner-private result through the existing durable
tables, while restart and replay preserve exactly-once business effects.
