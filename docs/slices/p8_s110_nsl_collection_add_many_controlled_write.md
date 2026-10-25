# P8-S110: NSL Collection ADD_MANY Controlled WRITE

## Scope

P8-S110 adds `PROJECT.MEMBERSHIP.ADD_MANY` v1.0.0 to the admitted NSL v0.2.1
Project WRITE artifact set. One Skill invocation accepts the S108 canonical
`target_subject_ids` collection and maps to one S109 EOS BusinessOperation. It
does not fan out into repeated single-member operations.

The Skill accepts between one and fifty canonical subject IDs, permits exactly
one WRITE tool call, and has no loop authority. `member_role` and the OA
`resolution_evidence_hash` remain part of the approved business payload.

## Authority Boundary

AE exposes the Skill in the capability snapshot but deliberately leaves it out
of the generic single-operation candidate parser. S111 owns natural-language
batch orchestration. S110 only binds a previously admitted S108 batch to the
exact source-backed NSL artifact.

The binding preserves all of the following without model rewriting:

- S108/S109 `payload_hash`
- sorted `target_subject_ids`
- Project, tenant, requester, role, and OA evidence identity
- NSL skill version, semantic hash, source hash, and source revision
- approval display projection

`model_authority=false` is explicit. Missing, duplicate, malformed, or
contract-incompatible artifact admission fails closed before execution.

## Source-Backed Artifact

- NSL source repository revision:
  `f5d899bb611ee2cd65ce9f6544ed6e51b450b7d4`
- Skill source SHA-256:
  `sha256:723f5683a4b6a9baa458874878d3b4956ecb259feca9077629c86500a127efe5`
- Skill semantic hash:
  `sha256:9a3362e5906cf9d62d720d77369acc6e39d40afcb1f0ccb59726b0ea85e7af02`
- WRITE artifact manifest SHA-256:
  `sha256:d9ec73d53392ab6df670886cbed1ddf8dd093a7c86ddb8195880fcc8c7f34392`

The NSL repository full gate passed `2329` tests with `98.95%` total coverage.

## Contracts

P8-S110 advances the Project WRITE admission to seven exact artifacts and adds
the strict `p8.project_membership_batch_skill_binding.v1` contract plus a
positive example. No database table, migration, public route, or operation
payload field is added.

## Verification

- source-backed focused regression and contract suite: `184 passed`
- AE Slice Gate: `5495 passed`, `44` expected protected-profile skips
- AE statement coverage: `98.35%`
- AE branch coverage: `96.36%`
- `project_membership_batch.py`: `100%` statement and branch coverage
- contract validation: `206` schemas, `270` positive examples, `229` negative
  examples, and `9` OpenAPI documents
- Slice Gate commands: `3/3`, `358.601` seconds
- NSL repository full gate: `2329 passed`, `98.95%` total coverage

The AE coverage report is `reports/quality/p8-s110-ae.coverage.json`.

## Exit

P8-S110 is complete when the source-backed artifact admission, exact approval
binding, contract validation, focused regression, and AE Slice Gate pass.
P8-S111 may then activate the natural-language multi-member workflow and its
user-facing aggregate result projection.
