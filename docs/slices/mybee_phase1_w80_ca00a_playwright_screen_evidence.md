# W80-CA00A: Playwright Screen Evidence Integrity and Retention Boundary

## Scope

- add semantic DOM assertions before named M1 screenshots;
- add private atomic screenshot manifests with size and SHA-256;
- render owner-scoped terminal AgentResult after restart;
- verify and collect screen evidence into the W80 restricted session;
- keep database schema and backend business APIs unchanged.

## Source Audit

The prior protected run produced sixteen screenshots. The second transaction
result was visually correct, but the first result was captured before the result
card appeared. The recovery image was byte-identical to the initial requester
workspace and therefore did not prove user-visible recovery. Both false-positive
paths came from treating API success as sufficient capture admission.

## Verification

- implementation commit: `128048a3`;
- focused Node M1 tests: `17 passed`;
- focused React workspace-route tests: `2 passed`;
- TypeScript typecheck and AE Web production build: passed;
- focused Python runner tests: `32 passed`;
- AE Slice Gate: `6,917 passed`, `53 protected skips`, statement `96.45%`,
  branch `94.67%`;
- exact-head nine-image OCI release set and AE product runtime: passed;
- DGX generation/embedding/reranking preflight: `3/3 passed`;
- actual PostgreSQL/OpenBao/RustFS/DGX/Playwright run: failed closed after
  three first-transaction approvals because the terminal IA AgentResult lacked
  `business_refs` and `business_summary`;
- visual evidence: the primary result region rendered the generic
  `request-processing result`, not the required voucher-result projection;
- cleanup: all eight isolated database schemas removed, `zero_residue=true`.

The failure is not a screenshot timing defect. It is a source-backed business
result propagation gap across PA AgentResult -> WC WorkResult event -> IA
delegated step result. W80-CA00A must not weaken its semantic DOM assertion;
live closure is deferred to a separate corrective contract boundary.
