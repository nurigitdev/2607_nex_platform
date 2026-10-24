# P8-S89: Coverage Closure

## Status

Completed on 2026-10-24.

## Scope

P8-S89 measures the complete default repository regression profile against the
canonical Platform coverage floor:

```text
statement coverage >= 96%
branch coverage    >= 94%
```

The measured source roots are the existing `services`, `scripts`, and
`providers` roots. No production source, test behavior, public API, contract,
database schema, migration, coverage threshold, source root, or exclusion
changed in this Slice.

Protected PostgreSQL, RustFS, Playwright, admitted-wheel, restart, and live
provider gates remain assigned to their explicit acceptance Slices. P8-S90
owns the actual database full gate and P8-S91 owns the IA Playwright full gate.

## Coverage Configuration Integrity

The repository used the existing configuration without modification:

```toml
[tool.coverage.run]
branch = true
source = ["services", "scripts", "providers"]
omit = [
  "*/__init__.py"
]
```

The SHA-256 digest of `pyproject.toml` before and after the run, at `HEAD`, and
at `HEAD^` was identical:

```text
d245f02f89a6923767deb19ddf5bf856813ec2139e4c05835850bf8245721a38
```

`git diff -- pyproject.toml` was empty. No exclusion or denominator
manipulation was used to satisfy the gate.

## Execution

The canonical coverage command was:

```bash
./.venv/bin/pytest -q \
  --cov=services \
  --cov=scripts \
  --cov=providers \
  --cov-branch \
  --cov-report=term \
  --cov-report=json:reports/quality/p8-s89-coverage.json \
  --junitxml=reports/quality/p8-s89-coverage.junit.xml
```

The repository collected 17,349 tests and completed in 2,069.67 seconds:

```text
passed    = 17,238
skipped   = 111
failed    = 0
errors    = 0
warnings  = 1,507
```

This exactly preserves the P8-S88 pass/skip population. All skips are explicit
protected environment guards; no test was deselected.

## Canonical Result

The committed threshold checker independently calculated coverage from the
JSON numerator and denominator:

```bash
./.venv/bin/python scripts/quality/check_coverage_thresholds.py \
  reports/quality/p8-s89-coverage.json 96 94
```

Result:

```text
statement = 168,378 / 174,095 = 96.72%  (minimum 96.00%)
branch    =  37,910 /  39,446 = 96.11%  (minimum 94.00%)
missing statements = 5,717
missing branches   = 1,536
measured files     = 1,453
```

Both canonical thresholds pass. The combined line-and-branch percentage
reported by coverage.py is a separate aggregate and is not used in place of
the two required gates.

Post-documentation verification also passed:

```text
NSL P8-S01..S06 Platform-side regression = 117 passed
P8 contract hygiene                      = PASS
threshold checker re-run                 = 96.72% / 96.11%
```

## NSL Certification Boundary

NSL native certification remains an independent release-admission property;
its source is not folded into the Platform coverage denominator. The admitted
P8 identity remains:

```text
source revision = a5a0f5fd7acf4adbbccf890dca2f9998d055d65e
certification   = nsl-linux-quality:a5a0f5fd7acf4adbbccf890dca2f9998d055d65e
wheel sha256    = 862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135
```

The full repository run includes the Platform-side release identity, wheel
lock, readiness, adapter, and compatibility regressions. P8-S89 does not
rebuild or recertify the external NSL repository and does not weaken its
independent PASS requirement.

## Evidence Retention

The generated reports are:

```text
reports/quality/p8-s89-coverage.json
reports/quality/p8-s89-coverage.junit.xml
```

They remain under the intentionally ignored `reports/` tree. This Slice
document is the durable repository evidence.

## Exit Decision

P8-S89 is closed. The complete default repository regression remains green,
statement coverage is 96.72%, branch coverage is 96.11%, no coverage exclusion
changed, and NSL certification remains independently governed. P8-S90 may now
run the actual AE/WC/OA/EOS PostgreSQL full gate.
