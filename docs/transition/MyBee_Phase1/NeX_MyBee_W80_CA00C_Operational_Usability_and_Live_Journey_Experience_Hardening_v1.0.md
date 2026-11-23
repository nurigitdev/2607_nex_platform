# NeX MyBee W80-CA00C Operational Usability and Live-Journey Experience Hardening v1.0

**Status:** CLOSED

**Predecessor:** W80-CA00B

**Database migration:** None

## 1. Purpose

W80-CA00B restored authoritative PA business results to the IA Workspace. This
amendment makes that result usable in an ordinary installed-service session and
closes the default authority profile needed to start the same flow without a
live-journey-only permission seed.

## 2. Scope

1. constrain the desktop Workspace to the available viewport and scroll the
   conversation independently from the composer;
2. convert admitted WorkResult projections into Korean user-facing titles,
   descriptions, fields, status labels, and bounded warnings;
3. add a least-privilege employee product baseline when OA creates a membership;
4. freeze the distinct IA and PA Agent authority profiles;
5. reconcile Project registration, PA lifecycle, WC coordination, WA evidence,
   and OA authorization boundaries without copying service scopes to users or
   Agents.

## 3. Authority Profiles

### 3.1 Employee baseline

New OA memberships receive `employee`, `workspace:use`, Project application,
Project read/participation, finance request/read, VoucherCandidate, and
VoucherDraft request scopes. The baseline is eligibility, not resource
authorization: Project-scoped writes still require an active OA Project grant,
an admitted Project role, current Project state, and any business approval or
SoD evidence required by EOS/WC.

The baseline explicitly excludes:

- `approval:read` and `approval:decide`;
- accounting approval and allocation-plan approval;
- Project administration, membership management, and work-code approval;
- WC Agent scopes;
- service-principal and WA evidence-ingest scopes.

Existing memberships are not silently rewritten. Explicitly supplied roles and
scopes continue to override the default at creation, and later authority changes
remain revision-guarded OA operations.

### 3.2 IA Agent

IA is an AE-managed OA subject with `nex-agent`, `nex-agent-ia`, `work:claim`,
and `work:delegate`. IA does not receive human finance scopes, approval scopes,
or service-principal scopes.

### 3.3 Project Agent

PA is created or reactivated from the authoritative EOS Project lifecycle event
and synchronized by AE. Its OA profile is `nex-agent`, `nex-agent-pa`,
`work:claim`, `work:delegate`, and `work:result:submit`. ACTIVE and CLOSING keep
the profile active; INACTIVE and CLOSED disable or retire execution according to
the existing lifecycle policy.

Project business rights remain bound to Project Code, Project role, EOS
authority, and the originating human principal. PA identity does not acquire a
blanket finance or Project-admin role.

### 3.4 WC, WA, and OA service trust

Cross-service calls continue to use signed service principals:

- AE -> OA manages Agent membership lifecycle and reads authorization;
- AE -> WC submits/delegates through the installed coordination APIs;
- AE -> WA ingests admitted work evidence;
- WC -> OA performs fresh requester/Agent authorization checks;
- WA -> OA verifies subjects and WA -> EOS verifies Project authority.

These service grants are not copied into employee or Agent membership scopes.

## 4. WorkResult Presentation Boundary

The browser consumes only the owner-safe business projection admitted by the AE
Workspace API. A dedicated presentation mapper converts status and typed
finance summaries into user labels. Operation IDs, hashes, projection IDs,
authority references, private classification, and raw technical warnings are
not rendered. Unknown warnings collapse to a bounded user action message.

## 5. Workspace Scrolling

On desktop and tablet, the Workspace uses a bounded viewport-relative height.
The conversation and context panel scroll independently while the composer
remains reachable. Mobile keeps a natural document flow and does not force a
small fixed viewport.

## 6. Acceptance

1. React tests for scrolling contract, voucher/allocation presentation, and
   technical-warning suppression;
2. OA tests for default membership admission and privileged-scope exclusion;
3. AE tests for exact IA/PA managed authority profiles and lifecycle behavior;
4. canonical service-trust assertions for AE/WC/WA/OA boundaries;
5. TypeScript, production build, browser-security, and focused service gates;
6. no migration, no fixture-specific authority, and no live provider required.

### 6.1 Verification evidence

- AE Web Node regression: `395 passed`;
- AE Web React regression: `134 passed`;
- TypeScript typecheck, production build, production-import audit,
  browser-security audit, and legacy-retirement audit: PASS;
- Workspace Playwright smoke: PASS, `8` requests, `3` result reads, `11`
  checks across desktop and mobile;
- OA Slice Gate: `1264 passed`, `14 skipped`, statement `96.69%`, branch
  `95.11%`;
- AE Slice Gate: `6930 passed`, `53 skipped`, statement `96.45%`, branch
  `94.68%`;
- contract validation, transition audit, product dependency audit, and AE
  coverage ownership audit: PASS.

The browser overlap acceptance now compares the visible rectangle clipped by
scrolling ancestors and the viewport. This preserves detection of real region
overlap without treating off-screen WorkResult content as overlapping the
fixed composer.

## 7. Decision

```text
WORKSPACE VIEWPORT SCROLL       = REQUIRED
RAW WORKRESULT UI               = FORBIDDEN
EMPLOYEE PRODUCT BASELINE       = DEFAULT FOR NEW MEMBERSHIPS
APPROVAL/ADMIN DEFAULTS         = FORBIDDEN
IA/PA AUTHORITY                 = SEPARATE MANAGED PROFILES
SERVICE SCOPES ON USERS/AGENTS  = FORBIDDEN
EXISTING MEMBERSHIP REWRITE     = FORBIDDEN
DATABASE MIGRATION              = NONE
```
