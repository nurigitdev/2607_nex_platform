# Platform Production Readiness Plan

Status: Canonical scope freeze for requirements S141 through S150. S143 is
complete, S144 is active, and S145-S147 are ready; production deployment
remains unapproved.

## Program Outcome

S141 through S150 convert the S140 MVP release candidate into evidence that can
support an explicit production go/no-go decision. They do not treat a
production-shaped runtime profile as proof that production controls exist.

## Frozen Requirement Sequence

| Requirement | Title | Required outcome |
| --- | --- | --- |
| `S141` | Platform production-readiness re-audit and deployment boundary checkpoint | Re-audit all nine S140 production deferrals, mock/test-only paths, environment configuration, direct coupling, service ownership, operational gaps, and implementation order. |
| `S142` | Reproducible deployment packaging and environment topology | Build immutable, reproducible service/process artifacts and explicit dev, test, staging, and production deployment composition. |
| `S143` | Production configuration, secret, and TLS lifecycle | Fail closed on incomplete production configuration and prove external secret injection, rotation, TLS, and certificate lifecycle. |
| `S144` | OA production trust, key custody, and enterprise federation | Replace local signing custody with an external adapter and prove enterprise IdP, rotation, revocation, JWKS, and introspection. |
| `S145` | PostgreSQL production resilience and disaster recovery | Prove migration, pool sizing, backup, restore, failover, rollback, RPO, and RTO across all five service-owned databases. |
| `S146` | Private object-storage migration and lifecycle | Move private CX and AE payloads behind object-storage ports with encryption, versioning, retention, owner scope, and rollback. |
| `S147` | Production model-serving capacity and rollout resilience | Prove model-independent capacity, scheduling, calibration, canary, failover, and rollback for embedding, reranking, and generation. |
| `S148` | Platform observability, SLO, alerting, and incident integration | Define SLIs/SLOs and connect redacted metrics, logs, traces, alerts, paging, and external incident delivery. |
| `S149` | Pre-production reliability, security, and recovery acceptance | Execute load, soak, failure injection, failover, security, privacy, recovery, and rollback rehearsal in staging. |
| `S150` | Production release-candidate and go-live readiness closure | Aggregate staging evidence into an explicit production go/no-go decision without performing an implicit deployment. |

## S140 Production Deferral Baseline

| Deferral ID | Production control | Primary owner | Target requirement | State |
| --- | --- | --- | --- | --- |
| `external_signing_key_custody` | External signing-key custody or HSM/KMS integration | OA | `S144` | `DEFERRED` |
| `managed_tls_certificate_lifecycle` | Managed TLS termination and certificate lifecycle | Platform integration | `S143` | `DEFERRED` |
| `production_secret_injection_rotation` | Production secret injection and rotation | Platform integration with OA, AE, CX, MO, and AG | `S143` | `DEFERRED` |
| `enterprise_idp_registration` | Enterprise IdP registration and federation metadata | OA | `S144` | `DEFERRED` |
| `production_object_storage_lifecycle` | Production object storage and lifecycle policy | CX and AE | `S146` | `DEFERRED` |
| `production_postgresql_backup_ha_dr` | Production PostgreSQL backup, restore, HA, and disaster recovery | OA, AE, CX, MO, and AG database owners with platform coordination | `S145` | `DEFERRED` |
| `external_notification_incident_endpoints` | External notification and incident endpoints | AG | `S148` | `DEFERRED` |
| `production_gpu_scheduling_capacity` | Production GPU scheduling, autoscaling, and capacity approval | MO | `S147` | `DEFERRED` |
| `production_monitoring_paging_slo_approval` | Production monitoring, paging, SLO ownership, and change approval | AG and platform integration | `S148`, `S150` | `DEFERRED` |

## Non-Drift Rules

- S140 remains the accepted MVP release-candidate baseline.
- No S141 audit may convert a documented deferral into implemented evidence.
- OA, AE, CX, MO, and AG retain their existing data and capability ownership.
- Cross-service access remains HTTP/API contract based; shared database reads
  remain prohibited.
