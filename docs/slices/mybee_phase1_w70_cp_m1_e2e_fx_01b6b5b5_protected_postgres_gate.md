# CP-M1-E2E-FX-01B.6B.5B.5 Protected PostgreSQL Gate and Resume Decision

## Scope

This Slice closes the installed WC assignment-dispatch boundary against actual
WC, OA, and AE PostgreSQL test databases. It proves that public WorkItem
creation, generic dispatcher route/claim, authoritative event delivery, and AE
handoff converge without direct smoke-side transition calls, business fixture
values, a database migration, or a remote model provider.

## Implemented Boundary

- added an opt-in protected Gate with strict database identity admission for
  `nex_wc_user/nex_wc_test`, `nex_ae_user/nex_ae_test`, and
  `nex_oa_user/nex_oa_test`;
- applies the current migrations for WC, AE, and OA before exercising the
  installed processes;
- creates WorkItems only through the public WC API and grants authority through
  OA membership and authorization APIs;
- runs two installed assignment-dispatch processes concurrently for `ROUTE`,
  closes them, restarts two processes for `CLAIM`, and verifies convergence to
  one Assignment, one Claim, and one outbox event;
- runs the existing WC event-delivery process with a bounded signed service
  token and verifies one authoritative AE handoff inbox and AgentExecution;
- restarts dispatcher and delivery processes and verifies idle replay;
- verifies an OA requester without `work:claim` remains `ROUTED` with no
  Assignment, Claim, or outbox mutation;
- verifies persisted dispatcher and event-delivery heartbeats;
- performs allowlisted tenant-scoped cleanup and verifies zero residue in all
  three databases;
- records only redacted database URLs, a hashed Agent ID, and non-secret
  process evidence.

## Concurrency Correction

The first actual concurrent run exposed a scheduler-local race: both processes
derived the same deterministic Job ID, and the losing enqueue surfaced
`job.duplicate_id` instead of converging. The scheduler now accepts that error
only when the persisted job has identical immutable dispatch semantics. A
missing or semantically different job fails closed as
`wc.assignment_dispatch_job_conflict`. Shared JobQueue behavior and transition
authority remain unchanged.

## Verification

| Evidence | Result |
|---|---|
| focused static-guard and Gate-runner tests | `5 passed, 1 skipped` |
| actual protected Gate | PASS, `15/15` checks |
| actual database identities | WC, AE, OA test database and role pairs admitted |
| concurrent route | one successful mutation; final state `ROUTED` |
| restart and concurrent claim | Assignment `1`, Claim `1`, outbox `1` |
| signed authoritative handoff | delivered outbox `1`, AE inbox `1`, AgentExecution `1` |
| replay and restart | dispatcher idle; delivery idle |
| fresh OA denial | state `ROUTED`; Assignment/Claim/outbox `0/0/0` |
| cleanup | WC, AE, OA remaining rows `0/0/0` |
| WC Slice Gate | `738 passed, 26 skipped` |
| WC coverage | statement `98.16%`, branch `95.95%` |
| contract and topology audits | PASS |
| remote provider | not required and not contacted |

Machine-readable local evidence is written to
`reports/quality/mybee-w70-01b6b5b5-protected-gate.json` and
`reports/quality/mybee-w70-01b6b5b5-nex-wc-slice-gate.json`.

## Decision

`CP-M1-E2E-FX-01B.6B.5B` is closed. The installed WC assignment dispatcher and
the existing event-delivery worker now prove authoritative route, claim, and
AE handoff on actual PostgreSQL with concurrency, restart, denial, heartbeat,
and zero-residue evidence. `CP-M1-E2E-FX-01B.7` may resume with decision `GO`.
