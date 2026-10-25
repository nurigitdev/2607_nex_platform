# P8 Final As-Built Baseline and P9 Handoff v1.2

**Status:** FINAL / P8.11 CLOSED / DEMO RELEASE CANDIDATE REFRESHED / P9 ENTRY AUTHORIZED

**Phase Closed:** P8 - Controlled WRITE / Approval / Delegation / Enterprise OS

**Amendment Closed:** P8.11 - NVT Project Operations and Batch Membership

**Next Phase:** P9 - NeX-WA / Work Asset

**Observed Date:** 2026-10-25

**Platform Branch:** `transition/p4-agent-runtime-foundation`

## 1. Purpose

This document is the additive successor to the immutable P8 Final As-Built
v1.0 and v1.1 records. It closes P8-CA05 after P8-S104 through P8-S113 and
refreshes the demonstration release candidate with governed NVTProject
operations and one collection-valued Project membership operation.

P8.11 does not change the existing approval-domain separation, exactly-once
WRITE, reconciliation, verification, attachment, Project membership, or
Voucher boundaries.

## 2. Verified Platform Baseline

The executable P8.11 baseline is the P8-S112 closure:

```text
repository = nurigitdev/2607_nex_platform
branch     = transition/p4-agent-runtime-foundation
commit     = afab33eab8f4e4119b9693aa04fb4bf1e01840dd
tree       = fd88a7a3847bcbd07b3aae0779044e324d5ec85c
contracts@s112 = 0a1bc8a671ff3c1183ca5927df382232256fc037
contracts@s113 = 00eb4f0601ccfc64a026cf974cdd4f511f186cb9
```

P8-S113 adds two missing negative contract fixtures and closure documents. Its
commit is resolved from Git history to avoid embedding a self-referential
hash. The current contract validation result in Section 7 includes those two
fixtures.

## 3. P8.11 Delivered Scope

P8.11 closes this source-backed path:

```text
governed NVTProject CREATE / GET / LIST / UPDATE
-> exact NSL source and semantic admission
-> natural-language NVT operation candidate admission

natural-language multi-member request
-> bounded scalar employee candidates
-> authoritative OA batch resolution
-> deterministic AE canonical admission
-> one WC NSL_WRITE approval
-> one NSL controlled WRITE
-> one EOS BusinessOperation and transaction
-> per-item partial result and exact replay
-> authenticated AE Web result projection
```

The canonical operations are:

```text
PROJECT.NVT_PROJECT.CREATE
PROJECT.NVT_PROJECT.GET
PROJECT.NVT_PROJECT.LIST
PROJECT.NVT_PROJECT.UPDATE
PROJECT.MEMBERSHIP.ADD_MANY
```

NVTProject identity and code remain immutable. UPDATE is optimistic and an
active Mother Project prevents NVTProject deactivation. Batch membership
accepts one to fifty authoritative subject IDs, executes no WRITE inside a
FOREACH construct, and returns deterministic aggregate and item outcomes.

## 4. Authority And Partial-Outcome Boundary

The generation model supplies only an untrusted semantic candidate. It does
not decide employee existence, employment status, display-name validity,
tenant eligibility, Project existence, approval, or mutation authority.

OA resolves employee IDs and optional name hints. AE admits only the resolved
subject set and binds the resolution evidence hash. WC owns the exact approval
decision. NSL owns controlled execution semantics. EOS owns the Project,
membership, BusinessOperation, idempotency, outbox, and verification state.

Invalid employee candidates do not block valid candidates after successful
authoritative resolution. Infrastructure, trust, and unknown-commit failures
remain operation-level failures and never masquerade as partial business
success.

## 5. NSL Source Admission

The admitted runtime package remains NSL v0.2.1. P8.11 source-admits two
additive artifact revisions without changing the runtime wheel:

```text
NVTProject artifacts revision = 6ab16da5e8840a1387c4c2c3d6eeb933e54849d4
ADD_MANY artifact revision    = f5d899bb611ee2cd65ce9f6544ed6e51b450b7d4
ADD_MANY source sha256        = sha256:723f5683a4b6a9baa458874878d3b4956ecb259feca9077629c86500a127efe5
ADD_MANY semantic hash        = sha256:9a3362e5906cf9d62d720d77369acc6e39d40afcb1f0ccb59726b0ea85e7af02
WRITE manifest sha256         = sha256:d9ec73d53392ab6df670886cbed1ddf8dd093a7c86ddb8195880fcc8c7f34392
```

The NSL repository gates passed at 2,327 and 2,329 tests for the respective
artifact revisions, with 98.95% total coverage.

## 6. Persistence And Migration Baseline

P8.11 adds no table or migration. It reuses `eos_nvt_project`,
`eos_project_member`, existing OA identity registries, WC approval state, AE
runtime state, and EOS BusinessOperation/idempotency/outbox state.

