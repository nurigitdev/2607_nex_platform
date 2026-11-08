BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ae_nsl_artifact (
    tenant_id TEXT NOT NULL CHECK (char_length(tenant_id) BETWEEN 1 AND 128),
    artifact_ref TEXT NOT NULL CHECK (char_length(artifact_ref) BETWEEN 1 AND 512),
    artifact_hash TEXT NOT NULL CHECK (artifact_hash ~ '^sha256:[0-9a-f]{64}$'),
    skill_id TEXT NOT NULL CHECK (char_length(skill_id) BETWEEN 1 AND 256),
    skill_version TEXT NOT NULL CHECK (char_length(skill_version) BETWEEN 1 AND 256),
    package_hash TEXT NOT NULL CHECK (package_hash ~ '^sha256:[0-9a-f]{64}$'),
    verified_at TIMESTAMPTZ NOT NULL,
    artifact_json JSONB NOT NULL CHECK (jsonb_typeof(artifact_json) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, artifact_ref),
    CONSTRAINT ux_ae_nsl_artifact_hash UNIQUE (tenant_id, artifact_hash),
    CONSTRAINT ck_ae_nsl_artifact_json CHECK (
        artifact_json ->> 'schema_version' = '1.0'
        AND artifact_json ->> 'artifact_ref' = artifact_ref
        AND artifact_json ->> 'artifact_hash' = artifact_hash
        AND artifact_json ->> 'skill_id' = skill_id
        AND artifact_json ->> 'skill_version' = skill_version
        AND artifact_json ->> 'package_hash' = package_hash
    )
);

CREATE INDEX IF NOT EXISTS idx_ae_nsl_artifact_skill
    ON ae_nsl_artifact (tenant_id, skill_id, skill_version, package_hash);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2201_ae_nsl_artifact',
    'P6 bounded verified NSL Skill artifact persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
