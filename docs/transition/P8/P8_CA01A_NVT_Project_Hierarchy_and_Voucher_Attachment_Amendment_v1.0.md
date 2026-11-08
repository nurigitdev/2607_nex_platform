# P8-CA01A — NVT Project Hierarchy and Voucher Attachment Amendment v1.0

**Status:** ADDITIVE AMENDMENT / PROPOSED FOR P8-CA01 INCORPORATION  
**Parent:** `P8-CA01 — Controlled WRITE / Approval / Delegation / EOS Contract Closure v1.0`  
**Phase:** P8 — Controlled WRITE / Approval / Enterprise OS  
**Scope:** EOS Project hierarchy and Voucher Draft attachment boundary only  
**Date:** 2026-10-21

---

## 1. Purpose

This amendment adds two small clarifications to P8-CA01:

```text
DEC-21  NVTProject / Project Hierarchy
DEC-22  Voucher Draft Attachment Boundary
```

The amendment does not change the existing P8 authority model, NSL WRITE
semantics, Approval model, Delegation Guard, or Golden A sequencing.

---

## 2. DEC-21 — NVTProject Is a Separate EOS Business Object

P8 SHALL model `NVTProject` separately from the ordinary `Project` table.

Conceptually:

```text
NVTProject
    │
    ├─ Mother Project A
    │    ├─ Level-2 Project A-1
    │    │    └─ Level-3 Project A-1-1
    │    └─ Level-2 Project A-2
    │
    └─ Mother Project B
         └─ Level-2 Project B-1
```

`NVTProject` is the top-level business/value-management anchor.

It is not counted as one of the three ordinary Project hierarchy levels.

```text
NVTProject          = separate top-level object

Project Level 1     = Mother Project
Project Level 2     = Child Project
Project Level 3     = Grandchild Project

maximum Project depth = 3
```

---

## 3. Mother Project Definition

Within the ordinary `Project` table:

```text
parent_project_id == NULL
```

means:

```text
Mother Project
```

A Mother Project SHALL belong directly to one NVTProject.

```text
Mother Project:
    parent_project_id = NULL
    nvt_project_id    = NOT NULL
```

---

## 4. Non-Mother Project Definition

A non-Mother Project belongs to another Project.

```text
Non-Mother Project:
    parent_project_id = NOT NULL
```

The canonical NVT relationship is resolved through its ancestor Mother Project.

Recommended initial rule:

```text
Child / Grandchild Project:
    parent_project_id = required
    nvt_project_id    = NULL
```

This avoids duplicated NVT ancestry that could become inconsistent.

Canonical traversal:

```text
Child
→ Parent
→ ...
→ Mother Project
→ NVTProject
```

---

## 5. NVTProject Initial Logical Model

Initial logical fields:

```text
NVTProject
────────────────────────────
nvt_project_id
nvt_project_code
name
status
created_at
updated_at
version
```

Only fields required for Project grouping, resolution, and aggregation are
required in initial P8.

Future NVT-specific economic/token attributes are not required now.

---

## 6. Project Initial Logical Model

Relevant hierarchy fields:

```text
Project
────────────────────────────
project_id
project_code
name

parent_project_id
nvt_project_id

status
start_date
end_date
currency
version
...
```

Foreign-key semantics:

```text
project.parent_project_id
→ project.project_id

project.nvt_project_id
→ nvt_project.nvt_project_id
```

---

## 7. Project Hierarchy Invariants

P8 SHALL enforce:

```text
PH-01
Mother Project:
parent_project_id IS NULL
AND nvt_project_id IS NOT NULL

PH-02
Non-Mother Project:
parent_project_id IS NOT NULL

PH-03
Project hierarchy depth <= 3

PH-04
Project hierarchy cycle is forbidden

PH-05
A Project cannot be its own ancestor

PH-06
All descendants of one Mother Project resolve to the same NVTProject

PH-07
NVTProject is not inserted into the Project parent_project_id chain
```

Example invalid cycle:

```text
Project A
→ Project B
→ Project C
→ Project A

= DENIED
```

---

## 8. NVT-Based Aggregation

The initial EOS query model SHALL support:

```text
NVTProject
→ all direct Mother Projects
→ all descendants of each Mother Project
→ aggregate / query the resulting Project set
```

Conceptually:

