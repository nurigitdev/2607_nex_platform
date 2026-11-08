# P8-S111: IA Multi-Member Orchestration and Result UX

## Scope

P8-S111 connects an untrusted natural-language INTENT candidate to the
authoritative P8-S107 through P8-S110 batch membership path and adds a safe
Korean result surface to authenticated AE Web Chat messages.

The orchestration path is:

```text
p65 INTENT candidate
  -> exact tenant-scoped Project-code resolution
  -> indexed scalar employee candidates
  -> OA batch resolution
  -> S108 canonical admission and approval projection
  -> S110 exact NSL capability binding
  -> S109 EOS aggregate/item result
  -> AE merged result projection
  -> AE Web Chat result surface
```

No table, migration, public API, or cross-service database read is added.
P8-S112 owns the actual multi-service HTTP/PostgreSQL/live-provider journey.

## Candidate Boundary

The shared `p65.intent_candidate.v1` contract remains scalar-only. S111 does
not expand it to model-produced arrays or records. The v3 prompt profile keeps
the existing Golden A rules and adds these untrusted hints:

- `intent_label = PROJECT.MEMBERSHIP.ADD_MANY`
- one exact Project code as a `QUERY_TERM` selector
- `employee_id_1`, `employee_id_2`, and matching optional
  `employee_name_1`, `employee_name_2` scalar parameters
- optional common `member_role`; omission defaults to `MEMBER`

The indexed values are accepted only by the dedicated batch adapter. Model
output never supplies tenant, Project ID, subject ID, scope, approval, or
mutation authority. Direct structured intake continues to support the CA05
limit of fifty candidates; the generic INTENT envelope keeps its existing
bounded parameter count.

## Runtime And Result Boundary

An admitted WorkIntent receives only the exact
`PROJECT.MEMBERSHIP.ADD_MANY` capability hint and the integrity-protected S108
admission reference. Stable subject IDs remain outside the model-authored
candidate and WorkIntent.

The AE result projection merges:

- pre-admission OA outcomes by safe input index or normalized employee ID;
- EOS commit outcomes by stable subject reference;
- deterministic aggregate requested, admitted, applied, and rejected counts.

The projection fails closed on payload, tenant, Project, role, evidence,
subject-set, outcome, or aggregate-count drift. It excludes raw prompts,
credentials, provider configuration, and authorization payloads. AE Web maps
the bounded outcomes to Korean labels, escapes all displayed identities, and
renders the result inside the existing authenticated Chat message.

## Contracts

- `p8.project_membership_batch_result_projection.v1`
- positive partial-result example in the canonical example index
- INTENT prompt binding v3, with v1 retained as historical lineage

## Verification

The following verification completed on 2026-10-25:

- focused orchestration, prompt-registry, and compatibility regression:
  `142 passed`, `2 skipped`;
- focused S111 backend coverage: `22 passed`, statement `100%`, branch `100%`;
- AE Web regression: `381 passed`, `0 failed`;
- AE Slice Gate: `5,517 passed`, `44 skipped`, statement `98.35%`, branch
  `96.38%`;
- repository Checkpoint Gate: `16,810 passed`, `116 skipped`, statement
  `98.66%`, branch `97.13%`;
- contract validation: `207` schemas, `271` positive examples, `229`
  negative examples, and `9` OpenAPI documents.

The first Checkpoint run detected that the S108 OA batch client had repeated
the local OA endpoint literal outside the shared endpoint registry. S111
removed that duplicate and now resolves the OA endpoint through
`nex_runtime.resolve_service_endpoint`. The deployment-coupling inventory is
therefore preserved at its canonical `49` occurrences in `29` files rather
than accepting a larger duplicate baseline.

## Exit

P8-S111 is complete when focused backend and Web regressions, contract
validation, the AE Slice Gate, and the CA05 Checkpoint Gate pass. P8-S112 may
then exercise the same path with actual OA/AE/WC/EOS PostgreSQL, live
generation, and authenticated Playwright.
