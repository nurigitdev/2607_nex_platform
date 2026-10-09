# Platform Pre-production Reliability, Security, and Recovery Acceptance

Status: S149 active through Slice 1491. The acceptance boundary,
release-bound workload profiles, bounded concurrency harness, and soak
stability evaluator, fault/recovery plan, Checkpoint Gate, and security/privacy
matrix, rollback rehearsal, and protected Single-host live orchestration are complete for
the Single-host Docker Compose staging topology. The protected target-workload
runner binds a 30-minute, 4 RPS, 7,200-request operation mix to the admitted
release candidate while keeping expensive provider calls explicitly capped.
Production deployment remains unapproved.

## Outcome

S149 proves that one immutable release candidate can sustain its declared
baseline, concurrency, and soak workloads while preserving SLOs, owner and
tenant isolation, restart recovery, rollback, and zero residue. It consumes
the production-shaped trust, PostgreSQL, RustFS, model-serving, and
observability controls completed by S144-S148. A passing result is staging
evidence for S150; it is not an implicit production deployment.

## Non-Drift Boundary

- The accepted topology is one Docker Compose host with OA, AE Web/API, CX,
  MO, AG, OpenBao, Traefik, five service-owned PostgreSQL databases, RustFS,
  and three remote model-provider capabilities.
- Evidence is bound to one release-candidate ID, immutable image/source
  digests, configuration digest, active SLO-policy digest, workload digest,
  fault-plan digest, and predecessor-evidence digests.
- Target load is explicit and bounded. A smaller test run may validate the
  harness but cannot claim production-sized capacity.
- Fault injection is allowlisted, reversible, time bounded, and followed by
  recovery and residue checks. Production resources are never targeted.
- Provider degradation is injected at the client or staging route boundary.
  S149 does not stop, mutate, or reconfigure the DGX provider processes.
- Security and privacy acceptance forbids cross-tenant reads, scope bypass,
  raw prompts, documents, generated content, vectors, credentials, endpoint
  URLs, database URLs, or physical storage paths in exported evidence.
- Failure of a required dependency is `FAIL` or `BLOCKED`; it is never
  converted into a passing degraded result.

## Workload and SLO Contract

The workload classes are `baseline`, `concurrency`, and `soak`. Every workload
profile declares arrival policy, concurrency, operation mix, warm-up,
measurement duration, cool-down, timeout, bounded data volume, and cleanup
budget. Initial targets are configuration-backed staging defaults and must be
tuned from measured evidence rather than embedded provider-specific constants.

The operation mix covers authenticated login and trust checks, document
upload-to-index, permission-filtered retrieval, grounded generation, artifact
access, AG operations reads, and persistence/readiness probes. Per-operation
results record only counts, latency buckets, safe reason codes, and opaque
correlation IDs.

The protected live mix preserves the admitted soak duration, target RPS, and
request count without applying the deterministic equal-weight mix to expensive
GPU operations. It executes 2,400 readiness probes, 1,440 OA trust reads, 1,440
AG operations reads, 720 CX ingestion persistence probes, 720 AE artifact
reads, 450 hybrid retrieval probes, and 30 grounded generation probes. Each
hybrid retrieval probe makes one embedding and one reranking call, so the
provider budgets are exactly 450 embedding, 450 reranking, and 30 generation
calls. Model names and revisions remain runtime configuration, not workload
constants.

The aggregate error-rate budget cannot hide a failed low-frequency capability.
All 450 hybrid retrieval operations and all 30 grounded generation operations
must succeed independently of the overall error-rate calculation.

Actual authenticated ingestion and grounded-generation/artifact journeys run
before and after the load as sentinels. The 7,200-request interval exercises
actual PostgreSQL and remote-provider boundaries; it is not represented as
7,200 complete browser journeys. A passing S149 result therefore requires both
sentinels, the bounded workload, and zero rehearsal residue.

Acceptance requires:

- all mandatory service SLOs remain `PASS`; `NO_DATA` is not acceptance;
- configured p95 latency, error-rate, throughput, saturation, queue-age, and
  freshness budgets pass for the exact workload profile;
- owner and tenant isolation has zero violations;
- retries, duplicate side effects, and cancellation remain within budget;
- recovery objectives pass after each injected fault; and
- cleanup leaves zero database rows, object versions, jobs, leases, alerts,
  notifications, and temporary runtime artifacts owned by the rehearsal.

## Fault and Recovery Matrix

Single-host S149 admits these reversible staging faults:

