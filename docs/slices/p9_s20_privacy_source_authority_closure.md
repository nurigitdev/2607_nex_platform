# P9-S20: Privacy Scopes and Source Authority Closure

## Scope

NeX-WA now separates protected read authority into three cumulative scopes:

```text
work:evidence:read
work:evidence:detail:read
work:evidence:audit:read
```

The basic WorkAsset route returns a bounded summary and `evidence_count`; it
does not expose evidence IDs or binding lineage. Individual WorkEvidence and
asset lineage require the detail scope. Supersession, replay, and conflict
policy provenance additionally requires the audit scope. Initial callers
remain limited to `nex-ae-api` and `nex-ag`, and all reads stay tenant-scoped.

## Correction Semantics

Source correction reuses the existing `wa_work_evidence` structure:

1. a corrected source revision creates a new immutable WorkEvidence;
2. `supersedes_evidence_id` must reference the same tenant and source lineage;
3. the old ACTIVE evidence becomes `SUPERSEDED` in the same transaction;
4. exact replay reuses the existing evidence;
5. same source identity with a different hash remains a conflict;
6. explicit invalidation changes only lifecycle status and preserves source and
   semantic hashes.

No migration or unrestricted audit payload was added. The audit projection is
bounded to revision refs, hashes, lifecycle states, links, and creation time.

Human Artifact admission retains a minimum `CONFIDENTIAL` classification and
preserves `RESTRICTED`; the read surface never downgrades classification.

## Verification

Focused tests cover atomic correction, replay, conflict, invalidation,
cross-lineage rejection, bounded basic reads, cumulative scope denial, wrong
audience, cross-tenant reads, audit lineage, and contract examples.

- Focused regression and contract validation: `62 passed`
- NeX-WA Slice Gate: `223 passed, 8 skipped`
- WA aggregate coverage: statement `97.35%`, branch `94.92%`
- WorkEvidence repository: statement `97.49%`, branch `96.55%`
- WA read API: statement `97.85%`, branch `95.00%`
- Contract validation: `225` schemas, `287` examples, `241` negative examples,
  and `10` OpenAPI documents passed
- Ruff and repository diff hygiene: passed

Actual AE/WC/OA/EOS/WA PostgreSQL source admission, signed service-token
authority, protected negative cases, and zero-residue validation are completed
by the immediately following P9-CA03 gate.
