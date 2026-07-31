# Common Schema + Contract Package Layout

Status: Draft seed for Slice 443.

Sources:

- [Common Contract Freeze Candidate Map](11_common_contract_freeze_candidate_map.md)
- [Generation Contract JSON Schema Seed](26_generation_contract_json_schema_seed.md)
- [Generation OpenAPI Endpoint Seed](27_generation_openapi_endpoint_seed.md)
- [Platform Development Environment Freeze](32_platform_development_environment_freeze.md)
- [Cross-Service Traceability Matrix](31_cross_service_traceability_matrix.md)

This document freezes the first repository layout for JSON Schema, OpenAPI,
examples, and contract fixtures. It keeps shared contracts explicit without
forcing an early shared runtime utility package.

## Package Principle

| Principle | Decision |
| --- | --- |
| Contract first | Schemas and OpenAPI files are versioned before implementation code depends on them. |
| No hidden runtime coupling | Services may generate code from contracts, but must not share private database models. |
| Service ownership | Each service owns its API files; shared definitions live under common schemas. |
| Examples are tests | Example payloads must validate and become contract fixtures. |
| Major version stability | Breaking changes require new major schema/API versions. |

## Target Layout

```text
contracts/
  README.md
  schemas/
    common/
      problem_json.v1.schema.json
      trace_refs.v1.schema.json
      actor_refs.v1.schema.json
      common_job.v1.schema.json
      generation_progress_event.v1.schema.json
    generation/
      ae_cx_generation_request.v1.schema.json
      ae_cx_generation_response.v1.schema.json
      cx_mo_generation_request.v1.schema.json
      cx_mo_generation_response.v1.schema.json
      cx_generation_execution.v1.schema.json
      cx_structured_draft.v1.schema.json
      cx_citation_claim.v1.schema.json
      ae_artifact_handoff.v1.schema.json
      ae_artifact_link.v1.schema.json
      generation_recovery_policy.v1.schema.json
      generation_compatibility_rule.v1.schema.json
      ag_generation_audit_event.v1.schema.json
    service/
      nex_oa/
      nex_cx/
      nex_mo/
      nex_ae_api/
      nex_ag/
  openapi/
    common-components.yaml
    nex-oa.openapi.yaml
    nex-cx.openapi.yaml
    nex-mo.openapi.yaml
    nex-ae-api.openapi.yaml
    nex-ag.openapi.yaml
  examples/
    generation/
    retrieval/
    artifact/
    audit/
    auth/
  tests/
    fixtures/
    negative/
```

`nex-ae-web` consumes API contracts but does not own backend OpenAPI files.

## Ownership Rules

| Area | Owner | Rule |
| --- | --- | --- |
| `schemas/common` | Platform contract maintainers | Only cross-service primitives and enums. |
| `schemas/generation` | AE/CX/MO/AG shared ownership by contract | Generation-specific request/response/event/artifact/audit schemas. |
| `schemas/service/nex_*` | Owning service | Service-local resources not shared across service boundaries. |
| `openapi/nex-*.openapi.yaml` | Owning service | Public/admin API surface for that service. |
| `examples` | Contract maintainers plus service owners | Must validate and remain redacted. |
| `tests/fixtures` | Contract test maintainers | Positive fixtures used by contract test suite. |
| `tests/negative` | Contract test maintainers | Rejection fixtures for unknown fields, enum errors, redaction, and forbidden fields. |

## Versioning Policy

| Change Type | Policy |
| --- | --- |
| Add optional response field | Same major version allowed. |
| Add required request field | New major version unless defaulting is explicit and tested. |
| Remove field | New major version. |
| Rename field | New major version. |
| Add enum value | Same major version only when unknown enum handling is documented and tested. |
| Change meaning of field | New major version. |
| Tighten validation | New minor/patch only if no existing valid payload breaks. |

Schema IDs should include explicit `.v1` style names. OpenAPI files should carry
service API version and contract catalog version.

## Example Payload Policy

| Example Type | Requirement |
| --- | --- |
| Positive examples | One minimal and one realistic example per public write/read contract. |
| Negative examples | At least one forbidden-field, unknown-enum, missing-required, and redaction case for high-risk contracts. |
| Secrets | Use placeholders such as `<redacted>` only. |
| Provider paths | Never include private model paths or raw host credentials. |
| Raw documents/prompts | Avoid full content; use short sanitized snippets or hashes. |

Examples should be small enough to review in pull requests.

## Contract Test Hooks

| Hook | Requirement |
| --- | --- |
| Schema validation | Validate every example against its JSON Schema. |
| OpenAPI validation | Validate OpenAPI examples and component references. |
| Backward compatibility | Compare current schemas against previous frozen versions. |
| Error envelope | Validate every documented error response uses `problem_json.v1`. |
| Redaction | Scan examples and contract fixtures for forbidden secret-like keys. |
| Service ownership | Check endpoint tags and file location match owning service. |

## Guardrails

- Do not put SQLAlchemy models, ORM base classes, or service database types in
  the contract package.
- Do not make frontend UI labels the source of enum values.
- Do not let examples become large private document corpora.
- Do not allow service-specific private fields to leak into common schemas.
- Do not introduce a shared runtime library until contract duplication becomes
  a real implementation pain.

## Next Inputs

This layout should feed:

- Testing strategy detail, starting from
  [Testing Strategy v0.1 Detail](34_testing_strategy_v0_1_detail.md).
- First sprint backlog for contract package bootstrap, starting from
  [Implementation Roadmap + First Sprint Backlog](36_implementation_roadmap_first_sprint_backlog.md).
- Service-specific OpenAPI/schema implementation slices.
- CI contract validation command design.
