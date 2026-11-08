# UXM-CA01: Source-Backed Entry Baseline and Design Asset Admission Closure

**Status:** PASS / CLOSED
**Program:** NeX Platform v2.1
**Product:** NeX-AE Web / Assistant Workspace
**Branch:** `transition/ae-web-uiux-modernization`
**Branch Point:** `c2c03b20e22691cc1984f044e0cacd5d698f9bd3`
**Branch Point Message:** `docs(uiux): add modernization design baseline`
**Closure Date:** 2026-11-08

---

## 1. Purpose

This closure reconciles the frozen UI/UX PAD and Slice Plan with the actual
repository immediately before implementation. It closes five entry gaps:

1. Admit the missing design token inputs with immutable hashes.
2. Reconcile the implementation branch point with current `master`.
3. Repair canonical document identity and reading order.
4. Freeze one unambiguous quality-gate cadence.
5. Activate a user-facing UX state foundation before Approval UI work.

No product code, database schema, public API, or production route is changed by
this closure.

## 2. Source-Backed Entry Baseline

The original PAD recorded source audit commit `4dcecb6c`. The implementation
branch is based on later master commit `c2c03b20`. Changes between these points
did not modify `apps/nex-ae-web`, so the PAD's architecture findings remain
valid while its implementation provenance is superseded by this record.

Current AE Web inventory:

```text
src/main.js physical lines       = 4,014
src/styles.css physical lines    = 1,966
top-level src files              = 66
src files including locales      = 67
Node test files                  = 94
Web scripts                      = 26
runtime dependencies             = 0
dev dependency                   = @playwright/test
local Node                       = v20.19.2
local npm                        = 10.8.2
OCI runtime baseline             = Node 22 bookworm slim
```

The source-backed findings that motivate modernization are still present:

```text
index.html default client mode   = mock
fetch clients default            = disabled
main.js direct service ports     = 8101 through 8105
main.js direct localhost health  = present
same-origin /ae-api proxy        = present in serve.mjs
```

Decision:

```text
CURRENT_SOURCE_AUDIT_REMAINS_VALID
IMPLEMENTATION_PROVENANCE_MOVES_TO_C2C03B20
```

## 3. Design Asset Admission

The user-provided design baseline files are admitted under canonical names:

```text
docs/transition/UIUX/tokens.json
docs/transition/UIUX/tokens.css
```

The misspelled intake names `tockens.json` and `tockens.css` are not canonical
and must not be referenced by implementation or automation.

Immutable admission hashes:

```text
tokens.json sha256 = c9b0437f12c2757c9085cd2b9866a71accfae5495bfa78638bdff5c5882897ad
tokens.css  sha256 = 3a90259fdecc2d142836d010ac63fd60c35baff1c066e66a6ea5ced9549ec9c8
```

Admission validation:

```text
JSON parse                         = PASS
top-level token groups             = 11
primitive tokens                  = 63
semantic tokens                   = 38
CSS custom-property declarations  = 227
semantic primitive references     = PASS, 0 missing
primitive CSS coverage            = PASS, 0 missing
semantic CSS coverage             = PASS, 0 missing
```

The admission does not yet claim that the supplied CSS is reproducibly
generated. UXM-S03 must:

1. Treat `tokens.json` as the canonical candidate.
2. Generate application `tokens.css` deterministically from JSON.
3. Compare generated output with the admitted CSS reference.
4. Validate light/dark completeness, references, contrast, and drift.
5. Record the promoted application token digest.

Decision:

```text
DESIGN_ASSET_INPUT_ADMITTED_FOR_UXM_S03
CANONICAL_APPLICATION_TOKEN_PROMOTION_PENDING_UXM_S03
```

## 4. Document Identity and Reading Order

The canonical PAD filename is:

```text
NeX_AE_Web_UI_UX_Modernization_Source_Audit_and_Pre_Architecture_Decision_v1.0.md
```

The former filename containing `UI_UX-Modernization` and `anD` is retired by
rename. The Slice Plan's nonexistent dated Parent PAD reference is replaced
with the canonical filename.

`docs/transition/UIUX/README.md` is the reading-order authority. This CA01 is a
mandatory implementation amendment: it does not rewrite historical PAD facts,
but it takes precedence for the implementation branch point, asset path, gate
cadence, and Slice order.

Decision:

```text
DOCUMENT_IDENTITY_RECONCILED
READING_ORDER_FROZEN
```

## 5. Canonical Gate Cadence

The Gate Matrix and execution narrative are reconciled to one cadence:

| Boundary | Gate |
|---|---|
| UXM-S01 through UXM-S04 | Checkpoint #1: Foundation and Design System |
| UXM-S05 through UXM-S07 | Security Boundary Checkpoint |
| UXM-S08, UXM-S08A, UXM-S09, UXM-S10 | Checkpoint #2: Approval UX |
| UXM-S11 through UXM-S14 | Checkpoint #3: Workspace and Result |
| UXM-S15 through UXM-S19 | Full Web Acceptance #1 |
| UXM-S20 through UXM-S21 | Cutover and Retirement Checkpoint |
| UXM-S22 | Repository Full Gate and Final As-Built |

Each Slice still performs focused tests and the existing AE Web Node regression.
Backend projection changes retain owning-service, contract, and protected
PostgreSQL verification requirements.

Decision:

```text
GATE_CADENCE_RECONCILED
```

## 6. UX State Mapper Ordering

The original plan implemented Approval screens before the shared UX state
mapper. That ordering could create temporary component-local status mappings.

`UXM-S08A: User-Facing UX State Mapper Foundation` is inserted after the
Approval projection contract and before the Approval React surface:

```text
UXM-S08  authoritative Approval projection
UXM-S08A minimal canonical UX state mapper
UXM-S09  Approval Inbox React surface
UXM-S10  Approval decision/evidence/risk UX
UXM-S11  mapper completion for Workspace/Result/Document terminology
```

S08A and S11 must extend the same `src/ux/workState.ts` source. Parallel state
vocabularies or component-local business-state translation are prohibited.

Decision:

```text
UX_STATE_FOUNDATION_PRECEDES_APPROVAL_VIEW
```

## 7. Branch and History Policy

The implementation branch is:

```text
transition/ae-web-uiux-modernization
```

Policy:

```text
one integration branch for UXM-S01 through UXM-S22
one verified commit per Slice
push after each Slice
master drift check at every major Checkpoint
merge current master into transition branch when required
no force-push or public-history rewrite
final PR uses merge commit after UXM-S22 Full Gate
```

## 8. UXM-S00 Disposition

This closure performs every source-freeze and entry-readiness responsibility
assigned to UXM-S00. UXM-S00 is therefore:

```text
SATISFIED_BY_UXM_CA01
```

Do not repeat UXM-S00 or create a second entry-gate document. The next
implementation Slice is UXM-S01.

## 9. Verification

```text
design token JSON parse                    = PASS
semantic/primitive reference resolution   = PASS
JSON-to-CSS token presence                 = PASS
current AE Web source inventory            = PASS
existing AE Web Node regression            = PASS, 404 passed
document parent reference                  = PASS
canonical reading order                    = PASS
gate cadence consistency                   = PASS
UX state execution order                   = PASS
product code changes                       = NONE
```

## 10. Closure Decision

```text
UXM_CA01 = PASS / CLOSED
UXM_S00  = SATISFIED
UXM_S01  = AUTHORIZED
```
