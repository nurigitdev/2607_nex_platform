# W80-CA00E.1 Semantic Handoff Inventory and v3 Contract

## Outcome

W80-CA00E.1 is complete. AE now owns a provider-neutral, hash-bound semantic
handoff projection for admitted INTENT and CONTEXT evidence. WC can transport
the projection through DelegationSpec v1.3 and claimed planning source v3, but
cannot create or upgrade AE semantic evidence.

## Contract Boundary

- `ae.semantic_handoff.v1` records tenant, owner, parent execution,
  WorkIntent, candidate/evidence hashes, source lineage, and creation time.
- Raw prompts, private candidate payloads, conversation content, and binary
  attachments are not copied into the handoff.
- DelegationSpec v1.3 requires a valid semantic handoff and checks tenant and
  parent-execution lineage.
- Claimed planning source v3 preserves delegation identity and semantic
  handoff while v1 and v2 remain accepted under their existing contracts.
- AE validates the same v3 source at both WorkIntent and AgentExecution
  admission boundaries.
- No relational migration was introduced. Existing WorkIntent, AgentContext,
  and semantic-candidate repositories remain the authoritative resolvers for
  the referenced identities.

## Product Decisions

- WC is a transport authority, not a semantic-evidence authority.
- The handoff contains references and hashes only; target-Agent context is not
  reused by this Slice.
- No capability, tenant, Project count, ratio, M1 value, or fixture fallback is
  embedded in product code.
- Evidence reuse decisions and target-Agent context rebuilding remain assigned
  to W80-CA00E.2 and W80-CA00E.3.

## Verification

- New AE/WC contract tests: `12 passed`
- Focused affected regression: `151 passed`
- Contract validation: `277 schemas`, `322 examples`, `260 negative examples`,
  `10 OpenAPI`
- WC Slice Gate: `752 passed`, `27 skipped`; statement `97.37%`, branch
  `94.62%`
- AE Slice Gate: `6934 passed`, `53 skipped`; statement `96.43%`, branch
  `94.65%`
- AE active-product coverage: statement `97.04%`, branch `94.94%`
- `git diff --check` and Python compilation: pass

Machine-readable coverage evidence:

```text
reports/quality/mybee-w80-ca00e1-ae-slice-gate.json
reports/quality/mybee-w80-ca00e1-wc-slice-gate.json
```

## Next Boundary

W80-CA00E.2 may add the fail-closed evidence reuse evaluator. It must resolve
and compare the referenced authoritative records before returning a reuse
decision; this Slice does not activate runtime reuse by itself.
