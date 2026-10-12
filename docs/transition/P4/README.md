# P4 Transition Implementation Baseline

**Status:** CONTROLLED P4 READING INDEX
**Frozen product baseline:** `docs/frozen/v2.1/`
**Transition baseline:** `docs/transition/`

This directory contains the implementation baseline for P4 Agent Runtime
Foundation. It does not amend any document under `docs/frozen/v2.1/`.

## Required Reading Order

1. `docs/frozen/v2.1/README_FROZEN_BASELINE.md`
2. Frozen Priority-A documents and machine-readable contracts
3. Frozen Agent-to-NSL Integration Contract
4. Frozen Result Publication boundary
5. `docs/transition/00` through `docs/transition/05`
6. `P4_Agent_Runtime_Foundation_SRS_v1.0.md`
7. `P4_Result_Persistence_and_Publication_Design_Hardening_FROZEN_v1.0.md`
8. `P4_Issue_Register_v1.0.md`
9. `P4_Result_Persistence_Publication_Traceability_v1.0.md`
10. Current branch source code

## Authority Rule

```text
Frozen semantic authority
> P4 SRS
> P4 Design Hardening Frozen decisions for SRS gaps
> P4 Issue Register and traceability records
> implementation convenience
```

The hardening document is additive. If it appears to conflict with Frozen
semantics or the P4 SRS, implementation must stop and record the conflict. It
must not silently reinterpret the higher authority.

## Change Rule

- No P4 implementation may modify `docs/frozen/v2.1/`.
- P4 implementation must preserve the v1.0 public Chat/RAG behavior.
- STEP 9 must map every active hardening requirement to a Slice and test.
- Source implementation must not begin until the STEP 9 plan is reviewed.
