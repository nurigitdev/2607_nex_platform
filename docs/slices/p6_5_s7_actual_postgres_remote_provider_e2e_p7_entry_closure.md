# P6.5-S7 Actual PostgreSQL + Remote Provider E2E / P7 Entry Closure

**Status:** IMPLEMENTED
**Date:** 2026-10-17
**Predecessor:** P6.5-S6 Provider Failure / Adversarial Hardening

## Scope

P6.5-S7 closes the source-backed generation transition with one protected
Golden Journey that combines the real AE test database, the real MO generation
route, deterministic candidate admission, and the existing P6 in-process NSL
READ runtime:

```text
IA natural-language prompt
-> exact Prompt Registry versions
-> MO live readiness
-> INTENT / CONTEXT / PLAN provider calls
-> WorkIntent / AgentContext / AgentPlan
-> PlanValidation VALID
-> deterministic ExecutablePlan
-> LOCAL_SKILL / RuntimeJob / dispatcher / AE worker
-> NSL_V01_IN_PROCESS READ
-> StepResult v1.2 / AgentResult / ResultDelivery(PENDING)
```

The runner does not call the vendor endpoint from AE. It builds the real NeX-MO
API surface in process, authenticates through the AE-to-MO service boundary,
and lets MO call the configured remote generation provider. The model revision
is discovered from active readiness and is not hardcoded into candidate
admission.

## Live Prompt Hardening

The first actual combined run exposed a repeated live-model omission:
`parameter_candidates` contained `name` and `value` but omitted required
`confidence`. The parser correctly rejected the output. The schema was not
weakened and v1 was not mutated.

The Prompt Registry now preserves context candidate prompt v1 as history and
activates v2 through the existing binding compare-and-swap lifecycle. V2 adds
only this exact-shape requirement:

```text
each parameter_candidates item = exactly name + value + confidence
```

The active Golden versions are intent v1, context v2, and plan v1. Binding
activation is idempotent and durable; no database migration or new table is
introduced.

## Protected Runner

`scripts/smoke/run_p65_s7_postgres_live_e2e.py` is opt-in through
`NEX_AE_P65_S7_POSTGRES_LIVE_E2E=1`. It requires:

```text
NEX_AE_TEST_DATABASE_URL -> nex_ae_user / nex_ae_test only
NEX_AE_P65_S7_NSL_SOURCE -> admitted NSL v0.1 source/wheel
NEX_MO_VLLM_BASE_URL or NEX_MO_VLLM_CHAT_COMPLETIONS_URL
NEX_MO_VLLM_API_KEY
```

The runner records only bounded lineage, model/profile identifiers, hashes,
counts, migration state, and cleanup results. Provider endpoint, API key,
database password, service token, prompt, provider output, candidate payload,
hidden reasoning, tenant ID, and owner ID are excluded.

## Actual Evidence

The protected run used `nex_ae_test` as `nex_ae_user`, with all 45 AE
migrations current through `2300_ae_semantic_candidate`. MO reported live
readiness for `general-llm-default / Qwen3.5-4B`.

```text
checks: 14/14 PASS
actual generation calls: INTENT, CONTEXT, PLAN (3)
semantic candidates: 3
executable steps: 2 (LOCAL_SKILL, DETERMINISTIC_REPORT)
runtime jobs / attempts: 2 / 2
NSL artifact / execution / backend run: 1 / 1 / 1
StepResult / AgentResult / ResultDelivery: 2 / 1 / 1
restart provider calls: 0
runtime residue: 0
planning/database residue: 0
private filesystem residue: 0
```

Sanitized machine-readable evidence is stored at
`reports/live/p65-s7-postgres-live-e2e.json`.

## Verification

The protected test was executed explicitly against the actual PostgreSQL test
database and live remote generation provider:

```text
protected PostgreSQL/provider E2E: 1 passed, 14/14 checks
focused regression: 453 passed, 1 skipped
AE Slice Gate: 4,362 passed, 11 skipped
AE Slice Gate statement / branch: 98.63% / 96.86%
Full Gate: 15,146 passed, 39 skipped
Full Gate statement / branch: 97.23% / 96.69%
contract validation: 174 schemas, 236 examples, 204 negative examples, 7 OpenAPI
AE Web: 331 passed
```

The protected P6.5-S7 test remains skipped by default in ordinary regression
and Full Gate runs. Its explicit activation passed before the gates, while the
Full Gate itself completed with exit code 0. Other opt-in protected acceptance
scripts remained explicitly skipped as designed.

## Exit

P6.5-S7 is closed when the actual provider supplies all three untrusted
candidates, only AE performs trusted binding and compilation, the same
ExecutablePlan continues through the P6 runtime to pending delivery, replay
does not repeat provider calls, and both durable and private-storage test data
leave zero residue. These conditions authorize P7 entry without granting the
LLM execution authority.
