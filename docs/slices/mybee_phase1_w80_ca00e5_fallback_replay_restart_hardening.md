# W80-CA00E.5 Fallback, Replay, and Restart Hardening

## Outcome

W80-CA00E.5 is complete. Cross-Agent semantic reuse now produces a stable
decision across retry and process restart, while preserving the full semantic
pipeline as the fail-safe fallback.

## Implemented Boundary

- Anchored semantic-reuse evaluation to the durable target AgentExecution
  `received_at` value instead of process-local wall-clock time.
- Kept the existing AgentExecution, semantic evidence, and stage projection
  stores authoritative; no replay-only relational storage was introduced.
- Preserved target-Agent context reconstruction and fresh authority admission
  before planning.
- Fixed the admitted provider-call matrix:
  - `REUSE_INTENT_REBUILD_CONTEXT`: PLAN only, one provider stage;
  - `REUSE_INTENT_AUGMENT_CONTEXT`: CONTEXT and PLAN, two provider stages;
  - `FULL_SEMANTIC_REPLAN`: INTENT, CONTEXT, and PLAN, three provider stages;
  - exact durable replay: zero provider stages.
- Confirmed an exact replay returns the same ExecutablePlan identity and hash
  with all three semantic stages resumed from durable evidence.
- Confirmed repeated background planning reconstructs the same semantic-reuse
  decision from the same handoff and target execution.

## Failure and Recovery Rules

- Missing, stale, incompatible, unauthorized, or tampered evidence cannot
  bypass the existing full-pipeline fallback and fail-closed admission rules.
- A restart cannot change the decision merely because wall-clock time moved;
  evidence freshness is evaluated against the original durable execution
  admission time.
- Event redelivery and ACK loss reuse existing execution/evidence identities;
  they do not authorize duplicate provider work.
- Provider-call reduction is an optimization only. Target authority, context,
  profile, compile, and executable-plan admission remain mandatory.

## Verification

- Focused affected regression: `99 passed`
- AE Slice Gate: `6981 passed`, `53 skipped`; statement `96.46%`, branch
  `94.71%`
- AE product coverage: statement `97.07%`, branch `95.00%`
- Contract validation: `277 schemas`, `322 examples`, `260 negative examples`,
  `10 OpenAPI`
- Checkpoint #2: `23250 passed`, `192 skipped`; statement `98.25%`, branch
  `96.72%`
- Checkpoint contract, Golden Journey transition, and demo/product dependency
  audits: pass
- Ruff and `git diff --check`: pass

Machine-readable evidence:

```text
reports/quality/mybee-w80-ca00e5-ae-slice-gate.json
reports/quality/mybee-w80-ca00e5-checkpoint-gate.json
```

## Persistence

No database migration or public API field was added. The durable
AgentExecution admission timestamp and existing semantic evidence are
sufficient to reproduce the decision deterministically.

## Next Boundary

W80-CA00E.6 must run the generalized prompt/work-class matrix, actual
AE/WC/OA/EOS PostgreSQL protected checks, live generation confirmation,
installed replay, coverage gates, and the Repository Full Gate. Live provider
execution requires an explicit DGX-idle confirmation before it starts.
