# Slice 1383: AE Web Korean-Default Message Contract

## Outcome

- Added one browser-native `ko`/`en` message catalog with Korean as the
  explicit default and fallback locale.
- Added exact catalog-parity validation, locale normalization, placeholder
  formatting, status translation, and declarative document bindings.
- Wired primary navigation, login, upload, retrieval, generation, timeline,
  artifact, audit, and accessible labels to stable message keys.
- Replaced the local dynamic status map and English event counter with the
  shared message contract.
- Reclassified the historical S101 localization gap as a preserved good
  boundary while leaving its remaining composition, package, and
  accessibility findings open.

## Decisions

- Locale selection changes presentation only. It does not fork identity,
  ownership, retrieval, generation, citation, or artifact behavior.
- Unknown provider or service status values remain visible as their bounded
  raw code instead of being hidden behind an incorrect translation.
- This Slice does not add a locale switch, database table, remote-provider
  dependency, or browser evidence. The two-viewport browser proof remains in
  Slices 1388-1390.

## Verification

- Node unit regression covers catalog parity, fallback, interpolation,
  statuses, accessible labels, missing roots, and malformed catalog parity.
- Repository smoke verifies the required key pairs, Korean document default,
  declarative bindings, composition wiring, and Node contract test.
- Slice Gate covers the Python evidence runner and the affected AE Web service
  regression set.

## Next

Slice 1384 defines the single correlated golden-journey state and
browser-safe evidence model.
