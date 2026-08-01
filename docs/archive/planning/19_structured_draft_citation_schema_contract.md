# Structured Draft + Citation Schema Contract

Status: Draft seed for Slice 429.

Sources:

- `NP-SRC-02`
  (`02_260723_NeX_Platform_Canonical_Terminology_State_API_Contract_v1.0.md`)
- `NP-SRC-09`
  (`09_260723_NeX_CX_Enterprise_Context_Knowledge_Lifecycle_Design_v1.2.md`)
- `NP-SRC-10`
  (`10_260723_NeX_AE_Work_Assistant_Workspace_Design_v1.4.md`)
- [AE-to-CX Generation Request Package Contract](../../16_ae_cx_generation_request_package_contract.md)
- [CX Generation Execution Record + Lineage Contract](18_cx_generation_execution_record_lineage_contract.md)
- [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md)

This document freezes the first CX-owned structured draft and citation schema
contract. It defines the generated content shape that CX can validate before AE
turns it into a chat answer, Markdown artifact, DOCX/PDF export, or a later
workspace object.

The contract intentionally separates three things:

- CX owns structured draft validation and citation evidence integrity.
- AE owns user-facing rendering, artifact records, previews, and downloads.
- MO owns provider execution metadata, not document semantics.

## Contract Scope

| Area | Owner | Decision |
| --- | --- | --- |
| Structured draft schema | CX | Freeze `cx_structured_draft.v1` as the first generated-content exchange shape. |
| Citation claim schema | CX | Freeze `cx_citation_claim.v1` for source-grounded claims and evidence anchors. |
| Template completeness validation | CX/AE | AE declares required sections; CX validates presence and returns metadata. |
| Artifact rendering | AE | AE renders the draft into Markdown/DOCX/PDF and owns download links. |
| Provider prompt and output parsing | CX | CX normalizes provider output into the structured draft before validation. |
| Provider runtime execution | MO | MO returns text/JSON and usage metadata; it does not validate source semantics. |

This is a logical schema contract, not a physical database design. CX can store
drafts and citations in separate tables or JSON columns as long as API behavior,
hashes, validation statuses, and ownership stay stable.

## Schema IDs

| Schema | Version | Purpose |
| --- | --- | --- |
| `cx_structured_draft.v1` | `1` | Top-level generated draft document. |
| `cx_structured_section.v1` | `1` | Section-level structure for report, proposal, summary, memo, or answer. |
| `cx_structured_block.v1` | `1` | Text, heading, list, table, quote, code, or future block. |
| `cx_citation_claim.v1` | `1` | Link between a generated claim and a CX evidence/source anchor. |
| `cx_draft_validation_result.v1` | `1` | Schema, citation, completeness, and safety validation metadata. |

All schema IDs must be explicit on the wire. UI labels can be localized, but
schema IDs and enum values remain stable English identifiers.

## Structured Draft Root

| Field | Required | Owner | Notes |
| --- | --- | --- | --- |
| `structured_draft_id` | Yes | CX | Stable draft ID linked to one CX generation execution. |
| `cx_generation_id` | Yes | CX | Root execution record from Slice 428. |
| `draft_schema_version` | Yes | Shared | Start with `cx_structured_draft.v1`. |
| `output_kind` | Yes | AE/CX | `chat_answer`, `structured_draft`, `markdown_artifact`, or future kind. |
| `language` | Yes | AE | Korean default; English supported. |
| `title` | No | AE/CX | Draft title or AE artifact title candidate. |
| `summary` | No | CX | Short generated abstract for preview and chat response. |
| `sections` | Yes | CX | Ordered array of section objects. Empty only for rejected/no-answer output. |
| `citations` | Yes when grounded | CX | Ordered or keyed citation claims used by sections/blocks. |
| `draft_status` | Yes | CX | `CREATED`, `VALIDATING`, `VALID`, `INVALID`, `REPAIRED`, or `FAILED`. |
| `content_hash` | Yes | CX | Hash over normalized root, sections, blocks, and citation refs. |
| `normalization_version` | Yes | CX | Normalizer/parser version used before hashing. |
| `created_at` / `updated_at` | Yes | CX | RFC3339 UTC timestamps. |

The root draft must not contain raw bearer tokens, provider credentials, model
paths, or unredacted provider prompts.

## Section Shape

| Field | Required | Notes |
| --- | --- | --- |
| `section_id` | Yes | Stable within the draft. |
| `template_section_id` | No | AE template section ID when available. |
| `section_type` | Yes | `TITLE`, `EXECUTIVE_SUMMARY`, `BODY`, `RISK`, `FOLLOW_UP`, `CONCLUSION`, `APPENDIX`, or future allowlisted value. |
| `heading` | Yes | User-facing heading text. |
| `order_index` | Yes | Zero-based order in the draft. |
| `required` | Yes | True when AE template says the section is mandatory. |
| `blocks` | Yes | Ordered array of block objects. |
| `section_validation_status` | Yes | `VALID`, `MISSING_REQUIRED_BLOCK`, `EMPTY`, `INVALID_CITATION`, or `NOT_CHECKED`. |
| `missing_reason` | No | Required when a required section is empty or missing. |

