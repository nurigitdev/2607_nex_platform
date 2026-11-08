BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_prompt_binding_history (
    binding_change_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    binding_key TEXT NOT NULL,
    old_prompt_template_version_id UUID NOT NULL
        REFERENCES ae_prompt_template_versions(prompt_template_version_id),
    new_prompt_template_version_id UUID NOT NULL
        REFERENCES ae_prompt_template_versions(prompt_template_version_id),
    changed_by TEXT NOT NULL CHECK (char_length(changed_by) BETWEEN 1 AND 200),
    reason TEXT NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 1000),
    correlation_id TEXT NOT NULL
        CHECK (char_length(correlation_id) BETWEEN 1 AND 200),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_ae_prompt_binding_history_change
        CHECK (old_prompt_template_version_id <> new_prompt_template_version_id),
    CONSTRAINT ux_ae_prompt_binding_history_correlation
        UNIQUE (binding_key, correlation_id)
);

CREATE INDEX IF NOT EXISTS idx_ae_prompt_binding_history_key_time
    ON ae_prompt_binding_history (binding_key, changed_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2100_ae_prompt_registry_hardening',
    'Immutable prompt versions and atomic binding history foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
