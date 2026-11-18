# CP-M1-E2E-FX-01B.6B.5B.4A Canonical AE NSL Wheel Packaging Reconciliation

## Scope

This corrective Slice reconciles the canonical nine-image release builder with
the already admitted NSL v0.2.1 wheel and AE Product Runtime package. It adds no
business behavior, fixture, database migration, remote-provider dependency, or
tenth image.

## Implemented Boundary

- retained the historical/default `ae-runtime` target for compatibility;
- promoted only the current canonical `nex-ae-runtime` artifact to the
  `ae-product-runtime` target;
- embedded the admitted NSL v0.2.1 wheel in that target and installed it with
  `--no-index --no-deps`;
- verified the wheel filename, byte size, SHA-256, source revision, and Platform
  dependency-lock SHA-256 before Docker is contacted;
- added the wheel bytes to the owner-scoped build context after admission and
  recalculated the OCI context digest so image provenance binds the artifact;
- embedded the existing verified Product Runtime admission, activation,
  rollback, capability registry, Skill package, EOS contract, and Project Agent
  policy assets in the same canonical AE image;
- retained `USER 65532:65532`, the read-only runtime contract, and an owner-only
  NSL state directory;
- added build-time `nsl`, `mybee_ax`, Product package, and AE worker source
  admission checks;
- required the complete canonical release validator to observe both the
  `ae-product-runtime` target and a passing wheel admission receipt;
- reconciled the packaged AE Web image command with its installed static server
  (`node scripts/serve.mjs`) while retaining `npm start` for host development;
- kept the prior wrapper image builder as a compatibility path; it is no longer
  required to make the canonical release-set AE package check pass.

## Fail-Closed Rules

The build is rejected before image construction when the wheel is absent, the
lock schema is invalid, the wheel digest or size differs, or the production
Python lock digest differs. A release is also rejected when the AE target,
artifact order, image command, non-root user, package-check inventory, package
readiness, isolation status, or wheel context path drifts.

## Verification

| Evidence | Result |
|---|---|
| focused deployment and packaging regression | `63 passed` |
| expanded topology, provenance, and installed-runtime regression | `137 passed` |
| changed catalog, OCI, and canonical builder coverage | statement `100.00%`, branch `100.00%` |
| wheel mutation rejection | PASS |
| Platform lock mutation rejection | PASS |
| actual `ae-product-runtime` Docker build | PASS |
| actual admitted wheel | `nex_skill_language-0.2.1`, SHA-256 `a89ce5fd...507cb` |
| build-time Product Runtime import/admission | PASS |
| isolated AE worker container package check | `package_ready=true`, `runtime_ready=false`, `secret_included=false` |
| remote provider | not required and not contacted |

The clean-tree canonical nine-image release build and complete twelve-process
background/package matrix are executed from the committed Slice revision. Their
machine-readable evidence is written to
`reports/deployment/canonical-platform-oci-image-build.json`; the report and
build logs remain local operational evidence and are not registry-pushed.

## Decision

The missing NSL wheel is no longer an AE package blocker in the canonical image
definition. `CP-M1-E2E-FX-01B.6B.5B.5` may resume only after the committed
nine-image build records a complete release set and all package checks pass.
