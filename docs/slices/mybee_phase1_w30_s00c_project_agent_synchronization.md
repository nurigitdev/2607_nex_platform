# MyBee Phase 1 W30-S00C Project Agent Synchronization

## Status

- Slice: `W30-S00C`
- Status: implemented and verified
- Design authority: `W30-CA02`
- AE migration: `2515_ae_project_agent_lifecycle.sql`
- Remote model providers: not required

## Boundary Decision

Project approval completion and Project Agent creation are one exceptional
cross-service lifecycle synchronization. EOS remains the Project system of
record and AE remains the Project Agent system of record. The synchronization
does not create a second WC delegation after WC has already completed the
Project committee approval.

The canonical flow is:

```text
WC final approval
  -> EOS Project + lifecycle outbox in one transaction
  -> signed EOS-to-AE lifecycle delivery
  -> idempotent AE inbox + Project Agent synchronization
  -> AE receipt
  -> EOS agent_sync_state=IN_SYNC
```

The originating WC work item and approval decision remain bound as correlation
and causation lineage. WC is not treated as the owner of the EOS-to-AE
lifecycle event.

## Persistence And Runtime

EOS appends deterministic `PROJECT_LIFECYCLE_CHANGED` events through the
existing business-operation, idempotency, and outbox tables. Initial Project
materialization and later lifecycle transitions set `agent_sync_state=PENDING`.
Only a matching AE receipt for the exact Project version and state changes the
EOS Project to `IN_SYNC`.

AE migration 2515 adds:

- `ae_project_lifecycle_inbox`, the immutable event and replay ledger;
- `ae_project_agent_sync`, the latest Project-to-PA lifecycle projection.

The existing `ae_agent_identity` table remains the Project Agent identity
system of record. One deterministic PA is reused for the entire Project
lifecycle:

| Project state | PA status | Capability mode |
| --- | --- | --- |
| `ACTIVE` | `ACTIVE` | `ORDINARY` |
| `INACTIVE` | `SUSPENDED` | `SUSPENDED` |
| `CLOSING` | `ACTIVE` | `CLOSURE` |
| `CLOSED` | `RETIRED` | `RETIRED` |

Skipped versions, invalid transitions, Project-code drift, profile-policy
drift, duplicate PA identities, and attempts to reactivate a retired PA fail
closed. Exact event replay returns the original receipt without creating a new
identity or inbox row.

The packaged profile policy is admitted by semantic hash at startup. Canonical
deployment binds EOS and AE to
`policy://nex-platform/project-agent-lifecycle/v1`; missing or drifted policy
configuration prevents lifecycle processing.

## Contract And Security

AE exposes the signed internal route:

```text
POST /internal/v1/project-lifecycle-events
```

Only the `nex-eos` service principal is admitted. Generic EOS outbox events
continue to use the payload-free metadata route; only Project lifecycle events
carry the strictly validated lifecycle payload to the dedicated route.

## Verification

- Focused lifecycle, S00B regression, contract, and observability suite:
  `98 passed, 2 skipped` before the final branch-hardening additions.
- Lifecycle-focused suite after branch hardening: `30 passed, 1 skipped`.
- Actual `nex_eos_test` and `nex_ae_test` protected smoke: passed.
  - verified database identities as `nex_eos_test` / `nex_eos_user` and
    `nex_ae_test` / `nex_ae_user`;
  - applied EOS migrations through 2532 and AE migrations through 2515 in
    isolated schemas;
  - delivered five signed lifecycle events through the EOS-to-AE HTTP
    contract;
  - retained one PA identity through ACTIVE, INACTIVE, reactivation, CLOSING,
    and CLOSED;
  - verified final EOS `agent_sync_state=IN_SYNC`, PA `RETIRED`, no pending
    outbox rows, and zero schema residue.
- NeX-AE Slice Gate: `5836 passed, 46 skipped`.
  - statement coverage: `96.99%`;
  - branch coverage: `95.19%`.
- NeX-EOS Slice Gate: `1332 passed, 43 skipped`.
  - statement coverage: `96.35%`;
  - branch coverage: `94.27%`.
- Contract validation, Golden Journey transition audit, and
  demo-to-product dependency audit: passed for both service gates.

Machine-readable Gate evidence:

- `reports/quality/w30-s00c-ae.coverage.json`
- `reports/quality/w30-s00c-eos.coverage.json`

## Next Entry

W30-S00D may close the cross-service Project-code and document/voucher
integrity boundary. It must consume this synchronization contract and must not
introduce a second Project Agent creation path through WC delegation.
