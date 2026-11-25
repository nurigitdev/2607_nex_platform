# W80-CA00G.0A Protected Live Progress and Playwright Evidence Acceptance

## Status

IMPLEMENTED / PROTECTED LIVE EXECUTION PENDING

## Purpose

Prove that the W80-CA00G.0 owner-scoped progress projection is visible during
installed product execution rather than only after the Chat request returns.
This Slice adds acceptance instrumentation only. It does not add a business
workflow, fixture branch, database migration, or alternate execution path.

## Protected Boundary

- Reuse the existing installed Journal and accounting-allocation product
  journeys with actual OA, AE, WC, EOS, WA PostgreSQL databases.
- Use the canonical remote generation provider and authenticated Chromium.
- Attach progress observation before the browser submits the prompt.
- Prove the first progress GET starts no later than the Chat POST response.
- Capture each observed append-only progress-list change in a separate,
  digest-bound Playwright manifest.
- Read the final owner-scoped projection and verify ordered unique sequences,
  terminal state, and absence of raw prompt/private payload.
- Observe a stable request count after terminal result to prove polling stops.
- Retain the existing isolated-schema cleanup and zero-residue contract.

## Screen Evidence

The existing business-journey screenshots remain unchanged. Progress captures
use separate manifests:

```text
mybee-m1-w80-ca00g0a-journal-progress-screen-manifest.json
mybee-m1-w80-ca00g0a-allocation-progress-screen-manifest.json
```

Each PNG is mode `0600`, each directory is mode `0700`, and every manifest entry
contains byte size, SHA-256 digest, capture time, expected state, assertion, and
interaction identity. Credentials and raw prompt are forbidden from report and
manifest metadata.

## Verification Plan

1. Node contract tests for PASS and fail-closed progress evaluation.
2. Python source/protected-result admission tests.
3. Build exact-head canonical OCI images and the packaged AE Runtime image.
4. Run `run_mybee_w80_ca00g0a_progress_acceptance.py --execute`.
5. Inspect representative PNG files for ordering, time Prefix, overflow, and
   terminal result coexistence.
6. Record provider revision, event inventory, screenshot manifest digest,
   database isolation, and zero-residue outcome here after execution.
