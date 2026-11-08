# P6.5 Final As-Built Baseline and P7 Handoff v1.0

**Status:** CLOSED / P7 ENTRY AUTHORIZED
**Date:** 2026-10-17
**Baseline:** P6.5-CA01 and P6.5-S1 through P6.5-S7

## 1. Closed Objective

P6.5 proved that IA natural-language planning can use the actual MO generation
provider without transferring execution authority to the model. The accepted
authority chain is:

```text
LLM candidate
-> strict schema and private-data checks
-> model-specific calibration
-> deterministic AE resolution and binding
-> PlanValidation VALID
-> deterministic compiler
-> existing P6 runtime
```

`LLM Candidate != Execution Authority` remains the controlling invariant.

## 2. As-Built Boundary

Closed:

- thin authenticated AE-to-MO generation client;
- exact live INTENT, CONTEXT, and PLAN candidate contracts;
- owner-private candidate payload storage plus PostgreSQL evidence metadata;
- deterministic WorkIntent, AgentContext, AgentPlan, validation, and compile;
- provider/adversarial fail-closed projection and restart reuse;
- actual `nex_ae_test` plus actual MO remote generation acceptance;
- generated `LOCAL_SKILL + REPORT` continuation through P6 in-process NSL READ;
- StepResult v1.2, AgentResult, and ResultDelivery(PENDING);
- zero database and private-storage test residue.

Not activated:

- model-authored executable steps or exact Skill/version authority;
- WRITE, approval, WC, PA, delegation, or Enterprise OS behavior;
- AE-side semantic retry disguised as provider retry;
- direct AE access to a vendor provider;
- automatic execution before PlanValidation `VALID`.

## 3. Prompt Registry Baseline

The active semantic prompt set at closure is:

| Binding | Version | Purpose |
| --- | --- | --- |
| `ae.intent_resolution.default` | `v1` | untrusted intent candidate |
| `ae.context_candidate_extraction.default` | `v2` | untrusted context hints with exact parameter confidence |
| `ae.plan_builder.default` | `v1` | untrusted logical plan candidate |

Context v1 remains immutable history. V2 activation uses the existing durable
binding CAS and history mechanism.

## 4. Live Acceptance

The P6.5-S7 protected journey passed against actual PostgreSQL and remote
generation:

```text
database / role: nex_ae_test / nex_ae_user
latest AE migration: 2300_ae_semantic_candidate
provider mode: live
provider profile / model: general-llm-default / Qwen3.5-4B
semantic provider calls: 3
acceptance checks: 14/14
StepResult / AgentResult / ResultDelivery: 2 / 1 / 1
database residue: 0
runtime residue: 0
private storage residue: 0
```

Endpoints, credentials, raw prompts, raw model output, candidate payloads, and
hidden reasoning are absent from evidence.

## 5. P7 Entry Contract

P7 may build on these stable boundaries:

1. `AgentExecution` remains the runtime root.
2. Candidate evidence is immutable and owner-private payloads stay outside
   PostgreSQL.
3. Prompt binding version, model profile/revision, and candidate hash remain
   explicit lineage.
4. Compiler and executor registry remain provider-free.
5. RuntimeJob starts only after deterministic validation and compile.
6. Existing P6 worker, dispatcher, NSL profile, result, and delivery semantics
   remain authoritative.
7. Provider/model changes require readiness plus exact calibration; no model
   name is embedded in execution authority.

## 6. Closure Verification

The closure gates passed without an unexplained coverage regression:

| Gate | Result |
| --- | --- |
| Protected PostgreSQL + remote-provider E2E | `1 passed`, `14/14` checks |
| Focused regression | `453 passed, 1 skipped` |
| AE Slice Gate | `4,362 passed, 11 skipped`; statement `98.63%`; branch `96.86%` |
| Full Gate | `15,146 passed, 39 skipped`; statement `97.23%`; branch `96.69%` |
| Contract validation | 174 schemas, 236 examples, 204 negative examples, 7 OpenAPI documents |
| AE Web | `331 passed` |

The Full Gate completed with exit code 0. The protected P6.5-S7 journey was
executed separately with its explicit activation environment and remains
skipped by default in broad regression. Other protected acceptance scripts
also retained their documented opt-in behavior.

P7 entry is therefore authorized. P7 must preserve the boundaries above and
must not treat provider output as execution authority.
