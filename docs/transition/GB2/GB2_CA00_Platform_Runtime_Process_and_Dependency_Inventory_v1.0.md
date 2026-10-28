# GB2-CA00 Platform Runtime Process and Dependency Inventory v1.0

## 1. Document Control

```text
Stage        : GB2-CA00
Slice        : GB2-CA00-S01
Status       : FROZEN
Date         : 2026-10-28
Authority    : GB2-CA00A and canonical S01-S20 implementation plan
Change type  : Documentation and contract verification only
```

This document freezes the source-backed current, demo, and target ownership
before GB2 runtime promotion begins. It does not admit a new process, alter a
database, or make a demo entrypoint canonical.

## 2. Classification Legend

| Code | Meaning |
|---|---|
| `P` | Platform canonical product/runtime source |
| `D` | Demo profile source; usable as extraction input, not canonical runtime |
| `T` | Test or protected-smoke source only |
| `H` | Historical evidence retained for traceability only |
| `X` | Invalid product-runtime dependency that must be removed during promotion |

An item marked `D` may contain valid behavior. Promotion means extracting or
rebinding that behavior through an owner-supported product boundary; it does
not mean renaming the demo module and declaring it canonical.

## 3. Machine-Readable Frozen Contract

The following block is normative and is checked against the repository source.

<!-- gb2-s01-contract:start -->
```json
{
  "schema_version": "gb2_platformization_inventory.v1",
  "current_artifact_count": 9,
  "current_installed_process_count": 20,
  "target_artifact_count": 9,
  "target_installed_process_count": 20,
  "promotion_process_ids": [
    "nex-ae-agent-runtime-worker",
    "nex-wc-event-delivery-worker",
    "nex-eos-outbox-publisher"
  ],
  "current_promoted_process_ids": [
    "nex-ae-agent-runtime-worker",
    "nex-wc-event-delivery-worker",
    "nex-eos-outbox-publisher"
  ],
  "embedded_component_ids": [
    "nex-ae-agent-runtime-dispatcher"
  ],
  "database_migration": "NO",
  "new_business_table": "NO",
  "new_public_business_api": "NO"
}
```
<!-- gb2-s01-contract:end -->

Counting rules:

- An installed OS process is counted once, whether it is an API, web process,
  worker, or daemon.
- `nex-ae-agent-runtime-dispatcher` remains embedded in the AE worker and is
  not a twenty-first process.
- The three promotion targets reuse `nex-ae-runtime`, `nex-wc-runtime`, and
  `nex-eos-runtime`; no tenth artifact is introduced.
- `current_promoted_process_ids` records the cumulative GB2 promotion state;
  after S07, all three promotion targets are current.
- `nex-wa-evidence-consumer` is already canonical in the current 20-process
  Platform. It is a reference implementation, not a GB2 promotion target.

## 4. Artifact Ownership Freeze

| Artifact | Owner | Kind | Current | Target | GB2 action |
|---|---|---|---|---|---|
| `nex-oa-runtime` | NeX-OA | Python service image | `P` | `P` | none |
| `nex-ag-runtime` | NeX-AG | Python service image | `P` | `P` | none |
| `nex-ae-runtime` | NeX-AE | Python service image | `P` | `P` | add canonical AE worker entrypoint |
| `nex-cx-runtime` | NeX-CX | Python service image | `P` | `P` | none |
| `nex-mo-runtime` | NeX-MO | Python service image | `P` | `P` | preserve owner-side provider readiness |
| `nex-wc-runtime` | NeX-WC | Python service image | `P` | `P` | add canonical event-delivery entrypoint |
| `nex-eos-runtime` | NeX-EOS | Python service image | `P` | `P` | add canonical outbox entrypoint |
| `nex-wa-runtime` | NeX-WA | Python service image | `P` | `P` | reference worker remains unchanged |
| `nex-ae-web` | NeX-AE Web | Node web image | `P` | `P` | none |

Canonical artifact ownership is defined by
`services/_shared/nex_runtime/deployment_artifacts.py`. The current catalog has
nine artifacts and twenty process bindings after S07.

## 5. Process Inventory

