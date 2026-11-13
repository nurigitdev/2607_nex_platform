# W40-CA02-S04 Restart, Replay, Fail-Closed Protected Acceptance and Entry Gate

## Status

`CLOSED` on 2026-11-13.

This Slice closes the thin installed MyBee accounting integration established
by W40-CA02-S01 through S03. It proves the canonical installed path with actual
EOS and OA PostgreSQL test databases, signed service trust, loopback HTTP,
process reconstruction, exact replay, tamper rejection, authorization denial,
and zero-residue cleanup.

No database migration, public API field change, or remote model provider was
required.

## Protected Acceptance Boundary

The protected runner constructs the real OA and EOS applications over loopback
HTTP and uses isolated schemas in `nex_oa_test` and `nex_eos_test`. It applies
the service migrations and exercises the installed path:

```text
EOS project entitlement outbox
  -> signed EOS-to-OA delivery
  -> OA project grant projection
  -> MyBee signed AE-to-EOS VoucherCandidate create/validate
```

The acceptance matrix proves all of the following:

1. transport failure leaves the entitlement event pending;
2. publisher reconstruction recovers delivery and records the OA ACK;
3. exact entitlement replay is idempotent;
4. tampered entitlement replay is rejected;
5. exact VoucherCandidate command replay returns the existing candidate;
6. changed-semantics replay is rejected as a conflict;
7. member-without-finance-scope, finance-scope-without-membership, stale
   entitlement projection, and malformed service token all fail closed;
8. restart and replay create neither duplicate candidates nor duplicate active
   grants; and
9. isolated PostgreSQL schemas are removed after the run.

Evidence:

```text
mybee_w40_ca02_s04_protected_acceptance=pass
grants=2
candidates=1
next=W40-S4-01
```

Detailed machine-readable evidence is written to:

- `reports/quality/mybee-w40-ca02-s04-protected-acceptance.json`

## Integration Defects Closed

The protected composition exposed an internal representation mismatch in OA.
The canonical authorization resolver returns immutable scope sequences, while
the project-entitlement decision boundary accepted only `list`. The boundary
now accepts non-string `Sequence` values and still rejects strings, bytes,
sets, empty scope entries, malformed hashes, and malformed authorization
responses with the existing fail-closed `503` behavior.

The Repository Full Gate also exposed a standalone GB2 AE worker runner that
did not include the installed MyBee domain package in its source path. The
runner now uses the same package visibility as the canonical OCI/runtime
composition. The W40 installed-startup regression fixture was updated with the
S03 capability registry, Finance authority profile, signed EOS trust, and EOS
endpoint requirements.

These are compatibility corrections to existing product composition. They do
not introduce an alternate runtime or weaken protected startup admission.

## Validation

Focused W40/OA regression:

```text
63 passed, 2 protected/optional skips
```

Protected PostgreSQL and signed-loopback acceptance:

```text
3 passed
actual PostgreSQL: PASS
actual loopback HTTP: PASS
signed service trust: PASS
restart/replay/tamper/conflict/fail-closed: PASS
zero residue: PASS
```

NeX-OA Slice Gate:

```text
status: PASS
tests: 1,244 passed, 14 protected/optional skips
statement coverage: 96.65%
branch coverage: 95.08%
contract and audit gates: PASS
```

NeX-EOS Slice Gate:

```text
status: PASS
tests: 1,624 passed, 48 protected/optional skips
statement coverage: 96.83%
branch coverage: 95.10%
contract and audit gates: PASS
```

NeX-AE Slice Gate:

```text
status: PASS
tests: 5,843 passed, 46 protected/optional skips
statement coverage: 96.90%
branch coverage: 95.10%
contract and audit gates: PASS
```

Repository Full Gate:

```text
status: PASS
tests: 21,733 passed, 162 protected/optional skips
statement coverage: 96.73% (threshold 96.00%)
branch coverage: 95.90% (threshold 94.00%)
product statement/branch: 98.52% / 97.08%
harness statement/branch: 94.19% / 92.96%
contracts: 245 schemas, 303 examples, 254 negative, 10 OpenAPI
AE Web Node tests: 374 passed
AE Web React tests: 130 passed
typecheck/build: PASS
production cutover and full web acceptance: PASS
```

Slice Gate evidence:

- `reports/quality/mybee-w40-ca02-s04-oa-slice-gate.coverage.json`
- `reports/quality/mybee-w40-ca02-s04-eos-slice-gate.coverage.json`
- `reports/quality/mybee-w40-ca02-s04-ae-slice-gate.coverage.json`

No embedding, reranker, or generation provider was used.

## Entry Decision

`W40-CA02` is closed and the installed MyBee accounting entry gate is
`ACCEPTED`. The canonical path now proves product composition, signed trust,
entitlement delivery, MyBee consumer authorization, restart/replay safety,
fail-closed dependency behavior, and zero-residue cleanup without relying on a
smoke-only business implementation.

The next planned Slice is `W40-S4-01`.
