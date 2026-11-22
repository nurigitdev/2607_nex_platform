# W70-S8-01E Compile, Admission, Alias, Trust, and Foundation Gate

## Status

- Slice: `W70-S8-01E`
- Status: `IMPLEMENTED_AND_VERIFIED`
- Date: `2026-11-15`
- Owners: NeX AE, NeX Runtime, NeX MyBee
- Database migration: none
- NSL compiler/runtime change: none
- Remote model provider: not required

## Decision

S8-01E closes Gate A from W70-CA01 without crossing the later M1 activation
boundary. The checked-in compiler fixtures are contract-profile evidence, not
product Skills. They prove that the admitted NSL v0.2.1 compiler supports the
three currently required domain/semantics pairs:

| Profile | Domain | Semantics |
| --- | --- | --- |
| `D04_READ` | D04 Accounting | `READ` |
| `D04_GOVERNED_WRITE` | D04 Accounting | `GOVERNED_WRITE` |
| `D12_READ` | D12 Project | `READ` |

The fixture Tool catalog uses canonical operation names and the admitted READ
and controlled-WRITE primitives. It does not replace EOS OpenAPI or JSON
Schema authority. Product Skill source, package signature, trust admission,
FL mapping, and runtime activation remain owned by `CP-M1-MB8-01`.

## Admission Result

The deterministic receipt is:

```text
reports/quality/mybee-w70-s8-01-foundation-gate.json
```

It records:

- the exact installed NSL v0.2.1 wheel and public API readiness;
- source, catalog, semantic, and NSO hashes for three compile profiles;
- an `NSL-E4001` negative compile for a status-only Tool omitted from the
  admitted compiler catalog;
- 11 fully typed candidates as
  `PROFILE_COMPILE_ADMITTED_SKILL_SOURCE_PENDING`;
- seven status-only candidates as `BLOCKED_STATUS_ONLY_CONTRACT`;
- all 18 candidates as `runtime_selectable=false`;
- deterministic one-way resolution for all three compatibility aliases;
- both candidate bundles as `NOT_SIGNED` and `BLOCKED_UNSIGNED`; and
- exact v1 Golden A active registry/bundle and v2 candidate registry/bundle-set
  continuity.

The receipt is rebuilt and checked with:

```text
python scripts/quality/run_w70_s8_01_foundation_gate.py --write
python scripts/quality/run_w70_s8_01_foundation_gate.py
```

Check mode fails when compiler output, source bytes, aliases, contract typing,
wheel admission, pack/registry/bundle hashes, trust state, or Golden A
continuity differs from the checked-in receipt.

## Trust Boundary

Passing Gate A does not make an unsigned descriptor executable. Existing
candidate manifests and locks intentionally remain:

```text
source_state=DESCRIPTOR_ONLY_NOT_COMPILED
compile_state=PENDING_S8_01E
signature_status=NOT_SIGNED
runtime_selectable=false
```

`PENDING_S8_01E` is the immutable S8-01D lock value and is not rewritten in
place. The S8-01E receipt supplies the later Gate result while preserving the
candidate lock history. A future product release must create a new signed
artifact and immutable release instead of mutating these locks.

The deployed Compose and OCI runtime continue to select the v1 Golden A
registry. Loading the v2 candidate release through the active v1 runtime
loader is rejected. Existing tenant-scoped SkillArtifactGateway regression is
part of the Gate, so a candidate receipt cannot weaken cross-tenant artifact
isolation.

## Negative Coverage

Focused tests cover:

- deterministic compile and NSO bytes;
- unexpected or permissive status-only compilation;
- missing domain/semantics compiler profile;
- alias target drift and canonical-as-alias confusion;
- status-only or unsigned candidate activation;
- semantic hash, trust state, continuity, and receipt tampering;
- invalid/non-object receipt input; and
- unreadable artifact evidence.

The new Foundation Gate module has 100% statement and branch coverage.

## Verification

S8-01E focused Gate:

```text
23 passed
Foundation Gate module: 100% statement / 100% branch coverage
```

S8-01A through S8-01E focused regression:

```text
209 passed
```

MyBee Phase-1 regression:

```text
693 passed, 1 skipped
```

Existing Golden A controlled-WRITE, capability registration, and
SkillArtifact tenant-isolation regression:

```text
205 passed, 3 skipped
```

The skips are existing opt-in protected PostgreSQL/live-provider cases and are
outside Gate A. Contract validation passes with 265 schemas, 316 positive
examples, 260 negative examples, and 10 OpenAPI documents. The deterministic
Gate runner also passes in check mode. No PostgreSQL or remote provider smoke
is required for this Foundation Gate.

## Handoff

`W70-S8-01E` closes S8-01 Gate A. It does not declare W70 M1 complete and does
not advertise a newly registered Tool as active. The next Slice is
`CP-M1-S8-02`, followed by `CP-M1-MB8-01` for the first signed minimal D04/D12
product Skill and `CP-M1-E2E-FX-01` for the protected public M1 journey.
