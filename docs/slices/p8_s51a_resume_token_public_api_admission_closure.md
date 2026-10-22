# P8-S51A: ResumeToken Public API Admission Closure

## Status

Completed on 2026-10-22.

## Scope

- Added the NSL v0.2 public `ResumeToken` type to the Platform admission set.
- Exposed the admitted type through `NslV02PublicApiAdapter` without importing
  any private NSL module.
- Re-ran reproducible wheel admission and the P8-S05/S06 adapter and
  compatibility checks.
- Kept P8-S51 durable resume authority unchanged. Token construction belongs
  to P8-S52.

## Release Identity

No NSL source or wheel content changed:

- source revision: `a5a0f5fd7acf4adbbccf890dca2f9998d055d65e`
- source-tree digest:
  `e7ffb07378ba01f4c9da6645f91b75614c605907`
- wheel digest:
  `sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135`
- wheel size: `194308` bytes
- Platform lock digest:
  `sha256:4921d3104651bba369876c2edecd4a5ae05a01353e6ce4c4def453a90eac3417`

The admitted public symbol set changed, so the semantic admission identity was
recomputed:

- previous release admission hash:
  `sha256:700020ba99ec0232266844c1b992a1e97adfbb297a2c3481f196a00cb6ba0f48`
- current release admission hash:
  `sha256:52c8f502a28b5bd8ba1e2837b9d688744a8dd15b0af057d2d25297b7fadfbc50`
- current adapter contract hash:
  `sha256:c022d3659d42da2e2bb041ff1c91631c21c5168d91cc64d8e7636a2acc98d3ea`

## Verification

- Reproducible wheel builds and admission: passed twice with identical digest.
- P8-S01 through P8-S06 focused tests: `117 passed`.
- Protected P8-S06 compatibility smoke: `8/8 passed`.
- AE Slice Gate: `4,778 passed`, `23 skipped`.
- AE Slice Gate coverage: statement `98.36%`, branch `96.26%`.
- Contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.
- Ruff and diff checks passed.

## Persistence And Provider Boundary

No database migration, PostgreSQL write, or remote model provider is required.
The existing certified wheel and lock remain the runtime artifact authority;
only the admitted public API inventory gained `ResumeToken`.

## Exit Decision

P8-S51A is closed. P8-S52 may construct `ResumeToken` only through the admitted
adapter and may connect it to `ApprovalResumeCoordinator` without a private NSL
import or a new execution identity.
