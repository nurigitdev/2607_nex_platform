# Platform MVP Release-Candidate Acceptance And Operations Closure

Status: S140 active through Slice 1398.

## Required Outcome

S140 executes one protected platform release-candidate matrix across OA, AE
Web/API, CX, MO, and AG. The matrix must prove all ten named generation golden
scenarios, all five service-owned test databases, restart-safe state, all three
live model-provider capabilities, Korean-default desktop/mobile browser
acceptance, redacted operations evidence, contracts, privacy, Full Gate, and
zero owned database/file residue.

Passing S140 means the MVP is a release candidate. It does not mean production
deployment approval.

## Boundary

- OA owns identity, sessions, signed user/service trust, JWKS, introspection,
  revocation, group membership, and authorization policy.
- AE owns workspaces, chat lineage, user-visible responses, artifacts, and the
  same-origin browser facade. The browser never calls another service directly.
- CX owns private source material, ingestion, retrieval, generation, citation,
  repair, and structured-draft lineage.
- MO owns provider aliases, routing, retry, readiness, telemetry, and runtime
  observations. CX reaches live providers only through MO capability aliases.
- AG reads redacted service APIs and owns operator projections and audit
  evidence. It never reads another service's database.
- Cross-service database reads and browser-supplied ownership are prohibited.
- Protected evidence uses only `nex_oa_test`, `nex_ae_test`, `nex_cx_test`,
  `nex_mo_test`, and `nex_ag_test`.
- Release-candidate evidence may retain opaque IDs, hashes, bounded status,
  counts, model revisions, durations, and safe routes. It must not retain
  passwords, tokens, prompts, source/evidence/generated text, file payloads,
  storage references, provider endpoints, database URLs, or private keys.

## Golden Scenario Matrix

The authoritative scenario semantics remain in
`docs/28_generation_e2e_acceptance_contract_test_plan.md`.

| Scenario | RC Evidence |
| --- | --- |
| `GEN-E2E-001` | General answer skips retrieval and citations. |
| `GEN-E2E-002` | Permission-filtered grounded answer uses valid evidence and citations. |
| `GEN-E2E-003` | Report generation produces owner-scoped MD and DOCX artifact files. |
| `GEN-E2E-004` | No-answer or low-confidence retrieval blocks unsupported grounding. |
| `GEN-E2E-005` | Prompt/template mismatch fails before a provider call. |
| `GEN-E2E-006` | Provider timeout retry preserves input hashes and lineage. |
| `GEN-E2E-007` | Citation repair is bounded to the same retrieval package. |
| `GEN-E2E-008` | Render retry preserves the accepted structured draft and creates new work. |
| `GEN-E2E-009` | Cross-owner artifact download is denied and owner download succeeds. |
| `GEN-E2E-010` | AG exports metadata-only redacted audit evidence. |

## Slice Plan

| Slice | Scope |
| --- | --- |
| `1392` | Freeze the S140 RC boundary, eight gaps, and non-production completion signal. |
| `1393` | Define typed RC evidence, gate identities, and deterministic aggregation. |
| `1394` | Execute named deterministic `GEN-E2E-001` through `GEN-E2E-010`. |
| `1395` | Define protected profile admission for five databases, three providers, and two viewports. |
| `1396` | Re-run five-database migration, restart, restoration, and cleanup; run Checkpoint Gate. |
| `1397` | Execute live embedding, reranker, generation, calibration, and grounded-provider acceptance. |
| `1398` | Bind Korean browser evidence to AG trace, audit, and operations acceptance. |
| `1399` | Harden failure/recovery, privacy, zero-residue, and deployment-deferral evidence. |
| `1400` | Execute the complete protected release-candidate acceptance matrix. |
| `1401` | Publish the operator runbook, close S140, and run Full Gate. |

## Frozen Gaps

1. There is no typed platform release-candidate evidence and gate matrix.
2. The ten named `GEN-E2E` scenarios do not have one executable aggregate
   runner.
3. Protected admission does not yet require five exact test databases, three
   live provider capabilities, and both browser viewports as one profile.
4. Five-database restart and restoration evidence is not bound to the final RC
   decision.
5. Live embedding, reranking, generation, and model calibration evidence is not
   aggregated under one model-independent RC gate.
6. Browser completion is not yet correlated with AG trace, audit, and
   operations evidence in one RC decision.
7. Failure/recovery, privacy, zero-residue, and deployment deferrals are not a
   single fail-closed release checklist.
8. No protected runner executes and closes the entire RC matrix.

## Completion Signal

S140 completes only when all deterministic and protected gates pass, all ten
named scenarios pass, all protected resources are cleaned up, Full Gate passes
at the repository thresholds, and every production-only dependency remains an
explicit deferral rather than an implicit claim.

## Deployment Deferrals

The following remain outside MVP release-candidate acceptance and block any
claim of production deployment readiness:

- external signing-key custody or HSM/KMS integration;
- managed TLS termination and certificate lifecycle;
- production secret injection and rotation;
- enterprise IdP registration and production federation metadata;
- production object storage and lifecycle policy;
- production PostgreSQL backup, restore, HA, and disaster recovery;
- external notification/incident endpoints;
- production GPU scheduling, autoscaling, and capacity approval;
- production monitoring, paging, SLO ownership, and change approval.

## Slice 1392 Decision

The boundary is frozen without adding tables or contacting PostgreSQL, a model
provider, or a browser. Protected execution is deferred to Slice 1400 after
deterministic contracts, admission, restart, live-provider, browser/operations,
and recovery evidence are independently executable.

## Progress

- Slice 1392 froze the boundary, ten named scenarios, eight release gaps,
  protected matrix dimensions, zero-residue rule, and production deployment
  deferrals.
- Slice 1393 defined nine blocking typed gate identities. Evidence must have an
  exact inventory, unique IDs, a valid digest, bounded freshness, no private
  payload, and gate-specific metrics. Five gates require actual protected
  execution and no required gate may be skipped.
- Slice 1394 made `GEN-E2E-001` through `GEN-E2E-010` executable as one
  deterministic aggregate. It reuses production functions and in-memory
  service flows, emits metadata-only hashed evidence, and explicitly makes no
  PostgreSQL, live-provider, or browser execution claim.
- Slice 1395 added fail-closed protected admission. Five exact service-local
  test databases, three model-independent live provider capabilities, signed
  trust/API operations modes, and both browser viewports must be present before
  protected release-candidate execution can start.
- Slice 1396 bound the existing S133 migration/restart/restoration machinery to
  the typed `five_database_restart` RC gate. A fresh protected run reached,
  restored, cleaned, and confirmed absence in all five service-owned test
  databases with two process generations and zero database residue. The
  fifth-Slice Checkpoint passed `11,270` tests at `98.91%` statement and
  `97.29%` branch coverage after stale S131 golden-scenario expectations and
  overlapping Checkpoint coverage sources were corrected.
- Slice 1397 bound the existing three-provider, S136 hybrid
  retrieval/calibration, and S137 grounded artifact journeys to the typed
  `live_provider_matrix` gate. A fresh protected run passed all three provider
  capabilities, twenty calibration samples, actual CX/AE PostgreSQL work, and
  zero residue. Model revisions are runtime bindings rather than acceptance
  constants.
- Slice 1398 bound the protected S139 desktop/mobile Chromium journey and the
  S138 five-database service-API trace journey to `korean_browser_journey` and
  `ag_trace_operations`. A fresh run passed both viewports, all eight trace
  families, restart-safe AG audit, and zero database/file residue while
  keeping browser provider behavior deterministic.
