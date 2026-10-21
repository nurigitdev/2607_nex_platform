# NeX-EOS

NeX-EOS is the service-owned system of record for the minimum enterprise
operations domain introduced by P8. P8-S07 provides only the executable
service, configuration, readiness, build identity, and service-trust shell.

No business domain route, migration, persistence runtime, or mutation is
activated in this Slice. Database bootstrap begins in P8-S08.

## Runtime

```bash
python scripts/dev/run_service.py nex-eos
```

The default port is `8107`. Database readiness uses
`NEX_EOS_DATABASE_URL`; P8-S08 will add the `NEX_EOS_TEST_DATABASE_URL`
migration profile.
