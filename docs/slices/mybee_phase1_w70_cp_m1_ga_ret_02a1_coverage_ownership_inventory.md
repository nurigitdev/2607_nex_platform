# CP-M1-GA-RET-02A.1: AE Coverage Ownership Inventory and Baseline Freeze

## Status

- State: `CLOSED`
- Date: `2026-11-16`
- Parent: `CP-M1-GA-RET-02A`
- Entry commit: `46de02aa`
- Database migration: none
- Public API change: none
- Remote provider: not required

## Goal

Freeze a deterministic, source-backed ownership inventory for every Python
module in `services/nex-ae-api/nex_ae_api`. Aggregate service coverage remains
canonical, but active product, retained compatibility, and hash-pinned Golden
A history are now separately visible. This Slice changes no runtime behavior
and does not omit any module from the AE coverage denominator.

## Durable Contract

`scripts/quality/ae_coverage_ownership.v1.json` is the machine-readable
classification authority. It uses a conservative default:

```text
default                          ACTIVE_PRODUCT
historical P8 replay surfaces   ACTIVE_COMPATIBILITY
hash-pinned Golden A sources    HISTORICAL_QUARANTINE
```

The inventory hash is generated through
`nex_runtime.semantic_hashes.semantic_sha256_hash_ref`. Exact overrides carry
a rationale, must resolve to existing modules, and may not be duplicated.

Ownership and reachability are deliberately separate. A product-owned API or
worker module can be outside the four canonical process entrypoint import
graphs and still remain product code. Conversely, no compatibility or
historical module is currently reachable from those graphs.

## Frozen Inventory

| Scope | Modules | In active graph | Statement coverage | Branch coverage |
| --- | ---: | ---: | ---: | ---: |
| `ACTIVE_PRODUCT` | 166 | 69 | 96.5514% | 94.3350% |
| `ACTIVE_COMPATIBILITY` | 5 | 0 | 61.9238% | 62.9630% |
| `HISTORICAL_QUARANTINE` | 5 | 0 | 86.8421% | 81.7647% |
| Total inventory | 176 | 69 | n/a | n/a |

Coverage evidence was available for 175 modules. The sole module without an
independent coverage.py row is the package-only `__init__.py`; it remains
classified and is not hidden or excluded.

The post-A0 aggregate baseline remains:

```text
statements = 37,411 / 39,011 = 95.8986%
branches   = 11,666 / 12,404 = 94.0503%
```

The A1 canonical AE Slice Gate measured:

```text
statements = 37,408 / 39,011 = 95.8909%
branches   = 11,663 / 12,404 = 94.0261%
```

The three covered-line/branch difference is recorded rather than normalized
away. The source denominator is identical and both canonical floors pass;
later RET-02A branch-hardening Slices must create deliberate margin instead of
depending on execution-order variation near the boundary.

## Fail-Closed Guards

The reporter fails when:

1. the manifest semantic hash, schema, or baseline metrics are malformed;
2. an override is duplicated, unavailable, or uses an unknown scope;
3. historical ownership differs from the hash-pinned quarantine inventory;
4. a historical asset hash changes;
5. a historical source re-enters the recursive canonical import graph; or
6. a canonical deployment input names a historical source module.

The inventory report contains only module paths, ownership, reachability, and
coverage counts. It records no source content, business payload, or secret.

## Baseline Findings

The report makes three different follow-up classes explicit:

- `product_capability_releases.py` is active product ownership but receives no
  current AE Gate execution. Its test ownership must be audited before adding
  tests.
- `product_capability_retirements.py` and `controlled_skill_runtime.py` are in
  the canonical active graph and have meaningful uncovered branches.
- historical and retained compatibility hotspots remain visible but may not
  be executed merely to raise the aggregate percentage.

`project_delegation_planning.py` remains the mandatory behavior-hardening
target in `CP-M1-GA-RET-02A.4`, even though its absolute missing-line count is
smaller than the modules above.

## Verification

```text
ownership inventory reporter       PASS
module classification              176 / 176
canonical active import graph       69 modules
historical active conflicts         0
historical deployment conflicts     0
focused A0/A1 regression             13 passed
AE Slice Gate                        6,019 passed / 46 protected skips
AE Slice Gate commands               5 / 5, PASS (461.735 seconds)
AE statement / branch                95.8909% / 94.0261%
ruff                                PASS
git diff --check                    PASS
```

Generated evidence is written to the ignored path:

```text
reports/coverage/mybee-w70-ga-ret-02a1-ae-ownership-inventory.json
```

## Exit

The ownership baseline is frozen without changing source roots, exclusions,
or thresholds. The next boundary is `CP-M1-GA-RET-02A.2: Explicit AE Test
Ownership Reconciliation`.
