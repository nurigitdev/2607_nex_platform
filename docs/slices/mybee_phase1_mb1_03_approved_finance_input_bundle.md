# MyBee Phase-1 MB1-03: Approved COA and FX Input Bundle

## Scope

MB1-03 closes the MyBee consumer boundary for the approved COA source and FX
source policy. It does not create a new database table, publish a COA without
fresh OA authority, adopt a chart for a company, or contain a live exchange
rate.

The bundle has two immutable inputs:

- `approved_seed_manifest.json` remains the admitted MyBee COA source. Its
  `automatic_publication_allowed`, `published`, and
  `company_adoption_allowed` flags remain false.
- `approved_rate_source_policy.json` admits a manual USD/KRW market-base policy
  profile for `SMBS_TODAY_EXRATE`. It contains source identity and EOS policy
  defaults, but no rate value.

## API And Trust Boundary

`mybee_ax.integrations.finance_inputs` validates both source inputs and emits
canonical requests only:

| Input | EOS operation | Fresh OA scope |
| --- | --- | --- |
| admitted COA manifest | `FINANCE.COA.PUBLISH_APPROVED` | `finance:catalog:publish` |
| company-bound FX policy | `FINANCE.FX_POLICY.CREATE_APPROVED` | `finance:fx:publish` |

The COA request binds the approved source hash, approval proof hash, and node
contract hash. It assumes the COA-02 DRAFT already exists; publication and
later company adoption remain distinct governed operations.

The FX request requires company, policy, effective-date, approver, and approval
proof bindings at runtime. Its `policy_hash` is calculated by the shared
`eos_fx_policy_hash_ref` helper used by both the MyBee consumer and EOS. The
source page is not fetched in this Slice. Automatic SMBS acquisition remains a
backlog item until its format and legal-use boundary are reviewed.

The static EOS OpenAPI now publishes the three S1-04 operations that were
already active in the FastAPI runtime: policy creation, rate batch import, and
rate resolution. The MyBee platform lock pins the updated OpenAPI digest.

## Reliability Notes

- The HTTP adapter holds the service token outside request payloads and sends
  tenant and subject headers explicitly.
- HTTP rejection, malformed responses, timeouts, and endpoint failures produce
  typed redacted errors.
- Unsupported currency pairs, stale policy hashes, invalid approval hashes,
  malformed identifiers, and invalid effective periods fail before transport.
- The domain package retains the `G-BOUNDARY` rule: no service-private imports,
  SQLAlchemy, psycopg, or database URL.
- The platform coupling baseline was reconciled from `50/30` to `51/31` for
  the already-present AE COA semantic-resolution loopback default discovered
  by this Slice Gate. The new MyBee HTTP adapter itself has no loopback default.

## Verification

Final Slice evidence:

```text
focused MB1-03 tests: 33 passed
MB1-03 consumer coverage: statement 100.00%, branch 100.00%
MyBee regression: 133 passed
actual nex_eos_test FX protected smoke: 41 passed
database identity: nex_eos_test / nex_eos_user
standard platform Slice Gate: 572 passed, 8 explicit protected skips
MyBee package statement coverage: 99.86% (threshold 95.00%)
MyBee package branch coverage: 99.07% (threshold 94.00%)
contract validation: PASS (233 schemas / 292 examples / 245 negative examples / 10 OpenAPI)
Golden transition audit: PASS
demo/product dependency audit: PASS
database migrations: NONE
remote model provider requirement: NONE
```

The eight Slice Gate skips are existing opt-in PostgreSQL topology, restart,
trust, and migration smokes. The S1-04 EOS PostgreSQL smoke was separately
enabled against the actual test database and passed; it is not included in
the skipped count above.
