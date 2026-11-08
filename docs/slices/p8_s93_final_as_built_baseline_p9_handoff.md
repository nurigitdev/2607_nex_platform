# P8-S93: P8 Final As-Built Baseline / P9 Handoff

## Status

Completed on 2026-10-24.

## Scope

P8-S93 froze the verified P8 runtime, persistence, contract, NSL, Golden A,
reliability, UI, regression, and coverage baselines. It did not change runtime
code, database schema, public contracts, or business behavior.

The authoritative handoff is:

```text
docs/transition/P8/P8_Final_AsBuilt_Baseline_and_P9_Handoff_v1.0.md
```

## Runtime Baseline

The accepted runtime and evidence baseline remains the P8-S92 closure:

```text
commit    = 89f70d742d7ff40f01a990729499ad875ae88bf1
tree      = 8a375453925ebf228a64e61b6c79e05d8f87701d
contracts = d889cf34cdf9fa92b6ce5894a9ddb0a061100034
```

The S93 commit contains documentation only and is a verified descendant of
this baseline. Its identity is resolved through Git history to avoid a
self-referential document hash.

## Source-Backed Revalidation

S93 revalidated the final evidence before authorizing P9:

```text
service migration inventories = 7
source migrations             = 158
applied test DB migrations    = 158
missing / unexpected          = 0 / 0

JSON schemas                  = 191
positive / negative examples  = 255 / 221
OpenAPI documents             = 9
canonical reference checks    = 1,050
parity / terminology checks   = 25 / 21

repository tests              = 17,238 passed / 111 protected skips
statement coverage            = 96.72% (required 96%)
branch coverage               = 96.11% (required 94%)
```

The migration comparison was read-only and used the actual OA, AG, AE, CX,
MO, WC, and EOS `_test` PostgreSQL databases. Contract hygiene and coverage
threshold validation were re-run after the documentation changes. No Full
Gate rerun was required because S93 changes no executable source or contract;
the canonical S88/S89/S90/S91/S92 evidence remains the accepted gate chain.

## Final Evidence Identity

```text
NSL wheel sha256         = sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135
NSL release admission    = sha256:048e8cc8603ce4fba4ffd5d1f482bdd1444f9061122e221b851fc197c6959b84
Golden A package         = sha256:3af8aea41d52883807440df4c12761bcfa6fe81f215bce3f1a32bccccf9c850e
protected evidence       = sha256:a57656b3edd6d3bac4211988c0e207d94051c94e18e983d634bd6cd56d9c13af
Full Gate evidence       = sha256:0b3e58341d287cc2790b107d1cb7870484a3c39673422f951e990ed286db6c69
```

## Exit Decision

```text
P8 CLOSED
P8 GOLDEN A CLOSED
P8 RELIABILITY CLOSED
P8 CONTRACT / DATABASE / UI GATES CLOSED
P9 ENTRY AUTHORIZED
```

P9 begins with a source-backed NeX-WA / Work Asset boundary and ownership
review. It must preserve all P8 authority, tenant isolation, approval-domain,
exactly-once WRITE, reconciliation, verification, attachment, and lineage
invariants frozen by the final handoff.
