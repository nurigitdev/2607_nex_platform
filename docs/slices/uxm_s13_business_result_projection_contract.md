# UXM-S13 Business Result Projection Contract Closure

## Outcome

PASS / CLOSED. The owner-scoped IA result facade now carries an admitted typed
business summary without exposing the raw AgentResult or StepResult payload.
The React v2 Workspace renders a source-backed Voucher result card and falls
back to a generic safe result when no supported business type is admitted.

## Source Audit

| Result type | System of record | Projection owner | Privacy boundary |
|---|---|---|---|
| Generic AgentResult | AE `ae_agent_result` and `ae_result_delivery` | AE facade | references, status, warnings, artifacts only |
| `FINANCE.VOUCHER_DRAFT` | EOS commit; AE admitted WorkIntent and StepResult lineage | AE facade | typed display fields only; no raw command/result |
| Unknown result type | owner service remains authoritative | none admitted | omitted and rendered as generic result |

The browser route remains:

```text
GET /api/v1/chat/interactions/{interaction_id}/agent-result
```

The existing tenant and owner claim predicates are unchanged. No service DB is
read across ownership boundaries and no browser call is made directly to EOS.

## Typed Summary

The admitted contract is:

```text
result_type = FINANCE.VOUCHER_DRAFT
summary_schema_version = ae_business_result_summary.v1
summary = outcome, verification, approval, voucher number, amount/currency,
          account codes, Project code, optional business object link
```

The source chain is:

```text
verified WorkIntent + EOS authority + NSL WRITE outcome
  -> StepResult.business_summary
  -> AgentResult.structured_result.business_summary
  -> owner-scoped AE facade
  -> strict browser projection
  -> Workspace BusinessResultCard
```

An unknown `result_type` is ignored. A malformed known type fails closed.
Tenant ID, principal ID, prompt, raw provider output, controlled WRITE payload,
and technical operation identity are not rendered.

## Business Object Link Decision

EOS exposes only an internal Voucher detail API. An owner-facing AE facade does
not yet exist, so `business_object_link` is explicitly `null`. The UI does not
invent a broken or authority-bypassing link. A later Slice may admit a same-
origin link after its authorization and projection contract exists.

## Contract Assets

```text
contracts/schemas/service/nex_ae_api/business_result_summary.v1.schema.json
contracts/examples/service/ae_business_result_summary.voucher_committed.json
contracts/openapi/nex-ae-api.openapi.yaml
```

No database migration was required.

## Verification

```text
focused AE business/result/product tests     = PASS, 68 tests
contract and OpenAPI hygiene                 = PASS, 46 tests
browser unit regression                      = PASS, 409 tests
React component regression                   = PASS, 88 tests / 17 files
browser result client focused tests          = PASS, 5 tests
Workspace React result-card focused tests    = PASS, 10 tests
TypeScript typecheck                         = PASS
modern production import audit               = PASS, 37 files
modern browser security audit                = PASS, 38 files
design token consistency                     = PASS, 146 variables / 15 components
React v2 production build                    = PASS
protected desktop/mobile Playwright smoke    = PASS, 4 requests / 8 checks
PostgreSQL / remote providers                = NOT REQUIRED
```

The desktop and mobile result-card states were visually inspected from:

```text
reports/uiux/security-boundary/02-workspace-desktop.png
reports/uiux/security-boundary/03-workspace-mobile.png
```

The card remains readable without overlap at both viewports, collapses to one
column on mobile, and does not expose the internal EOS operation identifier.
The temporary visual fixture was removed after capture.

The Vite bundle remains subject to the known size advisory. UXM-S14 owns the
installed runtime wiring, durable polling, progress, approval-resume, result,
artifact, and citation integration.

## Decision

```text
UXM-S13 = PASS / CLOSED
UXM-S14 = AUTHORIZED
```