| Fault class | Injection boundary | Required evidence |
| --- | --- | --- |
| `service_restart` | one Compose service/process | readiness loss, bounded restart, durable state reconstruction |
| `database_connection_loss` | client/route boundary | pool invalidation, retry budget, recovery without cross-service DB access |
| `object_storage_degradation` | RustFS client/route boundary | fail-closed private payload access, retry, integrity-preserving recovery |
| `provider_degradation` | embedding/reranking/generation client route | timeout/error classification, bounded retry, no silent model substitution, recovery |
| `edge_or_trust_degradation` | Traefik/OpenBao staging route | fail-closed admission, key/session safety, readiness recovery |

Service failover in this topology means restart and state restoration on the
same host. It does not prove node failover.

## Security and Privacy Acceptance

S149 combines authorization-negative matrices, tenant/owner isolation,
service-token audience and scope denial, expired/revoked credential denial,
object-key traversal rejection, unsafe redirect and header rejection, evidence
redaction, and log/trace/alert privacy checks. Security checks run under load
and again after recovery; a recovered service with weakened authorization is a
failure.

## Rollback and Zero Residue

Rollback restores the exact last-known-good image set, configuration, schema
compatibility state, model alias/calibration binding, and storage routing. It
must preserve committed user data while removing rehearsal-owned state. Every
fault has a named trigger, maximum exposure, recovery owner, last-known-good
reference, verification probes, and residue query.

## Single-host Backlog

The following capabilities cannot be honestly proven on one Compose host and
remain explicit post-S150 backlog rather than mocked success:

| Backlog ID | Deferred capability | Required future environment |
| --- | --- | --- |
| `multi_node_service_failover` | service rescheduling after node loss | multi-node orchestrator and replicated state |
| `postgres_automatic_failover` | primary loss and replica promotion | replicated PostgreSQL topology |
| `object_store_node_loss` | storage quorum and node-loss recovery | distributed object storage |
| `gpu_autoscaling_failover` | provider replica autoscaling and traffic shift | multiple GPU serving nodes/revisions |
| `external_dead_man_monitoring` | total host, power, and network-loss alerting | separate management node or external receiver |

These backlog items cannot satisfy a mandatory S149 gate. The S149 evaluator
must distinguish `NOT_APPLICABLE_SINGLE_HOST` from `PASS` and S150 must carry
the accepted topology limitation into its decision.

## Protected Acceptance

Protected evidence is explicit opt-in. It uses the six immutable images, the
Single-host Compose topology, actual five test databases, actual RustFS, and
the three live remote provider capabilities. It may inject only allowlisted
local faults and client-side provider degradation. External notification may
remain `EXTERNAL_NOT_ACTIVATED`; S150 then requires a time-bounded P1 waiver
and local compensating control before a `GO` decision.

## Slice Sequence

| Slice | Outcome |
| --- | --- |
| `1483` | **Complete.** Freeze workload, SLO, fault, security, recovery, zero-residue, Single-host, and distributed-backlog boundaries. |
| `1484` | **Complete.** Define release-bound workload profiles, operation mix, target budgets, and deterministic admission. |
| `1485` | **Complete.** Implement the bounded concurrency/load harness and metadata-only measurements. |
| `1486` | **Complete.** Implement soak windows, stability/leak trends, saturation, and SLO evaluation. |
| `1487` | **Complete.** Implement allowlisted fault injection, provider degradation, recovery state, and Checkpoint Gate. |
| `1488` | **Complete.** Execute security, authorization, tenant-isolation, and evidence-privacy acceptance. |
| `1489` | **Complete.** Implement rollback rehearsal, last-known-good restoration, cleanup, and zero-residue proof. |
| `1490` | **Complete.** Run protected Single-host Compose, PostgreSQL, RustFS, and remote-provider acceptance. |
| `1491` | **Complete.** Bind and execute the protected 30-minute target workload with pre/post actual journey sentinels and explicit provider-call caps. |
| `1492` | Execute allowlisted fault, security/privacy, and rollback checks while the protected workload is active. |
| `1493` | Aggregate release-bound evidence, classify topology limitations/backlog, and evaluate S150 admission. |
| `1494` | Publish the runbook, pass Full Gate, close S149, and activate S150. |

Checkpoint Gate runs at Slice 1487. Full Gate runs at Slice 1494.

## Completion Signal

S149 completes when deterministic and protected evidence is bound to one
release candidate, required Single-host gates pass under target workload and
fault scenarios, authorization isolation has zero violations, rollback meets
its recovery budget, rehearsal residue is zero, unsupported distributed
capabilities remain visible backlog, and S150 receives an explicit admission
result. Production deployment remains unapproved.
