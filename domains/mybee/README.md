# NeX MyBee AX Domain

`domains/mybee` contains MyBee office-work domain policy, catalogs, templates,
admitted Skill artifacts, and consumers of canonical NeX service APIs.

It does not own or duplicate:

- identity or current authorization;
- Agent Runtime or NSL execution;
- human workflow and approval;
- accounting, GL, Project, allocation, or P&L state;
- evidence/artifact persistence;
- model serving or governance.

Those responsibilities remain with OA, AE, WC, EOS, WA, MO, CX, and AG as
recorded in `docs/mybee_phase1/baselines/repo_compatibility_owners.md`.

## Development

```bash
./.venv/bin/pytest -q \
  tests/mybee_phase1/test_bootstrap.py \
  tests/mybee_phase1/test_boundary_imports.py \
  tests/mybee_phase1/contracts/test_nex_api_compatibility.py

./domains/mybee/compatibility/check_lock.py --root . --summary

./.venv/bin/pytest -q tests/mybee_phase1/test_work_code_registry.py
```

All integration uses canonical versioned contracts. Direct service-private
Python imports, cross-service database access, and a second MyBee runtime are
forbidden.

Approved finance bootstrap inputs are consumed through
`mybee_ax.integrations.finance_inputs`. The MB1-03 bundle binds the admitted
COA source manifest and the manual FX source-policy profile, then emits only
service-token-protected EOS API requests. It never opens an EOS database,
publishes COA automatically, fetches the external FX page automatically, or
stores a fabricated exchange-rate value.

MB1-03A adds the separately invoked one-shot
`scripts/operations/import_smbs_fx_once.py` operator adapter. Its default path
parses an operator-retained SMBS source file and produces a dry-run EOS import
request. Direct HTTP capture requires `--allow-insecure-http`, preserves the
raw response, and records `HTTP_UNVERIFIED`; it does not enable scheduled or
background acquisition. Admitted snapshots remain immutable EOS history and
are readable through `FINANCE.FX_RATE.HISTORY`.

MB1-03B normalizes that history into a tenant-neutral
`eos_fx_market_rate` observation and tenant/company/policy-specific
`eos_fx_rate_snapshot` adoption. One provider publication is retained once,
while each LegalEntity keeps an independent approved accounting lineage. The
external request contract remains compatible with MB1-03A.

S1-05 binds the immutable D12 catalog and its five mandatory FL work codes to
an EOS Project WorkCodeSet revision stream. Technical Project `ACTIVE` remains
separate from the `BUSINESS_READY` projection, which additionally requires an
effective company binding, an active human PM and Project membership, and a
distinct PA identity reference.

S1-06 adds immutable Project WorkAssignment planning against an exact S1-05
WorkCodeSet revision. A human performer requires both current OA execution
authority and an effective non-viewer Project membership; an Agent performer
must match the admitted PA identity. Standard projections contain Grade and
exact planned Man-Day only. Employee salary, actual rate, payroll, and actual
labor cost are rejected and remain outside this planning boundary.

MB1-02 publishes the immutable `mybee.d12.required-five` Project template and
a transport-neutral consumer for the S1-05 EOS WorkCodeSet and BusinessReady
operations. It validates the pinned catalog, canonical payload hash, tenant
and Project scope, readiness source hash, and nested WorkCodeSet before a PA
domain WRITE may proceed. It does not access EOS persistence directly or
activate the deferred NSL Tool binding.

The revisioned D12 source catalog lives at
`catalog/work_codes/catalog.v1.json`. It is source-authority attested and
content-digest pinned. EOS S1-05 now owns its approval, current revision, and
BusinessReady read APIs; NSL Tool authoring remains a later provider-owned
boundary.
