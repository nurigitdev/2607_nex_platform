# P6-S2 Skill Artifact Gateway

**Status:** COMPLETE
**Date:** 2026-10-14
**Predecessor:** P6-S1A Runtime Dispatch Semantic Hardening
**Next:** P6-S3 NSLStepExecutionBinding and SkillExecutionRequest

## Purpose

P6-S2 implements the AE boundary that converts one exact, already verified
NSL v0.1 Skill resolution plus current governance evidence into the canonical
P6 `VerifiedSkillArtifact` transition contract.

```text
exact skill/version
-> nsl.api verified-package resolver
-> exact semantic/package/signing identity
-> current tenant-scoped trust and admission
-> bounded immutable VerifiedSkillArtifact
```

This Slice does not execute NSL, create an execution binding, or duplicate NSP
signature verification. Those responsibilities remain with the existing NSL
package/security boundary and later P6 Slices.

## Source And Refactoring Audit

The exact NSL v0.1 source baseline exposes
`nsl.api.VerifiedPackageSkillResolver`. It accepts only
`VerifiedNspPackage` instances and returns exact `ResolvedSkill` data:

- `SkillObject` with ID, version, and semantic hash;
- package hash; and
- optional verified signer key ID.

The current AE module layout remains coherent, so no broad `agent_runtime/`
package move was introduced. `skill_artifacts.py` adds a narrow structural
port compatible with the public NSL API and does not import NSL private crypto
or verification modules.

## Gateway Semantics

The gateway requires:

- tenant ID;
- exact Skill ID/version, with no implicit latest selection;
- expected semantic hash from the executable plan;
- runtime contract reference;
- trust policy ID and environment; and
- an explicit observation time.

It fails closed when the exact selector or semantic/package identity differs,
the package has no signing key, trust is not `VALID`, governance is not
`ACTIVE`, the admission decision is not `ADMITTED`, a supplied evidence hash
differs, or evidence is future-dated.

The admission source is separate from the NSL resolver because NSL v0.1 does
not own publisher, trust-policy, governance, or artifact-admission facts.
Package/trust rejection occurs before any future NSL runtime invocation.

The gateway uses the shared `nex_runtime.semantic_hashes` implementation for
trust evidence, admission decision, artifact identity, and artifact hashes.
The admission hash follows the P6 transition projection and excludes only the
decision reference identity.

## Persistence

Migration `2201_ae_nsl_artifact` adds `ae_nsl_artifact` with:

- tenant-scoped artifact reference and artifact hash uniqueness;
- exact Skill/version/package indexes;
- verified time;
- the canonical bounded artifact JSON; and
- JSON-to-column identity checks.

Table, constraint, and index names are no longer than 30 characters.

Raw package bytes, NSO bytes, signature bytes, verification journals, secrets,
and provider data are not stored. They remain behind the opaque
`backend_artifact_handle` and evidence/decision references. Save is immutable
and idempotent; a reused reference with different content fails closed.

## Verification

Focused P6-S2 tests:

```text
22 passed
skill_artifacts.py statement coverage: 100%
skill_artifacts.py branch coverage: 100%
```

P5/P6 focused regression:

```text
183 passed
```

AE Slice Gate, explicitly including all P5/P6 tests:

```text
3652 passed, 5 protected opt-in tests skipped
statement coverage: 98.65% (previous floor 98.63%)
branch coverage: 96.89% (previous floor 96.87%)
contract validation: PASS
  schemas: 174
  examples: 236
  negative examples: 204
  OpenAPI documents: 7
```

Actual `nex_ae_test` protected PostgreSQL smoke:

```text
database: nex_ae_test
role: nex_ae_user
40 migrations current
latest migration: 2201_ae_nsl_artifact
checks: 14/14 PASS
artifact rows exercised: 1
remaining rows after cleanup: 0
```

The smoke covers migration currency, exact resolve, current admission,
idempotent insert/select, restart-style repository reload, tenant isolation,
semantic mismatch rejection, unsigned production rejection, bounded
projection residue checks, and cleanup.

Generation, embedding, and reranking providers are outside this Slice.
