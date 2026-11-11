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

The revisioned D12 source catalog lives at
`catalog/work_codes/catalog.v1.json`. It is source-authority attested and
content-digest pinned, but deliberately has no active API or NSL Tool binding;
EOS admission and runtime activation remain later provider-owned boundaries.
