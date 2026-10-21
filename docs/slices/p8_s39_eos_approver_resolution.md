# P8-S39 EOS Approver Resolution API

## Boundary Decision

EOS resolves the intended business approver from authoritative Organization
state. It does not authorize the resolved principal to decide an approval.
WC continues to own approval work and decisions, while OA performs the fresh
security authorization immediately before the WC decision commit.

The response therefore fixes this distinction in the contract:

```text
security_authorization = false
```

## Persistence Reuse

No table or migration was added. Resolution reuses the existing tenant-scoped
join:

```text
eos_org_unit
  -> eos_position
  -> eos_position_assignment
```

All three records must be active, and the organization unit and assignment
must be effective at the resolution time.

## Default Policy

The only admitted policy in this Slice is
`eos.approver.default.v1`. It deterministically maps risk to a position:

```text
LOW      -> PART_LEAD
MEDIUM   -> TEAM_LEAD
HIGH     -> GROUP_LEAD
CRITICAL -> CEO
```

The default policy fails closed when no effective assignment exists and
rejects requester self-approval. Model output cannot select or override the
approver.

## Contract And API

Protected endpoint:

```text
POST /internal/v1/organization/approver-resolutions
X-NeX-Tenant-Id: <tenant>
scope: service:call
```

The response preserves approval domain, risk, organization/project context,
resolved OA principal, position and assignment references. Its
`resolution_hash` is computed from stable semantic inputs and organization
versions; `resolved_at` is deliberately excluded so exact re-resolution is
hash-stable while the underlying assignment remains unchanged.

## Verification

- focused S39 tests: `25 passed`
- focused implementation coverage: `100% statement`, `100% branch`
- EOS regression: `324 passed`, `10 protected PostgreSQL skips`
- contract validation: `185 schemas`, `247 examples`, `215 negative`,
  `9 OpenAPI` passed
- Ruff checks: passed
- the historical S18 contract test now verifies its owned canonical entries
  instead of freezing the total number of EOS contracts