- Production secrets, endpoints, private payloads, and storage references must
  not enter source-controlled evidence.
- Mock and test modes remain valid regression baselines but cannot satisfy a
  production gate.
- A technology product is selected only when its boundary and acceptance
  requirements demand that decision.
- Slice Gate runs for every Slice, Checkpoint Gate at Slice 1406, and Full Gate
  at Slice 1411.

## Mock, Test, and Local-Only Path Baseline

These paths remain supported for development and regression. Every row is
`FORBIDDEN_IN_PRODUCTION`; a production profile must fail closed rather than
silently falling back to it.

| Path ID | Path class | Owners | Allowed scope | Production disposition | Transition target |
| --- | --- | --- | --- | --- | --- |
| `local_mock_profile_default` | Default profile and local process composition | Platform integration | local development and deterministic regression | `FORBIDDEN_IN_PRODUCTION` | `S142` |
| `memory_persistence` | In-memory queues, logs, events, and heartbeats | OA, AE, CX, MO, AG | local development and unit regression | `FORBIDDEN_IN_PRODUCTION` | `S142`, `S145` |
| `mock_model_provider` | Deterministic embedding, reranking, and generation provider | MO | local development and deterministic regression | `FORBIDDEN_IN_PRODUCTION` | `S147` |
| `test_mock_service_trust` | Mock service-token admission | OA and platform integration | local development and explicit compatibility tests | `FORBIDDEN_IN_PRODUCTION` | `S144` |
| `ae_mock_auth_session` | AE mock user/session facade | AE and OA | local development and browser regression | `FORBIDDEN_IN_PRODUCTION` | `S144` |
| `local_private_filesystem` | CX and AE private payload roots under local `/data` | CX and AE | local, test, and rollback-compatible staging adapters | `FORBIDDEN_IN_PRODUCTION` | `S146` |
| `local_model_filesystem` | MO model files under the local model root | MO | local model-provider development | `FORBIDDEN_IN_PRODUCTION` | `S147` |
| `test_database_profile` | Five service-local `_TEST_DATABASE_URL` targets | OA, AE, CX, MO, AG | protected test evidence only | `FORBIDDEN_IN_PRODUCTION` | `S145`, `S149` |
| `protected_opt_in_smoke` | Environment-enabled PostgreSQL, provider, and browser smoke runners | Platform integration and evidence owner | protected test or staging evidence only | `FORBIDDEN_IN_PRODUCTION` | `S149` |

## Environment and Production Admission Baseline

The typed `production` runtime profile currently selects PostgreSQL, live model
providers, signed service trust, service-API AG projections, OA-backed AE auth,
and secure AE session cookies. It requires 25 non-placeholder values: five
service database URLs, six service endpoints, eight signed-trust credentials,
and six live-provider endpoint or credential values. Mode conflicts, missing
values, and known placeholders fail closed.

This is configuration-shape evidence, not production control evidence. The
following gaps remain outside the production admission contract.

| Configuration gap ID | Current state | Owner | Target |
| --- | --- | --- | --- |
| `immutable_deployment_environment` | Typed process manifest exists; immutable packaged environment composition is not admitted | Platform integration | `S142` |
| `external_secret_provider_rotation` | Raw process environment values are required; external references, injection, and rotation are not admitted | Platform integration and all services | `S143` |
| `managed_tls_certificate_lifecycle` | HTTP and HTTPS endpoint shapes are accepted; managed certificate lifecycle is not admitted | Platform integration | `S143` |
| `external_signing_key_custody` | OA issuance remains fail-closed without an injected external signing provider | OA | `S144` |
| `enterprise_idp_registration` | OIDC verification primitives exist; production registration and federation metadata are not admitted | OA | `S144` |
| `postgresql_backup_ha_dr` | Connection and pool configuration exist; backup, restore, HA, RPO, and RTO are not admitted | Five database owners and platform integration | `S145` |
| `object_storage_lifecycle` | CX and AE use owner-private local filesystem adapters; production object storage is not admitted | CX and AE | `S146` |
| `external_incident_delivery` | AG HTTP transport settings exist; production endpoints and credentials are not required by the profile | AG | `S148` |
| `gpu_scheduling_capacity` | Live provider endpoints are required; GPU scheduling and capacity approval are not admitted | MO | `S147` |
| `monitoring_paging_slo_approval` | Operational telemetry exists; production paging, SLO ownership, and approval are not admitted | AG and platform integration | `S148`, `S150` |