The protected journey confirmed these current inventories:

| Service | Source / current | Newly applied |
| --- | ---: | ---: |
| `nex-oa` | 18 | 0 |
| `nex-ae-api` | 60 | 0 |
| `nex-wc` | 13 | 0 |
| `nex-eos` | 15 | 0 |

The all-service P8.10 baseline remains 159 source/applied migrations. CA05
introduces no cross-database foreign key or direct cross-service database read.

## 7. Contract Baseline

Canonical validation passes after S113 contract-hygiene reconciliation:

```text
JSON schemas      = 207
positive examples = 271
negative examples = 231
OpenAPI documents = 9
```

The two S113 fixtures prove that an unknown batch-result terminal state and a
model-authoritative Skill binding are rejected. This restores the historical
S101 AE contract-drift baseline to 33 without weakening its guard.

## 8. Protected Demonstration Acceptance

After the Repository Full Gate, P8-S112 was re-run with actual OA, AE, WC, and
EOS PostgreSQL test databases, live `Qwen3.5-4B` generation, and authenticated
Chromium Playwright:

```text
protected checks       = 10 / 10 PASS
requested candidates   = 3
admitted / applied     = 1 / 1
rejected               = 2 (name mismatch / employee not found)
NVT CRUD               = PASS
OA resolution          = PASS
WC approval            = PASS
EOS exact replay       = PASS
authenticated browser  = PASS
backend residue        = 0
```

The machine-readable report is local under the ignored `reports/` tree. Its
SHA-256 is:

```text
sha256:46c333edffa254dfe101f17f89a60d0f28ca1dc1795fac4174553f85841fe7cf
```

The report includes no credential, endpoint, token, provider configuration,
or raw prompt.

## 9. Repository Full Gate

P8-S113 executed the complete canonical Repository Full Gate:

```text
collected tests       = 17,650
passed                = 17,532
protected skips       = 118
failed / errored      = 0 / 0
statement coverage    = 96.63% (required 96.00%)
branch coverage       = 96.01% (required 94.00%)
AE Web                = 386 passed / 0 failed
contract validation   = 207 / 271 / 231 / 9
```

```text
coverage JSON sha256 = 5642ceaf288c26f9c11784beaaebbec3d7f35de0e6420a87f17a90f5dcde7ea5
JUnit XML sha256     = 2d1f7af38e872e2951469543daecb56bece62d26716d395101ef7dfb287e6321
```

The Full Gate preserves explicit protected-environment skips. The actual
database, provider, and browser path was therefore executed independently as
described in Section 8.

## 10. Closed P8.11 Invariants

1. NVTProject operations are tenant-scoped and current-authority protected.
2. NVTProject identity/code are immutable and UPDATE is optimistic.
3. Employee identity is OA-owned; names are confirmation hints only.
4. Batch membership is one approval, one NSL WRITE, and one EOS transaction.
5. Exact replay creates no additional semantic mutation.
6. Concurrent single and batch ADD preserve membership uniqueness.
7. Partial outcomes never hide infrastructure, authority, or unknown-commit
   failures.
8. The model cannot grant identity, tenant, approval, or WRITE authority.
9. No table, migration, cross-database foreign key, or direct cross-service
   database read was added.
10. Actual PostgreSQL, live generation, Playwright, Full Gate, and zero-residue
    acceptance pass.

## 11. Deferred Scope

The v1.0 and v1.1 deferred ledgers remain in force. P8.11 does not add Project
P&L, ledger/accounting completion, arbitrary bulk Project administration,
complex Project hierarchy, Skill-pack packaging, or model-owned business
authority.

## 12. P9 Entry

P9 remains NeX-WA / Work Asset and is not a scheduler. It must preserve every
P8 v1.0, v1.1, and v1.2 tenant, authority, approval-domain, exactly-once WRITE,
reconciliation, verification, attachment, operation-name, membership, batch,
and evidence-lineage invariant.

P9 entry is re-authorized with this v1.2 document as the current handoff
baseline. P9 starts with a source-backed ownership and contract audit and
receives no implied permission to mutate OA, AE, WC, EOS, or NSL state
directly.

## 13. Final Decision

```text
P8 v1.0 AND v1.1 BASELINES PRESERVED
P8-CA05 CLOSED
P8.11 CLOSED
NVT PROJECT OPERATIONS CLOSED
BATCH PROJECT MEMBERSHIP CLOSED
PROTECTED DEMONSTRATION ACCEPTED
REPOSITORY FULL GATE PASSED
ZERO-RESIDUE CLOSURE PASSED
DEMO RELEASE CANDIDATE REFRESHED
P9 ENTRY AUTHORIZED
```
