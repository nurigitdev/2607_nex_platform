# P8-S04: Installed NSL v0.2 Package Readiness

## Status

Completed on 2026-10-21. The exact NSL v0.2 wheel is installable and passes
the Platform readiness boundary against the committed v2 lock. The current
host `.venv` keeps its v0.1 installation for historical READ compatibility.

## Goal

Fail closed unless the runtime installation exactly matches the admitted NSL
v0.2 wheel, Platform dependency lock, and public API origin. Make AE worker
startup require readiness for the exact configured in-process package version.

## Source Audit and Changes

- Extended the shared installed-package inspector to dispatch strictly by lock
  schema. Existing `nsl_wheel_lock.v1` behavior remains compatible, while
  `nsl_wheel_lock.v2` uses the P8-S02 strict normalizer.
- Added `nsl_installed_package_readiness.v2` with lock schema, source tree,
  Linux certification, and release admission hash evidence.
- Verified installed distribution version, direct wheel URL, archive digest,
  API module location, required symbols, cryptography version, and Platform
  lock digest.
- Extended AE worker profile validation to accept `NSL_V02_IN_PROCESS` while
  retaining `NSL_V01_IN_PROCESS` as the default.
- Required v2 profile startup to receive v2 readiness for package `0.2.0` and
  lock schema v2. v1 readiness cannot satisfy a v2 worker.
- Rejected configuring v1 and v2 in-process profiles in one worker because one
  Python environment cannot activate two versions of the same distribution.
- Selected the v2 lock automatically only when the worker explicitly selects
  the v2 profile; the default loader remains on the v1 lock.

## Protected Installed Evidence

The protected runner installs the admitted wheel with `--no-deps` into a
temporary site-packages directory and inspects it in a separate Python
process. It does not modify the Platform virtual environment.

```bash
NEX_NSL_V02_READINESS=1 ./.venv/bin/python \
  scripts/deployment/check_nsl_v02_readiness.py --execute
```

Observed result:

```text
status                     = PASS
isolated install           = true
host environment mutated   = false
host NSL version            = 0.1.0
isolated NSL version        = 0.2.0
wheel sha256                = 862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135
release admission hash      = 700020ba99ec0232266844c1b992a1e97adfbb297a2c3481f196a00cb6ba0f48
public API complete         = true
runtime import origin       = installed_distribution
runtime profile activated   = false
```

Sanitized evidence is written to
`reports/deployment/p8-s04-nsl-v0.2-readiness.json`.

## Verification

- Focused readiness, lock, worker, and v1 compatibility regression:
  `78 passed`; shared inspector coverage set: `102 passed`.
- AE Slice Gate: `4,542 passed`, `17` protected infrastructure tests skipped;
  statement `98.29%`, branch `96.14%`.
- Shared package inspector bounded coverage: statement `96.76%`, branch
  `95.92%`.
- Protected readiness runner: statement `100%`, branch `100%`.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  8 OpenAPI documents.
- Platform Full Gate: deferred until P8-S06 as required.

## Exit Decision

The installed v0.2 package can now be admitted without replacing the existing
v0.1 host environment. Runtime execution remains unavailable until P8-S05
provides the narrow v0.2 public API adapter and exact backend composition.
