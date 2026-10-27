# P9-S21: Bounded AE Reconciliation and Backfill

## Scope

NeX-AE now exposes two signed, tenant-scoped reconciliation listings:

```text
GET /internal/v1/wa-sources/agent-results
GET /internal/v1/wa-sources/artifacts
```

Both routes require `service:call`, `work:source:read`, caller `nex-wa`, an
exclusive `created_after`, an inclusive `created_before`, and a page size no
larger than 100. The opaque cursor is bound to the source type and original
time window, so it cannot be replayed against another listing window.

AgentResult listing admits only `SUCCEEDED`/`PARTIAL` results whose execution
is `SUCCEEDED` and required Workspace/WC delivery is `ACKNOWLEDGED`. Artifact
listing admits all versions of tenant-owned `READY` Artifacts. List items are
the normal WA intake shape and contain only source refs, revision refs, hashes,
timestamps, and correlation IDs. No result body, prompt, Artifact bytes,
storage reference, owner-private field, or rendered content is returned.

## Runtime Boundary

`WaAeReconciliationService` scans both source types with explicit page and
page-count bounds. Every recovered item is submitted through the existing
`WaEvidenceIntakeService.admit()` path. Consequently restart, repeated windows,
and duplicate notifications reuse the deterministic Job identity instead of
creating another ingestion mechanism.

Supported execution modes are `OPERATOR` and `STARTUP`. The protected
maintenance entry point is:

```text
python -m nex_wa.reconciliation_main
```

It requires signed WA-to-AE source access outside the test profile. No timer,
cron policy, scheduler table, or background polling loop was added. Deployment
may invoke the bounded `startup` mode explicitly before the normal process.

## Persistence

No migration was introduced. AE uses existing `ae_agent_result`,
`ae_result_delivery`, `ae_agent_execution`, `ae_artifacts`, and
`ae_artifact_versions`. WA uses the existing `service_jobs` semantic identity
and idempotency rules.

## Verification

Tests cover missed AgentResult and Artifact recovery, stable cursor paging,
cursor/window mismatch, signed caller/scope denial, reference-only payloads,
restart, duplicate re-enqueue, explicit bounds, malformed source pages,
transport failures, maintenance bootstrap, and secret redaction.

```text
actual nex_ae_test PostgreSQL listing smoke = 1 passed
NeX-WA Slice Gate                         = 247 passed, 9 skipped
NeX-WA statement coverage                 = 97.27%
NeX-WA branch coverage                    = 94.42%
NeX-AE Slice Gate                         = 5,591 passed, 45 skipped
NeX-AE statement coverage                 = 96.99%
NeX-AE branch coverage                    = 95.30%
contract validation                       = 226 schemas, 290 examples,
                                            241 negative examples, 10 OpenAPI
Ruff / diff hygiene                       = PASS
```

The protected PostgreSQL smoke ran the current AE migrations, verified the
`nex_ae_test` / `nex_ae_user` identity, and executed both bounded listing SQL
paths without creating test residue.

## Exit

```text
notification loss recoverable = PASS
normal intake identity reused = PASS
general scheduler introduced  = NO
new persistence introduced    = NO
next Slice                    = P9-S22
```
