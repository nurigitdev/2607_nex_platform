# CP-M1-GA-RET-02A.0: Mixed Runtime Primitive Extraction and Quarantine Reconciliation

## Status

- State: `CLOSED`
- Date: `2026-11-16`
- Parent: `CP-M1-GA-RET-02A`
- Database migration: none
- Public API change: none
- Remote provider: not required

## Finding

The initial AE coverage-ownership inventory found that the canonical product
runtime imported two modules recorded as Golden A historical quarantine:

```text
product_runtime_profile
  -> m1_installed_skill_runtime
  -> product_controlled_skill
  -> golden_a_planning
```

The prior RET-02 Gate checked selected source files for direct import strings.
It did not traverse the local Python import graph, so this transitive binding
was not detected. Runtime inspection confirmed that importing
`product_runtime_profile` loaded both historical modules into `sys.modules`.

## Resolution

1. Added `controlled_skill_runtime.py` as the scenario-neutral owner of:
   - approval wait and resume lifecycle;
   - controlled execution authority;
   - fresh OA authorization access;
   - verified principal projection; and
   - controlled-WRITE outcome mapping.
2. Rebound the installed M1 D04 runtime to the neutral lifecycle and authority
   primitives without changing its signed Skill, adapter, or business logic.
3. Preserved `product_controlled_skill.py` and `golden_a_planning.py` byte-for-
   byte as hash-pinned historical replay assets.
4. Added a recursive AST-based local import graph rooted at the canonical AE
   process, product profile, semantic admission, and planning profile.
5. Extended the quarantine artifact with the exact recursive guard contract,
   required neutral runtime, and forbidden historical modules.
6. Extended the RET-02 Gate to fail when any hash-pinned historical module is
   reachable from the canonical active graph.

## Preserved Boundaries

- Golden A remains unavailable for new selection and canonical deployment.
- The generalized D04/D12 registry, signed release, and activation remain
  unchanged.
- Error codes, approval lifecycle, controlled-WRITE state mapping, and OA
  freshness semantics remain compatible.
- No database, service API, provider, or browser boundary changed.

## Verification

- focused neutral/M1/quarantine regression: `36 passed`
- Golden A quarantine artifact rebuild/check: PASS
- recursive quarantine Gate: PASS
- actual Python import isolation: PASS
- AE Slice Gate: PASS (`exit_code=0`, 5/5 commands, 465.602 seconds)
- AE statement coverage: `37,411 / 39,011 = 95.8986%`
- AE branch coverage: `11,666 / 12,404 = 94.0503%`
- `git diff --check`: PASS

The extraction introduced a new active module into the AE denominator, so the
aggregate statement percentage is temporarily below the RET-02 baseline while
remaining above the canonical `95.00%` Slice Gate. The parent RET-02A sequence
will reconcile explicit test ownership and harden active branches toward its
separate `96.25%` / `94.50%` margin targets. No historical module was imported
or executed to raise the aggregate.

The next boundary is `CP-M1-GA-RET-02A.1` coverage ownership inventory and
baseline freeze.