```text
NVT-X
    ↓
Mother-A ─┬─ Project-A1
          └─ Project-A2
                └─ Project-A2-1

Mother-B ─── Project-B1

NVT-X aggregate
=
Mother-A
+ A1
+ A2
+ A2-1
+ Mother-B
+ B1
```

Initial PostgreSQL implementation may use recursive hierarchy queries.

A materialized hierarchy, path column, or denormalized root projection is not
required by P8 unless performance evidence later requires it.

---

## 9. NVT Future Semantics Are Deferred

The long-term NVT concept may include:

```text
Token Budget
Budget Allocation
Token Consumption
Performance Evaluation
Value Measurement
Incentive
```

These are intentionally deferred.

P8 treats `NVTProject` only as:

> **the top-level business/value anchor above Mother Projects and the aggregation root for their Project hierarchies.**

Deferred:

```text
NVT token issuance
token accounting
token allocation
token consumption
token valuation
performance scoring
incentive calculation
```

This preserves room for future NVT semantics without making them Golden A
dependencies.

---

## 10. Project Resolution Impact

A Project reference used by Voucher Draft or another business transaction SHALL
still resolve to the actual ordinary Project stable ID.

Example:

```text
User:
"A 프로젝트 출장비를 처리해줘"

        ↓

Project Resolution
        ↓

NVT-X
  └─ Mother Project A
       └─ Project A-2
            ↓

Canonical ProjectRef = project://A-2
```

The transaction uses `ProjectRef`, not `NVTProject`, as a substitute for the
actual Project.

NVTProject provides hierarchy and aggregation context.

---

## 11. DEC-22 — Voucher Draft Is an Approval/Draft Business Object

The initial `VoucherDraft` is not merely an accounting row.

It is also the business draft that will later participate in enterprise
approval.

Therefore the model SHALL remain extensible for:

```text
supporting documents
receipts
invoices
contracts
estimates
images
PDF
spreadsheet
other business evidence
```

P8 does not need to implement the complete document-management lifecycle.

---

## 12. Voucher Attachment Boundary

Binary attachment content SHALL NOT be stored directly in the EOS
`voucher_draft` relational row.

EOS stores:

```text
business metadata
stable attachment references
evidence references
approval relationships
```

Object storage owns:

```text
binary object content
```

Canonical boundary:

```text
VoucherDraft
    │
    ├─ Voucher business fields
    ├─ Attachment metadata / refs
    └─ Evidence refs
             │
             ▼
        Object Storage
```

---

## 13. RustFS Reuse

The current NeX environment already uses RustFS.

P8 therefore does not need to introduce a new binary object-storage product for
Voucher attachments.

Architecture position:

```text
RustFS
= binary/object storage

EOS
= Voucher / Attachment business metadata SoR
```

This amendment intentionally does not freeze low-level RustFS implementation
details such as:

```text
bucket naming
object-key format
presigned URL behavior
retention implementation
replication
storage tier
client SDK choice
```

Those belong to the P8 SRS / implementation slice only when required.

---

## 14. Initial Voucher Attachment Model

Recommended relational association:

```text
voucher_draft_attachment
────────────────────────────────
attachment_id
voucher_id

object_ref
display_name
media_type
size_bytes

content_sha256       # optional initially but recommended
evidence_ref         # nullable

created_at
```

The exact physical table/schema may be refined during EOS SRS design.

The important contract is:

```text
Voucher Draft
1 : N
Attachment Reference
```

---

## 15. RustFS Reference Rule

EOS SHALL persist a stable opaque object reference.

Example logical field:

```text
object_ref
```

It SHALL NOT persist:

```text
RustFS access key
secret key
session credential
presigned URL as durable identity
local filesystem path
```

Temporary access URLs are delivery mechanisms, not business object identities.

---

## 16. Attachment Integrity

Initial P8 SHOULD support:

```text
content_sha256
```

for attachment integrity/provenance where available.

However:

```text
full enterprise document signing
content notarization
retention/legal hold
document lifecycle/version governance
```

are outside the first Golden A scope.

---

## 17. Approval Binding and Attachments

Long term, a material attachment change may invalidate an existing business
approval.

Example:

```text
Voucher approved
    ↓
amount changed
or
Project changed
or
Account changed
or
material attachment changed
    ↓
old approval proof invalid
    ↓
new approval required
```

This is consistent with:

```text
PayloadHash
WriteIntentHash
Approval Evidence
```

However initial P8 SHALL NOT require a full attachment-manifest hashing policy
to close Golden A.

---

## 18. Initial P8 Attachment Semantics

