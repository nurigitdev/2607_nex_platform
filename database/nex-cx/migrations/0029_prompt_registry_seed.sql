BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

WITH template AS (
    INSERT INTO cx_prompt_templates (
        service_id,
        purpose,
        name,
        owner_domain,
        status
    )
    VALUES (
        'nex-cx',
        'document_summary',
        'default_document_summary_system',
        'content',
        'ACTIVE'
    )
    ON CONFLICT (service_id, purpose, name)
    DO UPDATE SET status = 'ACTIVE', updated_at = now()
    RETURNING prompt_template_id
),
version AS (
    INSERT INTO cx_prompt_template_versions (
        prompt_template_id,
        version,
        role,
        segment_order,
        content,
        content_sha256,
        model_capability,
        summary_max_chars,
        summary_hard_limit_chars,
        metadata,
        status
    )
    SELECT
        prompt_template_id,
        'v1',
        'system',
        0,
        'Summarize extracted Markdown for retrieval. Keep the summary under {summary_max_chars} characters and never exceed {summary_hard_limit_chars} characters. Preserve concrete entities, dates, and user-visible decisions.',
        encode(digest('Summarize extracted Markdown for retrieval. Keep the summary under {summary_max_chars} characters and never exceed {summary_hard_limit_chars} characters. Preserve concrete entities, dates, and user-visible decisions.', 'sha256'), 'hex'),
        'summary',
        900,
        1000,
        '{"slice":"0029","policy":"summary_1000_0"}'::jsonb,
        'ACTIVE'
    FROM template
    ON CONFLICT (prompt_template_id, version, role, segment_order)
    DO UPDATE SET
        content = EXCLUDED.content,
        content_sha256 = EXCLUDED.content_sha256,
        metadata = EXCLUDED.metadata,
        status = 'ACTIVE'
    RETURNING prompt_template_version_id
)
INSERT INTO cx_prompt_bindings (
    binding_key,
    prompt_template_version_id,
    service_id,
    purpose,
    status
)
SELECT
    'cx.document_summary.default',
    prompt_template_version_id,
    'nex-cx',
    'document_summary',
    'ACTIVE'
FROM version
ON CONFLICT (binding_key)
DO UPDATE SET
    prompt_template_version_id = EXCLUDED.prompt_template_version_id,
    status = 'ACTIVE',
    bound_at = now();

INSERT INTO schema_migrations (version, description)
VALUES ('0029_prompt_registry_seed', 'Seed CX default prompt registry bindings')
ON CONFLICT (version) DO NOTHING;

COMMIT;
