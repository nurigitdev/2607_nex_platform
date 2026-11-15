# NeX MyBee Skill Sources

This directory contains repository-visible MyBee Tool and candidate Skill-Pack
sources. Read them in this order:

1. `tool_inventory.v1.json` freezes canonical operation identity, semantics,
   approval, OA action, and activation state.
2. `contracts/admissions/nex_eos/w70_tool_contract_admission.v1.json` binds
   every Tool to the canonical EOS OpenAPI and JSON Schema authorities.
3. `d04_accounting/manifest.v1.json` and
   `d12_project/manifest.v1.json` freeze the two candidate pack identities,
   authorities, runtime profile, trust state, and source digests.
4. Each pack's `tool_bindings.v1.json` binds its Tool subset to the admitted
   contracts and records compile, activation, and response-contract blockers.

The S8-01C packs are descriptor-only candidates. They contain no executable
`.ns` source, are not signed, are not runtime-selectable, and are not present
in the deployed AE Product Capability Registry. S8-01D owns registry and
multi-bundle lock integration; S8-01E owns compile/admission and protected
activation gating. Recording a Tool here must never be interpreted as
runtime activation.
