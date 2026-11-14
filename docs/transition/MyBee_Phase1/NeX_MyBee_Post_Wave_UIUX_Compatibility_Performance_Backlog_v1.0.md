# NeX MyBee Post-Wave UI/UX Compatibility and Performance Backlog v1.0

## 1. Status And Timing

```text
status             = DEFERRED_BACKLOG
implementation     = NOT_STARTED
entry_condition    = CURRENT_PLANNED_WAVES_COMPLETED
current_wave_scope = UNCHANGED
```

This backlog records non-blocking warnings observed during the Repository Full
Gate after `S7-01`. The warnings do not invalidate the completed gate and must
not expand or interrupt the current accounting Wave. They are handled as a
separate UI/UX compatibility and performance hardening stage after the planned
Waves have been completed.

## 2. Backlog Items

### `UIUX-COMPAT-001` — Starlette TestClient `httpx2` Transition

Current admitted versions are FastAPI `0.141.1`, Starlette `1.3.1`, and httpx
`0.28.1`. Starlette's `TestClient` first attempts to import `httpx2`, falls
back to `httpx`, and emits `StarletteDeprecationWarning`. Product outbound HTTP
clients still depend on `httpx`; this item must not remove or silently replace
that product dependency.

Required follow-up:

1. admit and pin a compatible `httpx2` test/smoke dependency;
2. regenerate the Python dependency lock and provenance evidence;
3. keep product `httpx` clients unchanged unless separately reviewed;
4. run focused FastAPI/Starlette `TestClient` regression and representative
   smoke runners; and
5. run the Repository Full Gate and confirm the deprecation warning is gone.

Acceptance boundary:

- no service API or runtime HTTP behavior change;
- no loss of existing TestClient coverage;
- deterministic dependency lock; and
- no warning suppression used as a substitute for migration.

### `UIUX-PERF-001` — AE Web Route-Level Bundle Splitting

The accepted production build generated one primary JavaScript asset of
approximately `660.73 kB` minified and `193.37 kB` gzip, above Vite's default
`500 kB` chunk warning threshold. The current router statically imports the
Workspace, Approval, Document, Artifact, and Operations routes, so code for
screens not visited by the user is included in the initial bundle.

Required follow-up:

1. capture a reproducible pre-change bundle inventory;
2. keep authentication, session bootstrap, the application shell, and shared
   providers in the initial chunk;
3. apply route-level lazy loading to Workspace, Approval, Document, Artifact,
   and Operations surfaces with an accessible deterministic loading state;
4. consider stable vendor chunking only after route splitting is measured;
5. repeat typecheck, React tests, production build, Playwright journeys, and
   production-cutover acceptance; and
6. record minified/gzip sizes and initial-route loading behavior before and
   after the change.

Acceptance boundary:

- authentication-first routing and role guards remain fail-closed;
- Korean-default UI and existing Playwright journeys remain unchanged;
- the warning threshold is not merely increased to hide the finding; and
- the initial route no longer downloads every feature implementation.

### `UIUX-COMPAT-002` — Bundler Directive Compatibility Observation

Vite/Rolldown also reported non-blocking module-level `"use client"` warnings
from React Query, React Router, Radix UI, and Lucide dependencies. No product
source currently owns those directives, and React tests plus production
acceptance passed. Recheck these warnings while performing `UIUX-PERF-001` and
after dependency upgrades; do not patch vendored packages locally without a
separate compatibility decision.

## 3. Entry And Exit Gates

Entry requires:

1. the currently planned functional Waves and their accounting gates are
   complete;
2. a clean Repository Full Gate baseline is available; and
3. the work is assigned a separate corrective Slice or controlled amendment.

Exit requires:

1. focused compatibility and bundle tests pass;
2. production dependency and frontend lock files are synchronized;
3. Repository Full Gate passes at or above the established coverage floors;
4. protected browser acceptance passes where applicable; and
5. the resulting warnings, bundle sizes, and any accepted residual risks are
   recorded in the Slice evidence.

## 4. Non-Goals

This backlog does not authorize:

- accounting contract, EOS persistence, or database migration changes;
- product HTTP client replacement as part of the TestClient transition;
- broad UI redesign or label changes;
- suppression of dependency or bundler warnings without root-cause closure;
  or
- delaying the current functional Wave solely because these warnings exist.

