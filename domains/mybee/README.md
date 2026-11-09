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
  tests/mybee_phase1/test_boundary_imports.py
```

All integration uses canonical versioned contracts. Direct service-private
Python imports, cross-service database access, and a second MyBee runtime are
forbidden.
