# CP-M1-E2E-FX-01A.4: Verified Multi-Skill Runtime Registry

## Status

- Slice: `CP-M1-E2E-FX-01A.4`
- Status: `CLOSED`
- Database migration: none
- Remote provider: not required

## Decision

Installed product execution selects a Skill only through an immutable signed
release, the admitted Product Capability Registry, and a generic operation
adapter registry. Filename, directory order, fixture identity, and scenario
branches are not selectors.

The generic AE catalog owns exact capability, Skill identity, semantic hash,
trust policy, operation semantics, and adapter ownership checks. MyBee owns
the D04 and D12 registrations and adapter factories. This keeps the installed
runtime extensible without moving product IDs into generic runtime code.

## Admitted Product Operations

- `FINANCE.VOUCHER.APPROVE_AND_POST` selects the signed D04 Journal Skill and
  the existing EOS controlled WRITE, verification, and reconciliation ports.
- `PROJECT.WORK_CODE_SET.GET` selects the signed D12 Project WorkCode Skill and
  reads the authoritative approved WorkCode projection from EOS with a signed
  service token.

Both selections are frozen in
`deployment/locks/ae-mybee-m1-runtime-admission.v1.json`. A regression test
rebuilds the projection from the signed NSP, Product Capability Registry, and
operation registry and requires exact equality with the lock.

## Fail-Closed Rules

- an unverified, missing, or mismatched Skill identity is rejected;
- capability, trust, semantic, or adapter ownership drift is rejected;
- duplicate capability and operation registrations are rejected;
- D12 rejects malformed input, non-approved EOS state, tenant/project
  mismatch, invalid lineage hash, transport failure, and unsigned access;
- D04 cannot construct adapters without the admitted NSL public API and
  result contract.

## Verification

- focused catalog, signed-release, and adapter regression: `68 passed`
- formatter and lint: PASS
- AE Slice Gate: PASS
- Golden A retirement residue Gate: PASS
- next boundary: `CP-M1-E2E-FX-01A.5`
