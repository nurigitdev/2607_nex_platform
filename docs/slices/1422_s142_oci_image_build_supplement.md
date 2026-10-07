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
or production deployment approval. S143 remains the next requirement.

## Verification

- Focused domain/runner tests: `45 passed`; statement and branch coverage both
  `100%` across the two new modules.
- Slice Gate: `366 passed, 6 skipped`; statement coverage `100%`; branch
  coverage `100%`; contract validation `166` schemas, `228` examples, `196`
  negative examples, and `7` OpenAPI documents.
- S142 repository closure: `8/8` audits passed with `6` artifacts, `13`
  process bindings, `5` profiles, and `65` lifecycle process steps.
- The protected Docker result is generated after this Slice is committed so
  the image labels and release manifest refer to a clean immutable revision.
