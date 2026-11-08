# P8-S75G: IA Voucher Evidence UX

## Status

Completed on 2026-10-23.

## User Experience

The authenticated IA composer now provides one approval-version-scoped Voucher
evidence batch with:

- multi-file selection and drag/drop;
- upload progress and explicit `READY` or failed state per file;
- retry and remove actions before submission;
- an approval-time lock that disables evidence mutation;
- a new-approval-version action before later evidence changes;
- immediate return to the login surface after session expiry.

The surface is keyboard reachable and responsive. It remains hidden before
authentication and is reset on logout or protected-surface teardown.

## Runtime Boundary

AE Web uses same-origin authenticated AE API routes for batch creation, upload,
finalization, locking, owner preview and download. The exact immutable manifest
is copied into the grounded-generation admission request. The browser does not
receive a bucket, object key, storage credential, presigned URL or filesystem
path.

NSL WRITE and BUSINESS FORMAL review projections render only display-safe
attachment metadata and protected AE routes. They expose file name, media type,
size and attachment identity without exposing opaque storage identity.

The locked manifest contract was reconciled with the already-admitted S75E
runtime shape during fetch-mode verification. `attachment_count` is part of the
canonical semantic hash, while batch lifecycle fields such as `state` and
`locked_at` are not part of the governed manifest. JSON Schema, positive and
negative examples, runtime validation and the browser adapter now share that
closed shape.

## Authenticated Playwright Evidence

The Chromium smoke authenticated through the existing mock browser boundary,
selected three files (image, PDF and ZIP), waited for all three to become
ready, submitted and locked the manifest, inspected display-safe review
metadata and links, opened a new approval version and logged out.

All eight checks passed:

- anonymous attachment surface hidden;
- multiple selection ready;
- approval submission locks the manifest;
- safe review manifest visible;
- new approval version required;
- logout returns to login;
- storage internals absent;
- Chromium launched through Playwright.

Result: `PASS`, with three selected and three locked files.

## Protected Integration Evidence

The existing P8-S75F protected integration journey was rerun for S75G against:

- actual `nex_ae_test` as `nex_ae_user`;
- actual `nex_wc_test` as `nex_wc_user`;
- actual `nex_oa_test` as `nex_oa_user`;
- actual `nex_eos_test` as `nex_eos_user`;
- digest-pinned RustFS `1.0.1` with SSE-S3 enabled.

It migrated all four services, published immutable evidence, locked the exact
manifest, obtained an OA-authorized WC decision, committed and replayed the EOS
Voucher, rejected manifest substitution and removed all test data and object
bytes. Result: `1 passed`, `0 skipped`. Post-run tenant-prefix counts were zero
in all four databases.

Remote embedding, reranking and generation providers were not required for
this UX and evidence-boundary Slice.

## Regression And Coverage

- AE Web regression: `373 passed`, `0 skipped`.
- Focused browser/manifest regression: `29 passed`.
- Focused AE contract/API/manifest regression: `40 passed`.
- NeX-AE Slice Gate: `5,277 passed`, `42` protected skips.
- NeX-AE statement coverage: `98.31%`.
- NeX-AE branch coverage: `96.28%`.
- Contract validation: `191` schemas, `253` examples, `221` negative examples
  and `9` OpenAPI documents.

The statement and branch coverage values match the P8-S75F baseline.

## Exit Decision

P8-S75G is closed. P8-S75H may now run the protected attachment-bearing
approval and Voucher journey plus the Repository Full Gate without changing
the S75G browser or manifest contracts.
