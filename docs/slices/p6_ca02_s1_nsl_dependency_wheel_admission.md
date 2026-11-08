# P6-CA02-S1 NSL Dependency Compatibility and Wheel Admission

**Status:** COMPLETE
**Date:** 2026-10-16
**Predecessor:** P6-CA02 In-Process NSL Runtime Profile Clarification
**Next:** In-process backend composition and readiness activation

## Purpose

This Slice closes only the package and dependency prerequisite for running NSL
inside the AE Runtime Worker. It does not change the active backend profile.

```text
clean NSL source revision
-> reproducible wheel build
-> METADATA / RECORD integrity
-> shared dependency resolution
-> wheel-only nsl.api import
-> immutable admission lock
```

Local checkout `sys.path` injection remains development evidence only and is
not an admitted deployment path.

## Dependency Decision

The original ranges had no intersection:

```text
Platform: cryptography>=43,<47
NSL:      cryptography>=49,<50
```

NSL's complete quality gate passed against Platform's installed and locked
`cryptography 46.0.7`. The admitted ranges are now:

```text
Platform: cryptography>=46,<47
NSL:      cryptography>=46,<50
lock:     cryptography==46.0.7
```

Platform also declares `packaging>=24,<27` because wheel admission uses the
standard requirement, version and wheel filename parsers. The production lock
was regenerated and now contains 53 exact hashed packages.

## NSL Repository Change

Independent NSL repository:

```text
repository: nurigitdev/2608_nsl
branch: codex/p6-ca02-nsl-wheel-admission
revision: 3b4cb198888570a857e6fb0d3aa077930bb23504
```

The change lowers the tested cryptography floor, pins the development baseline
to 46.0.7, updates architecture assertions, and corrects one unrelated brittle
CLI expectation for Linux `IsADirectoryError` sanitization.

Verification with the Platform Python 3.12.13 environment:

```text
1225 passed
coverage: 99.25%
```

The branch and exact revision were pushed to the NSL remote before Platform
wheel admission.

## Wheel Admission

`scripts/deployment/admit_nsl_wheel.py` is protected by both `--execute` and
`NEX_NSL_WHEEL_ADMISSION=1`. It:

1. requires a clean NSL Git tree;
2. materializes the exact `HEAD` twice through `git archive`;
3. builds both wheels with the commit timestamp as `SOURCE_DATE_EPOCH`;
4. rejects differing filenames or digests;
5. validates wheel path safety, METADATA and every RECORD SHA-256/size entry;
6. installs the wheel without dependencies into a temporary target;
7. imports the required public API from that target, not the checkout; and
8. binds the result to the Platform Python dependency lock.

Actual protected execution passed twice, first creating and then revalidating
the committed lock:

```text
wheel: nex_skill_language-0.1.0-py3-none-any.whl
size: 120665 bytes
RECORD entries/integrity entries: 56/55
sha256:290a202f540ec98291842e9281a28288cc7ac112525b6c0f02c10b8721aef21f
source revision: 3b4cb198888570a857e6fb0d3aa077930bb23504
Platform lock sha256:4921d3104651bba369876c2edecd4a5ae05a01353e6ce4c4def453a90eac3417
reproducible builds: 2
status: PASS
```

The wheel remains under ignored `reports/deployment/`; the version-controlled
admission authority is `deployment/locks/nsl-v0.1-wheel.json`.

## Regression and Coverage

Focused package, lock and orchestration regression:

```text
41 passed
statement coverage: 99.14%
branch coverage: 97.65%
```

Corrected Platform Slice Gate:

```text
375 passed, 6 protected PostgreSQL tests skipped
statement coverage: 99.14%
branch coverage: 97.65%
contract validation: PASS
schemas/examples/negative examples/OpenAPI: 174/236/204/7
```

An initial `nex-runtime` profile run completed all 1,557 collected tests with
one protected skip, but its gate failed at 90.16% statement and 87.25% branch
coverage because that profile includes legacy shared modules outside the
tests it selects. No test failed. The Slice was rerun under the correct
Platform packaging profile with explicit admission coverage scopes, producing
the passing result above.

The tests cover dependency and source drift, malformed wheel metadata,
unsafe paths, RECORD corruption, dirty source, non-reproducible builds,
missing lock data, runtime/lock version mismatch, install failure and public
API import failure.

## Boundary

- No database schema or table changed.
- PostgreSQL and remote model providers were not required.
- No runtime `sys.path` fallback was added.
- `NSL_V01_PROCESS_ISOLATED` remains the active historical/default profile.
- `NSL_V01_IN_PROCESS` activation and worker readiness evidence remain follow-up
  work.
