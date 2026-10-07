# Slice 1415: Owner-Scoped OCI Build Definitions

## Outcome

- Added digest-pinned Python 3.12 and Node 22 OCI build definitions for all six
  owner-scoped artifacts.
- Added five Python service targets and one AE Web target with exact dependency
  lock installation, OCI provenance labels, and non-root runtime users.
- Added deterministic owner-allowlist context materialization and context
  digests; repository-root builds are not admitted.
- Included only the owning service source, shared runtime, service-local
  migrations, bounded migration runner, and required lock inputs.

## Build Decision

The five Python service artifacts share one reviewed Containerfile while each
uses a distinct target and owner-specific materialized context. AE Web has a
separate Node Containerfile. This keeps build mechanics consistent without
combining service source or data ownership into one platform image.

Official base-image OCI index digests were resolved read-only. Docker daemon
access is unavailable in the current environment, so this Slice proves static
definition and deterministic context evidence. Actual build/run evidence is a
protected Slice 1420 responsibility.

## Verification

Validation rejects missing targets, mutable base references, duplicate or
unsafe context paths, missing non-root users, `ADD`, dependency installation
without hash enforcement, and npm installs outside `npm ci`. No production
resource is contacted.

- Focused tests: `16 passed`; deployment OCI module and smoke runner statement
  and branch coverage are both `100%`.
- Slice Gate: `984 passed, 11 skipped`; statement coverage `98.48%`; branch
  coverage `97.88%`; contract validation `166` schemas, `228` examples, `196`
  negative examples, and `7` OpenAPI documents.
- Deterministic context evidence: `6` artifacts, `6` unique targets, `801`
  files, and `6` digest-pinned base references.
- The `11` skips are pre-existing OA protected PostgreSQL smoke tests requiring
  explicit enablement; the OCI definition smoke ran and passed in this Gate.
