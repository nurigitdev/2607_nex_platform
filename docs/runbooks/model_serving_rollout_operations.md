# Model-Serving Rollout Operations

## Purpose

This runbook operates embedding, reranking, and generation revision rollouts
through the same NeX-MO admission lifecycle. It applies to the current
single-DGX topology and remains scheduler-neutral for future multi-node
capacity. It does not authorize a production deployment.

## Safety Boundary

- Treat `provider_capability`, catalog, revision, deployment, artifact digest,
  runtime engine, precision, and request-shape hash as one immutable identity.
- Never infer spare capacity from missing or stale GPU metrics.
- Never reuse calibration from another identity or feature schema.
- Never mutate a provider process or production alias from a smoke runner.
- Preserve the exact last-known-good binding until the rollout is closed.
- Keep endpoints, credentials, prompts, documents, vectors, scores, generated
  text, process commands, and SSH targets out of tracked evidence.

## Required Inputs

1. Candidate catalog entry and immutable artifact provenance digest.
2. Candidate deployment ID, runtime engine, precision, and request shape.
3. Current last-known-good alias binding and identity fingerprint.
4. Fresh provider preflight and GPU runtime observation.
5. Capacity request and placement policy.
6. Capability-specific calibration dataset, feature schema, policy, and
   thresholds.
7. Canary traffic ceiling, observation window, sample floor, quality, error,
   and latency budgets.
8. Operator identity, change record, rollback owner, and observation window.

Missing inputs stop admission. Model names are descriptive catalog metadata,
not routing or policy keys.

## Configuration Check

Use process-local secret injection. Do not write real values to `.env.example`
or reports.

```bash
./.venv/bin/python scripts/smoke/check_local_live_provider_config.py --summary
NEX_MO_RUNTIME_OBSERVABILITY_LIVE_SMOKE=1 \
./.venv/bin/python scripts/smoke/run_mo_runtime_observability_live_smoke.py --summary
```

The SSH collector defaults to explicit `host-bound` public-key authentication.
Use `NEX_MO_DGX_SSH_PUBKEY_MODE=unbound` only after an operator audits the SSH
agent limitation. Connect timeout must remain within 1-30 seconds and command
timeout within 5-120 seconds.

## Admission Sequence

### 1. Register

- Create the catalog candidate without changing the active alias.
- Record artifact and request-shape digests.
- Create a `REGISTERED` rollout with the exact last-known-good binding.
- Confirm one `rollout.registered` event and state revision 1.

### 2. Validate Runtime and Capacity

- Collect provider identity and response-shape evidence.
- Collect exact process count, expected revision, precision, GPU allocation,
  utilization, temperature, and freshness over the protected SSH collector.
- Build a capacity snapshot and request a deterministic reservation.
- Require headroom after placement. Capacity pressure returns a stable blocked
  reason and performs no alias mutation.

Run deterministic guards when changing the implementation:

```bash
./.venv/bin/python scripts/smoke/run_s147_gpu_capacity_admission.py --summary
./.venv/bin/python scripts/smoke/run_s147_revision_readiness.py --summary
```

### 3. Calibrate Exact Revision

- Evaluate embedding vector compatibility and retrieval quality.
- Evaluate reranking order, score semantics, distribution, and confidence.
- Evaluate generation response shape, grounding/citation quality, safety,
  latency, and output budget.
- Activate a profile only when identity, dataset, feature schema, sample floor,
  metrics, and policy all pass.

```bash
./.venv/bin/python scripts/smoke/run_s147_capability_calibration.py --summary
```

Any revision, deployment, request-shape, feature-schema, or policy change
returns `CALIBRATION_REQUIRED`.

### 4. Start Canary

- Verify READY state, fresh readiness, ACTIVE calibration, reservation, and
  last-known-good lineage.
- Cap candidate traffic at 25 percent or lower.
- Observe the complete minimum duration and sample count.
- Stop and mark BLOCKED on any identity mismatch, stale evidence, error,
  quality, or latency budget failure.

```bash
./.venv/bin/python scripts/smoke/run_s147_canary_rollout.py --summary
```

### 5. Activate

- Re-read the exact candidate and last-known-good binding.
- Revalidate readiness and capacity immediately before mutation.
- Atomically append the new active alias binding with expected revision.
- Persist `rollout.activated`, release only reservations allowed by policy, and
  retain lineage and candidate artifacts.

```bash
./.venv/bin/python scripts/smoke/run_s147_rollout_activation_rollback.py --summary
```

## Rollback

1. Stop further candidate traffic.
2. Confirm the stored last-known-good binding and exact identity.
3. Verify that last-known-good readiness is current.
4. Atomically append the rollback alias binding with expected revision.
5. Mark the rollout `ROLLED_BACK` and append `rollout.rolled_back`.
6. Release candidate reservations.
7. Preserve candidate catalog/artifacts for diagnosis; do not delete them as
   part of automatic rollback.
8. Confirm NeX-AG rollout/event projections remain metadata-only.

If the last-known-good revision is not READY, block automatic rollback and
escalate. Do not route to an arbitrary available model.

## Protected Test Acceptance

The acceptance uses only `nex_mo_test`, current DGX providers, and non-
disruptive runtime observation:

```bash
NEX_MO_MODEL_ROLLOUT_LIVE_ACCEPTANCE=1 \
NEX_MO_MODEL_ROLLOUT_LIVE_ACCEPTANCE_PROFILE=test \
NEX_MO_TEST_DATABASE_URL='<protected nex_mo_test URL>' \
./.venv/bin/python scripts/smoke/run_s147_model_rollout_live_acceptance.py --summary
```

Expected result is `12/12`, providers `3/3`, runtime `3/3`, rollouts `3/3`,
events `6/6`, and cleanup `0`. With no second configured candidate, the smoke
must report `CALIBRATION_REQUIRED` and perform zero canary, activation, or
rollback mutation.

## Failure Response

| Failure | Required response |
| --- | --- |
| Provider identity or request-shape mismatch | Block validation and verify deployment configuration. |
| Runtime observation stale or unavailable | Keep current alias; restore SSH/GPU evidence before retry. |
| Capacity or headroom insufficient | Release partial reservation and reschedule; do not overcommit. |
| Precision mismatch | Stop admission and correct the provider launch profile. |
| Calibration missing or failed | Keep `CALIBRATION_REQUIRED`; collect a new exact-revision profile. |
| Canary budget failed | Mark BLOCKED, stop candidate traffic, preserve evidence. |
| Activation revision conflict | Re-read alias state and restart admission from current lineage. |
| Active revision regression | Execute exact last-known-good rollback. |
| PostgreSQL unavailable | Stop transitions; recover durable state before any alias mutation. |

## Evidence and Handoff

Run deterministic closure and Full Gate:

```bash
./.venv/bin/python scripts/smoke/run_s147_model_serving_rollout_closure.py --summary
./scripts/quality/run_quality_gate.sh
```

S148 consumes redacted capacity pressure, readiness, calibration, canary,
activation, rollback, and persistence signals for SLI/SLO, alerting, paging,
and incident integration. S149 retains production-sized load, soak, failure
injection, multi-node or host-loss behavior, and production change rehearsal.
