# W80-CA00E.6 Cross-Agent Semantic Handoff Protected Acceptance

## Status

`CLOSED` on 2026-11-24.

W80-CA00E.6 accepts the W80-CA00E cross-Agent semantic handoff boundary after
the late-bound Project authority correction in W80-CA00E.6A. The accepted
runtime reuses upstream IA INTENT and CONTEXT evidence when valid, rebuilds
authority under the target Agent identity, and creates role-scoped PLAN
evidence without introducing a scenario-specific product runtime.

## Exact-Head Packaging

The protected journey used source commit
`e248abed0413bbb1fe6aba48613fccab24e3c612`.

- canonical release set: 9/9 OCI images;
- release-set digest:
  `sha256:de8b1a11bfc1f6f9feeaefaecb779d771b56b79ede2546551132b32e6e091eea`;
- all images admitted as non-root;
- 12 packaged worker/daemon checks passed;
- AE Product Runtime image:
  `nex-platform-canonical/nex-ae-product-runtime:e248abed0413`;
- runtime user: `65532:65532`;
- registry push: not performed.

## Protected Journey

The acceptance runner reused the installed product composition and exercised:

```text
OA-backed authenticated IA request
  -> IA semantic INTENT and CONTEXT admission
  -> WC delegation and claim handoff
  -> late-bound EOS Project authority alignment
  -> target PA authority rebuild and role-scoped planning
  -> business and NSL WRITE approvals
  -> controlled EOS execution
  -> result settlement and IA publication
  -> authenticated Playwright result and restart recovery
```

Actual persistence used `nex_ae_user@nex_ae_test`,
`nex_wc_user@nex_wc_test`, `nex_oa_user@nex_oa_test`, and
`nex_eos_user@nex_eos_test`. The protected PostgreSQL gate passed 13 admitted
selectors and 25 tests, and both the gate and installed journey reported zero
residue.

The live semantic path used the remote Qwen3.5-9B generation provider. It did
not invoke embedding or reranking providers.

## Semantic Reuse Evidence

```text
semantic admission requests = 4
semantic candidates          = 8
INTENT / CONTEXT / PLAN      = 2 / 2 / 4
generation requests          = 8
previous baseline            = 12
request reduction            = 4
embedding / reranking calls  = 0 / 0
generation mean latency      = 39,528.380 ms
generation p95 / maximum     = 57,619.453 ms / 57,619.453 ms
```

Latency is diagnostic evidence, not a correctness threshold for this Slice.
Correctness remains bound to evidence integrity, authority alignment, typed
fallback/denial behavior, result completion, and zero residue.

## Browser And Diagnostic Evidence

Authenticated Playwright acceptance passed with 15 primary journey captures,
2 restart-recovery captures, and 2 screen manifests. The state inventory
includes login, requester and approver workspaces, six recorded approval
states, two rendered results, and one recovered result.

The protected diagnostic session is
`mybee-w70-m1-20261123T225631Z-f23d5b1a`. Its ignored local evidence contains
the raw prompt, AgentPlan, and ExecutablePlan required by the W80 diagnostic
boundary. The tracked acceptance projection contains only bounded counts,
digests, identities, and decisions; credentials and secret values are
forbidden.

Ignored machine-readable evidence:

- `reports/quality/mybee-w80-ca00e6-protected-acceptance.json`;
- `reports/quality/mybee-w80-ca00e6-postgres-gate.json`;
- `reports/deployment/mybee-w80-ca00e6-live-journey.json`;
- `reports/deployment/mybee-w70-m1-diagnostic-evidence/`;
- `reports/deployment/mybee-w70-cp-m1-product-golden-screens/`.

## Verification

W80-CA00E.6 protected acceptance:

```text
source/generalized matrix = 102 passed
actual PostgreSQL         = PASS
remote generation         = PASS
authenticated Playwright  = PASS
restart recovery          = PASS
zero residue              = PASS
```

W80-CA00E.6A AE Slice Gate:

```text
tests                     = 6,998 passed / 53 protected skips
statement / branch        = 96.46% / 94.72%
product statement/branch = 97.07% / 95.01%
```

Repository Full Gate:

```text
tests                     = 23,986 passed / 193 protected skips
statement / branch        = 96.31% / 95.22%
product statement/branch = 98.25% / 96.72%
harness statement/branch = 93.57% / 91.62%
contracts                 = 277 schemas / 322 examples
                            260 negative examples / 10 OpenAPI
AE Web Node tests         = 395 passed
AE Web React tests        = 134 passed
typecheck/build           = PASS
production cutover        = PASS
full web acceptance       = PASS, 6 journeys / 71 checks / 16 screenshots
Full Gate exit            = 0
```

The existing non-blocking Starlette/httpx deprecation and frontend bundle-size
warnings remain unchanged.

## Decision

W80-CA00E.6 and W80-CA00E.6A are closed. Cross-Agent semantic handoff now
supports project-neutral WorkIntent admission followed by a strictly verified,
late-bound EOS Project authority without mutating WorkIntent, weakening
explicit Project scope, or adding tenant-, Project-, M1-, or fixture-specific
selection logic.