## Runtime and Deployment Coupling Baseline

| Coupling ID | Current evidence | Production disposition | Owner | Target |
| --- | --- | --- | --- | --- |
| `cross_service_domain_imports` | Zero foreign service-package imports | `CLEAR` | Every service | Continuous guard |
| `non_mo_provider_endpoint_access` | Zero provider endpoint references outside MO service source | `CLEAR` | MO and every consumer | Continuous guard |
| `service_http_api_edges` | 11 client anchors across 7 logical API edges | `TARGET_BOUNDARY` | API producer and consumer pairs | Continuous guard |
| `ag_legacy_cross_database_adapters` | Four compatibility adapters remain; managed protected profiles require API projection and reject PostgreSQL projection mode | `FORBIDDEN_IN_PROTECTED_PROFILES` | AG | `S142` |
| `loopback_endpoint_defaults` | 45 local loopback occurrences across 25 Python files; production requires all six service endpoint settings | `FORBIDDEN_IN_PRODUCTION` | Platform integration and client owners | `S142`, `S143` |
| `source_tree_process_commands` | All 13 manifest processes execute repository source commands | `REPLACE_WITH_IMMUTABLE_ARTIFACTS` | Platform integration | `S142` |

Shared `nex_runtime` infrastructure imports are allowed. Service-owned domain
package imports, cross-service database reads, and direct model-provider access
outside MO are not allowed. The retained AG adapters and loopback defaults are
compatibility mechanisms, not accepted production routes.

## Production Control Responsibility Matrix

`Accountable` owns the control decision and accepts its implementation
evidence. `Responsible` implements and operates the control. `Coordinator`
orders cross-service work but does not acquire another service's data or
domain ownership.

| Production control ID | Accountable | Responsible | Coordinator | Implementation target |
| --- | --- | --- | --- | --- |
| `external_signing_key_custody` | OA | OA | Platform integration | `S144` |
| `managed_tls_certificate_lifecycle` | Platform integration | Platform integration | Platform integration | `S143` |
| `production_secret_injection_rotation` | Platform integration | OA, AE, CX, MO, AG for their own secrets | Platform integration | `S143` |
| `enterprise_idp_registration` | OA | OA | Platform integration | `S144` |
| `production_object_storage_lifecycle` | CX and AE for their own namespaces | CX and AE | Platform integration | `S146` |
| `production_postgresql_backup_ha_dr` | OA, AE, CX, MO, AG for their own databases | Each database owner | Platform integration | `S145` |
| `external_notification_incident_endpoints` | AG | AG | Platform integration | `S148` |
| `production_gpu_scheduling_capacity` | MO | MO | Platform integration | `S147` |
| `production_monitoring_paging_slo_approval` | AG for operations; Platform integration for release approval | OA, AE, CX, MO, AG provide service signals; AG operates aggregation and paging | Platform integration | `S148`, `S150` |

Responsibility rules:

- OA owns identity, federation, token, and signing-key policy.
- AE owns browser/API session facade behavior, chat/workspace orchestration,
  rendered artifacts, and its private payload namespace.
- CX owns source content, extraction, indexing, retrieval, grounded-generation
  orchestration, and its private payload namespace.
- MO exclusively owns external model-provider access, model catalog, runtime
  telemetry, calibration binding, and GPU-serving operations.
