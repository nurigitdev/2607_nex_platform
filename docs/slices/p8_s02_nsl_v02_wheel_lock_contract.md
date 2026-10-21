# P8-S02: NSL v0.2 Wheel Lock Contract

## Status

Completed on 2026-10-21. The exact NSL v0.2 release admitted by P8-S01 is
stored as an immutable Platform wheel lock. Runtime profile activation remains
deferred to P8-S03.

## Goal

Create a strict, versioned Platform lock that binds the certified NSL source
and reproducible wheel to the current Platform dependency lock and required
public API. Preserve the existing `nsl_wheel_lock.v1` contract for NSL v0.1.

## Lock Contract

The committed lock is
`deployment/locks/nsl-v0.2-wheel.json` with schema
`nsl_wheel_lock.v2`. It binds:

```text
repository                 = nurigitdev/2608_nsl
source revision            = a5a0f5fd7acf4adbbccf890dca2f9998d055d65e
source tree                = e7ffb07378ba01f4c9da6645f91b75614c605907
distribution               = nex-skill-language
package version            = 0.2.0
wheel filename             = nex_skill_language-0.2.0-py3-none-any.whl
wheel sha256               = 862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135
wheel size                 = 194308 bytes
Python requirement         = >=3.12
NSL cryptography range     = >=46.0.7,<47.0.0
locked cryptography        = 46.0.7
Platform lock sha256       = 4921d3104651bba369876c2edecd4a5ae05a01353e6ce4c4def453a90eac3417
RECORD entries/integrity   = 70/69
```

The lock also records the ten P8 `nsl.api` symbols and the Linux certification
reference tied to the exact source revision.

## Source Audit and Changes

- Added a strict v0.2 lock projection, shape normalizer, and identity validator
  without changing the v0.1 lock schema or readiness path.
- Required exact field inventory and validated source object IDs, hash refs,
  wheel filename metadata, Python version, dependency compatibility, public
  API uniqueness, RECORD counts, and certification binding.
- Required the lock to equal both the P8-S01 release identity and the fresh
  wheel admission. A semantically valid but different revision, tree,
  filename, digest, version, dependency, or API inventory fails closed.
- Extended the protected command to emit P8-S02 evidence and use the v2 lock
  only for the explicit v0.2 release profile.
- Preserved wheel RECORD tamper detection in the existing archive inspection
  regression; a digest, size, coverage, or self-entry mismatch is rejected
  before a lock can be written.

## Protected Evidence

The lock was created from two reproducible builds of the clean archived NSL
source and then verified in a second protected invocation without rewriting it:

```bash
NEX_NSL_WHEEL_ADMISSION=1 ./.venv/bin/python \
  scripts/deployment/admit_nsl_wheel.py \
  --execute --release-profile v0.2 --write-lock

NEX_NSL_WHEEL_ADMISSION=1 ./.venv/bin/python \
  scripts/deployment/admit_nsl_wheel.py \
  --execute --release-profile v0.2
```

Both executions returned `PASS`, `release_identity_verified=true`,
`wheel_admitted=true`, and `runtime_profile_activated=false`. Sanitized local
evidence is written to
`reports/deployment/p8-s02-nsl-v0.2-wheel-lock.json`.

## Verification

- Focused S01/S02 plus preserved P6 admission regression: `79 passed`.
- Bounded Slice Gate: `447 passed`, `6` protected infrastructure tests skipped;
  statement `99.64%`, branch `99.00%`.
- v0.2 lock validator: statement `100%`, branch `100%`.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  8 OpenAPI documents.
- Platform Full Gate: deferred until P8-S06 as required.

## Exit Decision

The exact NSL v0.2 wheel admission record is reproducible and committed.
`NSL_V02_IN_PROCESS` remains unavailable until P8-S03 explicitly adds the
profile and makes activation depend on this lock.
