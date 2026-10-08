# Slice 1460: S146 Object Storage Compose

## Outcome

- Added a layered single-host Docker Compose override for digest-pinned RustFS
  1.0.1 and preserved the source-controlled S143 protected attestation by
  leaving its base Compose file unchanged.
- Added non-root durable storage, no host-published RustFS port, disabled
  console, internal object network, health dependency, and Traefik-managed TLS
  routing.
- Extended production admission to 20 secret references and 11 HTTPS
  connection bindings. CX and AE receive separate OpenBao-managed credential
  pairs and separate buckets; root credentials use Docker secret files only.
- Added static topology validation, drift tests, a bounded audit runner, and a
  Full Gate hook. The actual three-layer Compose render passed
  `docker compose config --quiet` on the host engine.

## Safety Decisions

- S143 historical evidence remains bound to the unchanged S143 Compose bytes.
  S146 capability is additive through an override rather than a rewrite of
  prior accepted topology.
- Application containers never receive RustFS root credentials. Raw access or
  secret values are forbidden in Compose; only versioned OpenBao references
  and Docker secret file paths are present.
- RustFS remains unreachable from a host port and from the general service
  network. Traefik alone joins both the service and object-storage networks.
- `OBJECT_ONLY` is the default. `OBJECT_FIRST` and `FILESYSTEM_FIRST` require
  explicit migration or rollback admission variables.

## Verification

- Focused regression covers valid topology, image/user/network/secret/route/
  bucket drift, unreadable assets, audit pass/fail, and the expanded production
  configuration lifecycle: `23 passed`, statement/branch coverage `100%/100%`.
- Platform Slice Gate: `450 passed`, `6 skipped`; scoped statement/branch
  coverage `100%/100%`.
- Contract validation passed with `166` schemas, `228` examples, `196`
  negative examples, and `7` OpenAPI documents.
- Docker Compose rendered the S143 + S144 + S146 stack successfully with
  immutable placeholder application image references.
- Protected RustFS/OpenBao execution is intentionally deferred to Slice 1461.
