# MyBee Phase-1 Existing V1 Regression Baseline

**Slice:** S0-02  
**Executed:** 2026-11-09 (Asia/Seoul)  
**Platform baseline ancestor:** `9fe6ddb151bd121c8fb66fbde62cc24cca29eddb`  
**Result:** PASS / PROTECTED LIVE CASES NOT RE-RUN

## Protected Compatibility Boundary

MyBee Phase-1 must preserve all of the following:

```text
EOS VoucherDraft state                         = DRAFT
FINANCE.CREATE_VOUCHER_DRAFT                   = unchanged v1 operation
balanced Decimal lines and tenant isolation    = required
project/account effective-date validation      = required
approved payload hash reuse                    = required
idempotent retry and ACK-loss reconciliation   = no duplicate VoucherDraft
Golden A result                                = COMMITTED / VERIFIED
```

The new accounting candidate and PostedJournal path is additive v2 behavior.
It must not reinterpret a v1 VoucherDraft as posted GL or mutate the v1 schema.

## Executed Regression

```text
./.venv/bin/pytest -q \
  tests/test_nex_eos_p8_s15_voucher_draft.py \
  tests/test_nex_ae_eos_p8_s66_golden_a_commit_journey.py

42 passed, 1 protected skip

./.venv/bin/pytest -q \
  tests/test_nex_ae_eos_p8_s67_golden_a_exactly_once.py \
  tests/test_nex_ae_eos_p8_s68_golden_a_evidence_package.py

11 passed, 1 protected skip
```

No deterministic regression failed. The skipped cases require explicitly
admitted PostgreSQL and remote-provider environments; they were not silently
counted as PASS.

## Existing Protected Evidence

The prior P8 closure remains the protected live evidence baseline:

- `docs/slices/p8_s66_golden_a_eos_commit_journey.md`
- `docs/slices/p8_s92_golden_a_fault_final_rerun.md`
- `docs/slices/p8_s103_final_asbuilt_demo_release_handoff.md`

Those records report actual PostgreSQL/provider execution with a
`COMMITTED / VERIFIED` outcome. S0-02 does not replace or fabricate a new live
receipt. A new protected rerun is mandatory when MyBee changes shared finance,
approval, NSL binding, idempotency, or publication code.

## Coverage

S0-02 changes documentation only. Product statement and branch coverage are
therefore unchanged; existing repository thresholds remain authoritative.
