# W70-S8-01B Canonical Schema and OpenAPI Tool Contract Admission

## Status

- Slice: `W70-S8-01B`
- Status: `IMPLEMENTED_AND_VERIFIED`
- Date: `2026-11-15`
- Owners: NeX EOS, NeX Runtime, NeX AE, NeX MyBee
- Database migration: none
- Remote model provider: not required

## Decision

W70 Tool contracts are admitted by binding every S8-01A canonical operation
identity to its exact current EOS OpenAPI operation. EOS OpenAPI and its
referenced EOS JSON Schemas remain the wire authority. MyBee does not copy or
redefine those business schemas.

The immutable admission artifact is:

```text
contracts/admissions/nex_eos/w70_tool_contract_admission.v1.json
```

It records, for all 18 W70 Tools:

- canonical and provider operation identities;
- exact HTTP method, path, and OpenAPI JSON Pointer;
- required and optional path, query, and header parameters;
- request-body component and canonical schema authority;
- every successful response status and schema authority; and
- the pinned Tool inventory and EOS OpenAPI byte digests.

Its semantic content digest is:

```text
sha256:b6b37073f96d9c7a6ed0a3bdb3e6dbd03ddab4b4396654f00b2976e48dcacedd
```

The pinned EOS OpenAPI digest remains:

```text
sha256:2d4fe5c257c1e8dd2ba39d92256011dd814407eb63ac9ea3b2c5ffab9b654d06
```

## Contract Typing Boundary

Eleven Tool contracts have schemas for all successful responses and are
`fully_typed`. Seven current candidate/deferred contracts include at least
one success response represented only by an HTTP status:

- `FINANCE.COST_ALLOCATION_PLAN.RELEASE`;
- `FINANCE.FX_RATE.HISTORY`;
- `FINANCE.FX_RATE.IMPORT`;
- `FINANCE.FX_RATE.RESOLVE`;
- `FINANCE.VOUCHER_CANDIDATE.GET_V2`;
- `PROJECT.WORK_ASSIGNMENT.ASSIGN`; and
- `PROJECT.WORK_CODE_SET.APPROVE`.

This Slice records those source gaps as `OPENAPI_STATUS_ONLY`; it does not
invent response payloads. The fail-closed loader rejects any Tool in
`ACTIVE`, `ACTIVE_COMPATIBILITY`, or `SHADOW` state when one of its successful
responses remains status-only. Candidate/deferred recording therefore cannot
silently become runtime activation.

Request and response schema authority is classified as:

- `CANONICAL_JSON_SCHEMA` for an EOS component linked to
  `contracts/schemas/service/nex_eos`;
- `OPENAPI_INLINE_SCHEMA` for a schema owned directly by the canonical EOS
  OpenAPI component set;
- `OPENAPI_PARAMETERS_ONLY` for a request without a JSON body; or
- `OPENAPI_STATUS_ONLY` for a successful response without a body schema.

## Fail-Closed Admission

`mybee_ax.integrations.nex_tool_contracts` verifies:

- exact artifact fields, version, revision, status, and semantic digest;
- exact S8-01A inventory digest and EOS OpenAPI byte digest;
- lexical order, uniqueness, and complete 18-operation coverage;
- provider identity, route, method, parameters, and operation pointer;
- service scope, OA business action, and side-effect metadata;
- request-body and all 2xx response schema bindings; and
- existence and EOS ownership of external canonical schema files.

Three repository-visible negative examples prove that lowercase methods,
non-2xx success declarations, and Skill-local schema ownership are rejected.
Semantic mutation tests additionally cover route, source digest, authority
metadata, parameter, request, response, operation coverage, and activation
drift.

## Verification

Contract package validation:

```text
contract_validation=pass
schemas=265 examples=316 negative_examples=260 openapi=10
```

Focused S8-01A/S8-01B identity and admission Gate:

```text
95 passed
nex_tool_contracts statement/branch coverage: 97%
```

Extended MyBee, Golden A capability/activator, and contract regression:

```text
626 passed, 1 skipped
```

The one skip is the existing opt-in W40-CA02 PostgreSQL/HTTP protected
acceptance. S8-01B changes no database or live provider behavior.

## Preserved Boundaries

S8-01B introduces no database migration, NSL compiler/runtime change,
capability activation, cross-service private import, remote-provider call, or
new business schema. W60 immutable GL lineage, authorization, Project
entitlement, P&L privacy, and historical Golden A compatibility remain
unchanged.

## Handoff

`W70-S8-01B` is closed. `W70-S8-01C` may build the D04/D12 Skill-Pack
manifest and artifact-digest layer over this admitted identity and contract
baseline. It must retain the activation guard for every status-only contract.
