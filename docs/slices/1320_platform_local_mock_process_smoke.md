# Slice 1320: Platform local mock process smoke

## Outcome

- Added the canonical `scripts/dev/run_platform.py` command for complete
  manifest-driven platform startup, runtime monitoring, safe status output,
  signal handling, and coordinated shutdown.
- Passed canonical endpoint values to child processes and taught AE Web to use
  `NEX_AE_WEB_BASE_URL` and `NEX_AE_API_BASE_URL` while preserving its legacy
  `HOST`, `PORT`, and `AE_API_PROXY_TARGET` overrides.
- Split subprocess, probe, and environment concerns from the state machine so
  the orchestrator remains below 300 lines.
- Added an actual dynamic-port local mock smoke that starts five APIs, AE Web,
  five workers, and two daemons; probes six HTTP endpoints; rechecks process
  survival; and stops all processes.

## Decision

The smoke proves real process lifecycle and HTTP reachability without claiming
business-job execution by the background shells. Durable worker queue handling
remains assigned to S133. PostgreSQL and remote model providers are excluded
from this database-free, provider-mock profile.

`scripts/dev/run_all_services.py` remains unchanged as the rollback command
while the complete topology command becomes the local default.

## Verification

- Focused Python regression: `29 passed`.
- AE Web regression: `293 passed`.
- Orchestrator and process-adapter scopes: statement `100.00%`, branch
  `100.00%`.
- Runtime command and actual-smoke helper scopes: statement `100.00%`, branch
  `100.00%`.
- Slice Gate (`nex-oa`): `963 passed`, `11 skipped`; statement `98.41%`,
  branch `97.71%`.
- Contract validation: `156` schemas, `214` examples, `184` negative
  examples, and `7` OpenAPI documents.
- Actual process evidence: `13` processes started and stopped; `5` API health
  probes and `1` AE Web probe passed on dynamic loopback ports.
- Slice Gate and contract validation results are recorded after execution.
