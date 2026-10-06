# Platform Production Readiness Plan

Status: Canonical scope freeze for requirements S141 through S150. S141 is
active; production deployment remains unapproved.

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
