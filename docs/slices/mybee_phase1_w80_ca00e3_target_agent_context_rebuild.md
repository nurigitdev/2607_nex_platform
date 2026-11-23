# W80-CA00E.3 Target-Agent Context Rebuild

## Outcome

W80-CA00E.3 is complete. Installed AE delegation now emits a v1.3 semantic
handoff from authoritative parent WorkIntent and INTENT/CONTEXT evidence, and
claimed target-Agent planning evaluates that handoff before rebuilding a fresh
target WorkIntent and AgentContext. Parent AgentContext data is never copied.

## Implemented Boundary

- Added authoritative execution-scoped WorkIntent and semantic-stage evidence
  lookups without a new table or migration.
- Added an installed semantic handoff projection source that emits v1.3 only
  when parent WorkIntent, INTENT evidence, and CONTEXT evidence are complete.
  Partial lineage fails closed instead of silently downgrading.
- Wired the provider-neutral reuse evaluator into claimed background planning.
- Activated `REUSE_INTENT_REBUILD_CONTEXT` so admitted INTENT and CONTEXT
  candidates bypass duplicate provider calls while PLAN remains target-role
  specific.
- Activated `REUSE_INTENT_AUGMENT_CONTEXT` so admitted INTENT is preserved and
  the target Agent regenerates CONTEXT and PLAN.
- Preserved `FULL_SEMANTIC_REPLAN` as the existing three-stage safe fallback.
- Added a default policy matrix for admitted CA, PA, and EA work classes. The
  matrix contains no tenant, Project, M1, or fixed business values.

## Authority and Privacy Rules

- The target WorkIntent uses the claimed target execution identity.
- The target AgentContext is rebuilt through the existing claimed-work context
  resolver using current WC claim and authority data.
- Parent AgentContext manifests, authority snapshots, and private payloads are
  not copied into the target execution.
- Cross-scope or tampered decisions and evidence fail closed before provider
  invocation.
- Reused semantic evidence remains input evidence and never grants authority.

## Verification

- Focused affected regression: `232 passed`
- Changed-module focused coverage: `203 passed`; target modules at `99%`
- AE Slice Gate: `6970 passed`, `53 skipped`; statement `96.45%`, branch
  `94.70%`
- AE product coverage: statement `97.06%`, branch `94.99%`
- Contract validation: `277 schemas`, `322 examples`, `260 negative examples`,
  `10 OpenAPI`
- Ruff and `git diff --check`: pass

Machine-readable evidence:

```text
reports/quality/mybee-w80-ca00e3-ae-slice-gate.json
```

## Checkpoint #1

Checkpoint #1 validates the combined W80-CA00E.1 through `.3` contract,
evaluator, installed handoff producer, and fresh target-context rebuild before
role-scoped planning profiles are introduced.

- Repository checkpoint: `23236 passed`, `192 skipped`
- Statement coverage: `98.24%` (threshold `95.00%`)
- Branch coverage: `96.71%` (threshold `94.00%`)
- Contract, transition, and product-dependency audits: pass

Machine-readable evidence:

```text
reports/quality/mybee-w80-ca00e3-checkpoint-gate.json
```

## Next Boundary

W80-CA00E.4 may replace capability-only planning-profile selection with the
four-part key `capability + source type + agent type + planning purpose`.
Compatibility behavior must be explicit; silent role or purpose fallback is
not admitted.
