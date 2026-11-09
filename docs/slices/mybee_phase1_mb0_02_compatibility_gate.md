# MyBee Phase-1 MB0-02: Platform Compatibility Lock Gate

## Scope

MB0-02 turns the Phase-1 Platform lock into a fail-closed executable boundary.
It verifies exact Frozen authority, canonical OA/AE/WC/EOS/WA OpenAPI, admitted
NSL wheel identity, and the pinned master ancestor.

## Implementation

- `mybee_ax.compatibility` owns reusable validation and typed error codes.
- `domains/mybee/compatibility/check_lock.py` is the source-checkout CLI.
- Existing tiered quality gates now admit the bounded `domains/` coverage root.
- No cross-repository release, runtime activation, API change, or DB migration
  is introduced.

## Fail-Closed Cases

```text
unsupported lock schema
invalid admission status
missing, absolute or traversal path
canonical OpenAPI owner/path drift
artifact hash mismatch
NSL package/revision/wheel mismatch
baseline commit not reachable from current HEAD
```

## Verification

```text
compatibility + quality-gate focused pytest
  29 passed
  statement=100%
  branch=100%

lock CLI
  mybee_platform_lock=pass openapi=5 nsl=0.2.1 baseline=9fe6ddb1

standard platform Slice Gate
  441 passed
  8 explicit protected skips
  MyBee statement=100.00% (threshold 95.00%)
  MyBee branch=100.00% (threshold 94.00%)
  contract validation=PASS (233/292/245/10)
  Golden transition audit=PASS
  product dependency audit=PASS

Group 1 cumulative focused regression
  96 passed
  2 explicit protected Golden A skips
  failures=0
```

No protected skip is counted as live acceptance. MB0-02 closes the W00
provider-consumer compatibility boundary; it does not activate a MyBee Skill
or mutate a database.
