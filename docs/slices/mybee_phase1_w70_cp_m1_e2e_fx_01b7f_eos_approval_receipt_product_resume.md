# CP-M1-E2E-FX-01B.7F: EOS Approval Receipt to Product Resume Closure

## Status

- Date: `2026-11-19`
- Status: `IMPLEMENTED`; protected exact-head live acceptance pending
- Parent boundary: `CP-M1-E2E-FX-01B.7`
- Database migration: none
- Remote provider: required only for the final installed journey

## Failure Reconciliation

The protected `.7E` journey reached the authenticated approval inbox and EOS
persisted the approved document envelope, but the Product execution remained at
`WAITING_APPROVAL:PLAN_BUILD`. The missing boundary was not another approval
transport. WC already delivered the approval decision to AE through its durable
outbox and retried until AE acknowledged it. AE forwarded the delivery to EOS,
but treated the returned authority receipt only as a transport receipt and did
not bind it to the existing Product wait.

This Slice closes that gap in the installed product path:

```text
WC approval outbox delivery
  -> AE protected approval facade
  -> EOS authority transition and typed receipt
  -> AE typed Product wait resolution
  -> existing generalized Product event persistence
  -> existing RESUME_EXECUTION runtime job
  -> Product coordinator resume
```

AE returns success to WC only after the EOS receipt has either been classified
as outside the Product boundary, remained non-terminal, or durably admitted to
the Product event and resume boundary. Consequently, an ACK loss or transient
AE persistence failure reuses the existing WC outbox replay contract.

## Typed Authority Receipt

The EOS client now admits only the installed receipt schemas and validates the
WC outbox/event/domain binding before returning them. Product resume applies
only to scoped receipts with an explicit product authority meaning:

- `DOCUMENT_SIGNOFF` maps to `BUSINESS_FORMAL` and uses the approved envelope
  as authority evidence;
- `ACCOUNTING_POSTING` maps to `ACCOUNTING_REVIEW` and uses the accounting
  approval evidence; and
- a generic BUSINESS_FORMAL receipt remains outside Product resume rather than
  being guessed into a Product workflow.

The receipt case reference must match the WC `resume_target_ref`, the decision
must match the terminal EOS state, and the event timestamp and lineage must
match the delivered decision. Missing, malformed, or drifted evidence fails
closed.

## Generalized Wait and Resume

`SqlAlchemyGeneralizedWaitEventRepository` now resolves an existing Product
wait by the exact tuple `(tenant_id, authority_kind, authority_ref)`. The query
joins the existing wait registration, typed Product wait binding, and immutable
preparation checkpoint. Zero matches fail closed; multiple matches are a
conflict. No scenario identifier, case identifier, Project count, tenant
dictionary, or fallback is embedded in product code.

Terminal receipts are persisted through the existing Product event admission.
That admission performs the existing event-inbox insert, typed binding insert,
wait transition, and deterministic `RESUME_EXECUTION` enqueue. Exact receipt
replay returns the same event and runtime job across process restart.

An approval resumes the existing preparation path. A rejection persists a
typed rejected authority event, creates the registered immutable terminal
checkpoint, and moves the waiting AgentExecution to its terminal state without
performing business mutation. Legacy v1 approval notifications remain readable;
new notifications use v2 with an explicit authority state.

## Verification

- focused approval, Product coordinator, composition, and rejection regression:
  `PASS`
- actual isolated-schema `nex_ae_test` PostgreSQL smoke: `1 passed`
  - migration head admitted from repository inventory
  - exact authority tuple resolved from persisted Product wait
  - one external event and one resume runtime job persisted
  - engine restart returned the exact replay
  - cross-tenant delivery failed with zero mutation
  - isolated schema removed after verification
- Ruff, compile, and diff checks: `PASS`
- AE Slice Gate: `6852 passed`, `52` protected skips, commands `6/6`
  - statement coverage: `96.45%`
  - branch coverage: `94.72%`
  - active Product coverage: statement `97.07%`, branch `95.01%`
  - report: `reports/quality/mybee-w70-cp-m1-01b7f-ae-slice-gate.coverage.json`

## Remaining Acceptance

The implementation boundary is complete without a migration. Closure still
requires one exact-head installed live journey using actual AE/WC/OA/EOS
PostgreSQL databases and the admitted generation provider. The run must prove
approval receipt admission, Product resume job execution, final result
publication, ACK/replay safety, and zero residue before this Slice is marked
`CLOSED` and the parent `.7` boundary is resumed.
