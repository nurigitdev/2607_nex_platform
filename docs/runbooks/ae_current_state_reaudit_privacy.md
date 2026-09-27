# AE current-state re-audit privacy runbook

## Scope

This runbook governs the protected `NEX_AE_CURRENT_STATE_POSTGRES_REAUDIT`
execution against `nex_ae_test` and its deterministic Playwright browser probe.

## Data Rules

- Use synthetic tenant, user, interaction, request, and feedback identifiers.
- Never use production prompts, generated output, uploaded content, credentials,
  cookies, session tokens, provider keys, or employee data.
- The database URL and execution errors must be redacted before evidence output.
- Evidence may contain schema object names, counts, booleans, and PASS/FAIL only.
- The domain insert/upsert/select probe must finish with transaction rollback and
  verify that no probe row remains.
- The Playwright result may report the tool, browser, and status only.

## Execution

1. Confirm the URL resolves to the exact service role and test database.
2. Apply the complete versioned SQL migration chain.
3. Inspect migration ledger, core tables, indexes, constraints, and forbidden
   private column names.
4. Run the synthetic domain insert/upsert/select/rollback probe.
5. Launch the deterministic Playwright Chromium readiness probe.
6. Emit metadata-only evidence and verify the database URL is redacted.

## Incident Rule

Use stop-and-escalate if the target is not the exact test database, a probe row
survives rollback, credential material enters output, migration drift appears,
or the actual browser cannot launch. Do not retry against another database.
