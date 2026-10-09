# Slice 1490: S149 Single-host Protected Live Acceptance

Status: Complete.

## Outcome

The S149 protected runner now composes the existing production-shaped S143,
S146, and S147 acceptance boundaries instead of introducing a second set of
infrastructure controls. Explicit opt-in proves the six-service Docker Compose
topology, all five real test databases, RustFS owner isolation and restart,
and all three remote provider capabilities. It records only metadata-safe
counts and evidence digests.

## Decisions

- S143 remains the owner of Compose, OpenBao, Traefik, secret/TLS rotation,
  service readiness, and release-set identity.
- S146 remains the owner of ephemeral RustFS provisioning, private object
  round trips, owner isolation, restart recovery, and zero-residue teardown.
- S147 remains the owner of live embedding, reranking, generation, model
  identity, runtime readiness, and MO persistence rehearsal.
- The live run exposed and closed a real integration drift: S146 had expanded
  the current production manifest by four object-storage secret references and
  two public endpoints, while the S143 base Compose environment still exposed
  only its older subset. The base environment now tracks all six additions
  without enabling S3 mode in services that do not own that transition.
- The S149 runner executes those boundaries sequentially and fails closed on
  the first nested failure. It never stops or mutates DGX processes.
- Load, soak, fault, security, and rollback measurements remain separate S149
  evidence. This Slice establishes live substrate currentness and does not
  mislabel its bounded provider probes as a production-sized load test.
- External incident delivery remains `EXTERNAL_NOT_ACTIVATED`; S150 must carry
  the time-bounded P1 waiver and local compensating control requirement.

## Verification

- Focused unit tests cover opt-in, nested failures, all fourteen admission
  checks, exception redaction, report writing, adapters, and CLI behavior.
- Provider admission explicitly requires generation reasoning mode to remain
  `disabled`.
- The protected report is written under `reports/deployment/`, which remains
  outside source control and excludes credentials, URLs, payloads, and raw
  nested evidence.
- Production resources are not contacted and production deployment remains
  unapproved.
