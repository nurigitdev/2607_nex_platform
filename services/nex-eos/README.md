# NeX-EOS

NeX-EOS is the service-owned system of record for the minimum enterprise
operations domain introduced by P8. P8-S07 provides only the executable
service, configuration, readiness, build identity, and service-trust shell.

No business domain route or mutation is active. P8-S08 adds the migration
baseline and pooled transaction runtime; business tables begin in P8-S09.

## Runtime

```bash
python scripts/dev/run_service.py nex-eos
```

The default port is `8107`. Database readiness and the pooled runtime use
`NEX_EOS_DATABASE_URL`; migrations support both `NEX_EOS_DATABASE_URL` and
`NEX_EOS_TEST_DATABASE_URL` profiles.
