# Slice 1389: AE Web Korean Golden-Journey Playwright Acceptance

## Outcome

- Added one deterministic composition of the production ingestion, grounded
  generation, and artifact journey coordinators that completes all nine stages
  with browser-safe evidence.
- Added an actual headless Chromium runner that operates the production AE Web
  login, upload, generation, preview, and download controls in both frozen
  viewports.
- Applied the shared layout evaluator after the visible workflow and captured
  one fixed-viewport screenshot per viewport under `reports/quality`.
- Enabled the local mock login form with a safe OA-shaped browser-session
  snapshot while leaving fetch and service trust paths unchanged.

## Actual Browser Evidence

- Browser: actual Playwright Chromium, headless.
- Desktop: `1440x900`, PASS, document width `1440`, 57 named controls, zero
  undersized controls, zero overlap pairs, visible focus, zero page errors.
- Mobile: `390x844`, PASS, document width `390`, 57 named controls, zero
  undersized controls, zero overlap pairs, visible focus, zero page errors.
- Both runs completed all nine correlated stages and the five visible action
  families: login, upload, generation, preview, and download.
- Screenshot references: `reports/quality/s139-playwright/desktop.png` and
  `reports/quality/s139-playwright/mobile.png` (generated evidence, not source).

## Decisions

- Deterministic browser acceptance uses production UI and production
  coordinators with local mock providers; it does not claim PostgreSQL or
  remote-provider evidence.
- Protected actual service-process and test-PostgreSQL execution remains the
  distinct Slice 1390 gate.
- Browser evidence retains only counts, booleans, bounded status, layout
  metrics, and relative screenshot references.

## Verification

- Node regression covers deterministic composition, redaction, two-viewport
  aggregation, missing configuration, failed viewport checks, invalid timeout
  and screenshot paths, launch failure, and forbidden evidence.
- Actual Playwright execution passed both frozen viewports after identifying
  and correcting context-grid min-content overflow, one undersized link, and
  keyboard focus measurement.

## Next

Slice 1390 repeats the accepted browser path against actual service processes
and service test PostgreSQL databases.
