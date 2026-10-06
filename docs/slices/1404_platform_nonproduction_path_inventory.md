# Slice 1404: Platform Nonproduction Path Inventory

## Outcome

- Classified nine mock, memory, test-only, local-filesystem, and protected
  opt-in path families from repository evidence.
- Preserved deterministic and fast regression paths as supported development
  capabilities.
- Marked every path `FORBIDDEN_IN_PRODUCTION` and assigned its production
  transition requirement.
- Confirmed the current production profile is shaped as PostgreSQL, live
  provider, signed trust, and service API projection rather than mock fallback.

## Decision

Nonproduction paths are not deleted merely to make the repository look
production-like. They remain explicit regression adapters. S142-S149 must make
the production selection fail closed so an absent setting cannot select
`local_mock`, memory persistence, mock trust/provider behavior, local private
storage, test databases, or a smoke harness by accident.

## Verification

The audit validates fifteen repository anchors, canonical documentation,
ownership, allowed scope, transition targets, and the production exclusion for
all nine path records. Slice Gate passed all 5 commands with 972 tests passed
and 11 policy skips. Overall statement coverage was 98.45% and branch coverage
was 97.80%; the new runner reached 100% statement and branch coverage.
Contract validation passed for 166 schemas, 228 examples, 196 negative
examples, and 7 OpenAPI documents.
