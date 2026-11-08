# P7-S6: WC WorkResult + AE Event Inbox / RESUME_EXECUTION

## Status

Completed on 2026-10-18. P7-S7 is authorized.

## Goal

Complete the result-return half of the P7 delegation loop without introducing
a second queue framework or allowing a stale background agent to resume its
parent execution.

```text
WC WorkResult + outbox
-> authenticated AE event inbox
-> durable WaitRegistration match
-> exactly one RESUME_EXECUTION RuntimeJob
```

## Implementation

- Added WC migration `1002_wc_work_result.sql` with the short
  `wc_work_result` table, result lineage, semantic hash, current Claim and
  Assignment authority, and result authorization evidence.
- Added an authenticated WC WorkResult route restricted to `nex-ae-api`.
- WorkResult commit atomically persists the result, moves WorkItem to
  `RESULT_SUBMITTED`, and creates `WORK_RESULT_SUBMITTED` in the existing WC
  outbox. A repeated identical result is idempotent; identity, revision,
  contract, Claim generation, Assignment, agent, or authorization drift fails
  closed.
- Reused `nex_runtime.JobQueue` and the existing `WC_EVENT_DELIVERY` technical
  job type. Job payloads contain only `outbox_id` and `event_id` references.
- Added AE migration `2404_ae_work_result_resume.sql` with the durable
  `ae_external_event_inbox`, wait match fields, and the `RESUME_EXECUTION`
  RuntimeJob type.
- AE event admission validates the Frozen-compatible event, locks the inbox
  and wait, verifies the child `CLAIMED_WORKITEM` execution authority, and
  atomically creates one stable resume job while retaining the parent
  execution and executable-step lineage.
- Wait-first, event-first, duplicate delivery, restart reconciliation,
  terminal parent, contract mismatch, and stale authority paths are covered.
- Added a thin AE-to-WC publication client that requires an exact WorkItem,
  result, and semantic-hash acknowledgement.

P7-S6 establishes result persistence, delivery, inbox, and resume semantics.
P7-S7 remains responsible for producing the actual background `AgentResult`
through the existing planner/runtime and invoking this publication boundary.

## PostgreSQL Evidence

The protected smoke applied and verified the current migrations against the
actual local test databases:

```text
nex_ae_test / nex_ae_user = migration 2404
nex_wc_test / nex_wc_user = migration 1002
```

The journey committed one WorkResult, replayed it idempotently after repository
restart, persisted the outbox `PENDING -> ENQUEUED -> DELIVERED` lifecycle,
matched one AE inbox event, moved the wait to `RESUME_QUEUED`, and persisted
exactly one `RESUME_EXECUTION` job. Duplicate event delivery reused that job,
and cleanup verified zero owned residue.

## Verification

- Focused P7-S6 tests: `42 passed` against actual AE/WC test PostgreSQL.
- WC Slice Gate: `126 passed`; statement `96.66%`, branch `94.19%`.
- AE Slice Gate: `4448 passed`, `11 skipped`; statement `98.32%`, branch
  `96.23%`.
- Contract validation: schemas `174`, examples `236`, negative examples `204`,
  OpenAPI documents `8`.
- Ruff on all changed Python files: PASS.

The skipped AE tests are separately protected historical smoke suites whose
own enable flags were not requested by this Slice. The P7-S6 actual PostgreSQL
test ran and passed inside both the focused and service regression evidence.
