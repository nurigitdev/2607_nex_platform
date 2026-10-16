# P7-CA00 AE Test Ownership Namespace Normalization

**Status:** COMPLETE
**Date:** 2026-10-16
**Predecessor:** P6-CA02-S8 Runtime-Profile Acceptance and P7 Entry Closure
**Next:** P7 planning and implementation

## Purpose

P4, P5, and P6 introduced AE-owned transition tests under phase-first names
such as `test_p6_*`. This change normalizes those tests to an owner-first
namespace so service-scoped discovery, quality gates, and source navigation
can identify the NeX-AE suite through one stable convention.

```text
test_p4_* -> test_ae_p4_*
test_p5_* -> test_ae_p5_*
test_p6_* -> test_ae_p6_*
```

The change is organizational only. It does not alter runtime behavior,
database schemas, contract identifiers, test function names, or protected
smoke activation policy.

## Inventory and Decision

The frozen pre-change inventory contained:

- P4: 3 test modules;
- P5: 16 test modules;
- P6: 30 test modules; and
- total: 49 AE-owned transition test modules.

Future AE transition tests use `test_ae_pN_*`. Tests that genuinely validate
a platform-wide boundary use `test_platform_pN_*` rather than being assigned
to AE for convenience.

The `nex-ae-api` Slice Gate now discovers the complete owned suite with only
the established `test_nex_ae_*.py` and `test_ae_*.py` patterns. The temporary
phase-specific `test_p5_*.py` and `test_p6_*.py` selectors were removed. This
also brings P4 transition tests into the ordinary AE Slice Gate automatically.

## Compatibility and Traceability

One cross-test import was updated to the owner-first module name. Current P6
traceability and closure documents now cite `tests/test_ae_p6_*` paths.

The P4 CA01 v1.0 manifest and addendum remain unchanged as historical frozen
evidence. A new additive
`P4_CA01_Controlled_Amendment_Manifest_v1.1.csv` records the owner-first test
path and the current closure-runner digest. The active P4 CA01 runner consumes
v1.1, preserving the original evidence instead of rewriting it.

`tests/test_ae_transition_test_namespace.py` fails if a new phase-first
`tests/test_p[0-9]*_*.py` module is introduced and confirms that P4, P5, and
P6 each retain owner-first coverage.

## Collection Parity

The P4-P6 target collection remained exactly stable:

```text
before: 461 tests
after:  461 tests
```

Repository-wide collection changed from 14,748 to 14,749 only because the
new namespace guard adds one test.

## Verification

Focused P4-P6 regression and namespace/gate tests:

```text
478 passed, 5 protected tests skipped
```

NeX-AE Slice Gate:

```text
3,948 passed, 10 protected tests skipped
statement coverage: 98.63%
branch coverage: 96.86%
changed quality and P4 closure scripts: 100% statement, 100% branch
contract validation: 174 schemas, 236 examples,
                     204 negative examples, 7 OpenAPI documents
commands: 5/5 PASS
```

Repository-wide Full Gate:

```text
14,711 passed, 38 protected tests skipped
statement coverage: 97.26%
branch coverage: 96.71%
contract validation: 174 schemas, 236 examples,
                     204 negative examples, 7 OpenAPI documents
exit code: 0
```

The protected skips require separately enabled PostgreSQL, provider, browser,
or release-acceptance environments. P7-CA00 changes no persistence or provider
behavior, so no database migration or remote-provider execution was required.

## Evidence Digests

```text
Full Gate log:
  sha256:c5bb97349ed93005426e4fa5ba2557d9e2b8321092a93c4e8d453841b3d03ef9
Platform coverage JSON:
  sha256:833f0cb109279d2e0518a1384598e905333d9d004149ce85ef585d8c4b2a1d24
Platform JUnit XML:
  sha256:1c7917ffbd78cc0bc6c2d021b3015fe262c3deea1a158a46f8327b7507fbc5a8
AE Slice Gate coverage JSON:
  sha256:8754fde965e09b475d6dc46fd03983ebec2ce3e609817fa4daf15c09d22724fd
```

## P7 Entry Decision

P7 entry is **ACCEPTED** with owner-first AE transition test discovery as the
canonical convention. The prior test semantics and all P4-P6 regression
evidence remain intact.
