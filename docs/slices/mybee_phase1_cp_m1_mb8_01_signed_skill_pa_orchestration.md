# CP-M1-MB8-01 Signed D04/D12 Skill and PA Orchestration Checkpoint

## Status

- Slice: `CP-M1-MB8-01`
- Parent packet: `MB8-01`
- Status: `CLOSED`
- Date: `2026-11-15`
- Gates: `G-NSL`, `G-PA`, `G-BOUNDARY`

## Boundary

This checkpoint activates only the minimum signed D04/D12 subset required by
the M1 Project Agent journey:

| FL code | Role | Capability | Signed Skill |
|---|---|---|---|
| `FL0012005` | Project context | `PROJECT.WORK_CODE_SET.GET` | `MYBEE.D12.PROJECT_WORK_CODE_CONTEXT@1.0.0` |
| `FL0004009` | Primary action | `FINANCE.VOUCHER.APPROVE_AND_POST` | `MYBEE.D04.JOURNAL_POSTING@1.0.0` |

The other 16 D04/D12 Tool bindings and both original pack manifests remain
`CANDIDATE`, unsigned as full packs, and `runtime_selectable=false`. Full
`MB8-01` certification remains an M2 responsibility. The canonical Compose
registry also remains v1 until the protected public M1 E2E Slice proves the
installed routing.

No database migration, NSL compiler/runtime change, service-internal import,
or remote model provider was introduced.

## Signed Release

The immutable release is bound by
`deployment/locks/ae-mybee-m1-signed-skill-checkpoint.v1.json`:

- NSL runtime: admitted `0.2.1` wheel and in-process v0.2 profile;
- NSP: `mybee-m1-d04-d12.v1.nsp`;
- package hash:
  `sha256:96888a02ee4924b6ac1f46bf7031627afc4d4a53d04bc77e13acd1940ea25348`;
- signing algorithm: Ed25519;
- key ID: `release:nex-mybee-m1-checkpoint-2026-11`;
- release lock hash:
  `sha256:0034adc847aedc5d4fe99a446f7b60dfaef5db218ebbed96ba0f96bf32feecf4`;
- M1 registry hash:
  `sha256:104e60e12282ab9849932487e931d22910a5a75abcd05dcd646e5251c3140cc5`.

The private signing key was used only while producing this immutable release
artifact and is not stored in the repository. The checked-in key material is
the 32-byte Ed25519 public verification key with `VERIFY_ONLY` usage.

Admission recompiles both checked-in `.ns` sources against the pinned Tool
catalog and requires exact skill version, semantic hash, NSO artifact hash,
candidate Tool contract, OA action, FL binding, Product Capability Registry,
NSP package hash, and production-policy signature agreement.

## PA Orchestration

`nex_tool_bindings.py` emits a deterministic two-step invocation plan only
when all of these conditions hold:

1. Project state is `ACTIVE`;
2. the synchronized Project Agent is type `PA`, status `ACTIVE`, and mode
   `ORDINARY`;
3. tenant, Project UUID, and user-facing Project code agree across both
   projections;
4. the Project work set contains `FL0012005`;
5. the requested business work code is exactly `FL0004009`;
6. the Journal command has the exact controlled-WRITE argument set and tenant;
7. the invocation uses the exact signed skill versions and registry identity.

The plan order is fixed to D12 Project context first and D04 governed Journal
WRITE second. Its semantic hash is reverified before scheduling. The MyBee
module does not call EOS, AE, SQLAlchemy, or HTTP directly; execution remains
owned by the existing AE runtime and the Journal adapters closed in
`CP-M1-S8-02`.

## Verification

Focused Slice Gate:

```text
tests/mybee_phase1/test_mybee_skill_admission.py
53 passed
nex_tool_bindings.py statement coverage: 97.70%
nex_tool_bindings.py branch coverage: 97.17%
thresholds: statement 95.00%, branch 94.00%
```

The test matrix covers production-policy signature verification, source and
artifact identity, exact registry admission, Golden A continuity, Project/PA
lifecycle denial, FL mapping denial, malformed Journal arguments, lock and
registry drift, plan tamper detection, and service ownership boundaries.

Extended MyBee and controlled-Journal regression:

```text
841 passed, 1 skipped
```

The one skip is the separately protected W40 installed PostgreSQL/HTTP
acceptance. This Slice introduces no database state and therefore does not
represent that skip as M1 signed-Skill evidence. Ruff, `py_compile`, and
`git diff --check` also passed.

## Post-Implementation Signed Skill/PA Checkpoint

The canonical repository Checkpoint Gate was executed after the Slice was
committed. The first run found two repository-baseline gaps rather than a
product-runtime regression:

1. the S141 exact loopback inventory did not include the local-development
   default in `nsl_eos_journal_execution.py`; production still requires an
   explicit `NEX_EOS_BASE_URL`, and the production composition continues to
   reject loopback endpoints;
2. the signed W70 Tool admission artifact was incorrectly listed in the P8
   example index even though it is owned by `contracts/admissions/`, not
   `contracts/examples/`.

The S141 file-by-file inventory was reconciled from `51/31` to `52/32`, and
the invalid example-index entry was removed without moving, copying, or
rehashing the signed admission artifact. Focused regressions passed with
`5 passed` for the coupling audit, `15 passed` for contract hygiene, and
`42 passed` for W70 Tool admission.

The canonical Checkpoint rerun completed with:

```text
22,060 passed, 178 skipped
statement coverage: 98.47% (threshold 95.00%)
branch coverage: 97.03% (threshold 94.00%)
contract validation: 265 schemas, 315 examples, 260 negative examples,
                     10 OpenAPI documents
golden journey transition audit: PASS, findings=0
demo/product dependency audit: PASS, findings=0
```

The local machine-readable coverage evidence is written to
`reports/quality/mybee-cp-m1-mb8-01-signed-skill-pa-checkpoint.coverage.json`;
`reports/` remains intentionally excluded from source control. The 178 skips
are explicit opt-in PostgreSQL, browser, RustFS, or live-provider protected
tests. This Checkpoint required no remote model provider and does not replace
the protected public M1 E2E gate.

Checkpoint decision: `G-NSL=PASS`, `G-PA=PASS`, `G-BOUNDARY=PASS`.

## Deferred Boundary

`CP-M1-MB8-01` is closed. It does not switch the installed canonical Compose
registry or claim all 18 Tools as product Skills. The next W70 boundary is
`CP-M1-E2E-FX-01`, which must prove the public IA-to-PA installed journey and
may promote routing only with protected evidence. Full pack activation,
coverage, finance sign-off, and certification remain M2 `MB8-01` work.
