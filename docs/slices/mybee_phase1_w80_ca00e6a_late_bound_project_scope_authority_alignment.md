# W80-CA00E.6A Late-Bound Project Scope Authority Alignment

## Outcome

W80-CA00E.6A closes the semantic handoff conflict exposed by the first
W80-CA00E.6 protected installed acceptance. An immutable WorkIntent that did
not name a Project at INTENT admission may now hand off the Project scope that
the same execution later resolved from EOS authority while building its
AgentContext.

The correction does not mutate WorkIntent, widen the semantic handoff schema,
or permit a receiving Agent to select a Project by itself.

## Failure Evidence

The first protected W80-CA00E.6 run delivered the WC claim handoff to AE five
times. Every request returned HTTP `409` with
`ae.semantic_reuse_deny_conflict` and was eventually dead-lettered.

The persisted evidence showed:

- the IA WorkIntent had `project_ref=null` because Project identity was not
  known at immutable INTENT admission;
- the later hash-bound AgentContext resolved one authoritative EOS Project;
- the semantic handoff carried that resolved Project scope;
- WorkIntent, INTENT candidate/evidence, and CONTEXT candidate/evidence hashes
  otherwise matched exactly.

The conflict was therefore a temporal authority-alignment gap, not evidence
tampering or a cross-Project request.

## Implemented Boundary

- Added an AgentContext repository query that resolves the latest generation
  for one tenant and execution at or before the immutable handoff timestamp.
- Wired that repository into the installed claim-handoff admission factory.
- Preserved an explicit WorkIntent Project as authoritative. A different
  handoff Project remains `SCOPE_MISMATCH` and cannot be overridden by a later
  context.
- When WorkIntent Project is absent, requires a hash-valid parent AgentContext
  with matching execution, tenant, owner, Agent type, WorkIntent lineage, and
  interaction lineage.
- Requires the parent context to contain a matching EOS-resolved `PROJECT`
  entity and no context conflicts.
- Keeps missing context, malformed entities, identity mismatch, interaction
  mismatch, hash tamper, ambiguity, and cross-Project data fail-closed.

## Persistence And Compatibility

- no database migration;
- no public API or semantic handoff schema change;
- no WorkIntent mutation;
- no Project inference from candidate order, confidence, tenant defaults, or
  scenario fixtures;
- existing explicit-Project behavior remains unchanged;
- historical handoffs without a resolvable authoritative context remain
  denied.

## Verification

- expanded semantic handoff, AgentContext, P7 delegation, and background
  runtime regression: `159 passed`;
- focused late-bound scope and repository regression after branch hardening:
  `98 passed`;
- canonical AE Slice Gate: `6998 passed`, `53 skipped`;
- AE statement coverage: `96.46%`;
- AE branch coverage: `94.72%`;
- AE product coverage: statement `97.07%`, branch `95.01%`;
- contract, Golden Journey transition, demo/product dependency, and AE
  ownership audits: pass;
- Ruff and `git diff --check`: pass.

Machine-readable coverage evidence:

```text
reports/quality/slice-nex-ae-api.coverage.json
reports/coverage/mybee-w70-ga-ret-02a-ae-ownership-hotspots.json
```

## Protected Continuation

W80-CA00E.6 must now rebuild the canonical nine-image release set and AE
Product Runtime image from this clean exact head, then replay the protected
actual-PostgreSQL and live-provider journey. Acceptance requires the WC claim
handoff to pass this boundary while retaining the expected semantic stage
counts, provider-call reduction, authenticated Playwright evidence, and zero
residue. Any later failure is a separate typed boundary and must not weaken
this authority rule.