`HB` below means the lifecycle signal currently represented by the source.
For current background processes, `no topology probe` is intentional wording:
the current manifest has no HTTP probe and S02 must not silently reinterpret a
`lifecycle_only` entrypoint as domain work.

| Process | Owner | Artifact | Entrypoint | Model | Database | Dependencies | HB | Work capability | Restart contract | Current -> Target |
|---|---|---|---|---|---|---|---|---|---|---|
| `nex-oa-api` | OA | `nex-oa-runtime` | `nex_oa.main:app` | installed API | OA | none | HTTP health/ready | `request_serving` | state from PostgreSQL | `P -> P` |
| `nex-mo-api` | MO | `nex-mo-runtime` | `nex_mo.main:app` | installed API | MO | OA | HTTP health/ready | `request_serving` | state from PostgreSQL | `P -> P` |
| `nex-cx-api` | CX | `nex-cx-runtime` | `nex_cx.main:app` | installed API | CX | OA, MO | HTTP health/ready | `request_serving` | state from PostgreSQL | `P -> P` |
| `nex-ae-api` | AE | `nex-ae-runtime` | `nex_ae_api.main:app` | installed API | AE | OA, CX | HTTP health/ready | `request_serving` | state from PostgreSQL | `P -> P` |
| `nex-ag-api` | AG | `nex-ag-runtime` | `nex_ag.main:app` | installed API | AG | OA, AE, CX, MO | HTTP health/ready | `request_serving` | state from PostgreSQL | `P -> P` |
| `nex-wc-api` | WC | `nex-wc-runtime` | `nex_wc.main:app` | installed API | WC | OA, AE | HTTP health/ready | `request_serving` | state from PostgreSQL | `P -> P` |
| `nex-eos-api` | EOS | `nex-eos-runtime` | `nex_eos.main:app` | installed API | EOS | OA, AE, WC | HTTP health/ready | `request_serving` | state from PostgreSQL | `P -> P` |
| `nex-wa-api` | WA | `nex-wa-runtime` | `nex_wa.main:app` | installed API | WA | OA, AE, WC, EOS | HTTP health/ready | `request_serving` | state from PostgreSQL | `P -> P` |
| `nex-ae-web` | AE Web | `nex-ae-web` | `npm start` | installed web | none | AE | HTTP root | `static_serving` | state from backend APIs | `P -> P` |
| `nex-ae-artifact-render-worker` | AE | `nex-ae-runtime` | shared background runner | installed worker | AE | AE, CX | no topology probe | `lifecycle_only` metadata | owner durable state | `P -> P` |
| `nex-ae-retention-daemon` | AE | `nex-ae-runtime` | shared background runner | installed daemon | AE | AE | no topology probe | `lifecycle_only` metadata | owner durable state | `P -> P` |
| `nex-ag-remediation-sync-worker` | AG | `nex-ag-runtime` | shared background runner | installed worker | AG | AG, CX | no topology probe | `lifecycle_only` metadata | owner durable state | `P -> P` |
| `nex-ag-dispatch-daemon` | AG | `nex-ag-runtime` | shared background runner | installed daemon | AG | AG | no topology probe | `lifecycle_only` metadata | owner durable state | `P -> P` |
| `nex-cx-async-generation-worker` | CX | `nex-cx-runtime` | shared background runner | installed worker | CX | CX, MO | no topology probe | `lifecycle_only` metadata | owner durable state | `P -> P` |
| `nex-cx-ingestion-worker` | CX | `nex-cx-runtime` | shared background runner | installed worker | CX | CX, MO | no topology probe | `job_claiming` | owner durable job state | `P -> P` |
| `nex-cx-remediation-worker` | CX | `nex-cx-runtime` | shared background runner | installed worker | CX | CX, MO | no topology probe | `lifecycle_only` metadata | owner durable state | `P -> P` |
| `nex-wa-evidence-consumer` | WA | `nex-wa-runtime` | `nex_wa.consumer_main` | installed worker | WA | WA, OA, AE, WC, EOS | owner process lifecycle | `job_claiming` | durable cursor/idempotency | `P -> P` |
| `nex-ae-agent-runtime-worker` | AE | `nex-ae-runtime` | `nex_ae_api.agent_runtime_process` | installed worker | AE | AE, OA, CX, MO, WC, EOS | PostgreSQL heartbeat | `job_claiming` | lease expiry and durable checkpoint | `P -> P` |
| `nex-wc-event-delivery-worker` | WC | `nex-wc-runtime` | `nex_wc.event_delivery_process` | installed worker | WC | WC, AE, OA | PostgreSQL heartbeat | `event_delivering` | job retry and outbox replay | `P -> P` |
| `nex-eos-outbox-publisher` | EOS | `nex-eos-runtime` | `nex_eos.outbox_publisher_process` | installed worker | EOS | EOS, AE, OA | PostgreSQL heartbeat | `outbox_publishing` | outbox retry and replay | `P -> P` |

