# W80-CA00G.0A Protected Live Progress and Playwright Evidence Acceptance

## Status

ACCEPTED / PROTECTED LIVE EXECUTION PASSED

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

## Acceptance Result

The exact-head acceptance passed on revision `f6f671f9a65c` on 2026-11-25.
The canonical nine-image release set and packaged AE product Runtime image were
built from that revision before execution.

- Actual OA, AG, AE, CX, MO, WC, EOS, and WA PostgreSQL: `8/8`; `210`
  migrations applied in isolated schemas.
- Actual remote generation: Qwen3.8-Flash-Next,
  `hf:fc694b54fb0174e0913e6adf86691ef85a4ead47`; provider contacted.
- Journal progress: `19` ordered events, `8` observed DOM changes and PNGs.
- Allocation progress: `8` ordered events, `4` observed DOM changes and PNGs.
- Progress GET overlapped the Chat POST in both journeys; polling stopped after
  the terminal result in both journeys.
- Owner scope, raw-prompt/private-payload exclusion, append-only rendering, and
  the `[HH:mm:ss]` diagnostic prefix all passed.
- Installed restart/recovery passed, all `17` service/process logs exited clean,
  and all `8` isolated schemas were dropped with zero residue.
- Playwright diagnostics accepted `23` captures across `6` manifests, including
  `12` `EXECUTION_PROGRESS_VISIBLE` captures.

Progress manifest digests:

```text
journal   sha256:9a7cec503141f2e9ed14644f8da8f72a0fdf11d8ec491c8d4aa1c5d2983388e6
allocation sha256:e6c455e10cf7a841e6ff80330e26f8011c0f9ef2c43d9e6b4534c8477ee3a9ab
```

### Post-Acceptance Prompt/Progress Order Correction

The user-facing order was corrected after the initial acceptance so that the
latest user prompt is the progress anchor. The installed Workspace now renders
the prior conversation, latest user prompt, append-only execution progress,
and subsequent IA response/result in that order. This preserves multi-turn
history while preventing progress from appearing above the request that caused
it.

The correction was re-accepted from exact-head revision `054ad2c14ecd` on
2026-11-25 with rebuilt canonical and packaged AE Runtime images.

- Focused Workspace tests, all `140` AE Web React tests, TypeScript checking,
  and the production Web build passed.
- Actual PostgreSQL, remote generation, installed Compose, OpenBao, RustFS, and
  authenticated Playwright acceptance passed again.
- Journal produced `19` ordered progress events; Allocation produced `8`.
- Representative Journal capture
  `mybee-m1-w80-ca00g0a-journal-progress-04-progress-09.png` proves the blue
  user prompt precedes the `execution progress` list.
- Restart/recovery and zero-residue cleanup remained accepted; all `8` isolated
  schemas were removed.

Re-acceptance progress manifest digests:

```text
journal    sha256:17f7967c22277140514f6cc1e8ef29f326236d69fd5e611b19dd55c9647211d7
allocation sha256:901ff37bc8aedcc4f14df362ff54d319626379ae2d8fa1a36dede3aa5dd5256e
```

The first protected attempt intentionally failed closed when the generation
provider secret was omitted: MO reported `http_status_401` and AE returned
`PROVIDER_NOT_READY`. The accepted execution explicitly injected the existing
provider key through the OpenBao secret boundary; the key is absent from reports
and manifests.

Machine-readable and restricted visual evidence:

```text
reports/deployment/mybee-w80-ca00g0a-progress-acceptance.json
reports/deployment/mybee-w80-ca00g0a-progress-screens/
reports/deployment/mybee-w70-m1-diagnostic-evidence/mybee-w80-ca00f5-20261125T104905Z-99ab05c8/
```
