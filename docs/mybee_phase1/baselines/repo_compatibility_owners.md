# MyBee Phase-1 Repository Compatibility Owners

**Slice:** S0-01  
**Baseline:** `master@9fe6ddb151bd121c8fb66fbde62cc24cca29eddb`  
**Status:** FROZEN ENTRY BASELINE / IMPLEMENTATION NOT STARTED

## Ownership

| Boundary | Canonical owner | MyBee usage |
|---|---|---|
| Identity and current authorization | NeX-OA | Canonical protected API and signed trust only |
| Agent runtime and NSL integration | NeX-AE-API | IA/PA orchestration and admitted Skill execution |
| Human work and approval workflow | NeX-WC | WorkItem, claim, assignment and human decision |
| Accounting, GL, Project, allocation and P&L | NeX-EOS | Canonical business API; no private DB or ORM import |
| Evidence and work artifacts | NeX-WA | Canonical evidence/artifact references |
| Context retrieval | NeX-CX | Canonical retrieval API where required |
| Model routing | NeX-MO | Provider-neutral generation boundary |
| Governance and trust operations | NeX-AG | Policy, trust and operational controls |
| MyBee domain policy | `domains/mybee/` | Catalogs, templates, Skills and API consumers only |

## Compatibility Rules

1. MyBee does not create a second accounting ledger, approval engine, Agent
   Runtime, identity store, evidence store, or model router.
2. No MyBee module imports a service-private ORM model or opens another
   service's database URL.
3. Provider and consumer changes are versioned and tested at their canonical
   API/schema boundary.
4. Existing Golden A v1 and `FINANCE.CREATE_VOUCHER_DRAFT` remain unchanged.
5. Frozen Platform or NSL semantics require a separately admitted controlled
   amendment; Phase-1 documentation cannot silently change them.
6. Posted accounting facts are corrected by governed reversal/fix-forward,
   never destructive mutation.

## Source And Database Baseline

The machine-readable source, contract, and migration inventory is
`source_manifest.json`. Its recorded commit is a stable ancestor baseline, not
an assertion that future implementation commits must retain the same HEAD.
Every migration-creating Slice must first compare its proposed number with the
actual service migration head and actual test database identity.
