# NeX Work Asset

Run the service shell from the repository root:

```bash
python scripts/dev/run_service.py nex-wa
```

The default endpoint is `http://127.0.0.1:8108`. Runtime persistence uses
`NEX_WA_DATABASE_URL`; migration and protected test work use
`NEX_WA_TEST_DATABASE_URL`.

P9-S01 through P9-S10 activate the owner-local core foundation:

- immutable, tenant-scoped WorkEvidence;
- versioned WorkAsset and evidence bindings;
- local atomic evidence/asset admission;
- protected, idempotent evidence intake through the shared JobQueue;
- bounded source-adapter and consumer composition;
- fenced stale-RUNNING recovery using worker heartbeats;
- protected exact WorkEvidence, WorkAsset, and evidence-lineage reads.

Consumer storage readiness can be checked without claiming work:

```bash
python -m nex_wa.consumer_main --check
```

Protected read scopes are `work:evidence:read` for exact WorkAsset and
`work:evidence:detail:read` in addition for exact WorkEvidence and lineage.
P9-S10 does not claim AE/WC source integration; those adapters activate in
later P9 slices.
