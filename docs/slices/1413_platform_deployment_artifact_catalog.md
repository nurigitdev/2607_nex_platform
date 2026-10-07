# Slice 1413: Immutable Deployment Artifact Catalog

## Outcome

- Added a typed catalog for six owner-scoped OCI artifacts and thirteen exact
  process bindings.
- Bound every API, web, worker, and daemon to one artifact and one semantic
  entrypoint while preserving existing runtime ownership.
- Added order-independent canonical JSON and a SHA-256 catalog digest.
- Added strict immutable image-reference validation that rejects tags,
  malformed repositories, and non-SHA-256 content digests.

## Design Decision

The catalog describes artifact ownership and build inputs without selecting a
registry or embedding configuration values. The artifact catalog digest is the
identity of this build specification; it is not an image content digest. Slice
1419 will bind real image digests into a release artifact set.

## Verification

Unit and smoke coverage validate the six artifacts against the existing
13-process runtime manifest, reject duplicate/unbound/owner-drifted records,
prove deterministic serialization, and confirm that only digest references are
admissible. Slice Gate passed all 5 commands in 187.185 seconds with 983 tests
passed and 11 protected-policy skips. Statement coverage was 98.48% and branch
coverage was 97.87%; both the artifact domain and smoke runner reached 100%
statement and branch coverage. Contract validation passed for 166 schemas, 228
examples, 196 negative examples, and 7 OpenAPI documents. No registry or
production resource was contacted.
