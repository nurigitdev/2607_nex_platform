# NeX MyBee W80-CA00B PA WorkResult to IA Business Result Propagation Closure v1.0

**Status:** CLOSED / EXACT-HEAD LIVE ACCEPTED

**Predecessor:** W80-CA00A

**Database migration:** None

**Public business API change:** None

## 1. Purpose

W80-CA00A proved that the installed M1 product flow completed its PA-side EOS
voucher, journal, allocation, and P&L operations while the originating IA
AgentResult exposed only a generic success card. The PA AgentResult contained
the admitted business summary, but the WC `WORK_RESULT_SUBMITTED` event carried
only technical outcome and lineage identifiers. The delegated IA StepResult
therefore could not preserve the product result through normal plan
finalization.

This amendment closes that propagation gap without adding a scenario fixture,
new table, or alternate result pipeline.

## 2. Canonical Decisions

1. PA remains the authority for its finalized AgentResult.
2. WC remains the authority for accepted WorkResult and durable event outbox.
3. The existing WorkResult event gains one optional, backward-compatible
   business-result projection.
4. The projection contains only the admitted business summary, business object
   references, external references, source AgentResult hash, and its own
   semantic hash.
5. Raw prompt, plan, arbitrary structured result, attachment content, and
   private evidence are forbidden from the projection.
6. AE validates projection integrity and the existing business-summary domain
   contract before creating the delegated StepResult. A voucher summary keeps
   its explicit primary operation identity, while a generic product result may
   carry multiple authoritative business-operation lineage references.
7. Existing IA plan finalization remains the only AgentResult assembly path.
8. IA finalization promotes every admitted EOS business-operation lineage
   reference into `business_refs`; it does not invent a primary operation for a
   multi-operation result.
9. Legacy WorkResult events without the projection remain processable.

## 3. Runtime Flow

```text
PA AgentResult
  -> AE WC WorkResult publisher
  -> WC accepted WorkResult / durable outbox
  -> hash-bound safe business projection
  -> AE external-event inbox / generalized resume
  -> delegated StepResult
  -> existing IA plan finalization
  -> owner-scoped WorkspaceResult projection
  -> typed voucher or Project-allocation result card
```

## 4. Integrity and Authorization

- WC constructs the projection only from an accepted `AGENT_RESULT` WorkResult.
- `source_agent_result_hash` binds the projection to PA result authority.
- `projection_hash` detects outbox, transport, and inbox payload drift.
- AE revalidates the business summary, requires the primary voucher operation
  to be present when a voucher summary declares one, and preserves additional
  product lineage without collapsing it to a single operation.
- Existing service-token, tenant, WorkItem, Claim, Assignment, wait, event, and
  replay checks remain unchanged.

## 5. Persistence Decision

The existing `wc_event_outbox.event_payload` and
`ae_external_event_inbox.event_payload` JSON structures already preserve the
complete event. The additive projection fits these stores, so no migration is
authorized. The existing WorkResult, generalized wait/event, RuntimeJob,
StepResult, AgentResult, and ResultDelivery stores are reused.

## 6. Acceptance

1. canonical projection build/validation and tamper rejection;
2. WC event projection with no arbitrary PA structured-result leakage;
3. AE event admission, replay compatibility, and lineage mismatch rejection;
4. delegated StepResult restoration of summary, optional primary operation,
   and complete multi-operation product lineage;
5. existing IA plan finalization producing the owner-safe summary;
6. focused AE/WC regression and coverage gates;
7. actual PostgreSQL protected smoke;
8. exact-head installed M1 journey showing both Project-allocation result cards
   and the recovered result after restart;
9. W80-CA00A screen manifest integrity and zero-residue cleanup.

## 7. Decision

```text
PARALLEL RESULT PIPELINE         = FORBIDDEN
SCENARIO FIXTURE                 = FORBIDDEN
SAFE BUSINESS PROJECTION        = REQUIRED
SOURCE AND PROJECTION HASHES     = REQUIRED
LEGACY EVENT COMPATIBILITY       = REQUIRED
DATABASE MIGRATION               = NONE
PUBLIC BUSINESS API CHANGE       = NONE
```

## 8. Implementation Evidence

- focused regression before the exact-head replay: `112 passed`, with only the
  separately executed protected PostgreSQL case skipped;
- exact failing-shape regression after the first live replay: `41 passed`,
  covering a `FINANCE.PROJECT_ALLOCATION` summary with two EOS business
  operations and final AgentResult promotion of both references;
- actual `nex_ae_test` and `nex_wc_test` PostgreSQL smoke: `28/28` checks,
  one accepted WorkResult, and one durable resume RuntimeJob;
- AE Slice Gate after the multi-operation correction: `6,925 passed`, `53`
  explicit protected skips, statement `96.45%`, branch `94.68%`;
- WC Slice Gate: `748 passed`, `27` explicit protected skips, statement
  `97.48%`, branch `94.81%`;
- shared-runtime contract tests: `15 passed`, new projection module statement
  and branch coverage `100%`;
- shared-runtime Slice Gate: `2,166 passed`, one protected skip, aggregate
  statement `87.12%`, branch `84.24%`, improving its prior aggregate baseline;
- schema, example, negative-example, OpenAPI, transition, and product-dependency
  audits passed in all applicable gates.

The first exact-head installed replay proved PA finalization, WC projection,
durable AE inbox admission, and resume-job creation, then failed closed at IA
resume because the consumer incorrectly treated two valid EOS operation
lineages as conflicting. It completed zero-residue cleanup. The implementation
now preserves multi-operation lineage and retains a primary operation only when
the typed summary identifies one.

## 9. Exact-Head Live Closure

- accepted source revision: `102390b5`;
- canonical release set: `9/9` OCI images, `9/9` non-root checks, `12`
  packaged background-process checks, registry push disabled;
- product runtime: NSL `0.2.1`, generalized M1 release, historical scenario
  dependency absent;
- actual infrastructure: Docker Compose, OpenBao, RustFS, OA, AG, AE, CX, MO,
  WC, EOS, WA, and all installed product workers;
- actual PostgreSQL: eight isolated service databases, `210` migrations, all
  cleanup receipts passing with zero residue;
- actual provider: `Qwen3.5-9B` through deployment
  `dgx-qwen3-5-9b-9111`, immutable revision
  `hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a`;
- business journey: two non-identical requests, six approval decisions, two
  immutable journals, two allocation batches, four allocation lines, four P&L
  projections, two AgentResults, and two acknowledged result deliveries;
- browser evidence: `15` main captures plus `2` restart captures, including the
  restored Project-allocation result with two user-facing Project codes;
- restart invariants: result hash stable, business references stable, and both
  journals, allocation batches, and AgentResults retained;
- diagnostic evidence: raw prompt, AgentPlan, and ExecutablePlan retained in
  the protected DEBUG bundle while configured secrets remained forbidden.

The live sequence found two product defects before closure. The first treated a
valid multi-operation Project-allocation result as if it required one primary
EOS operation. The second dropped the admitted `interaction_id` while the
authentication-first shell restored an existing session. Both were corrected
in generic product paths. No M1 value, tenant dictionary, fixed Project count,
or scenario fixture was introduced.

```text
LIVE ACCEPTANCE                 = PASS
AUTHORITATIVE RESTART RECOVERY = PASS
SCREEN EVIDENCE                = PASS
ZERO RESIDUE                   = PASS
W80-CA00B                      = CLOSED
```
