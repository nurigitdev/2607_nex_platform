# P8-S88: Full Repository Regression

## Status

Completed on 2026-10-24.

## Scope

P8-S88 runs the complete default repository regression profile after the
P8-S87 contract hygiene closure. It covers every collected test, including the
P4, P5, P6, P6.5, P7, and P8 transition suites and all earlier service
regressions.

No production source, test behavior, public API, contract, database schema,
migration, or runtime ordering changed in this Slice. Coverage measurement is
intentionally deferred to P8-S89, and protected PostgreSQL, RustFS,
Playwright, admitted-wheel, and live-provider gates remain assigned to their
explicit later acceptance steps.

## Execution

The canonical regression command was:

```bash
./.venv/bin/pytest -q \
  --junitxml=reports/quality/p8-s88-regression.junit.xml
```

The repository collected 17,349 tests and completed in 997.967 seconds:

```text
passed    = 17,238
skipped   = 111
failed    = 0
errors    = 0
warnings  = 1,507
```

All skips are explicit protected environment guards for PostgreSQL, RustFS,
Playwright, admitted NSL wheel, restart, or live-provider acceptance. The
default regression profile produced no unexpected skip and no deselected
test.

Warnings are the existing Starlette `TestClient` deprecation and Python 3.12
SQLite datetime adapter deprecation families. Neither warning family changed
test outcomes or indicates a P8 behavioral regression.

## P7 Claim / WorkResult Guard

The JUnit evidence was parsed independently after pytest completion:

```text
P7-marked cases               = 289
P7 passed                     = 280
P7 protected skips            = 9
P7 failures / errors          = 0 / 0

Claim/WorkResult cases        = 363
Claim/WorkResult passed       = 359
Claim/WorkResult protected skips = 4
Claim/WorkResult failures / errors = 0 / 0
```

The protected P7 skips are the pre-existing PostgreSQL or live Golden B
guards. All default-profile delegation, claim, handoff, WorkResult,
publication, resume, restart, idempotency, authorization, and contract hygiene
tests passed. P8 therefore introduces no observed P7 Claim/WorkResult behavior
regression.

## Evidence Retention

The generated JUnit report is
`reports/quality/p8-s88-regression.junit.xml`. The 6.8 MB report remains under
the intentionally ignored `reports/` tree; this Slice document is the durable
repository evidence.

## Exit Decision

P8-S88 is closed. The entire default repository regression profile passes with
zero failure or error, and the P7 Claim/WorkResult compatibility boundary is
preserved. P8-S89 may now run the full coverage closure without changing
coverage exclusions or thresholds.
