# Platform Reproducible Deployment Packaging and Environment Topology

Status: S142 complete with supplemental Slice 1422. Production deployment
remains unapproved, and S143 is active.

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

The four manifests under `deployment/environments` are the canonical
composition declarations. Their runtime-profile coverage must be exact and
non-overlapping. `test`, `staging`, and `production` require six distinct OCI
digest references; mutable tags, omitted references, loopback endpoints, and
local storage fallback are rejected. Resolved evidence exposes required
variable names and artifact counts only, never their values.

Environment composition does not imply worker execution admission.
`local_mock` and `test` are currently `LIMITED` because six background roles
remain lifecycle-only. `local_live`, `staging_live`, and `production` are
`BLOCKED` because their background profiles are not admitted; production also
retains the explicit deployment-approval deferral. This status can change only
after owner execution adapters and protected evidence are available.

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

The packaged lifecycle plan implements this order for all five runtime
profiles. `local_mock` skips PostgreSQL migration; every persistent profile
runs service-owned migrations in OA, MO, CX, AE, AG dependency order before
starting the six DAG layers. HTTP processes use liveness only in `local_mock`
and readiness everywhere else. Background roles require two consecutive live
process observations, consistent with the existing orchestrator contract.

Stop order is the exact reverse of flattened startup order. Restart repeats
stop, migration, start, and readiness. Rollback may select only a complete
previous six-artifact set and must verify that it remains compatible with the
already-migrated schema. Mixed-version rollback and automatic database
downgrade are prohibited. Slice 1419 will bind these logical artifact-set
requirements to immutable release identities.

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

Provenance is hierarchical and timestamp-free. Each artifact record binds the
full Git revision to its dependency lock, Containerfile/build definition,
owner-scoped context, immutable base image, platform, and optional final image
digest. `BUILD_INPUTS_READY` means these reproducible inputs are known but no
complete image set is claimed. `RELEASE_SET_READY` requires a clean source tree
and six distinct immutable final image references; partial sets are rejected.
Only then is a complete release-set digest issued.

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

Slices 1413 through 1419 have closed the immutable artifact, exact lock, OCI
definition, process binding, package-relative command, and environment
composition portions of this register, plus the deterministic packaged
lifecycle plan and build provenance/release identity. Slice 1420 closes the
protected package-context acceptance with all six owner contexts, five actual
test PostgreSQL migrations, seven background checks, and two complete network
process generations. At that boundary, OCI image build/run remained explicitly
unclaimed because the execution host could not access its Docker socket.

Slice 1421 closed the repository packaging boundary. At that checkpoint, the
accepted artifact was the immutable owner-scoped build input and
package-context identity, not a published image set; final image digests were
absent and an OCI-capable build host was still required.

Supplemental Slice 1422 adds a protected clean-commit command that builds and
loads all six images, captures BuildKit manifest and config digests, verifies
non-root users and six default packaged commands, executes seven background
container checks without network access, and admits only the exact six-image
set into the existing provenance contract. Runtime reports and logs remain
under ignored `reports/`; no registry push or published release is implied.

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
| `1422` | Protected OCI image build supplement | Six real local images, manifest/config digests, non-root/default-command inspection, seven network-isolated background checks, and external release-set evidence. |

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
- Slice Gate runs for every Slice, Checkpoint Gate at Slice 1416, Full Gate at
  Slice 1421, and a focused supplemental Slice Gate at Slice 1422.

## Completion Signal

Completion signal: Met. Six owner-scoped artifacts cover all thirteen runtime
processes, Python and Node inputs are integrity locked, all five runtime
profiles map exactly to four environment classes, and packaged migration,
startup, readiness, stop, restart, and rollback rules are deterministic.
Protected package-context acceptance passed against all five service-owned test
PostgreSQL databases without contacting a registry, model provider, staging,
or production resource.

No production resource was contacted by S142. Production deployment remains
unapproved. Slice 1422 can issue an ignored local complete-set report with
actual image digests, but no registry publication or deployable registry
reference is claimed. Registry, staging, and production admission remain later
protected decisions. In canonical admission terms, production deployment
remains unapproved.

## S143 Handoff

S143 receives immutable artifact identities, explicit environment composition,
and deterministic lifecycle plans. It owns external secret injection and
rotation, managed TLS termination, and certificate lifecycle. S142 artifacts
must therefore expose references and required variable names without embedding
their values.