Required sections come from AE's `template_ref.required_section_ids` and the
selected prompt/template compatibility rules. CX validates that all required
sections appear before returning a successful document-generation result.

## Block Shape

| Field | Required | Notes |
| --- | --- | --- |
| `block_id` | Yes | Stable within the draft. |
| `block_type` | Yes | `paragraph`, `heading`, `list`, `table`, `quote`, `code`, `callout`, or future allowlisted value. |
| `text` | No | Plain text content for paragraph-like blocks. |
| `markdown` | No | Markdown representation when AE can render directly. |
| `items` | No | Array for ordered/unordered list blocks. |
| `table` | No | Structured rows/cells for table blocks. |
| `citation_ids` | Yes when grounded claim exists | Citation claim IDs supporting the block. |
| `evidence_ids` | No | Convenience echo of evidence IDs referenced by citations. |
| `confidence_bucket` | No | `HIGH`, `MEDIUM`, `LOW`, or `UNKNOWN`. |
| `block_validation_status` | Yes | `VALID`, `UNSUPPORTED_BLOCK_TYPE`, `EMPTY`, `UNCITED_CLAIM`, or `NOT_CHECKED`. |

A block can be uncited only when it is clearly connective language, formatting,
section heading text, or an ungrounded mode explicitly allowed by the quality
policy.

## Table Block Shape

Tables are common in reports and proposals. The MVP schema should support them
without forcing AE to parse raw Markdown tables.

| Field | Required | Notes |
| --- | --- | --- |
| `columns` | Yes | Ordered column labels. |
| `rows` | Yes | Ordered rows. |
| `cells` | Yes | Cell values, optional citation IDs, and optional alignment hints. |
| `caption` | No | User-facing caption. |
| `source_table_ref` | No | Future link to extracted table artifacts when available. |

Images, charts, and rich layout objects are deferred. The schema keeps
extension points but does not require multimodal draft blocks in the first MVP.

## Citation Claim Shape

| Field | Required | Notes |
| --- | --- | --- |
| `citation_id` | Yes | Stable citation claim ID inside the draft. |
| `citation_label` | Yes | User-facing label such as `[1]`, `[A]`, or template-specific label. |
| `claim_text_hash` | Yes | Hash over the generated claim span or block content being supported. |
| `evidence_id` | Yes | Evidence item ID from the retrieval package. |
| `retrieval_package_id` | Yes | CX retrieval package that supplied the evidence. |
| `retrieval_package_hash` | Yes | Package hash used for drift detection. |
| `content_object_id` | Yes | Source document or content object ID. |
| `content_version_id` | Yes | Source content version used during retrieval. |
| `chunk_id` | Yes | Chunk that supports the claim. |
| `chunk_policy_id` | Yes | Chunk policy used to create the supporting chunk. |
| `source_anchor` | Yes | Page/slide/sheet/heading/offset anchor when known. |
| `quote_hash` | No | Hash of quoted source span if an exact quote is retained. |
| `support_level` | Yes | `DIRECT`, `INFERRED`, `BACKGROUND`, or `UNSUPPORTED`. |
| `permission_result` | Yes | Safe permission outcome already applied by CX. |

Citation claims reference CX evidence. They do not copy full private source
documents into AE-owned artifact metadata.

## Validation Statuses

| Field | Values |
| --- | --- |
| `structured_draft_validation_status` | `PENDING`, `VALID`, `INVALID`, `REPAIRED`, `FAILED` |
| `citation_validation_status` | `VALID`, `INVALID`, `PARTIAL`, `NOT_REQUIRED`, `FAILED` |
| `template_completeness_status` | `VALID`, `MISSING_REQUIRED_SECTION`, `PARTIAL`, `NOT_REQUIRED` |
| `section_validation_status` | `VALID`, `MISSING_REQUIRED_BLOCK`, `EMPTY`, `INVALID_CITATION`, `NOT_CHECKED` |
| `block_validation_status` | `VALID`, `UNSUPPORTED_BLOCK_TYPE`, `EMPTY`, `UNCITED_CLAIM`, `NOT_CHECKED` |

CX must not mark the root generation execution as `SUCCEEDED` when a required
structured draft validation or citation validation rule fails.

## Citation Validation Rules

