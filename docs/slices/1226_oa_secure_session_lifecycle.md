# Slice 1226: OA secure session lifecycle

## Result

- Session handles now use 32 random bytes through `secrets.token_urlsafe` and
  are not derived from tenant, subject, or timestamps.
- Sessions maintain a 30-minute sliding idle lease while preserving the
  existing absolute TTL and one-day maximum.
- Introspection refreshes active idle leases transactionally. It persists
  `EXPIRED` when the idle or absolute boundary has passed.
- Internal lease timestamps are not added to the browser session projection,
  preserving the existing public contract and reducing disclosure.
- Checkpoint Gate is required at this Slice before credential rotation work.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_secure_session_lifecycle.py \
  --coverage-target services/nex-oa/nex_oa/sessions.py \
  --coverage-target scripts/smoke/run_oa_secure_session_lifecycle.py \
  --smoke scripts/smoke/run_oa_secure_session_lifecycle.py

./scripts/quality/run_checkpoint_gate.sh
```

Observed results:

- Slice Gate: `264 passed, 1 skipped`; statement `97.95%`; branch `95.58%`.
- Checkpoint Gate: `9,376 passed, 12 skipped`; statement `98.80%`; branch
  `97.01%`; contract validation `132/190/160`, OpenAPI `7`.
