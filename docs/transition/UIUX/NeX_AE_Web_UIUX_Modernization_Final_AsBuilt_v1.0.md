# NeX AE Web UI/UX Modernization Final As-Built v1.0

## 1. Closure Status

```text
program                      = NeX AE Web UI/UX Modernization
implementation range         = UXM-S01 through UXM-S22
status                        = PASS / CLOSED
React UI                      = CANONICAL
legacy UI                     = RETIRED
PWA phase                     = NOT STARTED / SUCCESSOR
database or backend migration = NONE IN UXM-S22
```

This record freezes the source-backed UI/UX modernization baseline accepted by
UXM-S22. The accepted runtime source is the clean repository state below; the
documentation-only closure commit is intentionally not self-referenced.

## 2. Accepted Source Baseline

| Item | Value |
|---|---|
| Branch | `transition/ae-web-uiux-modernization` |
| Accepted commit | `25b9caf18bd98bf1b5cb30fec5b0d5fbb15fe6cd` |
| Accepted tree | `560b53c31cfd0138001244f35b56f1c804edb282` |
| React | `19.3.1` |
| Vite | `8.3.6` |
| TypeScript | `7.0.2` |
| `package-lock.json` SHA-256 | `df5c97ca4c0589a68b542c1a7137b8b781162a33d851ef2603c317001a8fd021` |
| `tokens.json` SHA-256 | `c9b0437f12c2757c9085cd2b9866a71accfae5495bfa78638bdff5c5882897ad` |
| `tokens.css` SHA-256 | `3a90259fdecc2d142836d010ac63fd60c35baff1c066e66a6ea5ced9549ec9c8` |

The admitted token projection contains 146 CSS variables across 15 component
groups. Reproducible generation and drift checks are part of the repository
quality gate.

## 3. Production Runtime

The sole production entry is `index.html -> /src/app/main.tsx`. Vite produces
the `dist/` artifact and the packaged Node server serves only that artifact.
The browser calls the AE facade through the same-origin `/ae-api` prefix.

Canonical routes:

| Route | Boundary |
|---|---|
| `/login` | Public authentication entry |
| `/workspace` | Protected default workspace |
| `/approvals` | Protected approval inbox and decisions |
| `/documents` | Protected document surface |
| `/upload` | Protected document upload view |
| `/retrieval` | Protected retrieval view |
| `/artifacts` | Protected artifact/result surface |
| `/operations` | Role-filtered operations and diagnostics |
| `*` | Session-aware redirect to `/login` or `/workspace` |

Authentication-first routing, role-based operations visibility, immediate
session-expiry return, owner-private projection, and user-facing state mapping
are retained as mandatory boundaries.

## 4. OCI Evidence

UXM-S22 built the AE Web image from the existing owner-scoped OCI allowlist,
not from the repository root.

| Item | Value |
|---|---|
| Local tag | `nex-platform-local/nex-ae-web:uxm-s22-25b9caf1` |
| Manifest/image digest | `sha256:1703cd1655b22fd62e0f4831b57da781483f9c10dea54e164e15cc01f8187073` |
| Config digest | `sha256:78af825377b2e4452acef821aaf322613bad8b6922a391fb064e161085e86f75` |
| Base image | `node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392` |
| Build-inputs digest | `sha256:f9af11874a41e2e4edee2ce8c5d714d73bd6a80953fd8a0a7915b20f4c753fa3` |
| Owner-scoped context digest | `sha256:b1918d982c6d92ad5db061ecbcab074c4c17bbfe785d765f8a109c667e56550f` |
| Context files | 163 |
| Platform | `linux/amd64` |
| Runtime user | `node` (`uid=1000`, `gid=1000`) |
| Packaged command | `node scripts/serve.mjs` |

The final image contains only `serve.mjs`, `dist/index.html`, and the two
hashed JS/CSS assets under `/app`. Runtime probes returned HTTP 200 for `/` and
the SPA `/workspace` route. With no AE proxy target configured, `/ae-api`
returned HTTP 503 with `ae_web_proxy_target_unavailable`, proving fail-closed
startup behavior. No registry push was performed.