| Rule | Required Behavior |
| --- | --- |
| Evidence membership | Every citation `evidence_id` must exist in the referenced retrieval package. |
| Hash match | `retrieval_package_hash` must match the package stored in the generation execution record. |
| Permission continuity | `permission_result` must match the permission snapshot used for retrieval. |
| Source anchor continuity | `source_anchor` must point to the evidence source location or be marked as missing. |
| Unsupported support | `support_level=UNSUPPORTED` makes the citation invalid for grounded claims. |
| Duplicate citation labels | Duplicate labels are allowed only when they intentionally point to the same citation ID. |
| Low confidence | Low-confidence evidence can be returned with warnings only when quality policy allows it. |

For grounded answers, summaries, and document generation, any claim that looks
factual and source-derived should have at least one citation claim unless the
quality policy explicitly allows uncited narrative text.

## Template Completeness Rules

| Rule | Required Behavior |
| --- | --- |
| Required section missing | Set `template_completeness_status=MISSING_REQUIRED_SECTION`. |
| Required section empty | Keep section and mark `section_validation_status=EMPTY`. |
| Required block missing | Mark the section as `MISSING_REQUIRED_BLOCK`. |
| Optional section missing | Do not fail completeness, but include a warning when AE requested it. |
| Section order drift | Preserve received draft order and return ordering warnings rather than silently reordering. |

AE decides whether to show, repair, clone, or re-render an incomplete artifact.
CX returns enough detail for AE to make that user-facing decision.

## Hashing And Normalization

CX persists the following hashes with the generation execution:

```text
structured_draft_content_hash
structured_draft_schema_hash
citation_claims_hash
template_completeness_hash
validation_result_hash
```

The hash input should be normalized JSON with stable key ordering, stripped
volatile timestamps, and canonical citation ordering by `citation_id`. Hashes
support reproducibility and audit, not deterministic LLM text generation.

## AE Safe Read Shape

`GET /api/v1/generations/{generation_id}/structured-draft` should expose a safe
draft view to AE.

| Field | Included | Notes |
| --- | --- | --- |
| Root draft metadata | Yes | Draft ID, schema version, status, content hash, language, title, summary. |
| Sections and blocks | Yes | User-facing content, block type, section IDs, validation status. |
| Citation claims | Yes | Citation labels, evidence IDs, source anchors, support levels, safe snippets. |
| Validation result | Yes | Schema, citation, completeness, and repair metadata. |
| Provider prompt body | No | Only hash/retention metadata when policy allows. |
| Provider credentials and endpoint URLs | Never | No runtime secrets or private provider host details. |
| AE artifact refs | No | AE owns artifact records and download links. |

AE can render this safe read view into chat, preview, Markdown, DOCX, or PDF
without receiving MO runtime secrets or unrelated CX corpus data.

## Error Codes

| Error Code | Trigger |
| --- | --- |
| `cx.structured_draft_schema_invalid` | Draft root, section, block, or table shape violates schema. |
| `cx.citation_anchor_missing` | Required citation has no usable source anchor. |
| `cx.citation_evidence_mismatch` | Citation points to evidence outside the retrieval package. |
| `cx.citation_permission_mismatch` | Citation permission metadata does not match the retrieval snapshot. |
| `cx.required_section_missing` | AE-required template section is absent. |
| `cx.required_section_empty` | AE-required section exists but contains no useful blocks. |
| `cx.unsupported_block_type` | Provider output contains a block type outside the allowlist. |
| `cx.structured_draft_repair_failed` | Repair was attempted but validation still failed. |

All errors use the common `application/problem+json` envelope and preserve
`request_id`, `trace_id`, `cx_generation_id`, and safe actor metadata.

## Contract Tests To Derive

- CX structured draft responses include `structured_draft_id`,
  `cx_generation_id`, `draft_schema_version`, `sections`, `citations`, and
  `content_hash`.
- Required template sections are present or produce
  `cx.required_section_missing`.
- Citation claims include `citation_id`, `citation_label`, `evidence_id`,
  `retrieval_package_id`, `content_version_id`, `chunk_id`, `chunk_policy_id`,
  `source_anchor`, and `support_level`.
- Citation evidence outside the retrieval package produces
  `cx.citation_evidence_mismatch`.
- Unsupported block types produce `cx.unsupported_block_type`.
- `structured_draft_content_hash`, `citation_claims_hash`, and
  `validation_result_hash` are stable for normalized equivalent drafts.
- AE safe read view excludes provider credentials, provider endpoint URLs, raw
  bearer tokens, and full private source documents.

## Next Inputs

This contract should feed:

- AE artifact rendering handoff contract, starting from
  [AE Artifact Rendering Handoff Contract](20_ae_artifact_rendering_handoff_contract.md).
- Generation progress event contract.
- Generation failure, repair, and retry policy contract.
- AG generation audit and lineage dashboard requirements.
- JSON Schema files for `cx_structured_draft.v1` and `cx_citation_claim.v1`.
