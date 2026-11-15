# W70-S8-01C D04/D12 Skill-Pack Manifest and Digest Foundation

## Status

- Slice: `W70-S8-01C`
- Status: `IMPLEMENTED_AND_VERIFIED`
- Date: `2026-11-15`
- Owners: NeX MyBee, NeX AE, NeX Runtime, NeX EOS
- Database migration: none
- Remote model provider: not required

## Decision

S8-01C establishes two repository-visible, descriptor-only Skill-Pack
candidates over the admitted S8-01A identity and S8-01B contract baseline:

| Pack | Tools | Fully typed | Status-only |
| --- | ---: | ---: | ---: |
| `MYBEE.D04.ACCOUNTING` | 13 | 8 | 5 |
| `MYBEE.D12.PROJECT` | 5 | 3 | 2 |
| Total | 18 | 11 | 7 |

The canonical source artifacts are:

```text
domains/mybee/skills/d04_accounting/manifest.v1.json
domains/mybee/skills/d04_accounting/tool_bindings.v1.json
domains/mybee/skills/d12_project/manifest.v1.json
domains/mybee/skills/d12_project/tool_bindings.v1.json
```

The manifests pin the Tool inventory, Tool contract admission, NSL v0.2.1
wheel lock, runtime profile, trust policy, binding catalog, and source bytes.
Each binding preserves the canonical operation identity and records its exact
input/output contracts, execution policy, and remaining activation blockers.

## Immutable Digests

```text
D04 manifest content:
sha256:3d47bea11f6ec67640d418b7fc9ce623cda7d2113f43e7230aeeccc9542be3fe

D04 binding catalog content:
sha256:d4900b8c98e521994c15671fd0fe368332d98af57adaa6c2d4a6161c266dd636
D04 binding catalog bytes:
sha256:52804f9a720086117bbe40c2d966504d511e2b47998ec57fe854278fc3d7f352

D12 manifest content:
sha256:067a6e4b074e90c643958bee72407f13ced7e9371c1b3e3308976ee771144a34

D12 binding catalog content:
sha256:0c4ac1a600b5ca4bd33dd9529e8a13a062721c441d70540f7167c8facc165fc4
D12 binding catalog bytes:
sha256:bc13608d0c6f50cdc1884cf7996aa2e86b3254e81123a9e3bab62f5ab7143274
```

Both manifests also pin:

```text
Tool inventory content:
sha256:ee010195add45d474551866c65112ec7417b386d53faef4bef79445f6a23d151

Tool contract admission content:
sha256:b6b37073f96d9c7a6ed0a3bdb3e6dbd03ddab4b4396654f00b2976e48dcacedd

NSL v0.2.1 wheel lock bytes:
sha256:7efa6376602f1c89951657ba170a51ae7157189a0f46e607cebbb9ef949964ea
```

## Fail-Closed Loader

`mybee_ax.integrations.nex_skill_packs` rejects:

- manifest, binding, source, inventory, admission, or wheel digest drift;
- missing, duplicated, reordered, or cross-pack Tool identities;
- contract, OA scope, semantics, approval, or activation-state drift;
- a status-only contract without an explicit activation blocker;
- a compiled, signed, trusted, or runtime-selectable candidate;
- source files outside the exact declared catalog; and
- read/write execution-policy drift.

The two JSON Schemas enforce the same descriptor shape at the artifact
boundary. The Python loader additionally reconciles every field against the
current S8-01A/S8-01B authorities rather than trusting self-declared metadata.

## Activation Boundary

Both packs remain:

```text
activation_state=CANDIDATE
runtime_selectable=false
source_state=DESCRIPTOR_ONLY_NOT_COMPILED
signature_status=NOT_SIGNED
compile_state=PENDING_S8_01E
```

No executable `.ns` source was created. No deployed Product Capability
Registry entry, runtime bundle lock, service configuration, API, or database
state changed. Golden A remains the only deployed compatibility capability.

S8-01D owns immutable registry and multi-bundle lock integration. S8-01E owns
Skill compilation, signed admission, and protected activation checks. The
seven status-only Tool contracts must also gain canonical success-response
schemas before activation.

## Verification

Static and focused identity/contract/pack Gate:

```text
ruff: pass
111 passed
nex_skill_packs statement/branch coverage: 98%
```

Extended MyBee, Golden A capability/activator, and contract regression is
clean:

```text
655 passed, 1 skipped
```

The one skip is the existing opt-in W40-CA02 PostgreSQL/HTTP protected
acceptance. S8-01C requires neither a database nor a live model provider.

## Handoff

`W70-S8-01C` is closed. The next Slice is `W70-S8-01D`, which may admit these
candidate pack identities into the immutable Product Capability Registry and
multi-bundle lock model without making either pack runtime-selectable.
