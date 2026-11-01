# GB2-CA00-S20F: Retrieval, Attachment, and Ingestion Edge Hardening

## Scope

- Harden AG retrieval filtering, permission-safe evidence projection, malformed evidence handling, and unavailable-source classification.
- Harden AE voucher attachment cross-tenant lookup, publication/removal replay, concurrent mutation, and post-write row-loss classification.
- Harden CX ingestion owner visibility, malformed retrieval lineage, storage metadata normalization, and unsupported private-storage rejection.
- Preserve product APIs, persistence schemas, and remote-provider contracts.

## Changes

- Added deterministic tests for retrieval time/calibration filters, `NO_ANSWER` and low-confidence projections, denied permission redaction, and malformed score/evidence types.
- Added attachment tests for object lookup isolation, idempotent cleanup, publication failures, concurrent item/batch mutation, and missing rows after update/finalization.
- Added ingestion tests for cross-owner retrieval hiding, malformed evidence lineage, invalid job/document ownership, object-storage path normalization, and invalid storage/subject metadata.
- No production source or database migration changed.

## Protected Evidence

- AE `nex_ae_test` attachment persistence/restart smoke: `1 passed`.
- CX `nex_cx_test` ingestion operations smoke: PASS, checkpoint version `2`, residue `0`, failed checks `0`.
- The CX smoke explicitly reports `dgx_required=False`.
- Remote generation, embedding, and reranking providers were unavailable and were not required for this Slice.

## Service Gates

- AG Slice Gate: `2,580 passed`; service statement `99.02%`, branch `96.96%`; `retrieval_operations.py` statement `96.18%`, branch `95.07%`.
- AE Slice Gate: `5,767 passed, 45 skipped`; service statement `97.69%`, branch `95.83%`; `voucher_attachments.py` statement `97.12%`, branch `96.09%`.
- CX Slice Gate: `2,501 passed`; service statement `98.96%`, branch `98.11%`; `ingestion.py` statement `97.70%`, branch `95.76%`.
- Contract validation, golden-journey transition audit, and demo/product dependency audit passed in all service gates.

Protected tests skipped in ordinary service gates are not counted as PostgreSQL evidence; the applicable AE and CX test-database checks above were explicitly enabled and executed separately.

## Fifth-Slice Checkpoint

The cumulative S20B-S20F Checkpoint Gate passed:

- `18,153 passed, 132 skipped`.
- Product/service statement coverage: `98.54%`.
- Product/service branch coverage: `97.09%`.
- Target scope branch coverage: AG `95.77%`, AE `96.09%`, CX `95.76%`.
- Contract schemas/examples/negative examples/OpenAPI validation: PASS.
- Golden-journey transition and demo/product dependency audits: PASS.

## Outcome

Retrieval, attachment, and ingestion denial/replay/conflict paths now have explicit deterministic coverage and applicable PostgreSQL evidence. The cumulative checkpoint remains healthy without making a remote-provider claim in an offline environment.
