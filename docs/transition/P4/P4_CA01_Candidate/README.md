# P4-CA01 Candidate Contract Files

These files are the accepted controlled-amendment outputs for the project-neutral IA PROMPT issue.

**Status:** APPROVED / FOCUSED REVALIDATION PASS / P4-CA01 AUTHORITY

The directory name is retained for history. Authority is granted by
`P4_CA01_Project_Neutral_PROMPT_ReFreeze_Addendum_v1.0.md`; the original Frozen
files remain unchanged.

Required validation:

- PROMPT + IA + project_id=null → PASS
- PROMPT + IA + project_id=non-empty → PASS
- CLAIMED_WORKITEM + project_id=null → FAIL
- PA + project_id=null → FAIL
- TenantId missing → FAIL
- Step8 trigger vocabulary unchanged
- E1 Authority/Identity regression PASS
- E2E-01 IA READ regression PASS

The Python candidate enforces the same source/agent/project conditions during
value-object construction. Focused probes SHALL cover both the JSON Schema and
the Python value object so an `Optional[str]` annotation cannot weaken
CLAIMED_WORKITEM or PA rules at runtime.

Acceptance evidence and hashes are recorded in
`P4_CA01_Controlled_Amendment_Manifest_v1.0.csv`. The prior Frozen hash history
is preserved rather than overwritten.
