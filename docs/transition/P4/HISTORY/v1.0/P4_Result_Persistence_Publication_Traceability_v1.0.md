# P4 Result Persistence and Publication Traceability v1.0

> **SUPERSEDED:** Historical P4 v1.0 record. Use the v1.1 baseline in the P4 parent directory.

**Status:** STEP 8.1 DESIGN PRESERVED / IMPLEMENTATION DEFERRED
**Companion:** `P4_Result_Persistence_and_Publication_Design_Hardening_FROZEN_v1.0.md`
**Scope review:** `P4_IA_Runtime_Foundation_Scope_Review_v1.0.md`

STEP 8.1 remains the approved design for future canonical AgentResult and
ResultDelivery work. The narrowed P4 IA Runtime Foundation has no authoritative
Project context and therefore cannot implement or claim conformant publication
preflight, ACK, or AgentExecution success.

P4's append-only Conversation journal, PERSONAL scope, and Conversation Weekly
Digest are transition-foundation records only. They do not satisfy or replace
canonical Project-partitioned Agent Memory, AgentResult, or ResultDelivery.

The table below preserves every obligation without assigning false P4 evidence.

| ID | Design obligation | P4/Frozen source | Narrowed P4 disposition | Future evidence |
|---|---|---|---|---|
| P4-HDN-T01 | Persist and reconstruct the complete AgentResult envelope. | P4-RES-001/002; AgentResult schema | `DEFERRED_CANONICAL_RESULT` | Schema-valid round-trip contract test. |
| P4-HDN-T02 | Normalized columns equal envelope and structured result fields. | P4-PER-005; HDN-001 | `DEFERRED_CANONICAL_RESULT` | Repository parity plus PostgreSQL smoke. |
| P4-HDN-T03 | Reject raw private-content duplication in runtime metadata. | P4-DATA-001/003/004/005 | Principle applies now in P4-S3/P4-S5/P4-S8; AgentResult part deferred. | Privacy scan and negative fixtures. |
| P4-HDN-T04 | Calculate deterministic semantic `result_hash`. | P4-RES-010; HDN-003 | `DEFERRED_CANONICAL_RESULT` | Fixed canonical JSON/hash vectors. |
| P4-HDN-T05 | Treat semantic AgentResult as immutable. | P4-IMM-001/002/003/004 | `DEFERRED_CANONICAL_RESULT` | Repository mutation rejection. |
| P4-HDN-T06 | Persist result, complete delivery plan, and publication job atomically. | P4-PER; HDN-004 | `DEFERRED_RESULT_PUBLICATION` | Fault injection with zero partial rows. |
| P4-HDN-T07 | Reuse identical result creation and reject semantic conflict. | P4-IDEMP-003 | `DEFERRED_CANONICAL_RESULT` | Equal/conflicting duplicate concurrency tests. |
| P4-HDN-T08 | Create exactly one required IA `WORKSPACE_RESULT`. | P4-DEL-002; ResultDelivery | `DEFERRED_RESULT_PUBLICATION` | Uniqueness and concurrency tests. |
| P4-HDN-T09 | Reject zero, missing, or incomplete required delivery plans. | P4-AC-07; HDN-005/008 | `DEFERRED_RESULT_PUBLICATION` | Empty/missing plan negative tests. |
| P4-HDN-T10 | Perform real `AS_OF_NOW` preflight on every attempt. | P4-CONSTRAINT-05; preflight schema | `DEFERRED_AUTHORITY_INTEGRATION` | Current allow/deny/revoke/scope tests. |
| P4-HDN-T11 | Preserve stable publication identity across retry/restart. | Publication protocol; HDN-006/007 | `DEFERRED_RESULT_PUBLICATION` | Deterministic identity and restart tests. |
| P4-HDN-T12 | ACK only after durable target confirmation. | P4-DEL-005/006/007/008 | `DEFERRED_RESULT_PUBLICATION` | Fresh-session readback success/failure tests. |
| P4-HDN-T13 | Never rerun legacy generation during publication retry. | Publication boundary; HDN-007 | P4-S7 proves the applicable compatibility continuation rule; publication retry remains deferred. | Provider call-count fault test. |
| P4-HDN-T14 | Finalize only after a valid non-empty plan and every required ACK. | P4-AC-07; HDN-008 | `DEFERRED_RESULT_PUBLICATION` | Transition and stale-version tests. |
| P4-HDN-T15 | Preserve disabled/shadow/required rollout semantics. | P4-ROLL-001..005 | P4-S5/P4-S9 applies modes only to IAChatRun; canonical runtime rollout remains deferred. | Three-mode service and integration tests. |
| P4-HDN-T16 | Recover pending publication after restart. | P4-JOB/LEASE; HDN-004/007 | `DEFERRED_RESULT_PUBLICATION` | PostgreSQL restart/reclaim smoke. |
| P4-HDN-T17 | Preserve authenticated Chat/RAG behavior. | P4-COMP-001..011; P4-AC-01 | P4-S1/P4-S7/P4-S9 | Owning-service regression and existing Playwright golden journey. |
| P4-HDN-T18 | Keep Frozen assets byte-identical. | P4-AC-11 | P4-S9 | Frozen checksum verification. |

## Narrowed P4 PostgreSQL Smoke

P4 protected smoke proves only the accepted foundation boundary:

1. apply AE migrations to the isolated AE test database;
2. issue concurrent first authenticated prompts and prove exactly one trusted
   IA, ACTIVE assignment, and PERSONAL scope;
3. create one Workspace and at least two project-neutral Conversations;
4. append ordered message/event references under owner isolation and prove no
   ordinary journal mutation path;
5. create mock-composed digest OPEN snapshots, FINAL, and late ADDENDUM with
   stable source watermarks and event-set hashes;
6. admit and deduplicate IAChatRun;
7. claim, expire, reject stale commit, and reclaim an IA runtime job;
8. complete compatibility lineage exactly once;
9. query through a fresh session after restart, retry duplicate operations,
   and prove stable row counts;
10. clean smoke-owned rows/objects and prove zero residue.

The smoke must not create placeholder Projects, AgentResult, ResultDelivery,
publication preflight, ACK, or canonical AgentExecution rows.

## Quality Cadence

- Slice Gate for every source Slice except where a broader gate is named;
- Checkpoint Gate at P4-S5;
- Full Gate at P4-S9;
- immediate Full Gate escalation for unexplained migration, trust, restart,
  idempotency, or coverage regressions.
