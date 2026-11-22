# MyBee Phase 1 MB2-01 Business Proposal Approval Consumer

## Status

- Slice: `MB2-01`
- Status: implemented and verified
- Dependencies: `S2-01`, `S2-02`
- Gates: `G-BOUNDARY`, `G-CONSUMER`
- Database migrations: none
- Remote model providers: not required

## Boundary

MB2-01 adds the MyBee business-proposal form/template and the canonical
consumer boundary for the existing EOS/WC approval flow. MyBee remains an API
consumer: it does not access an EOS or WC database, import service-private
modules, submit directly to WC, or create an approval engine of its own.

The consumer sends the existing
`FINANCE.ACCOUNTING_APPROVAL.REQUEST` operation to EOS with purpose
`DOCUMENT_SIGNOFF`. EOS remains the business-approval provider and publishes
workflow work to WC. The returned EOS receipt is admitted only when the WC
publication and the exact proposal revision are bound together. Once EOS has
materialized the approved document, MyBee reads it through the existing
`BUSINESS.DOCUMENT_APPROVED.GET` operation.

## Form And Template

`business_proposal.v1.json` freezes the first D04 proposal template:

- document type `BUSINESS_PROPOSAL` and work code `FL0004011`;
- company, single-Project, or Project-set scope;
- title, purpose, business justification, requested amount and validity;
- multiple attachment object references with content and manifest hashes;
- immutable template identity and semantic digest;
- explicit EOS provider, WC workflow-owner, and no-direct-WC boundaries.

`build_business_proposal_form()` validates user input before any provider call.
It normalizes Project order, attachment order, four-decimal money, ISO
currency, and UTC timestamps. It then derives deterministic document-content,
attachment-manifest, and approval-subject hashes. A changed revision, amount,
scope, Project set, or attachment manifest therefore cannot replay as the same
approval subject.

## Consumer Reliability

`NexBusinessApprovalClient` composes the already-admitted S2-02 scoped approval
request and S2-01 approved-document read contract. It fails closed when:

- the EOS/WC receipt does not bind the exact proposal revision and hash;
- the approved envelope has a different company, Project scope, amount,
  currency, validity period, content hash, or attachment hash;
- the envelope is not active and usable;
- EOS rejects the request, is unavailable, or returns malformed JSON;
- endpoint, service token, or timeout configuration is invalid.

The HTTP transport keeps the signed service token out of payloads, sends
tenant and subject headers explicitly, and exposes typed, redacted errors.

## Verification

```text
focused MB2-01 + S2-01/S2-02 consumer regression: 107 passed, 2 protected skips
focused source coverage: statement 100.00%, branch 100.00%
MyBee Phase-1 regression: 290 passed
platform Slice Gate: 534 passed, 10 explicit protected skips
Slice Gate coverage: statement 100.00%, branch 100.00%
contract validation: PASS (233 schemas / 292 examples / 245 negative / 10 OpenAPI)
Golden Journey transition audit: PASS
demo/product dependency audit: PASS
```

Coverage evidence is stored in
`reports/quality/mybee-mb2-01-slice.coverage.json`. The protected PostgreSQL
tests were not enabled because MB2-01 adds no persistence or provider write;
the underlying S2-01/S2-02 database boundaries were already verified by their
own Slices.

## Deferred Provider Composition

The current EOS source admits `DOCUMENT_SIGNOFF` scoped approval requests and
serves approved-document envelopes, but its accounting decision path does not
yet finalize a `DOCUMENT_SIGNOFF` case into an envelope. MB2-01 intentionally
does not fill that provider gap with MyBee-local behavior. A subsequent
provider Slice must compose WC terminal approval, EOS approval proof, and
ApprovedDocumentEnvelope materialization before a protected end-to-end
business-proposal signoff journey can be claimed.
