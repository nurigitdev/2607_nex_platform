# P9-S22: WC Supporting Re-resolution and Correction Handling

## Scope

WA reconciliation now resolves the latest canonical WC WorkResult revision for
an Agent execution while preserving append-only supporting evidence history.

The normalized source identity is:

```text
source_type         = WC_WORK_RESULT
source_ref          = work_item_id
source_revision_ref = result_id
```

WC returns the latest revision plus a bounded predecessor identity only when
the two records share one tenant, execution, WorkItem, Claim generation,
Assignment, and submitted-Agent lineage. Duplicate revision numbers or lineage
drift fail closed as ambiguous.

WA links `supersedes_evidence_id` only when the predecessor evidence already
exists locally. A missed-notification reconciliation may therefore admit the
latest revision without creating a dangling reference. Existing evidence is
never rewritten; when linked, the predecessor becomes `SUPERSEDED`, the new
revision remains `ACTIVE`, and the WorkAsset binds only the latest supporting
evidence.

No table or migration was added. The existing `wa_work_evidence` uniqueness,
supersession foreign key, source-lineage audit query, and atomic evidence-set
admission are reused.

## Verification

- WC latest-revision selection, predecessor projection, and ambiguity tests
- WA source identity, exact replay, re-resolution, missing-predecessor recovery,
  malformed predecessor, and lineage mismatch tests
- WorkEvidence source-identity lookup and existing immutable history tests
- NeX-WC and NeX-WA Slice Gates
- Canonical schema, example, and OpenAPI validation

Results:

- focused regression: `45 passed`
- WC regression: `489 passed, 21 skipped`; changed projection module statement
  and branch coverage `100%`
- WA Slice Gate with WC projection scope: `271 passed, 9 skipped`, statement
  `97.28%`, branch `94.91%`
- contract validation: `226` schemas, `290` examples, `241` negative
  examples, and `10` OpenAPI documents

The standalone WC aggregate coverage command also ran and exposed a pre-existing
gate-scope mismatch: unexercised `approval_event_delivery.py` and
`demo_runtime.py` are included in the service-wide denominator, producing
statement `86.37%` and branch `86.29%` despite all WC tests passing. S22 does
not hide that result or broaden scope to unrelated WC modules; the changed WC
projection module is fully covered and the canonical WA aggregate gate passes.
