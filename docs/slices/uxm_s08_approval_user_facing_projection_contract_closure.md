# UXM-S08 Approval User-Facing Projection Contract Closure

## Outcome

PASS / CLOSED. AE now owns an additive, display-safe approval projection with
explicit source availability. Missing authority is represented as `OPEN`; no
browser join, cross-service database read, or inferred business value is used.

## Source Matrix

| UX field | Current source owner | AE facade source | Privacy | Requirement | Runtime status |
| --- | --- | --- | --- | --- | --- |
| requester display | OA / originating workflow | No requester identity exists in `wc_approval_gate_detail.v1` | internal personal | required for target UX | `OPEN` |
| requested at | WC | approval detail `created_at` | internal operational | required | `AVAILABLE` |
| Project identity | EOS via WC formal projection | `gate.formal_approval.project_id` | internal business | conditional | `AVAILABLE` for `BUSINESS_FORMAL`, otherwise `OPEN` |
| Project display name | EOS | No admitted AE server-side resolver | internal business | optional | `OPEN` |
| amount / currency | originating business domain / EOS | Not present as a typed approval-detail field | internal financial | conditional | `OPEN` |
| business date | originating business domain / EOS | Not present as a typed approval-detail field | internal financial | conditional | `OPEN` |
| account | EOS | Not present as a typed approval-detail field | internal financial | conditional | `OPEN` |
| risk level / explanation | policy owner / EOS | No admitted typed risk projection | internal control | optional | `OPEN` |
| business line items | EOS | Not present as a typed approval-detail field | internal financial | conditional | `OPEN` |

The existing `summary` remains display text. JSON-looking text is not parsed as
an implicit business contract. This prevents product behavior from depending
on mock values or undocumented payload conventions.

## Contract

Canonical schema:

```text
contracts/schemas/service/nex_ae_api/user_approval_projection.v1.schema.json
schema_version = ae_user_approval_projection.v1
```

Authenticated facade route:

```text
GET /api/v1/approval-gates/{approval_work_item_id}/user-projection
```

The route derives tenant and subject from the browser session, asks WC for the
already-authorized gate detail using AE service trust, and returns only the
admitted projection. `AVAILABLE` requires an explicit value; `OPEN` requires a
null value or empty collection. Protected display markers fail closed.

## Boundary Decisions

- WC remains the approval gate and authorization system of record.
- AE owns the browser-facing projection and its redaction boundary.
- The browser never calls WC, EOS, or OA directly.
- The browser never performs a business join.
- Requester and Project display resolution remain future server-side owner
  integrations; no placeholder identity is fabricated.
- The schema admits future authoritative values for requester, Project,
  amount, account, risk, and line items without changing the status semantics.
- No persistence claim, database migration, or PostgreSQL smoke is introduced
  by this Slice.

## Implementation

- Added a pure AE projection builder with fail-closed source validation.
- Added the authenticated AE facade route and OpenAPI binding.
- Added same-origin fetch and mock client methods plus strict browser-side
  normalization for `AVAILABLE` and `OPEN` states.
- Added schema, redaction, missing-value, formal Project identity, browser
  session, and tenant propagation tests.

## Corrective Finding

The owning-service Slice Gate found a pre-existing UXM-S07 evidence gap: the
modern security-boundary Playwright runner was registered and had been run at
the Security Boundary Checkpoint, but it had no paired Node contract test.
The legacy runtime audit therefore counted 16 Playwright runners and 15 tests
and failed closed. A focused registration, summary, and protected-value guard
test now pairs that runner without changing runtime behavior.

## Verification

```text
focused AE projection/facade pytest = PASS, 63 tests
new projection statement/branch     = PASS, 100% / 100%
AE Web Node regression              = PASS, 407 tests
React regression                    = PASS, 55 tests
TypeScript typecheck                = PASS
modern import/security audits       = PASS, 20 / 21 files
React v2 production build           = PASS
contract validation                 = PASS, 231 schemas / 291 examples /
                                      245 negative examples / 10 OpenAPI specs
nex-ae-api Slice Gate               = PASS, 5/5 commands
AE owning-service regression        = PASS, 5,794 passed / 45 skipped
AE statement / branch coverage      = PASS, 97.04% / 95.34%
```

## Decision

```text
UXM-S08 = PASS / CLOSED
UXM-S08A = AUTHORIZED
```
