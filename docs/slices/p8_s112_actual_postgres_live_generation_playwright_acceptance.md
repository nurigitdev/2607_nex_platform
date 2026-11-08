# P8-S112: Actual PostgreSQL, Live Generation, and Playwright Acceptance

## Scope

P8-S112 closes the P8-CA05 protected acceptance path with actual OA, AE, WC,
and EOS PostgreSQL test databases, live generation, and an authenticated
Chromium journey. It does not use embedding or reranking for business
execution, and it adds no table or migration.

The protected journey is:

```text
Korean NVT create prompt
  -> live INTENT generation
  -> EOS NVT CREATE / GET / LIST / UPDATE
  -> EOS Project CREATE

Korean multi-member prompt
  -> live INTENT generation
  -> exact tenant-scoped Project resolution
  -> OA employee batch resolution
  -> WC NSL_WRITE approval
  -> EOS PROJECT.MEMBERSHIP.ADD_MANY
  -> exact idempotent replay
  -> AE result projection
  -> authenticated AE Web Chat rendering
```

## Authority Boundary

The AE INTENT prompt registry is advanced to v6. The previous v3, v4, and v5
profiles remain immutable historical lineage. v4 introduced the NVT
CREATE/GET/LIST/UPDATE vocabulary. The first live run showed why an additional
authority rule was required: a generation model may infer that an employee is
missing, a name is mismatched, or a Project code is ambiguous even though
those facts are owned by OA and EOS. v5 captured the authority boundary, and
v6 makes the NVT-versus-`GENERAL_ANSWER` fallback rule unambiguous.

v6 therefore requires the model to preserve employee IDs and optional name
hints without deciding identity status, employment status, name validity, or
Project existence. OA employee resolution and the EOS Project repository are
the only authoritative sources. Model output remains an untrusted semantic
candidate and cannot grant tenant, identity, approval, or mutation authority.

## Browser Integration

The existing authenticated AE Web shell now carries the bounded
`project_membership_batch_result` through:

- fetch client normalization;
- generation lifecycle state;
- presentation validation;
- normal and retry assistant-message rendering.

The protected Playwright journey logs in, submits a multi-member Korean
request, and verifies the partial result surface. It observes one applied
member and two rejected candidates with the safe Korean reasons for name
mismatch and employee-not-found, then logs out and verifies cleanup. The S112
runner maps these observations onto the existing shared credential Playwright
harness instead of creating a second authentication harness.

## Protected Evidence

The protected acceptance completed on 2026-10-25 with:

- actual PostgreSQL identities `nex_oa_test/nex_oa_user`,
  `nex_ae_test/nex_ae_user`, `nex_wc_test/nex_wc_user`, and
  `nex_eos_test/nex_eos_user`;
- all four migration inventories current: OA 18, AE 60, WC 13, EOS 15;
- live model profile `general-llm-default`, model reference `Qwen3.5-4B`;
- two live `INTENT` requests, for `PROJECT.NVT_PROJECT.CREATE` and
  `PROJECT.MEMBERSHIP.ADD_MANY`;
- OA batch result: 3 requested, 1 admitted/applied, 2 rejected;
- WC approval and EOS exact idempotent replay verified;
- authenticated Chromium result rendering and logout verified;
- backend and browser cleanup complete with zero protected-journey residue;
- `10/10` protected checks passed.

The MO readiness profile also validates the configured embedding and reranker
routes, but this S112 business journey invokes generation only. The committed
report contains no database endpoint, provider endpoint, credential, token,
or raw prompt.

## Verification

- focused Python regression: `205 passed`;
- AE Web full Node regression: `386 passed`, `0 failed`;
- AE service Slice Gate: `5,517 passed`, `44 skipped`, statement `98.35%`,
  branch `96.38%`;
- contract validation: `207` schemas, `271` positive examples, `229`
  negative examples, and `9` OpenAPI documents;
- protected OA/AE/WC/EOS PostgreSQL, live generation, and Playwright runner;
- protected result: `10/10` checks and zero residue.

The protected evidence is recorded in
`reports/acceptance/p8-s112-protected.json`.

## Exit

P8-S112 is complete when the focused regressions and AE Slice Gate pass, the
protected runner reports `10/10`, and both backend and browser cleanup leave no
journey residue. P8-S113 may then run the repository Full Gate and freeze the
P8-CA05 as-built handoff.
