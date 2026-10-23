# P8-S73: EOS Stage Advance / Final ApprovalProof

## Status

Completed on 2026-10-23.

## Scope

NeX-EOS now consumes an immutable WC `BUSINESS_FORMAL` decision envelope and
atomically performs one of three state transitions:

```text
APPROVE + remaining stage -> close current stage and activate exactly one next stage
APPROVE + final stage     -> approve instance and issue immutable ApprovalProof
REJECT                    -> reject instance and cancel unopened stages
```

EOS remains the system of record for ApprovalInstance, ApprovalStage,
ApprovalDecision and ApprovalProof. WC remains the system of record for the
human WorkItem, fresh OA-authorized decision and decision event.

## Admission Boundary

The EOS transition service does not trust a WC event alone. It admits the
following immutable envelope read from the WC source of record:

```text
terminal WC ApprovalWorkItem
+ WC ApprovalDecision
+ WC ApprovalEvent
```

Admission verifies the exact tenant, deterministic stage-scoped work-item ID,
EOS provider/domain, stage source and resume refs, BusinessOperation and
protected-operation refs, resolved approver/role/OrgUnit/Project targets,
terminal state/version, decision identity, decision value, OA authorization
revision/ref/time, event type and trace lineage.

The WC work-item semantic hash and event ID are included in the EOS immutable
decision hash. They do not require additional mutable columns in
`eos_approval_decision`. A replay with any changed semantic binding fails
closed.

Fresh OA authorization remains a WC responsibility. EOS verifies the persisted
authorization evidence and bounded decision-time relationship before accepting
it. `NSL_WRITE` and `AGENT_FORMAL` evidence cannot enter this boundary.

## Atomic Transition

`SqlAlchemyEosApprovalTransitionRepository` locks the ApprovalInstance and
target stage before mutation. One database transaction contains:

1. append-only ApprovalDecision insertion;
2. active-stage terminal transition;
3. next-stage activation or unopened-stage cancellation;
4. ApprovalInstance version/state update;
5. final immutable ApprovalProof insertion when all ordered stages approved.

Optimistic row-count guards detect concurrent state changes in addition to the
PostgreSQL row locks. The WC decision ID is the replay identity. Exact replay
returns the persisted result, while a changed binding returns conflict.

## Final ApprovalProof

Migration `2511_eos_approval_proof` adds `eos_approval_proof`, and additive
migration `2512_eos_approval_proof_decision_fk` binds its final WC decision ID
to the exact tenant-qualified EOS decision row. At most one proof exists per
tenant-qualified ApprovalInstance. Its proof hash binds:

```text
ApprovalInstance and final ApprovalStage
BusinessOperationId
protected operation ref
payload hash
write-intent hash
policy hash
instance binding hash
ordered ApprovalDecision chain hash
final WC decision and EOS decision hash
```

`approval_proof_ref` is projected as an opaque stable EOS reference. Issuance
time is evidence metadata and is excluded from the deterministic proof hash.
No proof is emitted for rejection or an incomplete chain.

The same migration changes the stage activation constraint so a never-opened
stage may become `CANCELLED` after rejection without a fabricated
`activated_at` value.

## Runtime Wiring

The EOS dependency graph exposes `EosBusinessApprovalTransitionService` only
when the EOS database runtime exists. No new public HTTP route is introduced in
this Slice; S73 establishes the service/repository boundary consumed by the
next contract/API Slice.

## Verification

- Focused S73 unit/SQLite regression: `62 passed`.
- New transition module statement coverage: `100.00%`.
- New transition module branch coverage: `100.00%`.
- Final NeX-EOS service regression: `578 passed`, `17` protected skips.
- Actual migrations against `nex_eos_test`: `2511_eos_approval_proof` and
  `2512_eos_approval_proof_decision_fk` applied.
- Actual `nex_wc_test` + `nex_eos_test` protected smoke: `1 passed`, no skip.
- Protected smoke verified actual database/user identities, WC decision and
  outbox persistence, two-stage EOS transition, final proof, restart read,
  exact replay and zero residue in both databases.
- Final NeX-EOS Slice Gate: `578 passed`, `17` protected skips; service
  statement coverage `99.64%`, branch coverage `99.71%`; explicit S73 module
  coverage `100.00% / 100.00%`; contracts passed with `188` schemas, `250`
  examples, `217` negative examples and `9` OpenAPI documents.

Remote embedding, reranking and generation providers were not required.

## Exit Decision

P8-S73 is closed. P8-S74 may add the IA `BUSINESS_FORMAL` experience while
preserving the distinct EOS proof, WC human-task and NSL WRITE evidence
domains.
