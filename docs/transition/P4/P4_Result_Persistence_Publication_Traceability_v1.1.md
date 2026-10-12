# P4 Result Persistence / Publication Traceability v1.1

| ID | Obligation | P4 v1.1 disposition | Evidence |
|---|---|---|---|
| RP-01 | Persist complete canonical AgentResult | IMPLEMENT | schema round-trip |
| RP-02 | AgentResult immutable | IMPLEMENT | mutation-negative test |
| RP-03 | deterministic result_hash | IMPLEMENT | fixed canonical hash vectors |
| RP-04 | one AgentResult per AgentExecution | IMPLEMENT | execution-level uniqueness and concurrency tests |
| RP-04A | one required WORKSPACE_RESULT | IMPLEMENT | uniqueness tests |
| RP-04B | stable pending-delivery publication identities | IMPLEMENT | Frozen derivation vectors and retry identity tests |
| RP-05 | ResultDelivery atomically created with result | IMPLEMENT | transaction fault injection |
| RP-06 | ResultDelivery ACK | DEFER | later publication phase |
| RP-07 | AS_OF_NOW publication preflight | DEFER | later authority/publication phase |
| RP-08 | PUBLISH_RESULT RuntimeJob | DEFER | generated later from durable PENDING delivery |
| RP-09 | SUCCEEDED only after ACK | ENFORCE NEGATIVELY | transition rejection |
| RP-10 | publication must not rerun generation | PRESERVE DESIGN | future call-count test |
| RP-11 | Frozen/amendment integrity | VERIFY | checksum/manifest evidence |

## P4 Result Exit Point

```text
AgentResult durable
+ WORKSPACE_RESULT ResultDelivery PENDING
+ AgentExecution not SUCCEEDED
```
