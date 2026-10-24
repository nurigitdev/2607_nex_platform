# P8-CA03: Pre-Entry Repository Consistency And Reliability Preparation Closure

## Status

Completed on 2026-10-24. P8.8 may begin with P8-S76.

## Scope

P8-CA03 closed three repository-level gaps without changing the P8
architecture:

1. the Repository Full Gate now enforces Statement `96%` and Branch `94%` by
   default;
2. the P8 README distinguishes historical CA02 entry state from the admitted
   NSL v0.2 and current P8.7A closure state;
3. the P8-S76 through P8-S86 reliability matrix now includes immutable
   attachment-manifest and RustFS object identity across ambiguity, recovery,
   verification failure, replay, revocation, tamper, and cross-tenant faults.

The tiered Slice/Checkpoint Gate remains independently configured at `95 / 94`.
No P8.8 Slice number was added or changed.

## Coverage Policy Verification

`scripts/quality/run_quality_gate.sh` now defaults to:

```text
STATEMENT_COVERAGE_MIN = 96
BRANCH_COVERAGE_MIN    = 94
```

Regression tests prove exact `96 / 94` acceptance and `95.9 / 93.9`
rejection. The Full Gate was run without environment overrides, so the
reported thresholds are the repository defaults rather than command-line
substitutions.

## Protected Baseline Verification

The P8-S75H attachment journey was re-run before the Full Gate using:

```text
actual nex_ae_test PostgreSQL
actual nex_wc_test PostgreSQL
actual nex_oa_test PostgreSQL
actual nex_eos_test PostgreSQL
rustfs/rustfs:1.0.1@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
SSE-S3 enabled
```

Result:

```text
1 passed
0 skipped
zero test-row residue
zero test-object residue
```

This protected run re-proved authenticated multi-file upload, duplicate
replay, restart reconstruction, immutable manifest lock, approval, exactly-one
EOS Voucher commit, tamper denial, cross-tenant denial, and cleanup.

## Repository Full Gate

The complete Repository Full Gate exited successfully:

```text
pytest              = 17,111 passed / 98 skipped
warnings            = 1,507
statement coverage  = 96.76% / required 96.00%
branch coverage     = 96.14% / required 94.00%
contract validation = 191 schemas / 253 positive / 221 negative / 9 OpenAPI
pytest duration     = 33m 55s
process exit        = 0
```

The protected/live skips were not broadened or altered. The S75H journey has
separate zero-skip evidence as recorded above.

## Exit Decision

PRE-01, PRE-02, and PRE-03 are closed. P8-S76 remains the canonical next
Slice. It will inject an ambiguous EOS commit response into an
attachment-bearing Voucher and must preserve exactly one business mutation,
one immutable manifest identity, and the original RustFS object identities.

Remote generation, embedding, and reranking providers are not required for
P8.8 reliability semantics.
