# Production Model-Serving Capacity and Rollout Resilience

Status: S147 complete through Slice 1472. S148 is active; production deployment
remains unapproved.

## Required Outcome

NeX-MO must admit embedding, reranking, and generation revisions through one
model-independent production rollout lifecycle. A revision may receive live
traffic only after immutable identity, runtime health, GPU capacity,
capability-specific calibration, canary, and rollback evidence all match the
candidate. Changing an alias, model revision, precision, engine, request shape,
or calibration feature schema invalidates the previous admission.

S147 must prove:

- bounded GPU placement and capacity admission for all three capabilities;
- exact-revision provider and runtime readiness;
- calibration profiles bound to capability, revision, deployment, request
  shape, dataset, metrics, and policy;
- canary observation before atomic alias activation;
- failover and rollback to the exact last-known-good binding;
- restart-safe PostgreSQL rollout state and metadata-only operations evidence;
- non-disruptive protected observation of the current DGX providers; and
- no model name, vendor, endpoint, credential, prompt, vector, or response
  payload in policy decisions or source-controlled evidence.

## Ownership

| Concern | Accountable owner | Supporting owner |
| --- | --- | --- |
| Catalog, alias, deployment identity, scheduling and activation | NeX-MO | Platform integration |
| Embedding quality and vector compatibility evidence | NeX-MO | NeX-CX |
| Reranking quality and confidence evidence | NeX-MO | NeX-CX |
| Generation contract and grounded-quality evidence | NeX-MO | NeX-CX and NeX-AE |
| Protected GPU/provider observation | NeX-MO | DGX operator |
| Cross-service operations projection | NeX-AG | NeX-MO |

MO is the only service that may contact model providers or inspect GPU runtime
state. CX and AE submit evaluation inputs through MO-owned interfaces and
consume only admitted aliases and metadata-safe rollout decisions.

## Stable Identity

Every candidate is identified by the following immutable tuple:

1. `provider_capability`
2. `alias`
3. `catalog_id`
4. `model_revision`
5. `deployment_id`
6. `artifact_digest`
7. `runtime_engine`
8. `precision`
9. `request_shape_hash`

The tuple is model-independent. Human-readable model names are catalog
metadata, never routing or policy keys. Reusing a deployment ID for different
artifact, revision, engine, or precision metadata is forbidden.

## Capacity and GPU Scheduling

The S147 scheduler is a policy and placement port, not a Kubernetes
requirement. It consumes product-neutral capacity snapshots for one or more
GPU nodes and creates deterministic reservations. The current protected
topology may contain one DGX node; the same contract supports more nodes later.

Each snapshot records only node and accelerator identities, allocatable GPU
count and memory, reserved capacity, active concurrency, queue depth,
utilization, temperature, freshness, and health. Admission requires:

- a fresh HEALTHY runtime observation for the exact revision;
- enough unreserved GPU and memory capacity for the candidate;
- post-placement memory and concurrency headroom;
- queue, utilization, and temperature below policy ceilings;
- no conflicting exclusive reservation; and
- a deterministic rejection reason when capacity is insufficient.

No scheduler may overcommit an exclusive GPU, silently replace a revision, or
interpret missing metrics as spare capacity. Autoscaling, multi-host HA, and
provider process mutation are not claimed by S147.

## Capability Calibration

All three capabilities require an ACTIVE profile for the exact candidate.

| Capability | Required evidence |
| --- | --- |
| `embedding` | vector dimension and finite-value compatibility, deterministic repeatability, retrieval-quality dataset metrics |
| `reranking` | ranking dataset, order/score semantics, quality metrics, score-distribution and confidence policy |
| `generation` | response-shape success, grounded/citation quality, safety/error rate, latency and output-budget metrics |

Profiles include dataset and feature-schema hashes, sample counts, acceptance
metrics, threshold policy, and an evidence digest. A revision, deployment,
request-shape, feature-schema, or policy change yields
`CALIBRATION_REQUIRED`. Thresholds are evaluated with data; they are not
copied automatically between revisions.

## Rollout State Machine

The forward path is:

`REGISTERED -> VALIDATING -> READY -> CANARY -> ACTIVE`

`READY` requires exact identity, health, capacity, and calibration admission.
`CANARY` requires an explicit traffic ceiling, observation window, minimum
sample count, quality/error/latency budgets, and a last-known-good binding.
Only a passing canary may atomically supersede the alias. Any identity drift,
stale evidence, capacity pressure, calibration failure, quality regression,
or operator cancellation moves the rollout to `BLOCKED` or `ROLLED_BACK`.

Rollback restores the exact previous catalog and alias binding, verifies its
readiness, releases candidate reservations, preserves audit history, and never
deletes the candidate artifact automatically.

