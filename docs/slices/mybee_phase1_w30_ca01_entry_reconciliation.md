# MyBee Phase 1 W30-CA01 Entry Reconciliation

## Status

- Slice: `W30-CA01`
- Status: design closure complete; runtime entry conditional
- Runtime code changes: none
- Database migrations: none created or applied
- Remote model providers: not required

## Source-Backed Findings

The reviewed EOS migration inventory ends at `2529`. Candidate migration
number `2522` in the original plan is historical and cannot be reused.
`W30-S00` now reserves `2530`; S3-01 reserves `2531`, subject to another HEAD
check when each implementation starts.

W20 component Slices remain closed, but the vertical proposal journey is not
yet complete. EOS can create a scoped `DOCUMENT_SIGNOFF` request and read an
ApprovedDocumentEnvelope, while the current scoped decision service accepts
only `ACCOUNTING_POSTING`. It explicitly rejects `DOCUMENT_SIGNOFF`, and no
public envelope-create route exists.

The existing generic approval proof cannot be reused as a shortcut for
company or Project-set signoff because its approval instance requires a
Project. Accounting evidence is a different proof domain. A synthetic or
unrelated Project would violate the approved W20 scope model.

## Decisions

- Add `W30-S00: Scoped Document Signoff Finalization` before S3-01.
- Persist immutable document materialization context before WC decision.
- Route `DOCUMENT_SIGNOFF` to a dedicated finalizer while preserving the
  existing accounting finalizer for `ACCOUNTING_POSTING`.
- Preserve the existing generic proof-backed envelope path and API projection.
- Keep W30 candidate-only: it creates no PostedJournal.
- Treat `MB3-01` as W30 closure through the CA delta. The hash-pinned v1.2
  matrix retains its historical W31 label to preserve FL catalog provenance.
- Execute W30 in this order:
  `W30-S00 -> S3-01 -> S3-02 -> S3-03 -> MB3-01`.

Canonical decision artifacts:

- `docs/transition/MyBee_Phase1/NeX_MyBee_W30_CA01_W20_to_W30_Entry_Reconciliation_v1.0.md`
- `docs/transition/MyBee_Phase1/NeX_MyBee_W30_CA01_Entry_Decision_v1.0.json`

## Verification

```text
W30-CA01 focused consistency and provenance regression: 31 passed
MyBee Phase-1 regression: 295 passed
contract validation: PASS (233 schemas / 292 examples / 245 negative / 10 OpenAPI)
Golden Journey transition audit: PASS
demo/product dependency audit: PASS
```

Coverage is not applicable because this Slice changes only controlled design
and machine-readable planning artifacts. The next runtime implementation is
W30-S00 and must include actual EOS/WC/OA PostgreSQL protected smoke.
