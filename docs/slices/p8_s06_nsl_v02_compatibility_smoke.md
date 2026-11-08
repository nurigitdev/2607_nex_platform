# P8-S06: NSL v0.2 Compatibility Smoke

## Status

Completed on 2026-10-21. P8.1 is closed with source-backed NSL v0.1 READ
regression, admitted NSL v0.2 READ execution, controlled WRITE-prefix
suspension, and zero EOS mutation evidence.

## Goal

Prove that the existing NSL v0.1 compatibility path remains operational while
the exact P8-admitted NSL v0.2 release can execute its READ path and reach the
approval boundary of a controlled WRITE path without performing a write.

## Compatibility Boundary

- Preserved the host `nex-skill-language==0.1.0` installation before and after
  the smoke.
- Verified the clean NSL v0.2 source revision
  `a5a0f5fd7acf4adbbccf890dca2f9998d055d65e` and tree
  `e7ffb07378ba01f4c9da6645f91b75614c605907`.
- Verified the admitted v0.2 wheel digest
  `sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135`.
- Installed that wheel into an ephemeral site-packages directory and launched
  a subprocess with an isolated import path. The Platform environment was not
  upgraded or mutated.
- Ran the v0.2 READ profile with `--no-isolate` inside that v0.2 subprocess.
  This matches the selected `NSL_V02_IN_PROCESS` runtime profile and prevents
  a nested NSL process from resolving the host v0.1 package.
- Required the P8-S05 public API adapter readiness and release-admission hashes
  before accepting the v0.2 execution evidence.

## Protected Smoke Evidence

The protected runner is
`scripts/smoke/run_p8_s06_nsl_compatibility.py`. It requires both `--execute`
and `NEX_AE_P8_S06_NSL_COMPATIBILITY_SMOKE=1`; the default Full Gate invocation
is skip-safe.

- NSL v0.1 READ: `FINANCE.PROJECT_BUDGET_CHECK`, `COMPLETED`, two tool calls,
  one output.
- NSL v0.2 READ: `FINANCE.VOUCHER_DRAFT_VALIDATE`, `COMPLETED`, three tool
  calls, one output.
- NSL v0.2 controlled prefix: `WAITING_FOR_APPROVAL`, checkpoint and approval
  request created, zero outputs, and no write result.
- Controlled-prefix audit: 27 events and three READ tools only:
  `ACCOUNT.GET_ACCOUNT`, `PROJECT.GET_PROJECT`, and
  `FINANCE.GET_ACCOUNTING_PERIOD`.
- `WRITE_REQUESTED` events: zero.
- EOS adapter configured: false; EOS mutation count: zero.
- Remote provider and PostgreSQL access were not required for this boundary.
- Result: all eight compatibility checks passed. The detailed local evidence
  is written to `reports/quality/p8-s06-nsl-compatibility.json` and remains an
  ignored runtime report.

## Verification

- P8-S01 through P8-S06 focused regression: `117 passed`.
- P8-S06 runner tests: `20 passed`; bounded statement coverage `99%` with all
  meaningful success, drift, malformed-evidence, and failure branches covered.
- Protected source-backed compatibility smoke: `PASS`, checks `8/8`.
- Final Full Gate: `15,559 passed`, `48 skipped`, zero failures or errors.
- Full Gate coverage: statement `96.84%`, branch `96.24%`, above the configured
  minimums of `96%` and `94%`.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  8 OpenAPI documents.
- AE Web Node regression: 331 tests passed.
- Ruff and `git diff --check`: passed.

## Exit Decision

P8-S06 and P8.1 are closed. The v0.1 compatibility path is preserved, the
exact NSL v0.2 release and public API boundary are admitted, the controlled
WRITE prefix fails closed at approval, and no EOS mutation occurred. P8.2 may
now begin from this compatibility baseline.
