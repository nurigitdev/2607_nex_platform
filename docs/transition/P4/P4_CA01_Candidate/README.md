# P4-CA01 Candidate Contract Files

These files are candidate controlled-amendment outputs for the project-neutral IA PROMPT issue.

They are NOT yet Frozen authority until the controlled-amendment review and focused revalidation pass.

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

After acceptance, update amendment manifests/hashes and issue a re-freeze addendum without silently overwriting the prior Frozen hash history.
