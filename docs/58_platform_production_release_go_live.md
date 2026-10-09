# Platform Production Release-candidate and Go-live Readiness

Status: S150 active from Slice 1495. Production deployment remains unapproved.

## v1.0 Supported Topology

NeX Platform v1.0 supports one Single-host Docker Compose deployment containing
OA, AE API/Web, CX, MO, AG, their worker/daemon processes, Traefik, OpenBao,
RustFS, five service-owned PostgreSQL databases, and three remote model-provider
capabilities. The deployment target is one managed application host plus the
already-operated PostgreSQL and DGX provider endpoints.

The v1.0 decision proves this topology. It does not claim Kubernetes,
multi-node service failover, database HA, storage quorum, GPU autoscaling, or a
separate management plane.

## Distributed-environment Backlog

These capabilities are post-v1.0 backlog and must remain
`NOT_APPLICABLE_SINGLE_HOST`, never synthetic `PASS` evidence:

| Backlog ID | Deferred capability | Future environment |
| --- | --- | --- |
| `multi_node_service_failover` | service replica placement and host-loss failover | multi-host orchestrator |
| `postgres_automatic_failover` | database leader election and automatic failover | PostgreSQL HA topology |
| `object_store_node_loss` | quorum and storage-node loss recovery | distributed object storage |
| `gpu_autoscaling_failover` | GPU scheduling, replica autoscaling, and node failover | multi-node GPU serving |
| `external_dead_man_monitoring` | host-loss detection independent of the application host | external monitoring plane |

## Decision Contract

S150 consumes the immutable S149 release candidate and evaluates exactly ten
mandatory gates:

1. `all_dependency_evidence_passed`
2. `evidence_fresh`
3. `artifact_configuration_digest_exact`
4. `no_open_p0`
5. `p1_waivers_valid`
6. `privacy_clean`
7. `rollback_drill_passed`
8. `zero_residue`
9. `approval_roles_complete`
10. `production_deployment_separate`

The only decision states are `GO` and `NO_GO`. A `GO` is release authorization
metadata with no implicit deployment command. Missing or stale evidence,
unapproved P1 risk, an open P0, incomplete approval roles, or residue produces
`NO_GO`.

## Freshness and Immediate Preflight

- S149 integrated evidence uses `GO_LIVE_WINDOW_24H`.
- Trust, PostgreSQL, RustFS, provider, observability, and incident controls use
  `IMMEDIATE_PREFLIGHT_4H`.
- Artifact, source, configuration, workload, and fault-plan digests must bind
  the exact admitted release candidate.
- Generation-provider probes require reasoning mode `disabled`.

## External Notification

External notification remains `EXTERNAL_NOT_ACTIVATED`. A v1.0 `GO` therefore
requires either protected external delivery evidence or a named, time-bounded
P1 waiver with expiry, local compensating control, and rollback trigger. S150
does not manufacture or self-approve that waiver.

## Slice Sequence

| Slice | Scope |
| --- | --- |
| `1495` | Freeze the Single-host v1.0 topology, ten decision gates, and distributed backlog. |
| `1496` | **Complete.** Build the immutable release-candidate evidence manifest. |
| `1497` | **Complete.** Enforce evidence freshness and digest-chain admission. |
| `1498` | Define P0/P1 risk and waiver governance. |
| `1499` | Define approval roles, change window, and separation of deployment; run Checkpoint Gate. |
| `1500` | Compose the immediate trust/data/storage/provider/operations preflight. |
| `1501` | Rehearse cutover, rollback, and zero-residue controls. |
| `1502` | Implement the ten-gate `GO`/`NO_GO` evaluator. |
| `1503` | Execute protected Single-host v1.0 go-live readiness acceptance. |
| `1504` | Publish the runbook, run Full Gate, and close S150 without deploying. |

Checkpoint Gate at 1499 and Full Gate at 1504 are mandatory.

## Completion Signal

S150 completes when the exact release candidate has fresh metadata-only
evidence, every mandatory gate has an explicit result, the decision is exactly
`GO` or `NO_GO`, unsupported distributed capabilities remain backlog, and no
command performs an implicit production deployment.
