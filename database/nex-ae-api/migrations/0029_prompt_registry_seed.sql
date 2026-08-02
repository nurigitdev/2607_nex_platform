BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

WITH template AS (
    INSERT INTO ae_prompt_templates (
        service_id,
        purpose,
        name,
        owner_domain,
        status
    )
    VALUES (
        'nex-ae-api',
        'grounded_chat',
        'default_grounded_chat_system',
        'agent-experience',
        'ACTIVE'
    )
    ON CONFLICT (service_id, purpose, name)
    DO UPDATE SET status = 'ACTIVE', updated_at = now()
    RETURNING prompt_template_id
),
version AS (
    INSERT INTO ae_prompt_template_versions (
        prompt_template_id,
        version,
        role,
        segment_order,
        content,
        content_sha256,
        model_capability,
        metadata,
        status
    )
    SELECT
        prompt_template_id,
        'v1',
        'system',
        0,
        'Answer using only supplied CX evidence. When evidence is insufficient, say that the answer cannot be grounded. Keep citations traceable.',
        encode(digest('Answer using only supplied CX evidence. When evidence is insufficient, say that the answer cannot be grounded. Keep citations traceable.', 'sha256'), 'hex'),
        'generation',
        '{"slice":"0029","retrieval_required":true}'::jsonb,
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
INSERT INTO ae_prompt_bindings (
    binding_key,
    prompt_template_version_id,
    service_id,
    purpose,
    status
)
SELECT
    'ae.grounded_chat.default',
    prompt_template_version_id,
    'nex-ae-api',
    'grounded_chat',
    'ACTIVE'
FROM version
ON CONFLICT (binding_key)
DO UPDATE SET
    prompt_template_version_id = EXCLUDED.prompt_template_version_id,
    status = 'ACTIVE',
    bound_at = now();

INSERT INTO schema_migrations (version, description)
VALUES ('0029_prompt_registry_seed', 'Seed AE default prompt registry bindings')
ON CONFLICT (version) DO NOTHING;

COMMIT;