For the first Golden A:

```text
attachments = optional
```

If no attachment exists:

```text
Golden A still PASS
```

If attachment refs are supplied:

```text
EOS validates reference shape / tenant ownership / existence as required
and persists their association with Voucher Draft
```

The exact rule for whether attachment content participates in:

```text
PayloadHash
WriteIntentHash
Formal Business Approval invalidation
```

is deferred to the later Voucher/Formal Approval SRS slice.

This avoids over-expanding P8 Golden A.

---

## 19. Recommended Golden A Shape After Amendment

```text
User Prompt
"출장비 84,000원을 A 프로젝트에 처리해줘"
        ↓
Project Resolution
        ↓
NVT-X
  └─ Mother-A
       └─ Project-A2
        ↓
Canonical ProjectRef
        ↓
Voucher Draft
  ├─ ProjectRef
  ├─ AccountRef
  ├─ Amount / Currency
  ├─ Description
  ├─ AttachmentRefs[]   optional
  └─ EvidenceRefs[]     optional
        ↓
NSL WRITE Approval
        ↓
EOS FINANCE.CREATE_VOUCHER_DRAFT
```

No NVT token accounting is required.

No mandatory attachment is required.

---

## 20. EOS SRS Delta

The future P8 EOS SRS SHALL include requirements equivalent to:

```text
EOS-PROJ-NVT-001
EOS SHALL maintain NVTProject as a separate top-level business object.

EOS-PROJ-NVT-002
A Mother Project SHALL have parent_project_id = NULL and one NVTProject ref.

EOS-PROJ-NVT-003
Ordinary Project hierarchy SHALL be bounded to maximum depth 3.

EOS-PROJ-NVT-004
Project hierarchy cycles SHALL be rejected.

EOS-PROJ-NVT-005
EOS SHALL support NVT-rooted Project aggregation/query.

EOS-VCH-ATT-001
Voucher Draft SHALL support zero or more attachment references.

EOS-VCH-ATT-002
Voucher attachment binary content SHALL not be stored directly in the
Voucher relational row.

EOS-VCH-ATT-003
EOS SHALL persist stable object references and metadata for attachments.

EOS-VCH-ATT-004
Existing RustFS object storage MAY be used as the binary storage provider.

EOS-VCH-ATT-005
Storage credentials and temporary access URLs SHALL not become durable
Voucher attachment identities.
```

Exact requirement IDs may follow the final P8 SRS numbering scheme.

---

## 21. Test Additions

Recommended minimum tests:

```text
PRJ-01 Mother Project requires NVTProject
PRJ-02 child requires parent Project
PRJ-03 Project depth 3 PASS
PRJ-04 Project depth 4 DENIED
PRJ-05 Project cycle DENIED
PRJ-06 NVT aggregate returns all Mother descendants
PRJ-07 descendant resolves correct NVT through Mother

ATT-01 Voucher Draft without attachment PASS
ATT-02 Voucher Draft with one attachment ref PASS
ATT-03 multiple attachment refs PASS
ATT-04 cross-tenant object ref DENIED
ATT-05 durable model stores object ref, not secret/presigned credential
```

Attachment-content upload/download testing may be placed in the later storage
integration slice.

---

## 22. Impact on P8-CA01

This amendment adds:

```text
DEC-21 — NVTProject / Project Hierarchy
DEC-22 — Voucher Draft Attachment Boundary / RustFS reuse
```

It does not alter:

```text
NSL v0.2 semantics
Approval domain separation
WC Delegation Guard
BusinessOperationId
Idempotency
UNKNOWN_COMMIT_STATE
EOS WRITE authorization
Golden A sequencing
```

The P8-CA01 exit state remains:

```text
P8-CA01 + P8-CA01A accepted
        ↓
P8 SRS ENTRY AUTHORIZED
```

---

## 23. Final Amendment Position

The Project hierarchy is:

```text
NVTProject
    ↓
Mother Project
    ↓
Project Level 2
    ↓
Project Level 3
```

where NVTProject is a separate EOS business object and ordinary Project depth is
bounded to three.

The Voucher attachment architecture is:

```text
EOS Voucher Draft
→ attachment metadata / stable refs
→ existing RustFS object storage
```

with binary storage and business metadata deliberately separated.

Final principle:

> **P8 introduces only the minimum NVT and attachment structure required to preserve the long-term business model; Token economics and full document-management semantics remain deferred so that Golden A stays small and executable.**
