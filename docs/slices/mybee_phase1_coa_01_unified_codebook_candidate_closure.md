# MyBee Phase-1 COA-01: Unified Codebook Candidate Contract and Data Identity Closure

## Scope

COA-01 converts the supplied 166-node internal design candidate into a
fail-closed, hash-bound review artifact. It does not approve accounting
content, create an EOS migration, publish a catalog, change an API, or enable
a runtime Seed.

The implementation adds:

- a strict JSON Schema for the supplied candidate;
- a semantic validator using `nex_runtime.semantic_hashes`;
- immutable semantic, identity-set and full node-contract hashes;
- cross-release code/semantic non-reuse checks;
- hierarchy, suffix, category, contra/balance and FX completeness checks;
- a machine-readable negative mutation matrix;
- an 88-leaf human reviewer table.

## Identity And Admission Result

| Boundary | Result |
| --- | --- |
| Candidate structure | `PASS` |
| 8-digit hierarchy and standard suffix | `PASS` |
| Unique code and semantic key | `PASS` |
| Required FX semantic set | `PASS` |
| Candidate status | `STRUCTURE_VALIDATED_ACCOUNTING_APPROVAL_PENDING` |
| Product Accounting Owner approval | `PENDING` |
| Runtime Seed | `DENIED` |
| `approved_seed_manifest.json` | unchanged, empty and not admitted |
| EOS migrations | unchanged; highest remains `2517` |

The MyBee platform lock had retained the pre-S1-01/S1-02 EOS OpenAPI digest.
Those two already-admitted Slices added LegalEntity/Project binding and
account-policy endpoints. COA-01 therefore reconciles only that lock entry
from `sha256:afee478a...` to the current reviewed
`sha256:609275ec...`; it does not modify the OpenAPI contract. OA, AE, WC and
WA lock entries were rechecked and were already current.

The three canonical hashes are frozen in
`domains/mybee/config/account_catalog/unified_codebook_candidate.identity.v1.json`.
The raw source-file hash remains bound to the CA01 Decision Delta. The
reviewer-facing leaf inventory is
`docs/transition/MyBee_Phase1/NeX_MyBee_COA01_Candidate_Reviewer_Diff_v1.0.md`.

## Fail-Closed Cases

The focused suite rejects duplicate code, duplicate semantic key, use of a
Tenant-reserved suffix by the GLOBAL candidate, parent drift, cross-release
code/meaning reuse, an unapproved Seed attempt, category/balance drift and a
missing required FX account. Identity manifest drift and malformed JSON also
fail closed.

## COA-02 Handoff

The exact candidate requires Product Accounting Owner approval before it can
be copied to an approved source manifest or used for production publication.
COA-02 may proceed with persistence/test scaffolding, but publication and
company adoption remain blocked until an approval proof is bound to the exact
semantic and node-contract hashes. No current result may be represented as
K-IFRS or DART code approval.

## Verification

```text
focused COA-01 regression: 43 passed
focused MyBee Phase-1 regression: 83 passed
nex-eos Slice Gate: 882 passed, 24 explicit protected skips
Slice Gate statement coverage: 95.97% (threshold 95.00%)
Slice Gate branch coverage: 94.79% (threshold 94.00%)
COA validator statement coverage: 100.00%
COA validator branch coverage: 99.02%
contract validation: PASS (233 schemas / 292 examples / 245 negatives / 10 OpenAPI)
Golden Journey transition audit: PASS
product dependency audit: PASS
MyBee package wheel: PASS; domain/coa_candidate.py included
database migrations: NONE
remote provider / PostgreSQL requirement: NONE
```

The 24 skips are pre-existing opt-in PostgreSQL and cross-service protected
smokes. This Slice is source/catalog-only, so none is claimed as live
acceptance and no database or remote provider was required.
