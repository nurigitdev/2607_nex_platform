# P5 Transition Machine Contracts

**Status:** P5-CA01 REVIEWED TRANSITION CONTRACTS
**Authority:** P5 implementation-facing interpretation; not a modification of the Frozen v2.1 set

These schemas freeze the exact machine shape used by P5 implementation:

- `p5-work-intent-v1.schema.json`
- `p5-agent-context-v1.schema.json`
- `p5-capability-snapshot-v1.schema.json`
- `p5-agent-plan-v1.schema.json`
- `p5-plan-validation-result-v1.schema.json`
- `p5-executable-plan-v1.schema.json`
- `p5-step-result-v1.schema.json`

Authority order:

```text
Frozen Agent/Platform semantics
> approved P4-CA01 project-neutral PROMPT amendment
> P5-CA01 decisions and these transition schemas
> legacy 99_* reference schemas
```

The schemas intentionally expose future Frozen vocabulary such as
`DELEGATE_WORK` and `LOCAL_SKILL`. P5 scope guards still reject execution of
those paths. Schema visibility is not runtime availability.

All `*_hash` values use `sha256:<64 lowercase hex>`. The canonical semantic
projection and exclusions are defined by P5-CA01 DEC-11.
