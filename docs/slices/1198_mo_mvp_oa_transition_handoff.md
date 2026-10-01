# Slice 1198: MO MVP to OA transition handoff

## Goal

Create an immutable, privacy-safe NeX-MO-to-NeX-OA transition package without
moving MO records or granting OA direct access to the MO database.

## Two-Stage Handoff

1. Build and verify a `SEALED` manifest containing relative asset paths and
   hashes, the protected acceptance read model, service trust requirements,
   stable subject requirements, model aliases, ownership boundaries, and the
   S121 OA entrypoint.
2. Bind that verified manifest to an `ACCEPTED` and `READY_FOR_OA` report,
   producing a hashed `BOUND` attestation.

Missing assets, modified hashes, wrong service identity, blocked acceptance,
invalid acceptance IDs, direct MO database access, privacy flag drift, or naive
timestamps fail closed.

## Ownership Boundary

- MO retains provider catalog, alias, telemetry, runtime, and acceptance data.
- OA retains identity, credential, membership, and session data.
- OA reads only the protected redacted MO acceptance projection and never
  queries `nex_mo_test` or a production MO database directly.
- The handoff contains no provider telemetry payload, endpoint, API key,
  database URL, credential, user identity payload, or local absolute path.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_mo_mvp_oa_transition_handoff.py
./.venv/bin/python scripts/smoke/run_mo_mvp_oa_transition_handoff.py --summary
```

No table or migration is added. Next Slice: `1199`.

## Result

- Slice Gate: `1036 passed, 5 skipped`; statement coverage `99.87%`, branch
  coverage `99.56%`.
- Handoff module and smoke scope: statement and branch coverage `100%/100%`.
- Evidence: assets `11`, privacy flags `5`, manifest `SEALED`, attestation
  `BOUND`, next Slice `1199`.