- AG owns cross-service operational projections, audit, alert aggregation,
  paging, and external incident dispatch, through service APIs.
- Each backend owns its own PostgreSQL schema, migration, pool, backup, restore,
  and recovery evidence. Cross-service database reads remain prohibited.
- Platform integration owns packaging, topology, environment admission, TLS,
  coordinated rollout, staging acceptance, and the explicit go/no-go packet;
  it does not own service domain data.

## Operational Incompleteness Register

Every row remains `OPEN`. `P0` means production admission is blocked without
the control. `P1` means the control must be complete before S149 acceptance or
must have an explicitly approved dependency and rollback plan.

| Operational gap ID | Domain | Priority | Owner | Target | Required evidence |
| --- | --- | --- | --- | --- | --- |
| `secret_rotation_operations` | trust/configuration | `P0` | Platform integration and all services | `S143` | External injection, rotation, revocation, restart, and no-secret evidence |
| `tls_certificate_operations` | trust/configuration | `P0` | Platform integration | `S143` | TLS termination, renewal, expiry alert, and rollback rehearsal |
| `signing_key_custody_rotation` | trust | `P0` | OA | External custody, rotation, overlap, revocation, JWKS, and restart evidence |
| `enterprise_federation_operations` | trust | `P1` | OA | IdP registration, metadata rollover, login denial, and outage recovery |
| `postgres_backup_failover_restore` | data | `P0` | Five database owners and Platform integration | `S145` | Backup, point-in-time restore, failover, rollback, RPO, and RTO evidence |
| `private_object_storage_lifecycle` | data | `P0` | CX and AE | `S146` | Encryption, owner scope, versioning, retention, restore, and rollback evidence |
| `gpu_capacity_scheduling` | model | `P1` | MO | `S147` | Capacity, concurrency, placement, saturation, and recovery evidence |
| `model_rollout_failover_calibration` | model | `P1` | MO and CX | `S147` | Model-independent canary, fallback, calibration, drift, and rollback evidence |
| `external_incident_dispatch` | incident | `P1` | AG | `S148` | Redacted delivery, retry, deduplication, outage, and recovery evidence |
| `monitoring_paging_slo_operations` | incident | `P0` | AG, Platform integration, and service owners | `S148` | SLI/SLO, alert, paging, ownership, escalation, and audit evidence |
| `staging_reliability_security_rehearsal` | release | `P0` | Platform integration and all services | `S149` | Load, soak, failure injection, security, privacy, recovery, and rollback evidence |
| `go_live_rollback_change_approval` | release | `P0` | Platform integration | `S150` | Fresh evidence manifest, approver decision, rollout, rollback, and residue checks |

The register covers all nine S140 deferrals and adds the three integration
controls needed to turn isolated production capabilities into an operable
release: model rollout/calibration, staging rehearsal, and explicit go-live
rollback/change approval.

## Implementation Dependency and Evidence Schedule

S142-S150 form a dependency DAG, not nine unrelated backlogs. Requirements in
the same wave may proceed in parallel, but closure evidence must satisfy every
listed dependency.

| Requirement | Wave | Completion dependencies | Evidence mode | External capability required |
| --- | --- | --- | --- | --- |
| `S142` | 0 | S141 closure | deterministic build plus protected process restart | none |
| `S143` | 1 | `S142` | protected staging injection/rotation/TLS | external secret manager; managed TLS/certificate endpoint |
| `S144` | 2 | `S143` | protected trust rotation/federation | external key custody; enterprise IdP |
| `S145` | 2 | `S143` | protected backup/restore/failover | production-like PostgreSQL topology |
| `S146` | 2 | `S143` | protected private payload migration/rollback | production-like object storage |
| `S147` | 2 | `S143` | protected capacity/canary/failover | GPU model-serving environment |
| `S148` | 3 | `S143`, `S144`, `S145`, `S146`, `S147` | protected telemetry/alert/incident delivery | monitoring and paging; external incident endpoints |
| `S149` | 4 | `S144`, `S145`, `S146`, `S147`, `S148` | integrated pre-production load/security/recovery | integrated staging environment |
| `S150` | 5 | `S149` | fresh aggregate evidence and explicit decision | change approval authority |

