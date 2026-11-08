# P8-S27 Delegation Hop Limit

## Scope

Enforce the initial Delegation Guard maximum depth of ten at nested child
admission without making the current depth-ten WorkItem unexecutable.

## Semantics

- prospective child depth is derived from immutable parent lineage
- prospective depth greater than policy max returns
  `wc.delegation_hop_limit_exceeded`
- a denied attempt creates zero WorkItem and zero lineage
- route and Claim do not increment delegation depth
- a current depth-ten WorkItem remains routable and claimable

## Verification

- focused P8.2A regression: `53 passed`
- P8-S27 Checkpoint Gate: PASS in `1249.057s`
- Checkpoint regression: `15,203 passed`, `57 protected skips`
- Checkpoint statement coverage: `98.71%` (threshold `95.00%`)
- Checkpoint branch coverage: `97.17%` (threshold `94.00%`)
- contract validation: `179` schemas, `241` examples, `210` negative
  examples, and `9` OpenAPI documents
