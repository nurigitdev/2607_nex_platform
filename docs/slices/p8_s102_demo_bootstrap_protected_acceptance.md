# P8-S102: Demo Bootstrap Protected Acceptance

## Scope

P8-S102 proves the P8.10 demonstration spine against actual test persistence,
the live generation provider, and an authenticated Chromium session.

- OA, AE, WC, and EOS migrations and state use their actual PostgreSQL test
  databases.
- The natural-language Voucher request uses live INTENT and PLAN generation.
- EOS commits the approved Voucher once, verifies the committed result, and
  reads it back through the membership-filtered GET and LIST boundaries.
- AE Web performs actual OA-backed employee login and logout through the
  same-origin AE facade in headless Chromium.
- All seeded PostgreSQL rows are removed after the journey.

No database migration or production API contract was added by this Slice.

## Release And Artifact Boundary

The NSL runtime and Skill artifacts remain independently admitted:

- runtime wheel: NSL `0.2.1`, source revision `d53658ec...`, wheel SHA-256
  `a89ce5fd...`;
- Project and Voucher Skill artifacts: their later exact source revisions and
  semantic/manifest hashes from P8-S98 through P8-S101.

The protected runner materializes a detached local checkout of the immutable
v0.2.1 runtime revision. This avoids weakening or rewriting its lock when the
NSL repository HEAD advances to add independently admitted Skill examples.

## Protected Journey

The executed path was:

```text
actual OA authorization and employee identity
  -> actual AE/WC approval and resume lineage
  -> live Qwen3.5-4B INTENT and PLAN generation
  -> admitted NSL v0.2.1 controlled WRITE
  -> actual EOS Project membership guard
  -> actual EOS Voucher commit and post-write verification
  -> membership-filtered Voucher GET and LIST
  -> authenticated AE Web Playwright presentation and logout
  -> cross-service cleanup and zero-residue check
```

MO readiness checked the configured generation, embedding, and reranking
routes because the current provider-readiness aggregate covers all three
capabilities. Only generation participated in the semantic Voucher journey.

The browser acceptance mounts smoke-only chat projection routes on the actual
AE test application after the authoritative backend journey has completed.
The browser therefore proves real OA login/session behavior, same-origin AE
routing, Chat submission/presentation, and logout; it does not claim that a
new production Chat-to-Voucher public API was introduced in this Slice.

## Verification

```text
focused Python regression = 75 passed / 2 expected protected skips
EOS Slice Gate            = 682 passed / 22 expected protected skips
EOS statement / branch    = 98.85% / 98.15%
AE Web regression         = 377 passed / 0 failed
protected acceptance      = PASS, 8/8 checks
actual PostgreSQL         = OA / AE / WC / EOS
live model                = Qwen3.5-4B
commit state              = COMMITTED
verification status       = VERIFIED
membership GET/LIST       = PASS
authenticated Playwright  = PASS
backend residue count     = 0
```

The committed evidence excludes raw prompts, credentials, database endpoints,
provider endpoints, cookies, and token material. The machine-readable local
report remains under the ignored `reports/` tree.

## Exit

P8-S102 closes the protected demonstration acceptance. P8-S103 owns the final
P8 As-Built/P9 handoff update, Repository Full Gate, and independent
zero-residue closure.
