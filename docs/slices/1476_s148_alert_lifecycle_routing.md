# Slice 1476: S148 Alert Lifecycle and Routing

## Outcome

- Added alert debounce, deterministic grouping, severity escalation,
  acknowledgement, suppression expiry, recovery, and reopen behavior.
- Kept alert detection independent from delivery routing and transport receipt.
- Added explicit local-only, private-network, and internet-connected routing.
- Kept local intents available while marking an unconfigured required external
  route `BLOCKED` and `EXTERNAL_NOT_ACTIVATED`.
- Added metadata-only payload and idempotency hashes without endpoint or
  private-content fields.

Slice 1477 persists alert, outbox, and delivery-attempt state and proves
restart-safe claim recovery.

## Verification

- Focused regression: `24 passed`; alert lifecycle/routing and smoke statement
  and branch coverage `100.00%`.
- AG Slice Gate: `2,519 passed`; statement coverage `98.90%`, branch coverage
  `96.56%`.
- Contract validation: `168` schemas, `230` examples, `198` negative examples,
  and `7` OpenAPI documents.
- Alert routing smoke: `8/8` checks, three profile decisions, four intents, one
  honestly blocked required external route, `next=1477`.
