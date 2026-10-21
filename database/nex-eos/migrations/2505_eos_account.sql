BEGIN;

CREATE TABLE IF NOT EXISTS eos_account (
    tenant_id VARCHAR(128) NOT NULL,
    account_id UUID NOT NULL,
    account_code VARCHAR(64) NOT NULL,
    name VARCHAR(256) NOT NULL,
    category VARCHAR(16) NOT NULL,
    account_type VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL,
    effective_from DATE NOT NULL,
    effective_until DATE NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_account PRIMARY KEY (tenant_id, account_id),
    CONSTRAINT ux_eos_account_code UNIQUE (tenant_id, account_code),
    CONSTRAINT ck_eos_account_category CHECK (
        category IN ('ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE')
    ),
    CONSTRAINT ck_eos_account_status CHECK (status IN ('ACTIVE', 'INACTIVE')),
    CONSTRAINT ck_eos_account_period CHECK (
        effective_until IS NULL OR effective_until > effective_from
    ),
    CONSTRAINT ck_eos_account_version CHECK (version > 0)
);

CREATE INDEX IF NOT EXISTS ix_eos_account_effective
    ON eos_account (
        tenant_id,
        status,
        effective_from,
        effective_until
    );

INSERT INTO schema_migrations (version, description)
VALUES ('2505_eos_account', 'NeX-EOS stable Account minimum model')
ON CONFLICT (version) DO NOTHING;

COMMIT;