The exact target dependency lists for the three promoted processes may be
reduced during S05-S07, but ownership, artifact placement, durable database,
and restart semantics are frozen here. Adding a new owner, artifact, database,
or broker requires an amendment rather than an incidental implementation
change.

## 6. Runtime Module Classification

| Module or edge | Class | Product import? | Demo import? | Promote? | Historical retention? |
|---|---:|---:|---:|---:|---:|
| `services/nex-ae-api/nex_ae_api/p8_demo_runtime_composition.py` | `D` | no | yes | extract generic AE factory in S03 | yes |
| `services/nex-ae-api/nex_ae_api/p8_demo_controlled_skill.py` | `D` | no | yes | productize finance activator in S10 | yes |
| `services/nex-ae-api/nex_ae_api/p8_demo_semantic_activation.py` | `D` | yes, invalid edge | yes | replace with registry in S09-S10 | yes |
| `services/nex-ae-api/nex_ae_api/demo_runtime.py` | `D` | no | yes | replace entrypoint in S05 | yes |
| `services/nex-wc/nex_wc/demo_runtime.py` | `D` | no | yes | replace entrypoint in S06 | yes |
| `services/nex-eos/nex_eos/demo_runtime.py` | `D` | no | yes | replace entrypoint in S07 | yes |
| `services/_shared/nex_runtime/demo_processes.py` | `D` | deployment tooling only | yes | rebind contract in S04-S08 | yes |
| `services/_shared/nex_runtime/demo_domain_activation.py` | `D` | no | yes | replace with canonical activation | yes |
| `services/_shared/nex_runtime/demo_domain_installation.py` | `D` | no | yes | provisioning remains outside runtime | yes |
| `services/nex-ae-api/nex_ae_api/agent_runtime_dispatcher.py` | `P` | yes | yes | reuse unchanged | no |
| `services/nex-ae-api/nex_ae_api/agent_runtime_worker.py` | `P` | yes | yes | reuse unchanged | no |
| `services/nex-ae-api/nex_ae_api/multi_step_engine.py` | `P` | yes | yes | reuse unchanged | no |
| `services/nex-ae-api/nex_ae_api/semantic_candidate_admission.py` | `P` | yes | yes | retain; remove demo edge | no |
| `services/nex-ae-api/nex_ae_api/nsl_approval_resume.py` | `P` | yes | yes | reuse unchanged | no |
| `services/nex-ae-api/nex_ae_api/workspace_result_publication.py` | `P` | yes | yes | reuse unchanged | no |
| product import edge `semantic_candidate_admission -> p8_demo_semantic_activation` | `X` | yes | n/a | remove in S09-S10 | record resolution |
| `services/nex-wc/nex_wc/handoff_delivery.py` | `P` | library/API boundary | yes | compose in S06 | no |
| `services/nex-wc/nex_wc/work_result_delivery.py` | `P` | library/API boundary | yes | compose in S06 | no |
| `services/nex-wc/nex_wc/approval_event_delivery.py` | `P` | library/API boundary | yes | compose in S06 | no |
| `services/nex-eos/nex_eos/outbox_publication.py` | `P` | library/API boundary | yes | compose in S07 | no |
| `services/_shared/nex_runtime/process_manifest.py` | `P` | yes | deployment | extend in S05-S08 | no |
| `services/_shared/nex_runtime/deployment_artifacts.py` | `P` | yes | deployment | retain nine artifacts, add bindings | no |
| `services/_shared/nex_runtime/deployment_entrypoints.py` | `P` | yes | deployment | extend taxonomy/commands | no |
| `services/_shared/nex_runtime/production_container_bootstrap.py` | `P` | installed runtime | demo-compatible | preserve owner bootstrap | no |
| `scripts/smoke/run_p8_demo_s10b_installed_runtime.py` | `T` | forbidden | smoke only | evidence source only | yes |
| `scripts/deployment/run_p8_demo_s10_installed_domain_acceptance.py` | `T` | forbidden | acceptance only | provisioning evidence only | yes |

