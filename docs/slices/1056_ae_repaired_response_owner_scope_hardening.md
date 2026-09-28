# Slice 1056: AE Repaired-Response Owner-Scope Hardening

## Goal

Close the legacy owner-isolation gap in repaired-response handoff, review, and
decision routes while preserving AG service-token compatibility.

## Implementation

- Replaced service-only route authorization with the common AE facade auth
  boundary, accepting internal service claims and browser user claims.
- Added exact `(tenant_id, owner_user_id)` get/list methods to both in-memory
  and SQLAlchemy handoff and decision stores.
- Applied owner filtering before browser handoff/review/decision projection.
- Restricted decision reads to the owner scope inherited from the selected
  handoff, including internal service calls.
- Bound browser-created decision actor identity to the authenticated claim.

## Security And Compatibility

- Cross-owner handoff and decision details return `404`; cross-owner
  collections are empty.
- Cross-owner browser handoff creation is rejected before CX is called.
- Existing AG service-token create/read/review/decision flows remain valid.
- No table or migration is added; existing indexed tenant/owner columns are
  used in SQL predicates.

## Verification

```bash
scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_nex_ae_repaired_responses.py \
  --test tests/test_ae_citation_quality_api.py \
  --coverage-target services/nex-ae-api/nex_ae_api/repaired_responses.py \
  --coverage-target services/nex-ae-api/nex_ae_api/repaired_response_decisions.py
```

## Observed Evidence

- Checkpoint Gate: pass (`8000 passed`, `2` separately protected PostgreSQL
  smoke tests skipped).
- Statement coverage: `98.66%` (threshold `95%`).
- Branch coverage: `96.63%` (threshold `94%`).
- Target coverage:
  - `repaired_responses.py`: statement `100%`, branch `100%`.
  - `repaired_response_decisions.py`: statement `100%`, branch `100%`.
- Contract validation: pass (`100` schemas, `156` positive examples, `119`
  negative examples, `7` OpenAPI documents).
