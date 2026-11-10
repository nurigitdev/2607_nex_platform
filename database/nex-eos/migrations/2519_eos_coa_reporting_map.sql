BEGIN;

CREATE TABLE IF NOT EXISTS eos_coa_reporting_release (
    mapping_release_id UUID PRIMARY KEY,
    jurisdiction VARCHAR(32) NOT NULL,
    taxonomy_name VARCHAR(128) NOT NULL,
    taxonomy_version VARCHAR(64) NOT NULL,
    effective_from DATE NOT NULL,
    effective_until DATE NULL,
    source_reference VARCHAR(512) NOT NULL,
    source_hash VARCHAR(71) NOT NULL,
    approved_proof_ref VARCHAR(71) NOT NULL,
    content_hash VARCHAR(71) NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ NULL,
    CONSTRAINT ux_eos_coa_reporting_release_version
        UNIQUE (jurisdiction, taxonomy_name, taxonomy_version),
    CONSTRAINT ck_eos_coa_reporting_release_period CHECK (
        effective_until IS NULL OR effective_until > effective_from
    ),
    CONSTRAINT ck_eos_coa_reporting_release_hashes CHECK (
        source_hash ~ '^sha256:[0-9a-f]{64}$'
        AND approved_proof_ref ~ '^sha256:[0-9a-f]{64}$'
        AND content_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_coa_reporting_release_status CHECK (
        status IN ('DRAFT', 'PUBLISHED', 'SUPERSEDED')
    ),
    CONSTRAINT ck_eos_coa_reporting_release_published CHECK (
        (status = 'DRAFT' AND published_at IS NULL)
        OR (status IN ('PUBLISHED', 'SUPERSEDED') AND published_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_coa_reporting_release_effective
    ON eos_coa_reporting_release (
        jurisdiction, taxonomy_name, status, effective_from, effective_until
    );

CREATE TABLE IF NOT EXISTS eos_coa_reporting_map (
    mapping_release_id UUID NOT NULL,
    mapping_rule_id UUID NOT NULL,
    entry_id UUID NOT NULL,
    statement_kind VARCHAR(32) NOT NULL,
    mapping_status VARCHAR(32) NOT NULL,
    taxonomy_concept_id VARCHAR(256) NULL,
    context_json JSONB NOT NULL,
    source_row_hash VARCHAR(71) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_coa_reporting_map
        PRIMARY KEY (mapping_release_id, mapping_rule_id),
    CONSTRAINT fk_eos_coa_reporting_map_release
        FOREIGN KEY (mapping_release_id)
        REFERENCES eos_coa_reporting_release (mapping_release_id),
    CONSTRAINT fk_eos_coa_reporting_map_entry
        FOREIGN KEY (entry_id)
        REFERENCES eos_coa_entry (entry_id),
    CONSTRAINT ck_eos_coa_reporting_map_statement CHECK (
        statement_kind IN (
            'BALANCE_SHEET', 'INCOME_STATEMENT', 'CASH_FLOW', 'EQUITY', 'NOTES'
        )
    ),
    CONSTRAINT ck_eos_coa_reporting_map_status CHECK (
        mapping_status IN ('MAPPING_PENDING', 'RESOLVED', 'NOT_APPLICABLE')
    ),
    CONSTRAINT ck_eos_coa_reporting_map_resolution CHECK (
        (mapping_status = 'RESOLVED' AND taxonomy_concept_id IS NOT NULL)
        OR (mapping_status <> 'RESOLVED' AND taxonomy_concept_id IS NULL)
    ),
    CONSTRAINT ck_eos_coa_reporting_map_hash CHECK (
        source_row_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_coa_reporting_map_entry
    ON eos_coa_reporting_map (entry_id, mapping_release_id, statement_kind);

INSERT INTO schema_migrations (version, description)
VALUES (
    '2519_eos_coa_reporting_map',
    'EOS approved reporting taxonomy release and COA mapping foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
