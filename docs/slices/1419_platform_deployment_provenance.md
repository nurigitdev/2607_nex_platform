# Slice 1419: Platform Deployment Provenance

## Outcome

- Added deterministic per-artifact provenance for the full Git revision,
  dependency lock, Containerfile/build definition, owner-scoped build context,
  immutable base image, target platform, and optional final image digest.
- Added a timestamp-free complete release manifest covering all six artifacts.
- Separated `BUILD_INPUTS_READY` from `RELEASE_SET_READY` so absent or partial
  image digests cannot be represented as a releasable set.
- Required a clean source tree and six distinct immutable image references
  before issuing a complete release-set digest.

## Identity Decision

The build-input manifest and deployable release set are intentionally distinct.
Current repository evidence records six reproducible artifact inputs but does
not claim that images were built. A synthetic complete-set proof validates the
digest algorithm without publishing those synthetic references as build
evidence. Slice 1420 owns actual local package/image execution evidence.

Artifact and release digests exclude timestamps, temporary directories, host
paths, runtime configuration values, credentials, private payloads, and
production endpoints. Partial artifact sets, mutable image tags, duplicate
image references, dirty-source release claims, and production deployment
approval all fail closed.

## Verification

- Focused tests: `11 passed`; provenance domain and smoke runner statement and
  branch coverage are both `100%`.
- Provenance smoke: six artifacts, six unique provenance digests, zero claimed
  built image digests, and one synthetic complete-set rule proof; no database,
  provider, registry, or production resource was contacted.
- Slice Gate: `979 passed, 11 skipped`; statement coverage `98.45%`; branch
  coverage `97.80%`; smoke-runner statement and branch coverage `100%`;
  contract validation `166` schemas, `228` examples, `196` negative examples,
  and `7` OpenAPI documents.
