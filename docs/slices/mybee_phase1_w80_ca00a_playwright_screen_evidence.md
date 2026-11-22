# W80-CA00A: Playwright Screen Evidence Integrity and Retention Boundary

## Scope

- add semantic DOM assertions before named M1 screenshots;
- add private atomic screenshot manifests with size and SHA-256;
- render owner-scoped terminal AgentResult after restart;
- verify and collect screen evidence into the W80 restricted session;
- keep database schema and backend business APIs unchanged.

## Source Audit

The prior protected run produced sixteen screenshots. The second transaction
result was visually correct, but the first result was captured before the result
card appeared. The recovery image was byte-identical to the initial requester
workspace and therefore did not prove user-visible recovery. Both false-positive
paths came from treating API success as sufficient capture admission.

## Verification

Pending implementation and exact-head protected live acceptance.
