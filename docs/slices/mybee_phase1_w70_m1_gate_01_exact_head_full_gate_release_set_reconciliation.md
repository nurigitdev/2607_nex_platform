# W70-M1-GATE-01: Exact-Head Repository Full Gate and Release-Set Reconciliation

## Status

- Date: `2026-11-22`
- Status: `COMPLETE`
- Milestone: `M1_RELEASE_SET_RECONCILED`
- Product source revision: `773769bafa2ac6680d3a775f81902a2e69103909`
- Database migration: none
- Public API change: none
- Registry push: not performed
- Production contact: not performed

## Decision

The W70 M1 repository and deployable product baseline are reconciled. The
canonical Repository Full Gate passed against the tracked product content that
was committed unchanged as the product source revision above. A clean-tree
nine-image OCI release set was then built from that revision and admitted by
the canonical Compose topology check.

The documentation commit that records this result is intentionally later than
the product source revision. It changes no packaged product, deployment,
migration, lock, or runtime input. The release set therefore remains bound to
the exact product source revision rather than to the evidence-only follow-up.

## Exact-Head Reconciliation

The first Full Gate runs identified four stale or incomplete repository
assumptions. Each was corrected before the passing run:

1. The D04 Skill inventory now admits the already signed and registered
   `journal_posting.v1_0_2.ns` artifact.
2. The Qwen3.5-9B generation path now preserves the configured two-attempt MO
   retry profile without downstream timeout inversion. MO uses a 125-second
   attempt budget; CX and AE use a 260-second total transport budget.
3. The current platform topology expectation is 21 processes and explicitly
   includes `nex-wc-assignment-dispatch-worker`.
4. The local development service launcher supplies the MyBee product runtime
   path to `nex-ae-api`, matching the installed OCI composition. Other
   services do not receive that product path.

No retry count, synchronous planning behavior, database schema, or external
contract was changed. The timeout correction enlarges only the maximum
transport budget required by the existing retry policy.

## Repository Full Gate

Command:

```bash
REPORT_DIR=reports/quality/mybee-w70-m1-gate-01-full-gate-r4 \
  scripts/quality/run_quality_gate.sh
```

Result:

- Exit status: `PASS` (`0`)
- Python tests: `24,031`
- Failures/errors: `0 / 0`
- Skipped: `193`
- Python test duration: `2,541.563s`
- Repository statement coverage: `96.3353%`
- Repository branch coverage: `95.3119%`
- Product statement coverage: `98.2666%`
- Product branch coverage: `96.7614%`
- Smoke/test harness statement coverage: `93.5929%`
- Smoke/test harness branch coverage: `91.6960%`
- AE Web tests and the remaining contract, schema, example, privacy, topology,
  and historical closure runners passed as part of the same command.

Local ignored evidence digests:

- `coverage.json`: `sha256:83810d5506d3f9a9a8dfd72db260c7af6695aa113239f6da2a9e102551bee1f5`
- `junit.xml`: `sha256:dc21d70f84d1e0bd77208bd03af438c0877fa64e3e25d5253f5023cca614db9c`

Protected PostgreSQL, Playwright, and live-provider runners that require an
explicit opt-in remain reported as `SKIPPED`; this Gate does not relabel them
as passed. The accepted M1 live journey remains the separately recorded
source-bound `CP-M1-E2E-FX-01B.7Q` evidence.

## OCI Release Set

Build command:

```bash
NEX_CANONICAL_PLATFORM_OCI_IMAGE_BUILD=1 \
  ./.venv/bin/python scripts/deployment/build_canonical_platform_images.py \
  --execute \
  --report reports/deployment/mybee-w70-m1-gate-01-canonical-images.json \
  --summary
```

Result:

- Artifacts/manifests: `9 / 9`
- Non-root images: `9 / 9`
- Background and packaged-entrypoint checks: `12 / 12`
- Build-inputs digest: `sha256:898a9a2de5ffe744e53dc222a3463d156000c5153eaf23d23be309fe65f7db03`
- Release-set digest: `sha256:90b5903337e04b8d5b8b7e2394c4a1f0e77206463e4e00cb3d725d720e33cd5a`
- NSL wheel: `nex_skill_language-0.2.1-py3-none-any.whl`
- NSL wheel digest: `sha256:a89ce5fde1a32749565ba0906a2f1faf1d440ff6db2dfc07c0b2a581378507cb`
- Secret included: `false`
- Registry push performed: `false`

The release contains `nex-oa-runtime`, `nex-ae-runtime`, `nex-cx-runtime`,
`nex-mo-runtime`, `nex-ag-runtime`, `nex-wc-runtime`, `nex-eos-runtime`,
`nex-wa-runtime`, and `nex-ae-web`. Every image records the same product source
revision and an immutable dependency-lock digest.

## Compose Reconciliation

Command:

```bash
NEX_CANONICAL_PLATFORM_COMPOSE_RENDER=1 \
  ./.venv/bin/python scripts/deployment/check_canonical_platform_compose.py \
  --execute \
  --image-report reports/deployment/mybee-w70-m1-gate-01-canonical-images.json \
  --report reports/deployment/mybee-w70-m1-gate-01-compose.json \
  --summary
```

Result:

- Status: `PASS`
- Compose services: `18`
- Installed processes: `21`
- Images: `9`
- Canonical runtime environments: `13`
- Secret or database URL rendered: `false / false`
- Manual component composition: `false`
- P8 demo process manifest used: `false`

The local ignored release and Compose reports have SHA-256 digests
`ffcf9903db84d61804e8d335c9964f165d66e88b78e6908517c32498d19c9cda`
and `ecfc211385fa03d9a1fd341639089709ad15d3c909fcb19fd26c306f4b08550a`.

## Exit and Handoff

`W70-M1-GATE-01` is closed. W70 M1 has a passing repository baseline and a
complete, non-root, source-bound nine-image release set. The next planned
boundary is W80, beginning with the W40/W60-to-W80 entry reconciliation before
`S5-01` through `S5-04` reversal, settlement, remeasurement, period close, and
Journal reconciliation work.