## 5. Repository Full Gate Evidence

The canonical `scripts/quality/run_quality_gate.sh` completed with exit code
zero on the accepted source baseline.

| Check | Result |
|---|---|
| Python repository regression | PASS, 20,385 passed / 133 explicit protected skips |
| Statement coverage | PASS, 96.73% (201,932 / 208,751) |
| Branch coverage | PASS, 95.99% (46,768 / 48,722) |
| Product-code coverage | PASS, 98.66% statement / 97.29% branch |
| Smoke/test-harness coverage | PASS, 94.18% statement / 92.95% branch |
| Contract validation | PASS, 233 schemas / 292 examples / 245 negative examples / 10 OpenAPI documents |
| Node regression | PASS, 374 tests |
| React/Vitest regression | PASS, 130 tests / 29 files |
| TypeScript | PASS, `tsc --noEmit` |
| Production cutover | PASS, 10 checks / 2 hashed assets |
| Full Web v2 acceptance | PASS, 6 journeys / 71 checks / 16 screenshots |
| Golden journey transition audit | PASS, 9 registered / 1 enforced / 0 findings |
| Demo-to-product dependency audit | PASS, 750 product files / 7 of 7 edges / 0 findings |
| Canonical generation binding | PASS, 10 of 10 checks / `Qwen3.5-9B` / port 9111 |

Protected PostgreSQL, remote-provider, and environment-specific browser tests
remain guarded by their explicit opt-in variables. The 133 skipped tests were
reported separately and are not represented as executed PASS evidence. UXM-S22
did not require a database migration or a live remote-provider call.

## 6. Browser and Security Acceptance

The six deterministic Playwright journeys are:

1. security boundary;
2. workspace execution;
3. approval checkpoint;
4. document and retrieval;
5. artifact and result;
6. operations isolation.

They cover desktop `1440x900` and mobile `390x844`. The 16 generated PNGs and
the receipt are under `reports/uiux/`; reports remain local generated evidence
and are intentionally excluded from Git.

Additional admitted audits:

```text
design token check             = PASS, 146 variables / 15 components
modern production import audit = PASS, 52 files
modern browser security audit  = PASS, 53 files
legacy UI retirement audit     = PASS, 117 files
same-origin runtime boundary   = PASS
static browser smoke           = PASS, 6 anchors
retrieval-quality smoke        = PASS, 18 React/domain source anchors
grounded-quality smoke         = PASS, 21 React/domain source anchors
```

Accessibility acceptance includes desktop/mobile overflow checks, landmark and
heading structure, keyboard-reachable controls, accessible labels, modal focus
behavior, and visible status semantics. Security acceptance prohibits direct
owner-service URLs, pre-authentication diagnostics, unsafe runtime fallback,
and browser exposure of private storage or internal provider details.

## 7. Full-Gate Reconciliation

The first UXM-S22 Full Gate correctly exposed three stale assumptions:

1. historical closure tests still expected deleted DOM renderer modules;
2. the static browser smoke could collide with a stale fixed-port Vite server;
3. retrieval and grounded-quality smoke scripts still anchored to retired
   `main.js` and `styles.css` paths.

The corrections rebound behavioral evidence to the React workspace and
business-result surfaces, added React parity for response-quality actions,
made static smoke ports isolated by default, and preserved explicit-port
support. The accepted corrective commits are `7e7c2f7f`, `515f245e`, and
`25b9caf1`. No retired renderer was restored.

The remaining Vite bundle-size and third-party `use client` advisories are
non-blocking build advisories. PWA/offline installation remains a successor
phase and is outside this modernization baseline.

## 8. Final Decision

```text
NeX AE Web UI/UX Modernization = CLOSED
React UI                       = CANONICAL
Legacy UI                      = RETIRED
Repository Full Gate           = PASS
OCI package acceptance         = PASS
PWA Phase                      = NOT STARTED / SUCCESSOR
```
