# P9-S16: AE Post-Completion Notification

## Scope

NeX-AE now sends a reference-only, best-effort notification to NeX-WA after
the authoritative source transaction has committed.

- IA requires `AgentResult SUCCEEDED|PARTIAL`, `WORKSPACE_RESULT
  ACKNOWLEDGED`, and `AgentExecution SUCCEEDED`.
- CA/PA/EA requires the same result/execution states and `WC_WORK_RESULT
  ACKNOWLEDGED`.
- Artifact intake requires an exact `READY` Artifact version.
- Notification uses signed `nex-ae-api -> nex-wa` service trust and
  `POST /internal/v1/evidence-intake`.

Notification failure never rolls back workspace publication, WC publication,
or Artifact readiness. Restart/replay may resend the same semantic request;
the existing WA deterministic intake identity reuses the original Job and
therefore does not create duplicate evidence.

## Persistence

No migration is introduced. AE source state remains authoritative and WA's
existing durable JobQueue provides notification idempotency. The outbound token
is resolved through `NEX_AE_TO_WA_SERVICE_TOKEN` for signed profiles; the test
profile retains the existing mock-token behavior.

## Verification

Tests cover pre-ACK suppression, post-ACK IA and background admission,
reference-only Artifact notification, timeout isolation, typed source failure,
duplicate/restart semantic identity, response tampering, and HTTP transport
failure.

- Focused regression: `66 passed`
- NeX-AE Slice Gate: `5,591 passed, 44 skipped`
- NeX-AE aggregate coverage: statement `97%`, branch `97%`
- New notifier coverage: statement `100%`, branch `100%`
- Ruff and repository diff hygiene: passed

Protected PostgreSQL integration remains assigned to the P9-CA03 gate after
P9-S20, where AE, WC, OA, EOS, and WA are exercised together.
