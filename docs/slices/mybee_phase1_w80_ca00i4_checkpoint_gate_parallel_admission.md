# W80-CA00I.4 Checkpoint Gate Parallel Admission

## Outcome

- Added an explicit `serial|parallel` execution mode to the canonical
  Checkpoint Gate entrypoint while preserving serial fallback behavior.
- Classified platform and multi-owner tests into the serial integration lane
  and unowned repository tests into a separate serial repository lane.
- Executed all owner-service lanes with bounded concurrency, then executed the
  integration and repository lanes serially.
- Combined every lane-local raw coverage file and applied the unchanged
  Checkpoint statement and branch thresholds.
- Kept contract validation, Golden Journey retirement audit, and demo-product
  dependency audit in serial closure.

## Exact-Head Four-Lane Acceptance

Run identity:

```text
w80-ca00i4-checkpoint-20261127
```

| Signal | Result |
| --- | ---: |
| Exact-once test files | `1761` |
| Owner-service phase | `1115.075s` |
| Serial integration phase | `164.143s` |
| Serial repository phase | `670.132s` |
| Complete parallel Checkpoint | `1988.144s` |
| Latest serial Checkpoint baseline | `2305.328s` |
| Wall-time improvement | `317.184s` (`13.76%`) |
| Combined statement coverage | `98.09%` |
| Combined branch coverage | `96.48%` |
| Final result | `PASS` |

The combined coverage passed the unchanged Checkpoint minimums of `95%`
statement and `94%` branch coverage. Every lane wrote an isolated raw coverage
file, coverage JSON, JUnit XML, stdout/stderr log, and evidence receipt.

## Three-Lane Comparison

Run identity:

```text
w80-ca00i4-checkpoint-p3-20261127
```

The same owner inventory was also measured with `max_parallel=3`. Individual
lanes generally became faster because of lower CPU and I/O contention, but the
runtime lane waited behind earlier work:

| Signal | Four lanes | Three lanes |
| --- | ---: | ---: |
| Owner phase | `1115.075s` | `1237.235s` |
| AE lane | `1115.072s` | `1075.161s` |
| CX lane | `746.554s` | `630.943s` |
| AG lane | `483.845s` | `420.128s` |
| Runtime lane | `255.962s` | `162.071s` |

Although the individual processes improved, the three-lane owner phase was
`122.160s` slower. The remaining Checkpoint phases are serial and independent
of owner concurrency, so the comparison was stopped after the complete owner
phase. Four remains the admitted default for the current host and inventory;
the value remains configurable for future hardware or inventory changes.

## Verification

```text
focused quality-orchestrator tests = 51 passed
shell serial/parallel mode validation = PASS
exact-once inventory missing/duplicate count = 0/0
four-lane actual Checkpoint = PASS
three-lane owner comparison = PASS
combined coverage thresholds = PASS
serial fallback preserved = PASS
```

W80-CA00I.5 may now reuse the admitted owner-test phase for the Repository Full
Gate while leaving all cross-service protected smoke, migration, Compose,
Playwright, and live-provider acceptance serial.
