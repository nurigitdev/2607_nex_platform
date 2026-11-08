# P8-S100: IA Project Operation Clarification and Admission

## Scope

P8-S100 connects the seven exact-admitted Project operations to the AE
planning boundary:

- `PROJECT.PROJECT.CREATE`
- `PROJECT.PROJECT.GET`
- `PROJECT.PROJECT.LIST`
- `PROJECT.PROJECT.DEACTIVATE`
- `PROJECT.MEMBERSHIP.ADD`
- `PROJECT.MEMBERSHIP.REMOVE`
- `PROJECT.MEMBERSHIP.LIST`

The LLM-produced `p65.intent_candidate.v1` remains an untrusted semantic
candidate. AE resolves tenant, Project code, employee number, stable IDs,
entity version, and exact NSL artifact identity before an operation may enter
planning or controlled execution.

## Decisions

- A Project display-name match requires clarification; only an exact
  tenant-scoped Project code can bind an existing Project.
- Stable authority fields supplied by the model are rejected by the existing
  INTENT candidate parser.
- Cross-tenant records are filtered before resolution.
- Missing or ambiguous Project/employee references stop with
  `CLARIFICATION_REQUIRED`; inactive authoritative records stop with
  `BLOCKED`.
- New Project and membership IDs are deterministic UUIDs derived from the
  tenant and admitted semantic input, not model output.
- Project currency defaults to the platform policy value `KRW` and remains a
  bounded admission argument.
- The admitted operation, exact Skill version, semantic hash, source hash,
  and deterministic arguments are integrity-protected by `admission_hash`.
- WorkIntent activation accepts only an intact v1.1 WorkIntent and an intact
  executable admission. It adds no direct EOS or OA authority.
- No database migration, public API duplication, or direct cross-service DB
  access was added.

## Contract

- Schema: `project_operation_admission.v1.schema.json`
- Positive example: `ae_project_operation_admission.continue.json`
- Negative example: `ae_project_operation_admission.model_authority.json`
- `model_authority` is contractually fixed to `false`.
- The P8-S99 write-artifact admission example is now included in the canonical
  example index; it had been omitted when S99 was recorded.

## Verification

- Focused Project admission tests: `38 passed`
- New module coverage: `99%` with branch measurement enabled
- Contract validation: `195 schemas`, `259 examples`, `223 negative examples`,
  and `9 OpenAPI` documents
- AE Slice Gate: `5,393 passed`, `44 expected protected skips`
- AE statement coverage: `98.33%`
- AE branch coverage: `96.30%`

The skipped cases are explicitly protected PostgreSQL, RustFS, admitted-wheel,
or external-runtime profiles. P8-S100 adds no persistence change. Actual
OA/AE/WC/EOS PostgreSQL, live generation, and browser acceptance remain owned
by P8-S102.

## Exit

P8-S100 closes deterministic IA clarification and admission for canonical
Project operations. P8-S101 may now add membership-filtered Voucher
create/get/list integration without granting the model final Project,
membership, account, or execution authority.
