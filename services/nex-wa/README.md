# NeX Work Asset

Run the service shell from the repository root:

```bash
python scripts/dev/run_service.py nex-wa
```

The default endpoint is `http://127.0.0.1:8108`. Runtime persistence uses
`NEX_WA_DATABASE_URL`; migration and protected test work use
`NEX_WA_TEST_DATABASE_URL`.

P9-S02 adds the owner-local migration ledger, shared JobQueue, worker heartbeat,
and separate API/worker connection-pool runtime. WorkEvidence and WorkAsset
behavior remains disabled until its owning slices.

P9-S01 registers only the service and process identities. WorkEvidence,
WorkAsset, intake, and consumer behavior activate in later owning slices.
