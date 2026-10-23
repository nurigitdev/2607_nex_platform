# NeX-EOS Database

This directory owns the NeX-EOS PostgreSQL migration stream.

P8-S08 starts the stream at `2500_eos_schema_migrations_baseline`. P8-S09 adds
`2501_eos_business_transaction_core` for service-owned business-operation,
idempotency, and transactional-outbox infrastructure. Voucher and organization
tables follow in later slices. P8-S70 advances the current head to
`2510_eos_approval_instance`, adding tenant-scoped immutable policy snapshots,
ordered approval-stage state, and append-only decision-history storage. P8-S73
adds `2511_eos_approval_proof`, providing immutable final business approval
proof persistence and permitting unopened stages to close as `CANCELLED`
after a terminal rejection without manufacturing activation time. P8-S73
advances the current head to `2512_eos_approval_proof_decision_fk`, binding a
proof to the exact tenant-qualified EOS decision row.

```bash
python scripts/db/run_migrations.py --service nex-eos --profile dev
python scripts/db/run_migrations.py --service nex-eos --profile test
```

The protected test reset helper preserves `schema_migrations` and truncates
only public tables with the `eos_` prefix after exact URL, database, role, and
confirmation validation.
