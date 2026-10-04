# Slice 1343: AE protected upload owner claims

## Outcome

- Added one AE upload owner policy for all runtime profiles.
- Preserved deterministic `local_mock` owner defaults for existing local
  regression and compatibility paths.
- Protected `test`, `local_live`, `staging_live`, and `production` profiles now
  reject missing owner scope and the `local-tenant`/`local-user` placeholders.
- Browser uploads remain OA-claim authoritative. Signed service uploads remain
  supported only when tenant and owner scope are explicit.
- Both JSON and multipart upload routes enforce the policy before CX is called.

## Boundary

This Slice does not persist handoff metadata and does not contact PostgreSQL or
remote model providers. Slice 1344 owns AE handoff persistence. CX remains the
sole owner of source bytes and derived private content.

## Verification

- Focused regression: `35 passed`.
- Slice Gate (`nex-ae-api`): `2794 passed`, `5 skipped`; statement coverage
  `98.37%`, branch coverage `96.24%`; all `5/5` commands passed.
- Changed policy and evidence statement/branch coverage: `100.00%` / `100.00%`.
- Policy evidence requires seven checks, two stable denial classes, and
  `next=1344`.
