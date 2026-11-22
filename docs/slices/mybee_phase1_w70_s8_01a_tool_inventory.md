# W70-S8-01A Canonical Tool Inventory and Operation Identity Closure

## Status

- Slice: `W70-S8-01A`
- Status: `IMPLEMENTED_AND_VERIFIED`
- Date: `2026-11-15`
- Owners: NeX Runtime, NeX AE, NeX EOS, NeX MyBee
- Database migration: none
- Remote model provider: not required

## Decision

W70 starts from one source-admitted, runtime-inactive Tool identity inventory.
The inventory records canonical operation identity, exact EOS provider
operation, D04/D12 pack ownership, READ or governed-WRITE semantics, approval
requirement, activation state, service scope, OA action, side-effect metadata,
and compatibility aliases.

This Slice does not activate a new capability or Skill. Existing Golden A
execution remains available only through its compatibility identity. All
other W70 entries remain `CANDIDATE` except
`FINANCE.VOUCHER_CANDIDATE.GET_V2`, which remains `DEFERRED` until a
Project/OA read policy is explicit.

## Source Inventory

The immutable source files are:

- `domains/mybee/skills/tool_inventory.v1.json`;
- `domains/mybee/skills/tool_inventory.schema.json`; and
- `domains/mybee/mybee_ax/integrations/nex_tool_inventory.py`.

The admitted inventory contains 18 entries:

- 13 D04 accounting Tools;
- 5 D12 Project Tools;
- 16 `CANDIDATE` entries;
- 1 `ACTIVE_COMPATIBILITY` Golden A entry; and
- 1 `DEFERRED` sensitive read entry.

The inventory content digest is:

```text
sha256:ee010195add45d474551866c65112ec7417b386d53faef4bef79445f6a23d151
```

The loader verifies exact root and Tool fields, canonical lexical order,
unique operation identities, shared semantic digest, owner boundaries,
READ/WRITE side-effect consistency, approval classification, OA action shape,
provider operation resolution, and alias/inventory agreement.

## Canonical Registry Extension

The existing `nex_runtime.operation_names` implementation remains the single
operation alias resolver. S8-01A extends it rather than introducing a MyBee
alias engine.

The registry version is now:

```text
mybee-w70-s8-01a.v1
```

New canonical operations are added through `W70_CANONICAL_OPERATIONS` and
merged with the historical P8 set through `PLATFORM_CANONICAL_OPERATIONS`.
The historical `P8_CANONICAL_OPERATIONS` and `P8_OPERATION_ALIASES` exports
remain available for compatibility.

The W70 aliases are:

| Requested identity | Canonical operation |
| --- | --- |
| `FINANCE.CREATE_VOUCHER_DRAFT` | `FINANCE.VOUCHER_DRAFT.CREATE` |
| `createEosVoucherDraft` | `FINANCE.VOUCHER_DRAFT.CREATE` |
| `FINANCE.VOUCHER.APPROVE_AND_POST.ADMISSION` | `FINANCE.VOUCHER_POSTING.ADMIT` |

Alias resolution precedes inventory lookup. Unknown, cyclic-by-construction,
misdirected, duplicate, non-canonical, or inventory-unbound identities fail
closed.

## EOS Contract Reconciliation

The source audit found that `FINANCE.FX_RATE.RESOLVE` and
`FINANCE.FX_RATE.HISTORY` are GET-only reads but lacked explicit
`x-nex-side-effect-free` metadata in canonical EOS OpenAPI. Both operations now
declare that metadata. No route, request, response, or persistence shape
changed.

The resulting EOS OpenAPI digest is admitted in the MyBee platform lock:

```text
sha256:2d4fe5c257c1e8dd2ba39d92256011dd814407eb63ac9ea3b2c5ffab9b654d06
```

The common canonical-operation alias schema and examples now pin the same W70
registry version as runtime code.

## Verification

Focused identity and inventory Gate:

```text
53 passed
statement coverage: 100%
branch coverage:    100%
```

Covered modules:

- `nex_runtime.operation_names`;
- `mybee_ax.integrations.nex_tool_inventory`.

Extended MyBee, Golden A capability/activator, and contract regression:

```text
584 passed, 1 skipped
```

The single skip is the pre-existing opt-in W40-CA02 PostgreSQL/HTTP protected
acceptance. S8-01A has no database or remote-provider behavior, so it does not
convert that protected test into a local fixture claim.

## Preserved Boundaries

S8-01A preserves:

- the historical Golden A capability, receipt, bundle, and Skill identities;
- current EOS OpenAPI and schema wire authority;
- W40/W50/W60 Posting, allocation, P&L, authorization, and privacy invariants;
- AE as capability/runtime owner and MyBee as domain-policy owner;
- no cross-service private imports or database access;
- no NSL compiler/runtime change; and
- no database migration or runtime activation.

## Handoff

`W70-S8-01A` is closed. `W70-S8-01B` may now bind canonical EOS JSON Schemas
and OpenAPI operations to positive and negative Tool contract examples. It
must not duplicate current EOS schemas or activate a `CANDIDATE` Tool.
