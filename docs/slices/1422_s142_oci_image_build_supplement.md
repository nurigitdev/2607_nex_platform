# Slice 1422: S142 OCI Image Build Supplement

## Outcome

- Added one protected command that materializes and builds all six owner-scoped
  OCI contexts from a clean committed source revision.
- Bound actual BuildKit manifest digests, Docker image IDs, pinned base images,
  source revision, dependency lock digests, definition digests, and context
  digests into the existing complete-set provenance contract.
- Added fail-closed inspection for non-root runtime users, immutable labels,
  six default packaged commands, and seven network-isolated background
  container checks.
- Kept JSON evidence and build logs under ignored `reports/`; no registry push,
  staging contact, production contact, or production approval is performed.
- Isolated Buildx from the host home and registry credentials with an ephemeral
  empty Docker CLI configuration.
- Added digest-pinned full Python and Rust builder stages for native wheels
  after the first real build exposed that `mecab-ko-python` cannot compile in
  the compiler-free slim runtime image. Final Python images retain the pinned
  slim base and install only the locked wheel set without index access.
- Recorded image ID, manifest digest, and config digest independently. Docker
  29 with the containerd image store reports the manifest as `.Id`, while
  older stores may report the config digest; both forms remain descriptor-
  checked and fail closed when the identities are unrelated.
- Separated container-default API commands from loopback local-process
  commands: packaged APIs bind to `0.0.0.0`, and AE Web explicitly clears the
  inherited Node entrypoint before its exact npm command is inspected.

## Protected Command

```bash
NEX_PLATFORM_OCI_IMAGE_BUILD=1 \
./.venv/bin/python scripts/deployment/build_platform_images.py \
  --execute \
  --report reports/deployment/s142-oci-image-build.json \
  --summary
```

Both `--execute` and the environment opt-in are required. A normal Quality
Gate invokes the command without either and verifies the skip boundary.

## Decision

Only an exact six-image set built from a clean revision can become
`RELEASE_SET_READY`. Local image evidence does not imply registry publication
or production deployment approval. A mutable or missing builder image, failed
native wheel build, partial image set, inspection mismatch, or background
check failure produces no release-set digest. S143 remains the next
requirement.

## Verification

- Focused OCI/provenance/closure tests: `80 passed`.
- Slice Gate: `391 passed, 6 skipped`; statement and branch coverage both
  `100%` across the five selected OCI build, definition, and provenance
  modules; contract validation `166` schemas, `228` examples, `196` negative
  examples, and `7` OpenAPI documents.
- S142 repository closure: `8/8` audits passed with `6` artifacts, `13`
  process bindings, `5` profiles, and `65` lifecycle process steps.
- The protected Docker result is generated after this Slice is committed so
  the image labels and release manifest refer to a clean immutable revision.
