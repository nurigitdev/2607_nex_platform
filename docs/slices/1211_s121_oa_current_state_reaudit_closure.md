# Slice 1211: S121 OA current-state re-audit closure

## Closure

S121 re-audited OA-FR-001 through OA-FR-005 across ten sequential Slices. The
current subject, membership, employee/password login, session, persistence, and
cross-service boundaries are reusable, but this checkpoint does not certify
production authentication completeness.

## Confirmed State

- All 5 OA requirements are traceable; 1 is implemented and 4 remain partial.
- The 11-migration chain and 5 core tables are structurally clean.
- Capability metadata and resolver transport-error privacy were repaired across
  5 surfaces.
- Actual `nex_oa_test` evidence passed 11/11 migrations, 22/22 workflow checks,
  and post-cleanup residue verification.
- Remaining quantified work is 4 lifecycle gaps, 5 security gaps plus 1 partial
  control, 4 cross-service trust refactors, and 25 contract/OpenAPI drift items.

## S122 Handoff

S122 should implement OA production identity trust and security hardening in
this order:

1. Fail-closed signed service tokens/JWKS and route-specific service scopes.
2. Random session identifiers, atomic failed-login lockout, and secure production
   browser authentication defaults.
3. Argon2id rehash/credential rotation, identity lifecycle transitions,
   deprovision revocation, and safe authentication audit events.
4. Cross-service resilience and OA OpenAPI/negative fixture closure.
5. Group identity design, while keeping SSO/MFA/recovery explicitly post-MVP.

No parallel Alembic history is introduced. Versioned SQL with
`schema_migrations` remains canonical.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_s121_oa_current_state_reaudit_closure.py --summary

./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_s121_oa_current_state_reaudit_closure.py \
  --coverage-target scripts/smoke/run_s121_oa_current_state_reaudit_closure.py \
  --smoke scripts/smoke/run_s121_oa_current_state_reaudit_closure.py

./scripts/quality/run_quality_gate.sh
```

Closure marker: `READY_FOR_TARGETED_S122_HARDENING`; feature marker:
`CONFIRMED_GAPS_NOT_PRODUCTION_AUTH_COMPLETE`.

Observed Full Gate:

- Python regression: `9,812 passed`, `11 skipped`, `123 warnings`.
- Statement coverage: `98.63%`; branch coverage: `97.04%`.
- Contract validation: 130 schemas, 188 examples, 157 negative examples, and
  7 OpenAPI documents.
- AE Web Node regression: `293/293` passed.
- S121 closure smoke: 8/8 audits passed; lifecycle gaps 4, security gaps 5,
  contract drift 25; next requirement `S122`.
