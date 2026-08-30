# Slice 0438: AE Web Artifact Delivery Accessibility Smoke

## Scope

Add deterministic browser-render smoke evidence that artifact preview/download
controls are keyboard reachable and expose selected/disabled format states
without requiring network or PostgreSQL access.

## Changes

- Added `apps/nex-ae-web/scripts/runArtifactDeliveryAccessibilitySmoke.mjs`.
- Added `apps/nex-ae-web/test/artifactDeliveryAccessibilitySmoke.test.mjs`.
- Registered `smoke:artifact-delivery-accessibility` in the AE Web package.
- Added the accessibility smoke to the default quality gate.

## Decisions

- This smoke renders artifact cards and download format selectors through the
  real browser-side modules, then inspects the generated action attributes.
- The smoke checks same-origin artifact routes, selected format state,
  disabled format state, region labels, focus-visible styling, and redaction.
- It does not use live network or PostgreSQL. Protected persisted browser
  evidence remains owned by the Slice 0435 and Slice 0439 smoke paths.

## Evidence

Targeted browser-side regression:

```bash
node --test apps/nex-ae-web/test/artifactDeliveryAccessibilitySmoke.test.mjs apps/nex-ae-web/test/artifactDownloadFormatSelector.test.mjs apps/nex-ae-web/test/artifactDeliveryActionState.test.mjs
```

Smoke summary:

```bash
node apps/nex-ae-web/scripts/runArtifactDeliveryAccessibilitySmoke.mjs --summary
```
