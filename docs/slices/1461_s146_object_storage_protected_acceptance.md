# Slice 1461: S146 Object Storage Protected Acceptance

## Outcome

Implemented and executed the protected RustFS acceptance against the real
test PostgreSQL databases and an ephemeral OpenBao, Traefik, and RustFS
single-host Compose stack.

## Implementation

- Added a SigV4 RustFS IAM admin port with exact bucket-scoped policies for
  separate CX and AE application credentials.
- Added OpenBao-backed RustFS SSE-S3 master-key materialization without placing
  the raw key in Compose, image layers, reports, or application containers.
- Hardened S3 metadata parsing so user metadata names are case-insensitive,
  matching the behavior observed from RustFS and S3 semantics.
- Added an opt-in protected runner that performs real platform test migration,
  metadata-only PostgreSQL probes, bucket/lifecycle bootstrap, adapter and
  migration round trips, owner isolation, restore, restart, and cleanup.

## Protected Evidence

- Five test database migrations were current; CX and AE metadata probes each
  completed insert/select/rollback against the expected database and role.
- Two versioned, AES256-default buckets each reported all three lifecycle
  rules. Two independent IAM users could use only their owner bucket, and both
  cross-bucket checks were denied.
- CX source and extracted Markdown plus AE generated response completed real
  encrypted round trips. Two migration inventories copied and verified one
  owner payload each without deleting the filesystem source.
- A delete marker was created, a historical encrypted version was restored as
  a new current version, and both pre-existing adapters read successfully
  after the RustFS container restarted on the same named volume.
- RustFS ran healthy as `10001:10001`; Traefik served its `/health` endpoint
  through the managed platform TLS certificate. Cleanup removed nine versions
  or delete markers, both buckets, containers, and named volumes.

## Privacy

The ignored runtime report contains metadata-only counts and digests. It does
not contain credentials, raw private payloads, object keys, endpoints, or
physical source paths. Production was not contacted or approved.

## Verification

- Platform Slice Gate passed with `411 passed`, `6 skipped`; scoped statement
  coverage was `99.70%` and branch coverage was `99.45%`.
- Object-storage, IAM, Compose, and protected-runner regression passed, as did
  contract validation for `166` schemas, `228` examples, `196` negative
  examples, and `7` OpenAPI documents.
- The protected acceptance completed with `status=PASS` using
  `nex_oa_test`, `nex_ag_test`, `nex_ae_test`, `nex_cx_test`, and
  `nex_mo_test`.

Slice 1462 owns closure attestation, the operations runbook, Full Gate, and
S147 activation.
