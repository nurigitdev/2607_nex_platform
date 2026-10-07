# Platform Reproducible Deployment Packaging and Environment Topology

Status: S142 active through Slice 1416; production deployment remains
unapproved.

## Required Outcome

S142 converts the S140 release-candidate source revision and S141 deployment
audit into immutable, reproducible deployment artifacts. It does not admit a
production environment or close the secret, TLS, database resilience, object
storage, GPU capacity, monitoring, or staging-rehearsal work owned by
S143-S150.

The accepted result must provide:

- digest-addressed artifacts built from declared and locked inputs;
- one explicit artifact owner for every API, web, worker, and daemon process;
- dev, test, staging, and production deployment topology without silent
  fallback between environment classes;
- deterministic dependency-ordered start, readiness, stop, restart, and
  rollback plans; and
- protected local evidence that exercises packaged entrypoints without
  contacting production resources.

## Artifact Boundary

Thirteen runtime processes are packaged into six owner-scoped artifacts.
Workers and daemons reuse their owning service artifact but have distinct,
immutable entrypoints. A single all-services Python image is prohibited because
it would erase service ownership and enlarge the deployment blast radius.

| Artifact ID | Owner | Process IDs |
| --- | --- | --- |
| `nex-oa-runtime` | OA | `nex-oa-api` |
| `nex-ae-runtime` | AE | `nex-ae-api`, `nex-ae-artifact-render-worker`, `nex-ae-retention-daemon` |
| `nex-cx-runtime` | CX | `nex-cx-api`, `nex-cx-async-generation-worker`, `nex-cx-ingestion-worker`, `nex-cx-remediation-worker` |
| `nex-mo-runtime` | MO | `nex-mo-api` |
| `nex-ag-runtime` | AG | `nex-ag-api`, `nex-ag-remediation-sync-worker`, `nex-ag-dispatch-daemon` |
| `nex-ae-web` | AE Web | `nex-ae-web` |

Each artifact identity is a repository-independent name plus an immutable
content digest. Mutable tags may be display aliases only and cannot be used by
an admitted staging or production topology.

## Packaged Entrypoint Admission

All thirteen process commands have package-relative forms. Python APIs use
module execution, AE Web uses its locked npm start command, and all seven
background roles use `python -m nex_runtime.background_process` with an
explicit process ID and profile. The source-tree script remains only as a thin
development compatibility wrapper.

Entrypoint presence is not treated as execution readiness. CX ingestion is the
only background role currently connected to a durable claiming loop through
this process shell. The other six roles prove import and lifecycle readiness
only. Their capability is recorded as `lifecycle_only`, and staging or
production background admission remains fail-closed until owner-specific
execution adapters receive separate protected evidence. Packaging must not
turn a passive process shell into a false production-readiness claim.

## Environment Topology

The existing runtime profiles remain the application-mode authority and map to
four deployment environment classes.

| Environment class | Runtime profiles | Intended evidence | Admission rule |
| --- | --- | --- | --- |
| `development` | `local_mock`, `local_live` | deterministic mock work or explicit local live integration | loopback and local storage are allowed only here |
| `test` | `test` | protected PostgreSQL and contract regression | test databases and explicit smoke opt-ins only |
| `staging` | `staging_live` | production-shaped rehearsal | immutable digests and externally injected configuration required |
| `production` | `production` | separately approved production rollout | immutable digests, no loopback/default fallback, and S143-S150 evidence required |

Profile selection, endpoint values, secrets, storage references, and database
URLs remain runtime configuration. They are never baked into an artifact.
Production composition must fail closed if any artifact digest or required
external value is absent.

## Dependency and Startup Topology

The current 13-process dependency graph is preserved. Packaged topology must
materialize the same process IDs and dependency edges, use liveness only for
development mock startup, and use readiness for every protected profile.

Required lifecycle order is:

1. validate artifact digests and environment-class admission;
2. run each service-owned migration as a bounded pre-start operation;
3. start dependency layers and wait for the profile-appropriate probe;
4. start owner-scoped workers and daemons from their packaged entrypoints;
5. stop in reverse dependency order; and
6. restart or roll back to the complete previous artifact set, never a mixed
   implicit version set.

