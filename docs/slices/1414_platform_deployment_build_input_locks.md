# Slice 1414: Deterministic Dependency and Build-Input Locks

## Outcome

- Added a Python 3.12 Linux production lock containing exact transitive
  versions and SHA-256 distribution hashes.
- Closed implicit production dependencies for MeCab Korean tokenization and
  YAML-backed operational contract diagnostics.
- Reused the npm lockfile's exact versions and SHA-512 integrity metadata for
  the AE Web artifact.
- Added a deterministic build-input manifest and digest over toolchain
  constraints, dependency locks, and the artifact catalog.

## Build Decision

Python service images install `deployment/locks/python-production.lock` with
hash enforcement. AE Web images use `npm ci`; range-only installs and mutable
lock resolution are prohibited. The first Python lock intentionally captures
the dependency versions already exercised by the successful regression
environment instead of silently upgrading to newer allowed versions.

The lock compiler preserves existing pins by default. Dependency upgrades are
explicit reviewed changes and require regression before a new lock is
accepted.

## Verification

The lock validator fails closed on a missing input, unpinned Python package,
missing SHA-256 hash, duplicate package, forbidden index/source directive,
invalid npm lock version, non-HTTPS Node source, missing integrity, runtime
constraint drift, or unlocked artifact family. No package is installed and no
production resource is contacted by the smoke evidence.

The accepted inputs contain 45 Python packages with 1,258 SHA-256 hashes and 4
Node packages with 4 SHA-512 integrity records. A hash-enforced pip dry run
confirmed all 45 exact Python versions match the regression environment. Slice
Gate passed all 5 commands in 169.178 seconds with 988 tests passed and 11
protected-policy skips. Statement coverage was 98.48% and branch coverage was
97.88%; both the lock domain and smoke runner reached 100% statement and branch
coverage. Contract validation passed for 166 schemas, 228 examples, 196
negative examples, and 7 OpenAPI documents.
