# Slice 1471: S147 Model Rollout Protected Acceptance

## Outcome

- Added an opt-in protected acceptance runner that accepts only
  `nex_mo_user@nex_mo_test` and the `test` profile.
- Reused the existing protected MO live acceptance for real embedding,
  reranking, generation, and SSH GPU/runtime observation.
- Rehearsed one temporary rollout per capability through durable
  `REGISTERED -> VALIDATING` transitions, repository restart, NeX-AG ADMIN
  API readback, and targeted cleanup.
- Proved that the current aliases remain unchanged and that the smoke never
  enters CANARY, ACTIVE, or ROLLED_BACK without candidate artifact provenance
  and an exact-revision ACTIVE calibration profile.
- Made SSH collector connect/command timeouts bounded and configurable. The
  collector now selects explicit `host-bound` public-key authentication by
  default, with `unbound` available only as an audited override.

The live environment currently exposes one active revision per capability.
Therefore the acceptance establishes current-model health and the safety of
the rollout persistence boundary; it does not claim that an unconfigured
candidate revision is promotion eligible. Its admission result remains
`CALIBRATION_REQUIRED` until a real candidate provides artifact provenance,
capacity, readiness, and calibration evidence.

## Protected Evidence

- Actual DGX provider requests and returned model identities: `3/3`.
- SSH model runtime health, precision, and GPU observation: `3/3`.
- Actual PostgreSQL identity: `nex_mo_user@nex_mo_test`.
- Current S147 migration and restart readback: `3/3` rollouts.
- Atomic event history: `6/6` events.
- Protected API readback: `200`, `3/3` items.
- Acceptance checks: `12/12`.
- Cleanup reported zero residue; a direct PostgreSQL query confirmed temporary
  rollout, event, and catalog counts `0/0/0`.

Provider endpoints, API keys, the database password, SSH target, raw provider
payloads, and process commands are excluded from tracked evidence.

## Verification

- MO Slice Gate: `1,253 passed`, `7 skipped`, statement coverage `99.80%`,
  and branch coverage `99.39%`.
- The new acceptance runner plus modified runtime plan, collector, and service
  scopes each reached statement/branch coverage `100.00%`.
- Contract validation remained `166/228/196/7`.
- Actual protected acceptance:
  `checks=12/12 providers=3/3 runtime=3/3 rollouts=3/3 events=6/6 cleanup=0`.
- Slice 1472 publishes canonical contracts, the operator runbook, closure
  traceability, and Full Gate evidence.
