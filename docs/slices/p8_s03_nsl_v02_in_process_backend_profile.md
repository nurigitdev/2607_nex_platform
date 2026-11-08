# P8-S03: NSL_V02_IN_PROCESS Backend Profile

## Status

Completed on 2026-10-21. `NSL_V02_IN_PROCESS` is now an explicit known AE
backend profile. The v0.1 default and both historical v0.1 profiles remain
unchanged.

## Goal

Introduce an exact runtime profile identity for NSL v0.2 while preserving P6
READ compatibility and preventing any v0.1 profile from being selected for a
future controlled WRITE operation.

## Profile Contract

```text
NSL_V01_IN_PROCESS       retained
NSL_V01_PROCESS_ISOLATED retained
NSL_V02_IN_PROCESS       added
default profile          NSL_V01_IN_PROCESS
READ                     any known exact profile
WRITE                    NSL_V02_IN_PROCESS only
unknown profile          rejected
unknown operation        rejected
router fallback          prohibited
```

## Source Audit and Changes

- Expanded the canonical known-profile set without changing
  `DEFAULT_NSL_V01_BACKEND_PROFILE` or the v0.1 profile set used by the current
  worker default.
- Added an operation-aware profile normalizer. `READ` preserves historical
  v0.1 compatibility and permits explicit v0.2 bindings; `WRITE` rejects both
  v0.1 profiles and accepts only `NSL_V02_IN_PROCESS`.
- Allowed the existing capability and NSL step-binding validators to preserve
  a v0.2 profile identity without adding a database column or migration.
- Reused the exact-match backend router. A known profile with no configured
  backend is unavailable, and a router key/backend identity mismatch is
  rejected without fallback.

## Activation Boundary

This Slice establishes profile vocabulary and operation compatibility only.
It does not declare the installed NSL package ready, change the worker default,
or construct a v0.2 backend adapter. Those responsibilities remain in
P8-S04 and P8-S05. Consequently, a persisted v0.2 binding cannot execute until
an exactly matching, readiness-admitted backend is configured.

## Verification

- Focused P8-S03 plus P6 binding/router regressions: `97 passed`.
- AE Slice Gate: `4,523 passed`, `17` protected infrastructure tests skipped;
  statement `98.29%`, branch `96.14%`.
- Profile module: statement `100%`, branch `100%`.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  8 OpenAPI documents.
- Platform Full Gate: deferred until P8-S06 as required.

## Exit Decision

The v0.2 profile is explicit and WRITE-safe, while historical v0.1 READ
profiles remain compatible. Installed-package admission is the next required
gate before worker readiness.
