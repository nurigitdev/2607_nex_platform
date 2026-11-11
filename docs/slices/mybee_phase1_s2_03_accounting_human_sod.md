# MyBee Phase 1 S2-03 Accounting Human SoD

## Status

- Slice: `S2-03`
- Status: implemented and verified
- Dependency: `S2-02`
- Requirements: `SRS-APR-001`, `SRS-APR-002`, `SRS-APR-003`,
  `SRS-APR-005`, `SRS-APR-008`, `SRS-FX-023`, `SRS-SEC-002`,
  `SRS-SEC-003`, `SRS-SEC-005`
- Gates: `G-HUMAN`, `PG-OA`

## Boundary

S2-03 consumes a terminal WC `BUSINESS_FORMAL` decision for the S2-02 scoped
approval case. EOS admits the exact case, stage, work-item, decision, event and
candidate review lineage before advancing the case. WC approval produces only
the cross-service observation `ACCOUNTING_APPROVED_PENDING_POST`; it never
means that a journal has been posted.

The existing v1 approval-instance transition remains available. The decision
API dispatches only `eos.scoped-approval-case:*` resume targets to this v2
accounting boundary.

## Candidate Review Snapshot

VoucherCandidate v2 is owned by S3 and does not yet exist as an authoritative
EOS aggregate. S2-03 therefore does not create a provisional candidate model.
Instead, the S2-02 request may carry one immutable accounting review context
bound to the candidate ID, revision and hash plus document, FX, rule-release
and accounting-period hashes.

The review snapshot also retains the display-safe FX facts required by
`SRS-FX-023`: source currency and amount, market base rate, reference date,
publication, functional currency and amount, and any exception. S3 may replace
request-time admission with an authoritative candidate lookup without changing
the approval evidence contract.

## Persistence

Migration `2528_eos_accounting_approval_human.sql` adds:

- `eos_acct_approval_context`: immutable candidate review snapshot;
- `eos_scoped_approval_decision`: immutable WC/OA decision lineage;
- `eos_accounting_approval_evidence`: immutable final accounting proof v2.

The case row remains the workflow cursor and advances with optimistic version
matching. Decision, event, outbox and work-item identities are unique per
tenant. Exact replay is idempotent; mixed identities, semantic drift, duplicate
stage decisions and delayed or out-of-order terminal events fail closed.

## Human Trust And SoD

- A Human approver must have fresh OA `finance:journal:approve` authority and
  the active policy-stage role.
- An optional OA `company_ids` projection restricts authority to those
  companies. Its absence represents a tenant-wide finance grant; a malformed
  projection is denied.
- The requester, VoucherCandidate preparer, sole business approver, and any
  agent/job/service principal cannot perform accounting approval.
- WC's earlier `approval:decide` proof is preserved as lineage, while EOS
  independently rechecks current OA authority at event consumption time.
- OA role matching is case-insensitive because OA normalizes role values;
  organization and Project scope identifiers retain exact matching.
- Revoked, inactive, wrong-tenant, wrong-company, malformed, or unavailable
  authorization is distinguished and handled fail closed.

## Evidence And Projection

The final proof includes company, candidate ID/revision/hash, document hash,
FX hash, rule-release hash, accounting period, Human approver, policy hash, WC
final decision, OA authorization revision, decision time and deterministic
proof hash. The MyBee projection exposes only the user-facing signoff fields
and deliberately redacts the full OA authorization chain.

## Recovery

The EOS decision and case transition commit before the next-stage WC
publication. If publication fails, replay of the same WC event reuses the
recorded decision and retries deterministic publication without creating a
second decision or evidence row. Concurrent same-semantics insertion is
admitted as replay; changed semantics are rejected.

## Verification

- Focused unit/regression: `69 passed`; protected PostgreSQL case separated.
- Focused S2-03 coverage: statement `97.66%`, branch `99.40%` aggregate.
  - accounting approval service: statement `97.34%`, branch `99.32%`;
  - signoff projection and accounting decision API: statement/branch `100%`.
- Actual `nex_eos_test` protected smoke: passed.
  - connected as `nex_eos_user` to `nex_eos_test`;
  - applied every EOS migration in an isolated PostgreSQL schema;
  - committed Human approval and one accounting proof;
  - rejected direct proof mutation with the PostgreSQL trigger;
  - dropped the isolated schema after the test (zero residue).
- NeX-EOS Slice Gate: `1181 passed`, `38 skipped`; statement coverage
  `97.07%`, branch coverage `96.34%`.
- OpenAPI/contract validation: `233` schemas, `292` examples, `245` negative
  examples and `10` OpenAPI documents passed.
- Golden Journey transition and product dependency audits: passed.
- Machine-readable evidence:
  `reports/quality/mybee-s2-03-nex-eos.coverage.json`.

## Deferred

- S3 VoucherCandidate authoritative lookup and stale-review reconciliation
- S4 controlled posting and `POSTED` state
- richer accounting organization responsibility projection if OA adds a
  dedicated company-accounting assignment contract
