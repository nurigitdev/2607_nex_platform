# W80-CA00G.0 Owner-Scoped Agent Execution Progress Projection Foundation

## Status

IMPLEMENTED / SLICE GATE PASSED

## Purpose

Provide a durable, owner-scoped diagnostic progress stream while the existing
synchronous Chat admission and asynchronous Agent execution paths continue to
run unchanged. This Slice does not introduce a second execution state machine,
business SoR, or Web-only fabricated progress.

## Contract

1. AE Web creates the UUID `interaction_id` before the Chat request.
2. Progress polling starts before awaiting Chat POST completion.
3. IA semantic stages, WC delegation/claim, assigned Agent semantic stages,
   runtime admission, result publication, and interaction terminal boundaries
   append deterministic activity events.
4. `GET /api/v1/chat/interactions/{interaction_id}/execution-progress` resolves
   only an authenticated browser owner's interaction and Workspace.
5. `after_sequence` is an ordered cursor; replay returns stable event IDs and
   does not duplicate lines.
6. The Web appends user-facing Korean messages and stops polling when the
   projection is terminal or the enclosing request ends.
7. The initial diagnostic view prefixes lines with the event time in
   `Asia/Seoul`. The prefix is derived from `occurred_at` and is not persisted as
   event identity.

## Persistence and Privacy

- Existing `ae_workspace_activities` is reused with activity type
  `agent.execution.progress`.
- Event IDs are UUIDv5 values over Workspace, interaction, event code, and
  source boundary.
- No database migration or parallel progress table is added.
- Raw prompts, semantic candidates, plans, executable plans, result payloads,
  and private business content are excluded.
- The ordered projection is admitted only through browser user ownership; a
  service principal cannot enumerate user progress.

## Product Boundaries

- Progress events are append-only observations, not commands and not the Agent
  execution SoR.
- Missing progress storage fails the progress endpoint closed and does not
  weaken Chat, WC, OA, EOS, or Runtime authority.
- A retry of the same semantic boundary is deduplicated by deterministic event
  identity. A genuinely different source boundary may append another event.
- Existing interaction/result activities are projected for terminal closure so
  polling does not require a duplicate finalization path.

## Implementation

- AE API: `interaction_execution_progress.py`, Chat semantic admission,
  background Agent planning, and installed route registration.
- Contract: JSON Schema and OpenAPI projection/route admission.
- AE Web: fetch/mock client, installed client registry, concurrent polling,
  append-only Workspace progress list, and diagnostic time prefix.
- Compatibility: `build_workspace_activity()` accepts an optional explicit
  activity ID while preserving the previous default identity behavior.

## Verification

- Backend focused contract, replay, cursor, SQL owner scope, failure isolation,
  and terminal tests: `11 passed`; module statement/branch `100% / 100%` in the
  canonical gate.
- Impacted AE Chat/background/runtime regression: `109 passed`.
- AE Web focused progress/workspace tests: `24 passed`.
- AE Web TypeScript check and production build: passed. The existing bundle-size
  and dependency module-directive warnings remain non-blocking.
- AE API compile and focused Ruff checks: passed.
- Canonical AE Slice Gate: `7,124 passed`, `55 skipped`; statement `96.44%`,
  branch `94.64%`.
- AE product coverage: statement `97.03%`, branch `94.92%`.
- Contract validation: `280 schemas`, `322 examples`, `260 negative examples`,
  `10 OpenAPI`.
- Golden journey transition audit, demo-product dependency audit, and AE
  coverage-ownership audit: passed with no findings or conflicts.

Machine-readable evidence:

```text
reports/quality/mybee-w80-ca00g0-ae-slice-gate.json
reports/coverage/mybee-w80-ca00g0-ae-slice-gate.report_ae_coverage_ownership.json
```

The installed PostgreSQL, remote-provider, and Playwright proof is closed by
[`W80-CA00G.0A`](mybee_phase1_w80_ca00g0a_protected_live_progress_acceptance.md).
It accepted both Journal and independent Allocation journeys with `27` durable
events, `12` progress screenshots, restart recovery, and zero residue.

## Deferred UX

This Slice deliberately renders append-only diagnostic lines. Replacing prior
messages in place, collapsing stages, exposing elapsed durations, and showing a
ChatGPT-style single live status are later UX refinements. They must continue to
derive from the same durable event projection rather than browser timers.
