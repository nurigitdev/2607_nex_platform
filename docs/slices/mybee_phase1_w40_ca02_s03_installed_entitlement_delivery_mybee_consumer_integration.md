# W40-CA02-S03 Installed Entitlement Delivery and MyBee Consumer Integration

## Status

`CLOSED` on 2026-11-13.

This Slice closes the installed product-consumer gap without creating a second
MyBee runtime, a placeholder NSL Skill, or a parallel capability registry. The
canonical AE Agent Runtime worker now binds the approved Finance capability and
activator to the real MyBee EOS Finance v2 HTTP consumer. The installed EOS
outbox publisher proves the exact project-entitlement delivery route to OA.

No database migration, API field change, or remote model provider was required.

## Installed Consumer Boundary

Added `nex_ae_api.mybee_product_consumer` as an AE-owned, non-NSL installed
binding. Protected `staging_live` and `production` startup now requires all of
the following:

1. admitted MyBee product package identity;
2. exact `FINANCE.CREATE_VOUCHER_DRAFT` ProductCapability registration;
3. exact Golden A Finance DomainIntentActivator registration;
4. valid EOS base URL and bounded timeout;
5. signed AE-to-EOS service token; and
6. construction of the real `NexVoucherCandidateClient` over
   `HttpVoucherCandidateProviderTransport`.

The binding admits these existing EOS Finance v2 operations:

- `FINANCE.VOUCHER_CANDIDATE.CREATE_V2`;
- `FINANCE.VOUCHER_CANDIDATE.VALIDATE`;
- `FINANCE.ACCOUNTING_APPROVAL.REQUEST`; and
- `FINANCE.VOUCHER_CANDIDATE.REVIEW_GET`.

The worker readiness projection exposes only the consumer identifier,
capability identity, admitted operation names, timeout, EOS origin, and a
deterministic semantic binding hash. Service tokens and business payloads are
not included.

## Capability Decision

The existing `FINANCE.CREATE_VOUCHER_DRAFT` capability and
`GoldenAFinanceIntentActivator` remain authoritative. This Slice deliberately
does not represent an HTTP consumer as a fake `LOCAL_SKILL` and does not add a
second ProductCapabilityRegistry. The installed binding verifies the approved
capability and activator before attaching the EOS consumer.

The canonical Compose overlay supplies only the bounded MyBee EOS timeout. It
continues to use the S02 OpenBao-resolved `NEX_EOS_BASE_URL` and signed
`NEX_AE_TO_EOS_SERVICE_TOKEN` trust path.

## Entitlement Delivery

`RoutingEosOutboxTransport` now provides a redacted route projection. Installed
EOS publisher readiness validates the exact route:

```text
PROJECT_ENTITLEMENT_SNAPSHOT -> nex-oa
```

All other EOS outbox events retain the existing AE route. Readiness contains no
token, event payload, or private endpoint path. The authoritative delivery path
remains:

```text
EOS transaction/outbox -> installed EOS outbox publisher -> OA inbox
```

Direct OA database mutation and direct MyBee-to-OA delivery remain prohibited.

## Runtime Ownership Audit

The executable W40 ownership audit now reports:

```text
status=PASS
integration_readiness=READY
integration_gaps=0
next_slice=W40-CA02-S04
```

It verifies the installed consumer, existing capability and activator, exact OA
route, canonical process topology, package ownership, and absence of a second
MyBee runtime.

## Validation

Focused installed binding, ownership audit, EOS route, and entitlement
regression:

```text
118 passed, 1 optional/protected skip
```

New installed consumer module coverage:

```text
statement coverage: 100%
branch coverage: 100%
```

Actual PostgreSQL protected smoke:

```text
nex_eos_test -> nex_oa_test entitlement delivery/ACK/replay/zero residue: PASS
nex_eos_test VoucherCandidate migration/immutability/zero residue: PASS
```

NeX-AE Slice Gate:

```text
status: PASS (5/5 commands)
tests: 5,864 passed, 46 protected/optional skips
statement coverage: 96.98% (threshold 95.00%)
branch coverage: 95.15% (threshold 94.00%)
contract validation: PASS (245 schemas, 303 examples, 254 negative, 10 OpenAPI)
Golden Journey transition audit: PASS
Demo/product dependency audit: PASS
```

NeX-EOS Slice Gate:

```text
status: PASS (5/5 commands)
tests: 1,637 passed, 48 protected/optional skips
statement coverage: 96.83% (threshold 95.00%)
branch coverage: 95.10% (threshold 94.00%)
contract validation: PASS (245 schemas, 303 examples, 254 negative, 10 OpenAPI)
Golden Journey transition audit: PASS
Demo/product dependency audit: PASS
```

Coverage evidence:

- `reports/quality/mybee-w40-ca02-s03-ae-slice-gate.coverage.json`
- `reports/quality/mybee-w40-ca02-s03-eos-slice-gate.coverage.json`

No embedding, reranker, or generation provider was used.

## S04 Entry Decision

`W40-CA02-S04` may proceed. S03 proves installed composition, capability
admission, redacted readiness, exact entitlement routing, and actual database
behavior. S04 must close the complete installed protected path with signed HTTP
calls, process restart/replay, fail-closed dependency behavior, and zero-residue
acceptance. S03 does not claim that broader installed E2E acceptance.
