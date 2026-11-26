# W80-CA00G.7: Protected Live Matrix and Full Gate Closure

## Status

`CLOSED / PROTECTED LIVE ACCEPTED / REPOSITORY FULL GATE PASSED`

The user-review and approval runtime is accepted on the installed canonical
platform. The matrix preserves sequential business approval, explicit voucher
review, accounting correction re-entry, immutable revision history, and latest
active-checkpoint execution without scenario-specific product branches.

## Accepted Journeys

Six independent journeys were executed:

1. one-stage business approval, ending at explicit voucher review;
2. two-stage business approval, ending at explicit voucher review;
3. three-stage business approval, voucher review, accounting approval, and
   immutable Journal posting;
4. middle-stage business rejection with no VoucherCandidate;
5. final-stage business rejection with no VoucherCandidate;
6. accounting rejection, latest-revision correction, explicit resubmission,
   accounting approval, and immutable Journal posting.

All decision replays returned success without duplicate business records. The
two business rejection routes remained terminal. Accounting rejection alone
created a new `WAITING_VOUCHER_REVIEW` checkpoint and resumed from the newest
immutable Candidate revision.

## Protected Environment

The exact-head run used the canonical installed topology rather than an
in-process product substitute:

- all eight service PostgreSQL databases with current migrations;
- canonical Compose services and installed background processes;
- OpenBao AppRole resolution and startup-issued signed service trust;
- RustFS private object storage;
- authenticated Playwright;
- the live DGX generation provider `Qwen3.8-Flash-Next` at immutable revision
  `hf:fc694b54fb0174e0913e6adf86691ef85a4ead47`.

The nine-image OCI release set passed non-root, packaged-entrypoint, manifest,
and background-process checks. Its release-set digest is
`sha256:e62dc4872f805ee5f9b4900863a1f73efcffced10dd5066586a1f81f85ab6f48`.
The installed AE Product Runtime image ID is
`sha256:8c1358441dd3aee7ba09f3e4c184b1472eacc0b534961c544cb56b914a4caeb7`.
The accepted product source revision is
`3e1e1ca2a08241ba96f3c1373e0f888c00beac6f`.

## Persistence and Replay Evidence

The final isolated database state contained:

| Record | Count |
| --- | ---: |
| Business proposals | 6 |
| Approved proposals | 4 |
| Rejected proposals | 2 |
| VoucherCandidates | 4 |
| Immutable VoucherCandidate revisions | 7 |
| Immutable Journals | 2 |
| Product preparation checkpoints | 24 |
| Duplicate pending authorities | 0 |

The seven VoucherCandidate revisions are derived from the six browser outcomes:
four initial approved-proposal Candidates, two explicit user-review revisions,
and one accounting-correction revision. The protected matrix derives this
invariant from the journey outcomes instead of relying on a fixed historical
count.

After restart, OA, AE, WC, and EOS returned `READY`; AE RuntimeJob, WC delivery,
and EOS outbox pending counts remained zero. Replay preserved the same
database counts and active authority. All eight isolated schemas were dropped
after acceptance, and the cleanup report recorded zero residue.

## Browser and Diagnostic Evidence

Authenticated Playwright observed all six routes and 593 authenticated HTTP
responses. Every browser acceptance check passed, including sequential
one/two/three-stage approval, terminal rejection, no Voucher creation for
rejected proposals, latest-revision correction, Journal completion, replay,
and screen evidence integrity.

The restricted diagnostic package contains raw prompt, AgentPlan, and
ExecutablePlan evidence under the approved DEBUG policy. It contains 65 files,
34 PNG captures, and six screen manifests. Secret values are forbidden and no
secret value was admitted. The manifest digest is
`2e861c505f53e5f5e7455511ee84287a9a514d90cf5b0f710458b2f14f68bb8c`.

## Verification

- EOS Slice Gate: `2,439 passed`, `69 skipped`; statement `96.37%`, branch
  `94.19%`.
- Protected matrix focused tests: `7 passed` and Ruff passed.
- React focused/full verification after the Full Gate timing reconciliation:
  `35 files`, `155 passed`.
- Repository Full Gate: `24,288 passed`, `199 skipped`; statement `96.12%`,
  branch `94.97%`; contract validation `PASS`; Node `407 passed`; React
  `155 passed`; final result `PASS`.

The Full Gate first exposed two test-baseline issues without a product-runtime
failure: the synthetic OCI fixture omitted four already-packaged activation
locks, and a React async assertion retained Testing Library's one-second wait
under full parallel load. Commit `87aaefe2` reconciles only those test
baselines. The complete Gate was then rerun from the beginning.

## Evidence Index

- Protected matrix:
  `reports/deployment/mybee-w80-ca00g7-protected-matrix.json`
- Browser evidence:
  `reports/deployment/mybee-w80-ca00g7-browser-evidence.json`
- Restart evidence:
  `reports/deployment/mybee-w80-ca00g7-restart-evidence.json`
- Canonical OCI build:
  `reports/deployment/canonical-platform-oci-image-build.json`
- Restricted diagnostic package:
  `reports/deployment/mybee-w70-m1-diagnostic-evidence/mybee-w80-ca00g7-20261126T103153Z-e9292096`

## Closure Decision

`W80-CA00G.7` is closed. The parent `W80-CA00G` contract is accepted for
amount-tiered sequential business approval, explicit user review, separate
accounting approval, correction re-entry, immutable audit lineage, installed
restart/replay, and authenticated user-facing evidence.
