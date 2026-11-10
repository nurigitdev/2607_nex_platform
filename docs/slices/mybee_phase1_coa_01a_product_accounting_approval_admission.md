# MyBee Phase-1 COA-01A: Product Accounting Approval Admission

## Scope

The Product Accounting Owner explicitly approved the exact COA-01 dataset in
the 2026-11-10 Codex session. COA-01A records that decision without inventing
an approver name, OA principal, digital signature, K-IFRS code authority or
DART concept identity.

The approval binds all 166 nodes and 88 postable candidates to:

```text
candidate file SHA-256 = sha256:904a122075109a1bb9021207075b1b3229f59d977cb0aee84c237de15ceaac04
candidate semantic hash = sha256:804cbc36814397ba9a74522dc7de7ffa444e001cde8ff6cbf8b8959129893fc0
code/semantic identity hash = sha256:412dee6066d65620e0b817bc652ab319b2ce33eccfccdce1b6e2cd77a0c4a673
node contract hash = sha256:e988aaf0f5eccb9578591d8e4f678cb8d751019583389346178a427771be7c13
approval proof hash = sha256:f16c845b752b8c6a810bc1c75f069c211030e3530996e87bb11f08fb99541d6e
approved source hash = sha256:7782f96ea7445c6b0c9d82bc4d3c431175e4f32c22a968c1430aea55f736e61c
```

## Approval Evidence

The approver is represented as `CODEX_SESSION_USER`, with asserted role
`PRODUCT_ACCOUNTING_OWNER`. The assurance is explicitly
`SELF_ATTESTED_BY_EXPLICIT_USER_INSTRUCTION`; signature status is
`NOT_CRYPTOGRAPHICALLY_SIGNED`. This is an honest record of the approval
channel rather than a fabricated enterprise identity.

The original Candidate and COA-01 identity manifest remain unchanged. They
are immutable pre-approval evidence. COA-01A adds an approval proof and an
approved source pointer over the same exact bytes.

## Runtime Boundaries

| Boundary | COA-01A result |
| --- | --- |
| Exact dataset accounting approval | `APPROVED` |
| Source admission | `APPROVED` |
| Controlled Seed eligibility | `true` |
| Automatic EOS publication | `false` |
| EOS Release published | `false` |
| Company adoption allowed | `false` |
| OA-authorized Product publisher | still required by COA-03 |
| Reporting taxonomy mapping | still pending where required |

`runtime_seed_allowed=true` means COA-02 may consume the admitted source in a
controlled persistence workflow. It does not mean startup-time auto-import or
authorization to publish/adopt the chart.

## Implementation

- `product_accounting_approval.v1.json` records the human decision and exact
  reviewed scope.
- `approved_standard_chart.v1.json` binds the approval to the immutable
  Candidate without duplicating 166 rows.
- `approved_seed_manifest.json` advances to v2 and admits only that approved
  pointer.
- `coa_approval.py` verifies every hash and boundary fail-closed using shared
  `nex_runtime.semantic_hashes` helpers.
- Candidate tamper, role/assurance drift, fake signature, scope drift,
  automatic publication and manifest drift are rejected.

## Verification

```text
focused COA-01/01A + EOS account-policy regression: 125 passed, 1 protected skip
focused MyBee Phase-1 regression: 112 passed
nex-eos Slice Gate: 911 passed, 24 explicit protected skips
Slice Gate statement coverage: 96.02% (threshold 95.00%)
Slice Gate branch coverage: 94.80% (threshold 94.00%)
COA candidate validator: statement 100.00%, branch 99.02%
COA approval validator: statement 99.10%, branch 95.45%
contract validation: PASS (233 schemas / 292 examples / 245 negatives / 10 OpenAPI)
Golden Journey transition audit: PASS
product dependency audit: PASS
MyBee package wheel: PASS; domain/coa_approval.py included
database migrations: NONE
remote provider / PostgreSQL requirement: NONE
```

The protected skips are pre-existing opt-in PostgreSQL and cross-service
smokes. This source-admission Slice changes no database or runtime publication
path, so none is claimed as live acceptance.
