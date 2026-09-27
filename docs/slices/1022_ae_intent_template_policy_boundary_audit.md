# Slice 1022: AE Intent, Template, Prompt, and Runtime Policy Boundary Audit

## Goal

Freeze the S103 ownership, compatibility, persistence, and quality boundary
before changing AE chat generation behavior.

## Findings

- AE already owns the user-facing intent and policy decision by contract, but
  chat currently builds CX generation defaults directly.
- Prompt/template tables and one grounded-chat seed exist in PostgreSQL while
  runtime lookup remains process-local.
- The shared compatibility catalog is useful but has mode-name and prompt
  binding drift and is not part of chat admission.
- Resolved template, prompt, compatibility rule, output, and quality policy
  versions are not persisted as one replay-safe decision snapshot.

## Frozen Decisions

- Explicit user mode wins; deterministic intent classification is fallback.
- Canonical modes are `GENERAL_ANSWER`, `GROUNDED_ANSWER`,
  `DOCUMENT_SUMMARY`, and `DOCUMENT_GENERATION`.
- An exact active compatibility rule and explicit versions are required. A
  resolved record never stores an implicit `latest` value.
- Existing prompt registry/render-event tables and chat `generation_summary`
  are reused; no new table is planned for S103.
- Policy snapshots contain stable IDs, versions, hashes, bounded parameters,
  and safe reason codes, never raw prompts or provider endpoints.
- AE sends a resolved policy package to CX. CX remains provider-prompt owner and
  MO remains provider runtime owner.
- Remote providers are not required. Actual `nex_ae_test` evidence is required
  in Slice 1030.

## Slice Plan

1. `1022`: boundary audit.
2. `1023`: intent and execution-mode contract.
3. `1024`: PostgreSQL prompt/template registry adapter.
4. `1025`: runtime compatibility policy resolver.
5. `1026`: protected policy API and Checkpoint Gate.
6. `1027`: generation policy package composer.
7. `1028`: workspace chat runtime-policy orchestration.
8. `1029`: contract, OpenAPI, privacy, and observability hardening.
9. `1030`: actual PostgreSQL smoke.
10. `1031`: S103 closure and Full Gate.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_intent_template_policy_boundary_audit.py \
  --coverage-target scripts/smoke/run_ae_intent_template_policy_boundary_audit.py \
  --smoke scripts/smoke/run_ae_intent_template_policy_boundary_audit.py
```

The audit performs no database mutation and no provider call.

## Observed Evidence

- Slice Gate: `1985 passed` with one known warning.
- Repository statement coverage: `97.76%`.
- Repository branch coverage: `95.56%`.
- Boundary runner statement/branch coverage: `100%`/`100%`.
- Contract validation: 93 schemas, 147 positive examples, 110 negative
  examples, and 7 OpenAPI documents.
- Audit result: seven foundations, eight open gaps, zero issues, next Slice
  `1023`.