## Reproducibility Rules

- Python and Node production dependencies must be exact, integrity-verifiable
  build inputs. Range-only dependency files are not release locks.
- Base runtime images must resolve to immutable digests in admitted topology.
- Build contexts are owner scoped and exclude `.git`, environments, caches,
  reports, test evidence, local secrets, and private data.
- Artifact manifests contain no secret value, database credential, private
  payload, provider key, or machine-specific path.
- The same declared source tree and lock inputs must yield the same build-input
  digest. Runtime timestamps and evidence locations are excluded from it.
- Build provenance records source revision, lock digests, build definition
  digest, artifact digest, and toolchain identity.

## Current-State Audit

At Slice 1412 the repository already has five typed runtime profiles, six
endpoints, thirteen process definitions, an acyclic dependency graph, profile
aware probes, and deterministic local start/stop orchestration. It does not yet
have OCI build definitions, exact Python production locks, immutable artifact
manifests, process-to-artifact bindings, deployment compositions, build
provenance, or packaged lifecycle smoke evidence. All thirteen process commands
still execute repository source paths.

The measured gap register is:

1. `immutable_artifact_domain`
2. `exact_python_production_lock`
3. `oci_build_definitions`
4. `process_artifact_bindings`
5. `environment_compositions`
6. `packaged_process_commands`
7. `build_provenance_and_release_digest`
8. `packaged_lifecycle_acceptance`

These are implementation gaps, not production incidents. S142 evidence must
remain local or explicitly protected and must not contact production resources.

Slices 1413 through 1416 have closed the immutable artifact, exact lock, OCI
definition, process binding, and package-relative command portions of this
register. Environment compositions, provenance, and packaged lifecycle
acceptance remain open.

## Slice Sequence

| Slice | Scope | Exit evidence |
| --- | --- | --- |
| `1412` | Packaging and topology boundary audit | Canonical artifact/profile decisions and measured gap inventory. |
| `1413` | Immutable artifact manifest domain | Six artifacts, thirteen bindings, canonical serialization, and digest validation. |
| `1414` | Deterministic dependency and build-input lock | Exact Python/Node inputs and lock-integrity validation. |
| `1415` | Owner-scoped OCI build definitions | Reproducible Python service and AE Web image definitions with minimal contexts. |
| `1416` | Worker/daemon packaged entrypoint parity | Seven background roles mapped to owner artifacts; fifth-Slice Checkpoint Gate. |
| `1417` | Explicit environment compositions | Development, test, staging, and production topology with fail-closed profile rules. |
| `1418` | Packaged dependency/startup lifecycle | Migration, start, readiness, stop, restart, and rollback plans. |
| `1419` | Build provenance and artifact-set release manifest | Source, lock, definition, image, and set digests with privacy validation. |
| `1420` | Protected packaged-runtime acceptance | Local OCI/package validation with zero production contact and rollback evidence. |
| `1421` | S142 closure | Contract/runbook closure, zero drift, Full Gate, and S143 handoff. |

## Non-Drift Rules

- OA, AE, CX, MO, and AG retain service-local data, migration, and process
  ownership.
- Cross-service calls remain HTTP/API based; packaging cannot introduce shared
  database reads or cross-service domain imports.
- Only MO may contact model providers.
- Local mock, test database, loopback, and local filesystem paths stay explicit
  development/test adapters and cannot become production fallbacks.
- AG compatibility database adapters are excluded from protected packaged
  execution; AG uses service API projections there.
- S142 does not choose a production orchestrator, registry, secret manager,
  ingress, database platform, object store, GPU scheduler, or monitoring vendor.
- Slice Gate runs for every Slice, Checkpoint Gate at Slice 1416, and Full Gate
  at Slice 1421.

## S143 Handoff

S143 receives immutable artifact identities, explicit environment composition,
and deterministic lifecycle plans. It owns external secret injection and
rotation, managed TLS termination, and certificate lifecycle. S142 artifacts
must therefore expose references and required variable names without embedding
their values.
