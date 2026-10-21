# NeX-EOS Database

This directory owns the NeX-EOS PostgreSQL migration stream.

P8-S08 starts the stream at `2500_eos_schema_migrations_baseline`. P8-S09 adds
`2501_eos_business_transaction_core` for service-owned business-operation,
idempotency, and transactional-outbox infrastructure. Voucher and organization
tables follow in later slices. P8-S22 advances the current head to
`2508_eos_operation_name_compatibility`, aligning persisted operation-name
constraints with canonical dotted names such as `FINANCE.CREATE_VOUCHER_DRAFT`.

```bash
python scripts/db/run_migrations.py --service nex-eos --profile dev
python scripts/db/run_migrations.py --service nex-eos --profile test
```

The protected test reset helper preserves `schema_migrations` and truncates
only public tables with the `eos_` prefix after exact URL, database, role, and
confirmation validation.
