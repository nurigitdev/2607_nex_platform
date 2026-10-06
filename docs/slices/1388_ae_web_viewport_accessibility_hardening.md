# Slice 1388: AE Web Viewport and Accessibility Hardening

## Outcome

- Froze desktop `1440x900` and mobile `390x844` as the two S139 acceptance
  viewports.
- Added a shared viewport evaluator for Korean document language, one main
  landmark, one primary heading, nine required regions, horizontal overflow,
  accessible control names, 24-pixel minimum targets, focus visibility, and
  five non-overlap region pairs.
- Marked stable layout regions in the production AE Web shell and added a
  localized keyboard skip link.
- Hardened long-label wrapping, component width constraints, mobile status
  alignment, and artifact row stacking without creating a second mobile flow.

## Decisions

- Desktop and mobile run the same DOM, same clients, and same journey state.
- Touch target acceptance uses the WCAG 2.2 AA 24-pixel minimum; larger
  application controls remain preferred through the existing design system.
- Hidden or disabled controls remain accessible by name but only visible
  controls are evaluated for target dimensions.
- Screenshot and actual Chromium evidence are deliberately owned by Slice
  1389; this Slice freezes the evaluator and production markup/CSS boundary.

## Verification

- Node regression covers both accepted viewports and each individual layout,
  accessibility, target, focus, region, overlap, and dimension rejection path.
- Repository smoke freezes the two dimensions, nine region markers, five
  non-overlap pairs, localized skip link, responsive breakpoints, and positive
  and negative contract tests.

## Next

Slice 1389 executes the deterministic Korean golden journey in Chromium for
both viewports and captures redacted screenshot evidence.
