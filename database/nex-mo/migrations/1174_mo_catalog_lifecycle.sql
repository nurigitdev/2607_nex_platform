BEGIN;

CREATE TABLE IF NOT EXISTS mo_model_catalog (
    catalog_id TEXT PRIMARY KEY,
    capability TEXT NOT NULL
        CHECK (capability IN ('embedding', 'reranking', 'generation')),
    model_name TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    runtime_profile TEXT NOT NULL,
    precision TEXT NOT NULL,
    provider_type TEXT NOT NULL,
    response_formats_json TEXT NOT NULL,
    max_input_tokens INTEGER NOT NULL CHECK (max_input_tokens > 0),
    max_output_tokens INTEGER NOT NULL CHECK (max_output_tokens >= 0),
    embedding_dimensions INTEGER CHECK (embedding_dimensions > 0),
    catalog_state TEXT NOT NULL
        CHECK (catalog_state IN ('DRAFT', 'ACTIVE', 'RETIRED')),
    revision INTEGER NOT NULL CHECK (revision > 0),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_mo_model_catalog_runtime UNIQUE (
        capability,
        deployment_id,
        model_revision
    ),
    CONSTRAINT ck_mo_model_catalog_embedding_dims CHECK (
        (capability = 'embedding' AND embedding_dimensions IS NOT NULL)
        OR (capability <> 'embedding' AND embedding_dimensions IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS mo_alias_bindings (
    binding_id TEXT PRIMARY KEY,
    alias TEXT NOT NULL,
    capability TEXT NOT NULL
        CHECK (capability IN ('embedding', 'reranking', 'generation')),
    catalog_id TEXT NOT NULL REFERENCES mo_model_catalog(catalog_id),
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    binding_state TEXT NOT NULL
        CHECK (binding_state IN ('ACTIVE', 'SUPERSEDED', 'ROLLED_BACK')),
    change_reason VARCHAR(500) NOT NULL,
    changed_by TEXT NOT NULL,
    previous_binding_id TEXT REFERENCES mo_alias_bindings(binding_id),
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_mo_alias_binding_revision UNIQUE (
        alias,
        capability,
        binding_revision
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_mo_alias_binding_active
    ON mo_alias_bindings (alias, capability)
    WHERE binding_state = 'ACTIVE';

CREATE INDEX IF NOT EXISTS ix_mo_model_catalog_capability
    ON mo_model_catalog (capability, catalog_state, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_mo_alias_binding_catalog
    ON mo_alias_bindings (catalog_id, created_at DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('1174_mo_catalog_lifecycle', 'MO durable catalog and alias lifecycle')
ON CONFLICT (version) DO NOTHING;

COMMIT;
