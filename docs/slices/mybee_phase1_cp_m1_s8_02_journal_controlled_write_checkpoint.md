# CP-M1-S8-02 Checkpoint-only Journal Controlled WRITE

## Status

- Slice: `CP-M1-S8-02`
- Parent packet: `S8-02`
- Status: `CLOSED`
- Date: `2026-11-15`
- Gates: `G-NSL`, `G-RECOVERY`, `G-V1`

## Boundary

This checkpoint productizes the existing EOS v2 Journal Posting boundary for
AE/NSL controlled WRITE. It does not activate a selectable D04 Skill, alter the
NSL compiler/runtime, add a database table, or claim the full M2 `S8-02` packet.

The source audit retained the existing authorities:

- EOS `FINANCE.VOUCHER.APPROVE_AND_POST` remains the only Journal mutation;
- EOS `FINANCE.JOURNAL.RECONCILE` remains the authoritative uncertain-outcome
  lookup and verifies committed Journal, idempotency, and outbox lineage;
- NSL `WriteCallRequest`, `WriteCommitted`, `WriteNotCommitted`,
  `WriteCommitUnknown`, and `VerificationObservation` remain the runtime types;
- the P8 VoucherDraft v1 adapters remain unchanged.

## Implementation

### Journal execution

`nsl_eos_journal_execution.py` now:

- admits only `FINANCE.VOUCHER.APPROVE_AND_POST`;
- verifies the NSL domain-separated payload hash over the exact Journal
  business payload, including the path-scoped Candidate identity;
- sends the existing EOS v2 command with signed service authentication;
- maps exact `201 CREATED` and `200 REPLAYED` receipts to the same committed
  NSL business result;
- maps authoritative 4xx responses to `WriteNotCommitted`;
- maps timeout, connection loss, 5xx, unsupported success status, or malformed
  success lineage to `WriteCommitUnknown`.

### Reconciliation

`nsl_eos_journal_reconciliation.py` performs GET-only lookup through
`FINANCE.JOURNAL.RECONCILE` and admits only these state tuples:

| Commit state | Reconciliation | Verification | Retry |
|---|---|---|---|
| `COMMITTED` | `COMMITTED_CONFIRMED` | `VERIFIED` | `DO_NOT_REPOST` |
| `NOT_COMMITTED` | `NOT_COMMITTED_CONFIRMED` | `NOT_APPLICABLE` | `RETRY_SAME_IDENTITY_ONLY` |
| `UNKNOWN_COMMIT_STATE` | `RECONCILIATION_REQUIRED` | `NOT_RUN` | `DO_NOT_REPOST` |
| `COMMITTED` | `COMMITTED_VERIFICATION_FAILED` | `FAILED` | `DO_NOT_REPOST` |

Every tuple requires `new_idempotency_key_allowed=false`. A committed but
failed verification is kept as typed UNKNOWN and cannot trigger a second
Posting.

### Immediate verification

`nsl_eos_journal_verification.py` converts the same authoritative Journal
reconciliation projection into a strong read-after-write NSL observation. This
is intentionally service-to-service and does not impersonate a user to call the
OA-protected reporting endpoint. Only `COMMITTED_CONFIRMED + VERIFIED` and the
exact committed `journal_id` produce `matched=true`.

## Verification

Focused Slice Gate:

```text
tests/test_nex_ae_mybee_nsl_eos_integration.py
95 passed
new Journal adapter modules: 97% combined statement/branch coverage
```

Extended regression:

```text
654 passed, 7 skipped
```

The seven skips are protected PostgreSQL tests that are disabled during the
ordinary regression command, not silent functional skips. The relevant actual
PostgreSQL tests were then enabled explicitly against
`nex_eos_user@nex_eos_test`:

```text
atomic Journal Posting commit/replay                   PASS
Posting replay race, conflict, and outbox recovery     PASS
2 passed
```

Static checks:

```text
ruff                                                     PASS
py_compile                                               PASS
git diff --check                                         PASS
database migrations added                                0
```

## Deferred Boundary

`CP-M1-S8-02` is closed. Runtime-selectable signed D04/D12 Skills and FL mapping
remain `CP-M1-MB8-01`. Full `S8-02` still depends on the M2 period/FX
reconciliation boundary in `S5-04`; this checkpoint does not relax that
dependency.
