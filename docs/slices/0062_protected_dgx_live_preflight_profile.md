# Slice 0062 Protected DGX Live Preflight Profile

Status: Implemented.

Backlog candidate: `S6-012` Protected DGX live preflight execution profile.

Requirement coverage: `MO-PROVIDER-001`, `MO-CONFIG-001`, `TRACE-PLAT-001`,
`PLAT-FR-007`.

## Scope

Slice 0062 adds the preferred operator entrypoint for live DGX provider smoke:

- `scripts/smoke/run_protected_dgx_live_profile.py` stays skipped unless
  `NEX_MO_PROTECTED_LIVE_PROFILE=dgx` or `--profile dgx` is set.
- When the profile is active, the runner uses an isolated environment copy with
  `NEX_MO_PROVIDER_MODE=live` and `NEX_MO_LIVE_PREFLIGHT=1`.
- The runner executes the local live config guard first.
- DGX live preflight is only called after the local config guard passes.
- Combined evidence uses `protected_dgx_live_profile.v1` and embeds the
  redacted config snapshot plus redacted live preflight evidence.
- Endpoint URLs, API keys, raw response bodies, and model paths are excluded
  from committed or printed evidence.

The default quality gate remains mock-first. This profile is for protected
operator/manual execution and should write only redacted evidence under
`reports/live/` when live credentials are available in the shell or `.env.local`.

## Files

- `scripts/smoke/run_protected_dgx_live_profile.py`
- `tests/test_protected_dgx_live_profile.py`
- `.env.example`
- `services/nex-mo/README.md`
- `docs/README.md`

## Evidence

Slice evidence should include:

```bash
./.venv/bin/pytest tests/test_protected_dgx_live_profile.py tests/test_local_live_provider_config.py tests/test_dgx_live_provider_preflight.py
./.venv/bin/python scripts/smoke/run_protected_dgx_live_profile.py --summary
scripts/quality/run_quality_gate.sh
```

The summary command should print skipped status unless the protected DGX profile
is explicitly enabled.
