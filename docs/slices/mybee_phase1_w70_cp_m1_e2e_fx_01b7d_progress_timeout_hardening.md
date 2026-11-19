# CP-M1-E2E-FX-01B.7D: Approval/Result Progress Diagnostics and Playwright Timeout Budget Hardening

## Purpose

The protected installed journey passed semantic admission and submitted its
first transaction, but then remained in approval/result polling until the
parent Playwright process was terminated after 960 seconds. The browser's own
result deadline was 900 seconds, while the parent budget also included platform
startup, login, and submission. The parent therefore terminated before the
browser could publish its bounded `ProductResultTimeout` evidence or before the
runner could inspect the isolated AE and WC databases.

This corrective Slice makes the timeout hierarchy explicit and preserves a
redacted progress snapshot before installed teardown.

## Decision

- Separate UI action timeout from business result timeout.
- Keep UI actions bounded at 60 seconds.
- Keep each of the two admitted transaction result windows at 900 seconds.
- Set the parent process budget to two result windows plus a 180-second
  startup/teardown margin: 1,980 seconds.
- Emit an atomic progress heartbeat at stage changes and at most every five
  seconds while waiting for approval or result.
- Persist only bounded stage, sequence, transaction index, poll count, approval
  count, and pending-gate count. Do not persist prompts, credentials, IDs,
  response bodies, or provider output.
- If the parent process still expires, return structured
  `PLAYWRIGHT_PROCESS_TIMEOUT` evidence from the last admitted heartbeat.
- Before teardown, collect bounded AE execution/attempt and WC WorkItem,
  assignment, claim freshness, approval, and outbox states.
- Do not add a database migration, public API field, fixture, or product-state
  mutation.

## Implementation

- The Playwright harness now accepts distinct action and result timeout
  environment contracts.
- A progress reporter writes owner-local `0600` JSON through an atomic temporary
  file rename. Write failure never replaces the authoritative journey failure.
- Approval/result polling records liveness every five seconds and immediately
  records pending and completed approval transitions.
- The Python runner clears stale progress before launch, validates all progress
  fields on read, and rejects unbounded values.
- The parent timeout is derived from the admitted two-transaction journey rather
  than a single hard-coded browser deadline.
- Browser failure evidence now includes bounded progress counters. The reporter
  preserves the last admitted counters when changing its state to `FAIL`, so
  both parent-process and browser-owned result timeouts retain useful progress.
- WC diagnostics query only enum-like operational state and never project
  opaque identifiers or business payloads.

## Verification

- Focused Python regression: `17 passed`.
- Focused Playwright harness regression: `10 passed`.
- Full AE Web regression: `385 passed`.
- AE Slice Gate: `6828 passed, 51 skipped`.
- AE statement coverage: `96.40%` with threshold `95.00%`.
- AE branch coverage: `94.64%` with threshold `94.00%`.
- Product coverage: statement `97.02%`, branch `94.94%`.
- Contract validation, Golden Journey transition audit, Demo product dependency
  audit, AE coverage ownership, and all six tiered gate commands: `PASS`.
- Actual `nex_ae_test` and `nex_wc_test` read-only diagnostic smoke: `PASS`;
  empty tenant scope returned bounded `none` states.
- No database or public API contract changed.

## Protected Live Rule

The committed exact-head installed journey must be rerun with the canonical
Qwen3.5-9B provider. A failure is acceptable evidence only when it records:

1. the exact browser stage and bounded progress counters;
2. AE execution and attempt state;
3. WC work, assignment, claim, approval, and outbox state;
4. no prompt, credential, opaque ID, or response body;
5. complete container and isolated-schema cleanup.

The diagnostic Slice does not itself change the product workflow. Any newly
identified workflow defect must be handled as a separate corrective boundary
before `CP-M1-E2E-FX-01B.7` can close.
