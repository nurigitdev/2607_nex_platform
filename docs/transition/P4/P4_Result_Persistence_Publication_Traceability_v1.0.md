# P4 Result Persistence and Publication Traceability v1.0

**Status:** STEP 8.1 DESIGN-TO-TEST BASELINE
**Companion:** `P4_Result_Persistence_and_Publication_Design_Hardening_FROZEN_v1.0.md`

STEP 9 shall replace each `TBD_STEP9` Slice cell with an approved P4 Slice and
concrete test path before implementation begins.

| ID | Design obligation | P4/Frozen source | Required evidence | Slice |
|---|---|---|---|---|
| P4-HDN-T01 | Persist and reconstruct the complete AgentResult envelope. | P4-RES-001/002; AgentResult schema | Schema-valid round-trip contract test | `TBD_STEP9` |
| P4-HDN-T02 | Normalized columns equal envelope fields and `structured_result_json`. | P4-PER-005; HDN-001 | Repository parity tests plus PostgreSQL smoke | `TBD_STEP9` |
| P4-HDN-T03 | Reject raw private-content duplication in runtime metadata. | P4-DATA-001/003/004/005 | Privacy scanner and negative fixtures | `TBD_STEP9` |
| P4-HDN-T04 | Calculate deterministic semantic `result_hash`. | P4-RES-010; HDN-003 | Fixed canonical JSON/hash vectors | `TBD_STEP9` |
| P4-HDN-T05 | Treat semantic AgentResult as immutable. | P4-IMM-001/002/003/004 | Repository/API update rejection tests | `TBD_STEP9` |
| P4-HDN-T06 | Persist result, complete delivery plan, and publication job atomically. | P4-PER; Frozen publication protocol; HDN-004 | Fault injection at each insert with zero partial rows | `TBD_STEP9` |
| P4-HDN-T07 | Reuse identical result creation and reject semantic conflict. | P4-IDEMP-003 | duplicate-equal and duplicate-conflict concurrency tests | `TBD_STEP9` |
| P4-HDN-T08 | Create exactly one required IA `WORKSPACE_RESULT`. | P4-DEL-002; Frozen ResultDelivery | service invariant, uniqueness, concurrency, PostgreSQL tests | `TBD_STEP9` |
| P4-HDN-T09 | Reject zero/missing/incomplete required delivery plans. | P4-AC-07; HDN-005/008 | empty-plan and missing-workspace negative tests | `TBD_STEP9` |
| P4-HDN-T10 | Perform real `AS_OF_NOW` preflight on every attempt. | P4-CONSTRAINT-05; Frozen preflight schema | allow/deny/revoke/current-scope contract tests | `TBD_STEP9` |
| P4-HDN-T11 | Preserve stable publication identity across retry/restart. | Frozen publication protocol; HDN-006/007 | deterministic identity and restart tests | `TBD_STEP9` |
| P4-HDN-T12 | ACK only after durable workspace target confirmation. | P4-DEL-005/006/007/008 | read-back success, missing target, and ambiguous failure tests | `TBD_STEP9` |
| P4-HDN-T13 | Never rerun legacy generation/business work during publication retry. | Frozen publication boundary; HDN-007 | call-count fault test with generation count unchanged | `TBD_STEP9` |
| P4-HDN-T14 | Finalize only after valid non-empty plan and every required ACK. | P4-AC-07; HDN-008 | transition matrix and stale-version tests | `TBD_STEP9` |
| P4-HDN-T15 | Preserve disabled/shadow/required rollout semantics. | P4-ROLL-001..005 | three-mode unit, service, and integration tests | `TBD_STEP9` |
| P4-HDN-T16 | Recover pending publication after process restart. | P4-JOB/LEASE; HDN-004/007 | actual PostgreSQL restart/reclaim smoke | `TBD_STEP9` |
| P4-HDN-T17 | Preserve legacy authenticated Chat/RAG behavior. | P4-COMP-001..011; P4-AC-01 | owning-service regression and Playwright golden journey | `TBD_STEP9` |
| P4-HDN-T18 | Keep Frozen assets byte-identical. | P4-AC-11 | three Frozen checksum manifests | P4 closure |

## Minimum PostgreSQL Smoke Assertions

The protected P4 database smoke shall prove actual SQL effects, not only
connection readiness:

1. apply all AE migrations to the isolated AE test database;
2. seed trusted tenant/IA/project/workspace context;
3. insert one execution and terminal legacy mapping fixture;
4. atomically create one AgentResult, one required workspace delivery, and one
   publication job;
5. query the rows through a fresh session;
6. validate envelope/schema/hash/projection parity;
7. perform a current preflight using deterministic test authority evidence;
8. confirm the durable workspace target and mark delivery ACK;
9. finalize the execution with the current version;
10. rerun duplicate admission/publication and prove row counts remain stable;
11. inject one transactional failure and prove zero partial rows;
12. delete only smoke-owned rows and prove zero residue.

Skipped protected smoke is not passing evidence. A protected smoke report shall
record executed, passed, failed, skipped, database identity, migration head,
row-count assertions, and cleanup result without exposing credentials.

## Quality Cadence

- Slice Gate for every source-code Slice;
- Checkpoint Gate at the fifth P4 Slice or earlier risk escalation;
- Full Gate at the tenth/closure Slice;
- immediate escalation to Full Gate for migration, trust, completion, or
  cross-service changes when the approved STEP 9 plan requires it.