## Persistence and Operations

The MO test and production schemas use concise owner-scoped tables:

- `mo_model_rollouts` for immutable candidate identity and current state;
- `mo_rollout_events` for append-only state, admission, canary, and rollback
  evidence; and
- existing catalog, alias, telemetry, and runtime-observation tables as source
  evidence.

Persisted and projected records contain IDs, status, counts, durations,
metrics, hashes, failure codes, and timestamps only. Endpoints, credentials,
raw prompts, documents, vectors, scores per document, and generated text are
forbidden.

## Protected Acceptance

Protected acceptance is opt-in and non-disruptive. It may query the three
current provider routes and collect redacted GPU/runtime evidence over the
existing protected path. It must not stop providers, load another model,
change a live alias, or consume production traffic without a separate operator
change approval.

The rehearsal persists a candidate and state transitions only in
`nex_mo_test`. Current live revisions can prove baseline identity, health, and
capacity observation. If there is no second revision or safe GPU headroom, the
canary/promotion decision must be `BLOCKED_CAPACITY` or
`CANDIDATE_REVISION_REQUIRED`, never a synthetic production promotion.

## Gap Register

1. Freeze immutable, model-independent revision and deployment identity.
2. Add product-neutral GPU capacity snapshots and deterministic placement.
3. Add concurrency, queue, pressure, reservation, and headroom admission.
4. Bind provider/runtime readiness to the exact candidate revision.
5. Require capability-specific calibration for embedding, reranking, and
   generation.
6. Add bounded canary metrics, state transitions, and promotion guards.
7. Add atomic alias failover and exact last-known-good rollback.
8. Persist rollout state, expose metadata-safe operations, and prove protected
   restart behavior.

## Slice Sequence

| Slice | Scope |
| --- | --- |
| `1463` | Freeze the S147 boundary, gaps, non-disruptive acceptance, and implementation order. |
| `1464` | Add immutable model revision and capacity snapshot domains. |
| `1465` | Implement deterministic GPU placement, reservation, and capacity admission. |
| `1466` | Bind provider and runtime readiness to exact revision identity. |
| `1467` | Add capability-specific calibration lifecycle and invalidation. |
| `1468` | Implement canary state machine, metric budgets, and Checkpoint Gate. |
| `1469` | Integrate atomic alias failover, rollback, and reservation release. |
| `1470` | Add PostgreSQL persistence, restart recovery, and operations API. |
| `1471` | Execute non-disruptive DGX/provider and `nex_mo_test` protected acceptance. |
| `1472` | Publish contracts/runbook, run Full Gate, close S147, and activate S148. |

Checkpoint Gate runs at Slice 1468. Full Gate runs at Slice 1472.

## Non-Drift Rules

- Policy and state transitions use capability and immutable IDs, not model
  names or vendor-specific fields.
- Mock providers and local model paths remain forbidden in protected profiles.
- Missing, stale, mismatched, or incomplete evidence fails closed.
- Source-controlled evidence is value-free and metadata-only.
- Production aliases and provider processes are never mutated by a smoke test.
- Production deployment remains unapproved until S148-S150 complete.

## Completion Signal

S147 completes only when all eight gaps close, protected observation and
test-database rehearsal produce zero residue, rollback remains executable, the
operations runbook is published, and Full Gate passes. S148 then consumes
capacity, saturation, rollout, calibration, canary, rollback, and failure
signals for monitoring and incident response.

## Closure Decision

Completion signal: Met.

- Immutable revision identity, scheduler-neutral GPU capacity, deterministic
  reservation, exact-revision readiness, capability calibration, bounded
  canary, atomic activation, and exact rollback are implemented.
- PostgreSQL rollout/event state is restart-safe and available through
  NeX-AG-only metadata projections.
- Actual protected acceptance passed all 12 checks against the three current
  DGX providers and `nex_mo_test`, then removed all temporary rows.
- The current environment has no separately configured candidate revision, so
  protected acceptance correctly stopped at `CALIBRATION_REQUIRED` and made no
  live alias or process mutation.
- Canonical schemas reject provider endpoints and raw payloads in rollout
  operations evidence.

Production deployment remains unapproved. S147 does not claim multi-host HA,
autoscaling, production traffic canary, or production capacity approval; S149
owns production-sized reliability rehearsal and S150 owns the final go/no-go.

## S148 and S149 Handoff

- S148 consumes capacity pressure, runtime readiness, calibration validity,
  canary budgets, activation, rollback, persistence health, and failure codes
  as redacted observability signals.
- S149 consumes the rollout runbook and exact last-known-good rollback contract
  for load, soak, failure injection, and recovery rehearsal.