The `X` row is the only known direct demo dependency from a product runtime
module in this inventory. S09-S10 own its removal; S01 does not mask it.

## 7. Dependency Ownership Inventory

| Dependency | Canonical owner/source | Current status | GB2 target boundary |
|---|---|---|---|
| PostgreSQL runtime state | each service owner and its database | `P` | preserve owner-local SoR and pools |
| OpenBao runtime resolution | `services/_shared/nex_runtime/openbao_secret_resolver.py` and `services/_shared/nex_runtime/production_container_bootstrap.py` | `P` | shared readiness may aggregate owner result; no second resolver |
| OpenBao demo provisioning | `services/_shared/nex_runtime/demo_domain_installation.py` | `D` | provisioning stays outside product process readiness |
| S3-compatible object client | `services/_shared/nex_runtime/object_storage.py` | `P` | reuse existing client and owner configuration |
| Object lifecycle | `services/_shared/nex_runtime/object_storage_lifecycle.py` | `P` | reuse existing owner lifecycle contract |
| RustFS IAM | `services/_shared/nex_runtime/rustfs_iam.py` | `P` | provisioning/IAM remains an operator boundary |
| Provider readiness | `services/nex-mo/nex_mo/provider_readiness_service.py` | `P` | NeX-MO remains probe/cache owner |
| Provider readiness API | `services/nex-mo/nex_mo/provider_readiness_api.py` | `P` | shared readiness consumes projection only |
| Provider probe/evaluation | `services/nex-mo/nex_mo/provider_readiness_plan.py` and `services/nex-mo/nex_mo/provider_readiness_evaluator.py` | `P` | no duplicate provider client or cache in shared runtime |

Dependency readiness introduced later in GB2 is an aggregation and
normalization seam. It must not become a second OpenBao resolver, RustFS
lifecycle engine, provider probe implementation, or persistent readiness SoR.

## 8. Promotion Boundaries and Non-Goals

Frozen promotion ownership:

1. S03 extracts a generic AE installed runtime composition from demo wiring.
2. S04 rebinds the P8-DEMO profile through that generic composition.
3. S05 promotes the AE worker without creating a second dispatcher, worker,
   engine, or result finalizer.
4. S06 promotes WC delivery using its existing handoff, result, and approval
   delivery components.
5. S07 promotes EOS publication using its existing outbox publisher.
6. S08 closed the canonical `9 artifacts / 20 processes` topology and made
   the current manifest the default `scripts/dev/run_platform.py` topology.

Explicit non-goals for S01-S08:

- no new broker;
- no new business state or public business API;
- no database migration or new table;
- no second scheduler, dispatcher, execution engine, delivery engine, or
  outbox engine;
- no product runtime import from `scripts/`, `tests/`, or protected smoke;
- no claim that a component smoke is Golden Journey evidence.

## 9. Acceptance and S02 Authorization

| Check | Result |
|---|---|
| Current manifest count is source-backed | `20` installed processes, closed by S08 |
| Target additions are unambiguous | AE worker, WC worker, EOS publisher |
| Target process count is exact | `20` installed processes |
| Current and target artifact count is exact | `9` artifacts |
| Embedded dispatcher counting is explicit | excluded from installed count |
| Artifact and database ownership is explicit | PASS |
| Demo/product/test/historical/invalid classifications are explicit | PASS |
| New migration, table, and public API are excluded | PASS |
| S02 Runtime Process Capability Taxonomy | AUTHORIZED |
| Current CLI defaults to the 20-process topology | PASS |
| Historical 13-process CLI topology remains explicit | `--topology historical` |
| Current protected environment contract | `8 DB + 10 endpoint + 15 signed trust = 33` |
| Protected current-topology acceptance | `8 DB / 11 background / 8 API / 3 work-loop`, PASS |
