# W40-CA02-S01 Product Runtime Composition and Ownership Audit

## Status

`CLOSED` on 2026-11-13.

This Slice audits the source-backed installed composition for the thin W40
accounting product checkpoint. It assigns each existing responsibility to one
canonical owner and records the remaining assembly gaps without creating a new
MyBee service, database, API, or business feature.

## Ownership Decision

| Boundary | Canonical owner | Decision |
| --- | --- | --- |
| MyBee domain policy and service consumers | `domains/mybee` | reusable product library; no process or database ownership |
| IA intent activation and product execution | `nex-ae-api` | existing Agent Runtime process is the only product execution owner |
| VoucherCandidate, Project, accounting state | `nex-eos` | authoritative business SoR |
| Project-Code entitlement and authorization | `nex-oa` | authoritative authorization SoR |
| human approval | `nex-wc` | existing approval/workflow owner |
| EOS lifecycle and entitlement delivery | `nex-eos-outbox-publisher` | existing durable outbox process |

A new MyBee backend, worker, JobQueue, database, or Compose service is rejected.
MyBee may be packaged into the AE product runtime as a library, but EOS, OA,
and WC ownership must remain behind their signed public APIs.

## Source-Backed Findings

The audit confirmed that the existing product foundations are real product
code rather than smoke-only orchestration:

- canonical Compose contains AE API/worker, EOS API/outbox publisher, OA, and WC;
- canonical EOS configuration carries the OA base URL and secret reference for
  the EOS-to-OA service credential;
- `nex_eos.outbox_publisher_process` owns the routed AE/OA transport and uses
  `HttpOaProjectEntitlementTransport`;
- `build_eos_dependencies()` composes the PostgreSQL VoucherCandidate
  repository, fail-closed Project authorization gate, and HTTP OA decision
  source;
- MyBee already owns a strict HTTP `NexVoucherCandidateClient`, without direct
  EOS persistence access; and
- no non-AE service imports `mybee_ax`, and no second MyBee runtime entrypoint
  exists.

The installed integration is intentionally reported as `NOT_READY`. Three
source-backed gaps remain:

1. `MYBEE_AE_PACKAGE_NOT_ADMITTED`: the AE OCI source roots and derived product
   runtime image do not contain `domains/mybee` or an admitted MyBee wheel.
2. `MYBEE_PRODUCT_CAPABILITY_NOT_ADMITTED`: the product capability registry
   contains only the existing Golden A voucher-draft capability.
3. `MYBEE_PRODUCT_ACTIVATOR_NOT_ADMITTED`: the AE product activator registry
   contains only `GoldenAFinanceIntentActivator` and does not expose the MyBee
   VoucherCandidate consumer.

These are composition gaps, not reasons to duplicate the business logic. They
become the bounded input to `W40-CA02-S02` and `W40-CA02-S03`.

## Executable Audit

Added:

- `scripts/quality/run_mybee_w40_ca02_runtime_ownership_audit.py`;
- `tests/mybee_phase1/test_w40_ca02_runtime_ownership_audit.py`.

The audit distinguishes repository integrity from integration readiness:

```text
status=PASS
integration_readiness=NOT_READY
integration_gaps=3
next_slice=W40-CA02-S02
remote_provider_required=false
database_migration_required=false
```

It fails closed for a second MyBee process, a non-AE service import, missing
canonical processes or trust configuration, absent EOS/OA product composition,
malformed source/configuration, or an incomplete MyBee HTTP consumer.

## Validation

Audit unit and branch regression:

```text
13 passed
audit statement/branch coverage: 98%
```

Focused product boundary regression:

```text
144 passed, 1 protected PostgreSQL smoke skipped
```

The protected skip is the existing opt-in W40 EOS/OA PostgreSQL smoke. S01
does not mutate persistence; actual database and installed process evidence is
reserved for S03/S04.

Platform Slice Gate:

```text
status: PASS (6/6 commands)
tests: 440 passed, 8 protected PostgreSQL skips
audit statement coverage: 97.84% (threshold 95.00%)
audit branch coverage: 96.43% (threshold 94.00%)
contract validation: PASS (245 schemas, 303 examples, 254 negative, 10 OpenAPI)
Golden Journey transition audit: PASS
Demo/product dependency audit: PASS
```

Coverage evidence:

- `reports/quality/mybee-w40-ca02-s01-slice-gate.coverage.json`

Machine-readable local evidence is generated at:

- `reports/quality/mybee-w40-ca02-s01-runtime-ownership-audit.json`

The report is intentionally ignored by Git and may be regenerated with:

```bash
./.venv/bin/python \
  scripts/quality/run_mybee_w40_ca02_runtime_ownership_audit.py \
  --summary
```

## S02 Entry Boundary

`W40-CA02-S02` may proceed with the ownership decision fixed above. It must:

1. package the MyBee library into the existing AE product runtime artifact;
2. preserve the existing immutable capability and runtime-bundle admission
   sources; a MyBee registration is added only with its real executable
   consumer binding in S03, never as a placeholder Skill;
3. preserve signed AE-to-EOS and EOS-to-OA trust resolution through OpenBao;
4. keep MyBee free of a process entrypoint and private service imports; and
5. introduce no migration unless a separately proven persistence gap exists.

Remote embedding, reranker, and generation providers are not required for this
checkpoint.