Execution rules:

- S142 first removes source-tree packaging ambiguity and materializes explicit
  environment topology.
- S143 then establishes the secret and transport boundary required by every
  external production integration.
- S144-S147 may proceed in parallel after S143, with independent rollback and
  protected evidence.
- S148 may build its framework earlier, but cannot close until S144-S147 emit
  production-shaped signals and incident metadata.
- S149 runs only after all trust, data, storage, model, and observability
  controls close.
- S150 consumes fresh S149 evidence, records an explicit go/no-go decision,
  and never performs an implicit production deployment.

## Production Evidence, Privacy, Rollback, and Decision Contract

Every S142-S150 protected result must provide a metadata-only envelope with
these fields: `schema_version`, `evidence_id`, `requirement_id`, `control_ids`,
`release_candidate_id`, `environment_class`, `execution_mode`,
`actual_execution`, `started_at`, `completed_at`, `source_revision`,
`artifact_digests`, `configuration_digest`, `dependency_evidence_digests`,
`checks`, `metrics`, `privacy`, `rollback`, `residue`, and `evidence_digest`.
Digests must be computed over a canonical serialization and dependency digests
must bind the exact upstream evidence consumed by the run.

Source-controlled or exported evidence must not contain fields for `secret`,
`password`, `token`, `api_key`, `cookie`, `authorization`, `database_url`,
`provider_endpoint`, `private_payload`, `source_document`, `prompt_content`,
`physical_storage_path`, or `signing_private_key`. Counts, opaque IDs, and
one-way digests are allowed; raw values are not.

Freshness classes:

| Class | Requirement |
| --- | --- |
| `BUILD_BOUND` | Artifact and configuration digests must exactly match the candidate; wall-clock age alone cannot validate a different build. |
| `RELEASE_WINDOW_72H` | S142-S148 component evidence consumed by S149 must be no older than 72 hours and belong to the same release candidate. |
| `GO_LIVE_WINDOW_24H` | Integrated S149 evidence consumed by S150 must be no older than 24 hours. |
| `IMMEDIATE_PREFLIGHT_4H` | Trust, database, storage, provider, monitoring, and incident readiness must be re-probed within 4 hours of the S150 decision. |

Every rollback object must include `plan_id`, `owner`, `trigger_conditions`,
`last_known_good_artifacts`, `last_known_good_configuration`,
`data_migration_strategy`, `drill_status`, `recovery_metrics`, and
`residue_counts`.

The S150 decision evaluator has ten mandatory gates:
`all_dependency_evidence_passed`, `evidence_fresh`,
`artifact_configuration_digest_exact`, `no_open_p0`, `p1_waivers_valid`,
`privacy_clean`, `rollback_drill_passed`, `zero_residue`,
`approval_roles_complete`, and `production_deployment_separate`. A P1 waiver
must name its owner, risk, expiry, compensating control, and rollback trigger.
The only decision states are `GO` and `NO_GO`; there is no implicit or
conditional deployment state.

## S141 Slice Plan

| Slice | Scope |
| --- | --- |
| `1402` | Freeze the production-readiness boundary, nine deferrals, audit surfaces, and S142 handoff. |
| `1403` | Inventory and trace every S140 production deferral to an owner and target requirement. |
| `1404` | Audit mock, local-only, test-only, filesystem, and protected opt-in execution paths. |
| `1405` | Audit environment profiles, configuration sources, secrets, and production fail-closed behavior. |
| `1406` | Audit direct imports, direct provider calls, cross-database access, and deployment coupling; run Checkpoint Gate. |
| `1407` | Freeze service and platform responsibility assignments for every production control. |
| `1408` | Inventory operational incompleteness across trust, data, model, and incident lifecycles. |
| `1409` | Freeze the dependency-ordered S142-S150 implementation and protected-evidence schedule. |
| `1410` | Harden production evidence, privacy, rollback, and go/no-go contract requirements. |
| `1411` | Publish the canonical re-audit, close S141, run Full Gate, and activate S142. |

