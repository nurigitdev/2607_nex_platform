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
