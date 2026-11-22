# CP-M1-E2E-FX-01B.7Q: Installed Result Finalization and WA Settlement Closure

## Status

- Date: `2026-11-22`
- Status: `COMPLETE`
- Parent boundary: `CP-M1-E2E-FX-01B.7`
- Predecessor: `CP-M1-E2E-FX-01B.7P`
- Database migration: none
- Public API change: none
- Remote provider: actual Qwen3.5-9B required for final acceptance

## Failure Reconciliation

The post-`.7P` installed journey completed D12 and D04, posted the immutable
Journal, and then exposed two downstream gaps. First, the existing
`RESULT_VERIFY` path did not reliably settle the IA AgentResult and workspace
publication after the installed Product execution. Second, after that runtime
continuation was restored, WA evidence was still absent.

Bounded AE operational diagnostics separated the WA symptom from the business
execution. The notifier persisted `ae.wa_notification.retry_pending` with
detail `WA_INTAKE_HTTP_404`; WA had no admitted job or asset. The public WA
intake contract, signed service token, and evidence consumer were already
installed. Source reconciliation proved that the canonical Traefik dynamic
configuration, mounted after the P9 WA overlay, replaced that overlay while
omitting the `wa.nex-staging.test` router and `nex-wa:8108` upstream. The 404
therefore occurred before WA authorization or intake logic.

## Decision

1. Preserve the existing generic RuntimeJob continuation, WorkResult,
   `RESULT_VERIFY`, AgentResult, workspace publication, and WA evidence
   contracts. Do not add a scenario-specific finalizer or queue.
2. Keep WA notification outcome observability bounded and secret-free through
   the existing AE operational-event store.
3. Make the canonical dynamic configuration authoritative for the complete
   installed route set, including WA. A later Compose overlay must not silently
   remove a previously admitted service route.
4. Reuse the existing WA intake API, JobQueue consumer, and work-asset
   persistence. Add no database migration, tenant branch, M1 fixture, or fixed
   business identifier.
5. Require exact-head OCI packaging, actual eight-database PostgreSQL,
   authenticated Playwright, live generation, restart replay, and zero-residue
   cleanup before closing the parent journey.

## Implemented Boundary

- The canonical Traefik configuration now routes
  `wa.nex-staging.test` to `http://nex-wa:8108` over the existing TLS
  entrypoint.
- Shared installed-topology admission includes WA in the ordered route and
  service inventory and validates its exact upstream port.
- Runtime Traefik rendering regression proves that provider endpoint
  substitution preserves the WA router and upstream.
- `AeWaPostCompletionNotifier` emits bounded `accepted`, `reused`,
  `retry_pending`, or `permanent_failure` operational evidence. HTTP status,
  transport unavailability, and invalid ACK diagnostics remain typed without
  persisting response bodies or credentials.
- The installed result path uses the existing generalized continuation and
  workspace publication mechanisms; no Golden A, demo, M1 business value, or
  acceptance fixture was added to product code.

## Verification

- Focused topology, installed acceptance, WA trust/deployment, AE notifier,
  and product-journey regression: `95 passed`.
- Changed shared topology module coverage: `33 passed`, statement `96.90%`,
  branch `95.56%` (`86/90`).
- The broader `nex-runtime` inventory also completed `2,123 passed`, `1`
  protected PostgreSQL skip. Its ad hoc service-wide Gate is not claimed as a
  passing admission Gate because the existing aggregate baseline is statement
  `86.81%` and branch `83.88%`, below the generic `95/94` defaults. The changed
  `demo_compose.py` boundary is covered separately above; raising the unrelated
  historical shared-runtime baseline remains a distinct coverage-hardening
  concern.
- Exact-head canonical OCI release at Git revision `8f59e29ba0a0`:
  - nine of nine images and manifests built;
  - nine of nine non-root runtime users;
  - all twelve background/package checks passed;
  - release-set digest
    `sha256:fd1f2367cbef88c09504b539e300e4cf8a048a013850a89b832938960f215507`;
  - no registry push and no secret inclusion.
- Exact-head AE Product runtime:
  - image
    `nex-platform-canonical/nex-ae-product-runtime:8f59e29ba0a0`;
  - image ID
    `sha256:1cfe4625f2b3370aa4789415ffcfaab572ea573c72e878a63fa0b690bae89aab`;
  - non-root user `65532:65532`;
  - active profile `VERIFIED_PRODUCT_RELEASE`.
- Protected installed journey report:
  `reports/deployment/mybee-w70-cp-m1-01b7q-product-golden-journey.json`.
- The journey used actual OA, AG, AE, CX, MO, WC, EOS, and WA PostgreSQL
  databases through eight isolated schemas and applied all `210` current
  migrations.
- Live provider binding was Qwen3.5-9B on canonical port `9111`, immutable
  revision `hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a`, deployment
  `dgx-qwen3-5-9b-9111`, with reasoning mode disabled.
- Authenticated Playwright completed two non-identical transactions using
  three separated principals and six approval decisions. It captured 15
  journey screenshots and passed all authentication, SoD, approval replay,
  plan compilation, terminal result, and delivery ACK checks.
- Authoritative database evidence after the live run:
  - two VoucherCandidates, immutable Journals, allocation Batches,
    AgentResults, and acknowledged result deliveries;
  - four allocation lines and four P&L projections;
  - exact first-Batch total `13,502,000.0000`, Project amounts
    `5,400,800.0000` and `8,101,200.0000`, residual `0.0000`;
  - AE WA outcome `accepted`;
  - WA evidence event `admitted`;
  - latest WA job `SUCCEEDED`, four successful WA jobs, and four work assets.
- Restart acceptance recovered the authoritative result hash and business
  references and retained exactly two Journals, allocation Batches, and
  AgentResults. WA evidence remained admitted and successful.
- Cleanup dropped all eight isolated schemas and removed every Compose
  container, network, and volume. `zero_residue=true` and no `m1_*` schema
  remained in the AE development database.
- Final AE Slice Gate:
  - `6,914 passed`, `53 skipped` protected opt-in tests;
  - statement coverage `96.46%` against `95.00%`;
  - branch coverage `94.69%` against `94.00%`;
  - contract validation passed for `274` schemas, `320` examples, `260`
    negative examples, and `10` OpenAPI documents;
  - coverage ownership and tiered quality audits passed.

No provider secret, database password, prompt content, unrestricted exception,
or response body is included in committed evidence.

## Exit Rule

The Slice and parent `CP-M1-E2E-FX-01B.7` protected product journey are
closed. The exact-head installed runtime completed semantic planning, three
approval boundaries per transaction, D12, D04 controlled WRITE, immutable EOS
posting, allocation and P&L projection, IA AgentResult publication, and WA
settlement for two non-identical requests. Restart replay was exactly-once,
all required quality gates and changed-boundary coverage passed, and cleanup
left zero runtime or database residue.
