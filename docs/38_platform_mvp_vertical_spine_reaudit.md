# Platform MVP Vertical-Spine Current-State Re-Audit

Status: S131 current-state checkpoint complete; integrated MVP acceptance is
not yet complete.

This document is the canonical result of the S131 repository re-audit. It
records what is actually implemented across OA -> AE Web/API -> CX -> MO -> AG,
which boundaries are reusable, and which gaps must be closed without changing
the frozen S131-S140 direction in
[37 Platform MVP Integration and Release Plan](37_platform_mvp_integration_release_plan.md).

## Executive Decision

The service ownership model remains sound. OA owns identity and trust, AE owns
the user workspace and artifacts, CX owns private content/retrieval/generation
lineage, MO owns provider connectivity, and AG owns redacted operator
projections. No service merge or shared database is required.

The repository contains most component capabilities needed by the MVP spine,
but it is not yet one deployable or accepted vertical runtime. S132 must first
materialize the topology and remove unsafe integration defaults. Subsequent
requirements must prove restart-safe PostgreSQL and protected end-to-end
journeys rather than infer them from distributed component tests.

## Current Implementation

| Area | Verified implementation | Remaining integration boundary |
| --- | --- | --- |
| OA -> AE trust | OA login, session, token issue/introspection/revocation, AE session facade, audience-bound service identity, trace propagation, and browser redaction exist. | Defaults remain `mock`/`TEST_MOCK`; the checked-in profile does not activate OA-backed signed trust, and secure cookies are profile-dependent work. |
| AE Web/API -> CX | Eight HTTP clients cover upload, documents, retrieval, generation, async generation, recovery, repair, and artifact source reads with owner/service/trace context. | Protected profiles must fail closed instead of falling back to `local-tenant`/`local-user`; seven clients independently own CX base URL configuration. |
| CX -> MO | Embedding, reranking, and generation use three MO capability routes and aliases. CX has no direct remote provider host reference. | CX uses 5-second client timeouts while MO upstream budgets are 15/15/60 seconds. Two live-capable aliases still have mock-oriented names. |
| AE artifacts -> AG | AE preserves interaction, CX generation, and content-hash lineage. AG has authenticated traced HTTP clients and raw-field denylists. | AG generation reads omit CX owner context. A dedicated ADMIN-scoped redacted CX audit API is required; AG must not guess an owner or read CX data directly. |
| AG operations | Job, event, log, worker, trace, generation, artifact, and governance projections are implemented. | Four AG adapters still read other service databases as legacy projection sources and must move behind service APIs. |
| Persistence/jobs | All five services attach service-local persistence and JobQueue controls. There are 89 SQL migrations and separate API/worker pools. | The aggregate runner does not coordinate migrations, readiness, AE Web, workers/daemons, restart, or durable reload. |
| Contracts/trace/privacy | 156 schemas, 214 positive examples, 184 negative examples, 7 OpenAPI specs, 13 traced HTTP clients, durable trace fields, and explicit redaction controls exist. | No single trace evidence spans the complete vertical journey, and executable named Golden Scenarios remain `0/10`. |

## Call Topology

The audit found 11 concrete HTTP capabilities over seven logical edges:

```text
Browser -> AE Web -> AE API -> OA
                         |-> CX -> MO
AG ---------------------|-> AE API/CX
AG ------------------------> all-service readiness
```

There are no cross-service Python package imports in the audited topology.
Provider host configuration is confined to MO. These are accepted foundations.
The 16 independently resolved base URL occurrences are configuration debt,
not a reason to introduce a shared domain package.

## Prioritized Gap Inventory

| ID | Priority | Gap | Required closure |
| --- | --- | --- | --- |
| `S131-GAP-01` | P0 | No typed runtime manifest or dependency-aware startup/readiness graph; AE Web and workers/daemons are omitted. | S132 |
| `S131-GAP-02` | P0 | Four AG cross-service database projection adapters bypass service API ownership. | S132/S138 |
| `S131-GAP-03` | P0 | CX-to-MO client timeout budgets are shorter than MO upstream provider budgets. | S132 |
| `S131-GAP-04` | P0 | No coordinated five-database migration, process restart, and durable reload proof. | S133 |
| `S131-GAP-05` | P0 | OA-backed signed trust is not materialized as the protected runtime profile. | S132/S134 |
| `S131-GAP-06` | P0 | AE owner context has local fallback instead of protected-profile fail-closed behavior. | S134/S135 |
| `S131-GAP-07` | P0 | AG generation audit is incompatible with owner-scoped CX reads and lacks a dedicated redacted admin API. | S138 |
| `S131-GAP-08` | P0 | The ten specified generation Golden Scenarios have no named executable aggregate runner. | S137/S140 |
| `S131-GAP-09` | P1 | AE/CX/AG HTTP transport, endpoint, token, timeout, and error translation are duplicated. | S132 |
| `S131-GAP-10` | P1 | Some worker modules lack canonical executable process entrypoints. | S132/S133 |
| `S131-GAP-11` | P1 | Two MO aliases encode mock implementation language despite supporting live routes. | S132/S136 |
| `S131-GAP-12` | P1 | Golden Scenarios are not yet bound to exact contracts, privacy checks, and recovery evidence. | S137/S140 |

## S132 Handoff

S132 should start with structure rather than feature expansion:

1. Define one typed runtime manifest for the five APIs, AE Web, required
   workers/daemons, ports, service URLs, persistence modes, provider modes,
   readiness dependencies, and timeout budgets.
2. Keep `local_mock` deterministic while materializing explicit protected
   profiles. Reject incomplete or contradictory protected configuration.
3. Replace AG cross-database source selection with typed service API clients,
   leaving S138 generation-audit projection details behind an explicit port.
4. Make aggregate startup readiness-gated and produce machine-readable process
   status without claiming S133 restart evidence early.
5. Preserve a rollback path to the existing service runner and mock-first
   quality gates until the new topology passes its closure Slice.

S132 does not need live model providers. Actual test databases begin at S133;
embedding/reranker evidence begins at S136, and generation evidence begins at
S137.

## Evidence

- S131 Slices: `1302` through `1311`.
- Checkpoint Gate: Slice 1306, `10,275 passed`, `24 skipped`, `98.89%`
  statement coverage, and `97.20%` branch coverage.
- Full Gate: Slice 1311, `10,910 passed`, `25 skipped`, `98.21%` statement
  coverage, and `97.06%` branch coverage.
- AE Web Node regression: `293 passed`, `0 failed`.
- Contract corpus: `156` schemas, `214` positive examples, `184` negative
  examples, and `7` OpenAPI documents.
- Closure runner: `9/9` audits and `11/11` checks passed.
- Database mutations: none for S131.
- Remote provider calls: none required for S131.

Any change to this inventory or the S132-S140 handoff must first update this
document and the canonical integration plan with the evidence that caused the
change.
