# P8-S99: Canonical Project NSL Governed WRITE Skills and Tools

## Scope

P8-S99 admits four canonical Project mutation Skills from the owning NSL
repository without changing the historical P8-S98 READ artifact admission:

- `PROJECT.PROJECT.CREATE`
- `PROJECT.PROJECT.DEACTIVATE`
- `PROJECT.MEMBERSHIP.ADD`
- `PROJECT.MEMBERSHIP.REMOVE`

The source artifacts are fixed at NSL revision
`98a72a8df685c0bedb1d798e98b42369656cb071`. Runtime execution remains bound
to the separately admitted NSL v0.2.1 wheel from P8-S99A.

## Decisions

- Project creation and membership addition use `OperationKind.CREATE`.
- Logical Project deactivation and membership removal use
  `OperationKind.UPDATE`.
- Every Skill contains exactly one approval node and one governed WRITE.
- Tool contracts require atomic commit, stable idempotency, current
  preconditions, and explicit post-WRITE verification metadata.
- Human approval routing remains a Platform `RuntimePolicy` decision; source
  text grants no execution authority.
- Project mutations verify through `PROJECT.PROJECT.GET`; membership mutations
  use a filtered `PROJECT.MEMBERSHIP.LIST` read-after-write projection.
- The Platform adapter, EOS transaction, OA authorization, durable evidence,
  reconciliation, and verification execution remain outside the `.ns` source.

## Verification

- NSL focused Project READ/WRITE regression: `11 passed`
- NSL authoritative quality gate: `2320 passed`
- NSL statement coverage: `99.25%`
- NSL branch coverage: `98.05%`
- Historical S98 plus current S99 exact-source protected regression: `5 passed`
- Platform EOS Slice Gate: `663 passed`, `21 expected protected skips`
- Platform statement coverage: `99.03%`
- Platform branch coverage: `98.40%`
- Contract validation: `194 schemas`, `257 examples`, `222 negative examples`,
  and `9 OpenAPI` documents

The skipped PostgreSQL cases belong to protected runtime smoke profiles. P8-S99
adds no database mutation path; actual OA/AE/WC/EOS PostgreSQL and live-provider
acceptance remains scheduled for P8-S102.

## Exit

P8-S99 closes the deterministic source and exact-admission boundary. P8-S100
may connect these admitted Skills to IA clarification, RuntimePolicy, the
controlled-WRITE worker, and the canonical EOS routes.
