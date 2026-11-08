# P8-S01: Actual NSL v0.2 Wheel Identity Closure

## Status

Completed on 2026-10-21. The exact NSL v0.2 source and wheel identity is
admitted for P8-S02 lock creation. No runtime profile is activated by this
Slice.

## Goal

Bind the P8 implementation baseline to one reproducible NSL v0.2 release
without weakening the existing NSL v0.1 wheel admission path. The identity
must include source commit and tree, wheel filename and digest, dependency and
Python requirements, Linux certification reference, and the P8 public API
inventory.

## Release Identity

```text
repository          = nurigitdev/2608_nsl
source revision     = a5a0f5fd7acf4adbbccf890dca2f9998d055d65e
source tree         = e7ffb07378ba01f4c9da6645f91b75614c605907
distribution        = nex-skill-language
package version     = 0.2.0
wheel filename      = nex_skill_language-0.2.0-py3-none-any.whl
wheel sha256        = 862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135
wheel size          = 194308 bytes
Python requirement  = >=3.12
NSL dependency      = cryptography>=46.0.7,<47.0.0
Platform lock       = cryptography==46.0.7
certification       = nsl-linux-quality:a5a0f5fd7acf4adbbccf890dca2f9998d055d65e
```

The admitted API inventory is `ApprovalRequest`, `ApprovalEvidence`,
`ApprovalSuspensionCoordinator`, `ApprovalResumeCoordinator`,
`CheckpointPort`, `ResumeCheckpointPort`, `IdempotencyCoordinator`,
`WriteExecutionPort`, `PostWriteVerificationPort`, and
`RuntimePreflightValidator` from installed `nsl.api`.

## Source Audit and Changes

- Added the focused `nsl_release_identity.v1` module, which accepts only a
  passing wheel admission and fails closed on repository, source
  revision/tree, wheel digest, dirty source, dependency inventory, public API
  inventory, or certification drift.
- Extended the protected admission command with an explicit v0.2 identity-only
  profile while preserving all v0.1 defaults.
- Used the NSL repository's canonical `tools/wheel_release.py` with its pinned
  release toolchain. The generic P6 `uv build` path is intentionally retained
  only for the existing v0.1 profile because it does not reproduce the
  certified v0.2 wheel digest.
- Built the archived clean source twice, compared both wheel digests, installed
  the wheel into an isolated target, and imported the required symbols from
  that installed package.
- Preserved P8 evidence schema identity on protected skip and failure paths.

## Protected Evidence

The following command completed with `PASS` and
`reproducible_build_count=2`:

```bash
NEX_NSL_WHEEL_ADMISSION=1 ./.venv/bin/python \
  scripts/deployment/admit_nsl_wheel.py \
  --execute --release-profile v0.2 --identity-only
```

Sanitized local evidence is written to
`reports/deployment/p8-s01-nsl-v0.2-identity.json`. It contains no credential,
provider endpoint, prompt, or private business data.

## Boundary Decision

P8-S01 proves only the immutable source-to-wheel release identity. It does not
write the committed wheel lock, activate `NSL_V02_IN_PROCESS`, or make the
installed package worker-ready. Those responsibilities remain respectively in
P8-S02, P8-S03, and P8-S04.

## Verification

- Focused P8-S01 and preserved P6 admission regression: `43 passed`.
- Shared runtime regression: `1,579 passed`, `1` protected PostgreSQL smoke
  skipped because its activation flag was not requested.
- Bounded Slice Gate: `411 passed`, `6` protected infrastructure tests skipped;
  statement `99.56%`, branch `98.72%`.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  8 OpenAPI documents.
- Actual source built twice with the canonical release tool: `PASS`.
- Wheel RECORD integrity: 69 hashed entries across 70 records.
- Runtime profile activation: `false` by construction.
- Platform Full Gate: deferred until P8-S06 as required.
