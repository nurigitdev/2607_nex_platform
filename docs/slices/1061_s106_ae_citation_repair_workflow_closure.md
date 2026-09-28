# Slice 1061: S106 AE Citation Repair Workflow Closure

## Goal

Close S106 with machine-checkable evidence that citation quality and bounded
repair are durable, owner-scoped, privacy-safe, restart-safe, and integrated
with the AE-to-CX asynchronous generation lifecycle.

## Closure

- CX remains the authority for grounded citation validation and performs at
  most one bounded inline repair with the same admitted retrieval package.
- AE owns the user-facing citation-quality workflow and persists only its safe
  metadata projection in the existing chat generation summary.
- AG operator remediation remains a separate workflow and lineage; it is not
  conflated with bounded inline repair.
- Exact tenant and owner scope protects citation-quality and legacy repaired
  response handoff, review, and decision routes.
- READY asynchronous handoffs persist `VALIDATED`, `REPAIRED`, or
  `ATTENTION_REQUIRED` workflow state and serve subsequent reads without an
  additional CX request.
- Deterministic operational events expose outcome and repair counts while
  excluding prompt, response, invalid output, evidence, identity, provider,
  credential, and storage details.
- Canonical JSON Schema, positive and negative fixtures, chat contracts, and
  AE OpenAPI 1.4 freeze the owner-visible workflow.
- Actual `nex_ae_test` and `nex_cx_test` evidence proves migration currency,
  a two-call bounded repair, CX and AE persistence, restart reads, owner
  isolation, transient private content, and zero probe residue.
- No database table was added and remote providers remain outside this
  metadata workflow boundary.

## Verification

```bash
NEX_AE_CITATION_REPAIR_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='<AE test database URL>' \
NEX_CX_TEST_DATABASE_URL='<CX test database URL>' \
./.venv/bin/python \
  scripts/smoke/run_s106_ae_citation_repair_workflow_closure.py --summary

scripts/quality/run_quality_gate.sh
```

## Observed Evidence

- Full Gate: `8463 passed`, `2 skipped`.
- Coverage: statement `98.80%`, branch `96.82%`.
- Contracts: schemas `101`, examples `159`, negative examples `122`,
  OpenAPI documents `7`.
- PostgreSQL smoke: AE `nex_ae_test`, CX `nex_cx_test`, checks `18/18`,
  provider calls `2`, cleanup residue `0/0`.
- Closure: components `10/10`, gaps `8/8`, PostgreSQL `pass`, next `S107`.
