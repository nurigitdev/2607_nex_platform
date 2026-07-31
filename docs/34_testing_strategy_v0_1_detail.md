# Testing Strategy v0.1 Detail

Status: Draft seed for Slice 444.

Sources:

- [Testing Strategy Skeleton](05_testing_strategy_skeleton.md)
- [Generation E2E Acceptance + Contract Test Plan](28_generation_e2e_acceptance_contract_test_plan.md)
- [Cross-Service Traceability Matrix](31_cross_service_traceability_matrix.md)
- [Platform Development Environment Freeze](32_platform_development_environment_freeze.md)
- [Common Schema + Contract Package Layout](33_common_schema_contract_package_layout.md)

This document freezes the first detailed testing strategy for NeX-Platform MVP.
It carries forward the useful NeX-PCX discipline: small slices, focused tests,
single-pass regression coverage, branch coverage awareness, Playwright evidence
for UI changes, mock-first provider testing, and separate live smoke evidence.

## Test Philosophy

| Principle | Decision |
| --- | --- |
| Mock-first correctness | CI must prove behavior without DGX/vLLM availability. |
| Live smoke is evidence | Live provider checks are valuable but should not replace deterministic tests. |
| Contract before implementation | JSON Schema/OpenAPI examples become validation fixtures. |
| One quality gate | Run regression and coverage in one command whenever possible. |
| Branches matter | Branch coverage is reported and treated as a first-class gate. |
| Evidence stays small | Screenshots, smoke markdown, and contract fixtures should be reviewable. |

## Test Layers

| Layer | Scope | Required For MVP |
| --- | --- | --- |
| Unit | Pure functions, policy decisions, tokenizers, prompt/template compatibility, validators. | Yes |
| Repository integration | Service-owned database migrations, repositories, transactions, freshness checks. | Yes |
| API integration | FastAPI/service endpoints, auth claims, errors, filters, pagination, idempotency. | Yes |
| Contract | JSON Schema, OpenAPI examples, service-to-service request/response payloads. | Yes |
| Mock E2E | AE -> CX -> MO mock -> CX -> AE artifact -> AG read path. | Yes |
| UI | Korean-default AE/AG flows with Playwright screenshots for visible changes. | Yes when UI changes |
| Live smoke | DGX embedding/reranker/vLLM route health and request evidence. | Protected/manual |
| Operations | Startup, shutdown, readiness, queue drain, provider metrics, audit export. | Yes for release hardening |

## Quality Gate

The implementation should provide a single quality gate command that runs
regression tests and coverage together.

```bash
NEX_PROFILE=test \
NEX_TEST_DATABASE_URL="postgresql://<service_test_user>:<secret>@127.0.0.1:5432/<service_test_db>" \
  scripts/quality/run_quality_gate.sh
```

The gate must report:

- Regression pass/fail.
- Statement coverage percentage.
- Branch coverage percentage.
- Threshold values.
- Slowest test summary when available.
- Contract fixture validation summary.

The first policy target is statement coverage 95% and branch coverage 85% unless
the implementation team records a temporary written exception.

## Required Branch Coverage Themes

| Theme | Branches To Exercise |
| --- | --- |
| Auth | Valid token, expired token, missing scope, invalid service claim, AG read-only claim. |
| Retrieval | No-answer, low confidence, stale index, denied source, partial source anchors. |
| Generation | Template mismatch, incompatible output schema, provider timeout, invalid draft, citation repair, missing required section. |
| Artifact | Render success, render failure, retry, unauthorized download, missing format, rollback/current version. |
| Provider | Mock success, throttled, timeout, unhealthy route, metric unavailable, live disabled. |
| Admin | Redaction, cursor filtering, operator note, export denied, service unavailable. |
| Common API | Idempotent replay, conflicting idempotency key, unknown enum, problem+json error. |

## Contract Test Requirements

| Contract Area | Required Fixture Types |
| --- | --- |
| Common errors | Valid problem+json, missing required field, secret redaction negative. |
| Auth claims | User claim, service claim, missing scope, invalid audience. |
| Retrieval package | Ready, no-answer, low-confidence, permission-filtered, hash mismatch. |
| Generation request | Grounded answer, report generation, template mismatch, raw provider field forbidden. |
| Provider request | Alias success, timeout, throttled, invalid capability. |
| Structured draft | Valid report, missing section, invalid citation, unsupported block. |
| Artifact handoff | Valid DOCX target, unsupported format, hash mismatch, unauthorized download. |
| AG audit | Timeline, generation detail, artifact detail, redacted export, forbidden raw prompt. |

Every positive example in `contracts/examples` should have a corresponding
schema validation test. Every high-risk negative example should assert a stable
error code.

## Mock E2E Minimum

The first MVP E2E suite should automate:

1. OA creates or validates a test actor and service claims.
2. AE creates a chat document and accepts a prompt.
3. CX returns a deterministic retrieval package.
4. AE sends a generation request using an explicit compatibility rule.
5. CX calls MO mock generation by alias.
6. MO returns deterministic structured draft content and usage metadata.
7. CX validates sections and citations.
8. AE creates an artifact and download metadata.
9. AG reads redacted generation/artifact/provider/audit summaries.
10. The E2E evidence references the relevant trace ID.

Live DGX/vLLM smoke should reuse the same trace/evidence style but remain
separate from CI.

## UI Evidence

| UI Change | Evidence |
| --- | --- |
| AE chat/upload/search/generation/artifact UI | Playwright screenshot in Korean default. |
| AG dashboard/audit/provider readiness UI | Playwright screenshot in Korean default. |
| Form or state change | Screenshot before/after or deterministic interaction capture. |
| Accessibility-sensitive component | Keyboard navigation or accessible-name assertion where practical. |

Screenshots should be small, deterministic, and stored outside source unless the
team explicitly chooses a versioned visual-regression fixture policy.

## Release Evidence Checklist

| Evidence | Release Gate |
| --- | --- |
| Quality gate output | Required. |
| Schema/OpenAPI validation summary | Required. |
| Mock E2E run log | Required. |
| Migration revision output | Required when schema changed. |
| Playwright screenshots | Required for user-visible UI changes. |
| Live provider smoke markdown | Required only for protected live/provider release gate. |
| AG redaction sample | Required before admin dashboard release. |

## Documentation-Only Slice Rule

When a slice changes only documentation:

- Run link/keyword checks with `rg`.
- Run `git diff --check`.
- Skip pytest unless the slice changes executable examples, scripts, schemas,
  generated fixtures, or test expectations.

## Next Inputs

This testing strategy should feed:

- Design system expansion for UI evidence rules, starting from
  [Design System v0.1 Expansion](35_design_system_v0_1_expansion.md).
- First sprint backlog and quality gate tasks, starting from
  [Implementation Roadmap + First Sprint Backlog](36_implementation_roadmap_first_sprint_backlog.md).
- CI command design and contract validation implementation.
