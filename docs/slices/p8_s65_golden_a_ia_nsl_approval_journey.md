# P8-S65: Golden A IA to NSL Approval Journey

## Status

Completed on 2026-10-23.

## Scope

- Connected the Golden A Korean prompt to the actual NeX-MO generation route
  for live INTENT and PLAN candidates.
- Added a deterministic journey service that binds the untrusted candidates to
  the S63 Project, Account, voucher policy, capability, Skill, and tool
  identities before compilation.
- Persisted the canonical WorkIntent, project-neutral IA AgentContext,
  CapabilitySnapshot, AgentPlan, PlanValidation, ExecutablePlan, and steps in
  actual `nex_ae_test` PostgreSQL.
- Ran the admitted NSL v0.2 controlled-WRITE prefix, published its
  ApprovalRequest to actual `nex_wc_test`, obtained a fresh OA authorization
  from actual `nex_oa_test`, approved it, ingested the AE event, and resumed the
  exact NSL checkpoint.
- Preserved the P8-S66 boundary by proving no EOS write was requested or
  executed.

No database migration, public API field, EOS mutation, idempotency policy, or
automatic retry was added.

## Identity Boundary

The actual NSL wheel does not use one identifier for every layer:

```text
business capability = FINANCE.CREATE_VOUCHER_DRAFT
NSL Skill            = FINANCE.VOUCHER_DRAFT_CREATE @ 1.1.0
WRITE tool           = FINANCE.CREATE_VOUCHER_DRAFT
approval id          = CREATE_VOUCHER_DRAFT
```

The shared LOCAL_SKILL capability contract now supports an optional explicit
`capability_id` alias. Same-ID P6 bindings keep their existing representation;
only a verified capability-to-Skill difference uses the alias. Compilation
and P8-S65 admission both verify the exact capability, Skill version, Skill
semantic hash, tool, executor, and backend profile.

## IA And Authority Boundary

The IA remains project-neutral: `AgentContext.project_ref` is `null`. The
deterministically resolved Golden A Project is carried as an interaction-scoped
resolved entity and authoritative activation binding. This does not convert
the IA into a Project Agent.

The live model may propose only:

```text
intent label and confidence
project-code candidate
amount/currency/date/type/category/settlement candidates
logical LOCAL_CAPABILITY and REPORT steps
```

The model cannot set tenant or principal identity, ProjectRef, AccountRef,
approval authority, exact Skill version/hash, executor/backend, idempotency
key, BusinessOperationId, or EOS commit state. Missing, ambiguous,
low-confidence, invalid, or authority-bearing candidates stop fail-closed.

The INTENT system prompt advanced from v1 to v2 within the same canonical
prompt template. Startup activation uses the existing binding CAS/history
mechanism, so a PostgreSQL restart upgrades the version with durable history
instead of switching across templates.

## Protected Live Journey

The protected runner is
`scripts/smoke/run_p8_s65_golden_a_approval_journey.py`. It requires explicit
activation and exact test database roles. It also verifies the admitted NSL
wheel before execution.

Observed environment:

```text
AE PostgreSQL = nex_ae_user @ nex_ae_test
WC PostgreSQL = nex_wc_user @ nex_wc_test
OA PostgreSQL = nex_oa_user @ nex_oa_test
generation    = general-llm-default / Qwen3.5-4B
NSL Skill     = FINANCE.VOUCHER_DRAFT_CREATE @ 1.1.0
```

All migrations were current: AE `59/59`, WC `13/13`, OA `18/18`. Provider
readiness checked the configured live generation, embedding, and reranker
routes; only generation was invoked by this Slice. The actual semantic call
order was exactly `INTENT`, `PLAN`.

The live PLAN compiled to one exact LOCAL_SKILL plus one deterministic result
projection step. PostgreSQL row counts matched the compiled plan. The NSL
prefix returned `WAITING_FOR_APPROVAL`; WC matched one valid event and rejected
the mismatched lineage probe; the approval status was `APPROVED`; AE consumed
the exact checkpoint and completed the resume runtime job as `DONE`.

P8-S65A supersedes the original four-scalar WRITE example with a Golden A
v1.1 contract. The protected ApprovalRequest now binds payload hash
`sha256:240a7e83a1b3355ba98b5473cc239f1aea6a318b17e53e385c01837666fb8eb9`
over the stable ProjectRef, AccountRefs, balanced lines, and other business
fields. Approval request/evidence identities are generated and retained as
control lineage outside that hash.

Final protected result:

```text
checks             = 20/20 PASS
actual PostgreSQL  = true
actual provider    = true
approval           = APPROVED
resume             = DONE
lineage exact      = true
EOS mutations      = 0
AE/OA/WC residue   = 0
```

The sanitized machine evidence is written below `/tmp`; database passwords,
provider endpoints, API keys, raw prompts, raw model output, and tenant-private
payloads are excluded.

## Verification

- New deterministic journey tests: 9 passed.
- Protected-runner and profile guards: 5 passed, 1 protected test skipped by
  default.
- New journey module statement coverage: `100%`.
- New journey module branch coverage: `100%`.
- Existing P6, P6.5, P8-S53, P8-S63, P8-S64, and prompt persistence focused
  regression remained green.
- Actual PostgreSQL, remote-provider, OA authorization, WC approval, and NSL
  resume gate: `PASS`, no inferred skip.
- P8-S65A revalidation NeX-AE Slice Gate: `5,130 passed`, `35 skipped`
  protected tests.
- Slice Gate statement coverage: `98.41%` against `95%`.
- Slice Gate branch coverage: `96.38%` against `94%`.
- Contract validation: 188 schemas, 250 positive examples, 217 negative
  examples, and 9 OpenAPI documents.

## Exit Decision

P8-S65 is closed. Golden A now reaches a durable, human-approved NSL resume
point from a natural-language IA prompt while preserving project neutrality,
candidate-only model authority, exact Skill admission, fresh OA authorization,
and zero EOS mutation. P8-S66 may continue this exact lineage through governed
WRITE execution and EOS commit verification.