## S141 Completion Signal

S141 completes when nine repository-grounded audits pass, all nine S140
deferrals have an explicit owner and target requirement, mock/test-only and
direct-coupling debt is visible, production gaps are prioritized, and the
S142-S150 dependency order is fixed. S141 performs no production deployment
and requires no production credential, database, object store, IdP, or model
provider connection.

Any scope change must update this document first and identify the evidence or
dependency that caused the change.

Completion signal: Met. The canonical result is recorded in
`docs/49_platform_production_readiness_reaudit.md`, and the repeatable audit
procedure is recorded in
`docs/runbooks/platform_production_readiness_reaudit.md`. All nine repository
audits pass, all production gaps remain explicit, and no production resource
was contacted. S140 remains the release-candidate rollback baseline while S142
starts reproducible packaging and topology work.

At the S141 closure boundary, S141 is complete; production deployment remains
unapproved, and S142 is the active requirement. This historical handoff remains
the immutable input to the completed S142 work below.

## S142 Completion Update

S142 completed through Slice 1421 with six owner-scoped artifact definitions,
integrity-locked Python and Node inputs, exact process bindings, four explicit
environment compositions, deterministic packaged lifecycle rules, provenance,
and protected package-context restart evidence against all five test databases.
No final OCI image set was published because the execution host lacks Docker
socket access; this prerequisite remains explicit and production deployment is
still unapproved. S143 is now active for external secret injection, rotation,
managed TLS, and certificate lifecycle.

After the Slice 1421 closure, Docker access was restored on the approved local
build host. Supplemental Slice 1422 adds protected six-image build, inspection,
network-isolated background checks, and ignored local release-set reporting.
It does not publish to a registry or alter the S143 production-approval state.
At that historical handoff boundary, S142 is complete and S143 is active;
production deployment remains unapproved.

## S143 Completion Update

S143 completed through Slice 1432 with fail-closed production-shaped
configuration, sixteen owner-scoped external references, MO-only provider
credential custody, rolling generation rollback, and managed TLS lifecycle.
The protected single-host Docker Compose acceptance used OpenBao and Traefik
containers, five actual PostgreSQL test databases, six immutable application
images, and three live DGX provider capabilities. Its value-free attestation
binds the source, release set, configuration, and ignored reports.

S143 performed no registry push or production contact. Production deployment
remains unapproved. The wave-two requirements S144, S145, S146, and S147 may
now proceed independently under their existing owners and protected evidence
contracts; S148 closure remains dependent on all four.

## S144 Activation Update

S144 starts at Slice 1433 on the accepted S143 single-host Docker Compose
topology. OpenBao Transit supplies staging external RSA-3072 custody and the
OpenBao OIDC provider supplies the TLS federation issuer; Traefik remains the
managed edge and `nex_oa_test` remains the only protected database target.
Logical process, network, policy, credential, and persistence isolation is
mandatory even though the containers share one host. No corporate IdP or
production resource is contacted, and production deployment remains
unapproved.

## S144 Completion Update

S144 completed through Slice 1442 on the accepted single-host Docker Compose
topology. The protected acceptance used the actual `nex_oa_test` migration
head, the committed six-image release set, OpenBao non-exportable RSA-3072
Transit custody and OIDC provider, and ten Traefik TLS routes. Its value-free
attestation binds source, artifacts, configuration, predecessor evidence, and
the ignored protected report.

S144 is complete and its S148 dependency is ready. The browser callback route,
state-cookie lifecycle, and redirect journey remain S149 integrated-staging
prerequisites. No corporate IdP, registry, or production resource was
contacted, and production deployment remains unapproved. S145 is the next
implementation requirement.
