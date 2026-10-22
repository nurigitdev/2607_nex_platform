# P8-S45 AE WaitRegistration Generalization

**Status:** PASS
**Date:** 2026-10-22

## Scope

P8-S45 extends the existing P7 `ae_wait_registration` source of record rather
than creating a parallel approval wait table.

```text
wait_type    = WORK_RESULT | NSL_APPROVAL
external_ref = bounded string identity
```

Historical `WORK_RESULT` callers retain their default behavior. New approval
callers may use an NSL-owned ApprovalRequestId that is not a UUID. The existing
state model, typed-step uniqueness, and P7 resume columns remain unchanged.

## Migration

Migration `2502_ae_wait_registration_generalization` converts PostgreSQL
`external_ref UUID` to `TEXT` using the existing textual UUID representation,
then adds bounded-reference and two-value wait-type checks. It neither drops
nor rewrites historical wait rows.

## Verification

- focused S45 plus historical P7 wait regression: `16 passed`, `1 protected skip`
- actual `nex_ae_test` migration: applied
- actual PostgreSQL protected smoke: `9 passed`
- actual smoke covers one step holding distinct `WORK_RESULT` and
  `NSL_APPROVAL` waits and cleans all scoped rows
- AE Slice Gate: PASS
  - Python: `4646 passed`, `19 protected skips`
  - statement coverage: `98.32%`
  - branch coverage: `96.20%`
  - `delegated_work.py` statement coverage: `97.90%`
  - `delegated_work.py` branch coverage: `100.00%`
  - contracts: `188` schemas, `250` examples, `217` negative examples,
    `9` OpenAPI documents
- final database audit: migration ledger `1`, `external_ref=text`, scoped rows `0`
- remote providers: not required

## Handoff

P8-S46 may add immutable NSL approval lineage and a typed binding API while
reusing this repository and table.
