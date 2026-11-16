# CP-M1-GA-RET-02A.4: Project Delegation Active Branch Hardening

## Status

- State: `CLOSED`
- Date: `2026-11-16`
- Parent: `CP-M1-GA-RET-02A`
- Entry commit: `fcee1ac6`
- Product source change: none
- Database migration: none
- Public API change: none
- Remote provider: not required

## Goal

Harden the active installed Project-delegation path through meaningful denial,
ambiguity, malformed-authority and dependency-failure regression. Coverage
margin must come from current product behavior rather than Golden A replay or
historical imports.

## Active Branch Matrix

The dedicated A4 regression covers the following fail-closed boundaries
through public activator and source contracts:

| Boundary | Expected classification |
| --- | --- |
| WorkIntent capability mismatch | `PROJECT_DELEGATION_INVALID` |
| EOS Project Code mismatch or inactive Project | `PROJECT_DELEGATION_INVALID` |
| malformed EOS Project version | `PROJECT_DELEGATION_INVALID` |
| AE Project Agent identity mismatch | `PROJECT_DELEGATION_INVALID` |
| missing or multiple explicit Project Codes | `PROJECT_CODE_AMBIGUOUS` |
| malformed selector collection or confidence | `PROJECT_DELEGATION_INVALID` |
| WorkIntent schema/hash drift | `PROJECT_DELEGATION_INVALID` |
| OA tenant, subject, Project, action or proof mismatch | `PROJECT_AUTHORIZATION_DENIED` |
| stale OA source version | `PROJECT_AUTHORIZATION_DENIED` |
| malformed OA source version | `PROJECT_DELEGATION_INVALID` |
| OA HTTP timeout/network failure | retryable `PROJECT_AUTHORIZATION_UNAVAILABLE` |
| OA HTTP denial/status failure | non-retryable `PROJECT_AUTHORIZATION_UNAVAILABLE` |
| missing or multiple synchronized Project Agents | `PROJECT_AGENT_NOT_UNIQUE` |
| inactive, suspended or non-ordinary Project Agent | `PROJECT_AGENT_NOT_ACTIVE` |
| Project Agent projection database failure | retryable `PROJECT_AGENT_SOURCE_UNAVAILABLE` |
| disabled/partial/complete HTTP composition | none / fail-closed / admitted |

The distinction is intentional: ambiguity may lead to user clarification,
business authority denial must not be retried as infrastructure failure,
malformed evidence is invalid rather than denied, and transient database or
network failure remains explicitly retryable.

## Projection And Composition Verification

SQLite-backed tests exercise the real `ae_project_agent_sync` projection for
each non-ordinary state and for duplicate Project Code rows with different
internal Project identities. A failing SQLAlchemy session source verifies the
retryable operational path. The HTTP activator factory verifies all three
configuration states without contacting EOS or OA:

1. no Project-delegation settings: feature remains disabled;
2. partial URLs or service tokens: startup fails closed; and
3. complete URLs and tokens: EOS, OA and AE projection sources are assembled.

No test fixture was added to the installed runtime, and no production branch
was changed to make it easier to execute.

## Coverage Result

| Metric | A3 Gate | A4 Gate | Delta |
| --- | ---: | ---: | ---: |
| Aggregate statement | 96.3908% | 96.4497% | +0.0590 pp |
| Aggregate branch | 94.5663% | 94.6630% | +0.0967 pp |
| Active product statement | 97.0695% | 97.1306% | +0.0611 pp |
| Active product branch | 94.8851% | 94.9836% | +0.0985 pp |
| Historical statement / branch | 86.8421% / 81.7647% | unchanged | 0 |

`project_delegation_planning.py` moved from statement `86.4706%` and branch
`60.0000%` to statement and branch `100%`. All 23 previously missing
statements and 12 missing branches are now covered. Historical coverage did
not change.

## Verification

```text
A4 focused branch regression             27 passed
existing delegation + A4 regression      39 passed
project delegation statement / branch    100% / 100%
AE Slice Gate                            6,228 passed / 46 protected skips
AE Slice Gate files                      434
AE Slice Gate commands                   6 / 6, PASS
AE Slice Gate duration                   499.015 seconds
aggregate statement / branch             96.4497% / 94.6630%
active product statement / branch        97.1306% / 94.9836%
historical statement / branch            86.8421% / 81.7647%
ownership and quarantine checks          7 / 7, PASS
historical active/deployment conflicts   0 / 0
```

Generated evidence remains under ignored report paths:

```text
reports/coverage/mybee-w70-ga-ret-02a4-project-delegation.json
reports/quality/mybee-w70-ga-ret-02a4-ae.coverage.json
reports/coverage/mybee-w70-ga-ret-02a4-ae.coverage.report_ae_coverage_ownership.json
reports/quality/slice-latest.json
```

## Exit

The mandatory active-product hotspot is hardened without changing product
semantics, adding a broad selector, or executing historical code for margin.
The next boundary is `CP-M1-GA-RET-02A.5`, the parent coverage-margin closure
and public M1 E2E resume decision gate.
