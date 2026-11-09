BEGIN;

CREATE TABLE IF NOT EXISTS eos_account_catalog_release (
    tenant_id VARCHAR(128) NOT NULL,
    release_id UUID NOT NULL,
    source_reference VARCHAR(512) NOT NULL,
    source_version VARCHAR(128) NOT NULL,
    source_hash VARCHAR(71) NOT NULL,
    effective_from DATE NOT NULL,
    published_by VARCHAR(128) NOT NULL,
    approved_proof_ref VARCHAR(71) NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_account_catalog_release
        PRIMARY KEY (tenant_id, release_id),
    CONSTRAINT ux_eos_account_catalog_source
        UNIQUE (tenant_id, source_reference, source_version),
    CONSTRAINT ck_eos_account_catalog_hashes CHECK (
        source_hash ~ '^sha256:[0-9a-f]{64}$'
        AND approved_proof_ref ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_account_catalog_status CHECK (
        status IN ('DRAFT', 'PUBLISHED', 'SUPERSEDED')
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_account_catalog_effective
    ON eos_account_catalog_release (tenant_id, status, effective_from);

CREATE TABLE IF NOT EXISTS eos_posting_rule_release (
    tenant_id VARCHAR(128) NOT NULL,
    posting_rule_id UUID NOT NULL,
    company_id UUID NOT NULL,
    catalog_release_id UUID NOT NULL,
    rule_code VARCHAR(128) NOT NULL,
    rule_version INTEGER NOT NULL,
    rule_hash VARCHAR(71) NOT NULL,
    effective_date DATE NOT NULL,
    account_mapping_hash VARCHAR(71) NOT NULL,
    approved_proof_ref VARCHAR(71) NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_posting_rule_release
        PRIMARY KEY (tenant_id, posting_rule_id),
    CONSTRAINT fk_eos_posting_rule_company
        FOREIGN KEY (tenant_id, company_id)
        REFERENCES eos_legal_entity (tenant_id, company_id),
    CONSTRAINT fk_eos_posting_rule_catalog
        FOREIGN KEY (tenant_id, catalog_release_id)
        REFERENCES eos_account_catalog_release (tenant_id, release_id),
    CONSTRAINT ux_eos_posting_rule_version
        UNIQUE (tenant_id, company_id, rule_code, rule_version),
    CONSTRAINT ck_eos_posting_rule_hashes CHECK (
        rule_hash ~ '^sha256:[0-9a-f]{64}$'
        AND account_mapping_hash ~ '^sha256:[0-9a-f]{64}$'
        AND approved_proof_ref ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_posting_rule_version CHECK (rule_version > 0),
    CONSTRAINT ck_eos_posting_rule_status CHECK (
        status IN ('DRAFT', 'PUBLISHED', 'SUPERSEDED')
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_posting_rule_effective
    ON eos_posting_rule_release (
        tenant_id, company_id, status, effective_date
    );

CREATE TABLE IF NOT EXISTS eos_company_account_policy (
    tenant_id VARCHAR(128) NOT NULL,
    policy_id UUID NOT NULL,
    company_id UUID NOT NULL,
    account_id UUID NOT NULL,
    catalog_release_id UUID NOT NULL,
    posting_rule_id UUID NOT NULL,
    parent_account_id UUID NULL,
    is_postable_leaf BOOLEAN NOT NULL,
    is_monetary BOOLEAN NOT NULL,
    statement_line_ref VARCHAR(128) NOT NULL,
    allowed_currencies JSONB NOT NULL,
    valid_from DATE NOT NULL,
    valid_until DATE NULL,
    rule_revision INTEGER NOT NULL,
    approved_proof_ref VARCHAR(71) NOT NULL,
    state VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_company_account_policy
        PRIMARY KEY (tenant_id, policy_id),
    CONSTRAINT fk_eos_company_account_company
        FOREIGN KEY (tenant_id, company_id)
        REFERENCES eos_legal_entity (tenant_id, company_id),
    CONSTRAINT fk_eos_company_account_account
        FOREIGN KEY (tenant_id, account_id)
        REFERENCES eos_account (tenant_id, account_id),
    CONSTRAINT fk_eos_company_account_catalog
        FOREIGN KEY (tenant_id, catalog_release_id)
        REFERENCES eos_account_catalog_release (tenant_id, release_id),
    CONSTRAINT fk_eos_company_account_rule
        FOREIGN KEY (tenant_id, posting_rule_id)
        REFERENCES eos_posting_rule_release (tenant_id, posting_rule_id),
    CONSTRAINT fk_eos_company_account_parent
        FOREIGN KEY (tenant_id, parent_account_id)
        REFERENCES eos_account (tenant_id, account_id),
    CONSTRAINT ux_eos_company_account_release
        UNIQUE (tenant_id, company_id, account_id, catalog_release_id),
    CONSTRAINT ck_eos_company_account_currencies CHECK (
        jsonb_typeof(allowed_currencies) = 'array'
        AND jsonb_array_length(allowed_currencies) > 0
    ),
    CONSTRAINT ck_eos_company_account_period CHECK (
        valid_until IS NULL OR valid_until > valid_from
    ),
    CONSTRAINT ck_eos_company_account_revision CHECK (rule_revision > 0),
    CONSTRAINT ck_eos_company_account_proof CHECK (
        approved_proof_ref ~ '^sha256:[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_eos_company_account_state CHECK (
        state IN ('APPROVED', 'REVOKED')
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_company_account_effective
    ON eos_company_account_policy (
        tenant_id, company_id, state, valid_from, valid_until
    );

CREATE OR REPLACE FUNCTION eos_reject_company_account_overlap()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.state = 'APPROVED' AND EXISTS (
        SELECT 1
        FROM eos_company_account_policy existing
        WHERE existing.tenant_id = NEW.tenant_id
          AND existing.company_id = NEW.company_id
          AND existing.account_id = NEW.account_id
          AND existing.policy_id <> NEW.policy_id
          AND existing.state = 'APPROVED'
          AND (
              existing.valid_until IS NULL
              OR existing.valid_until > NEW.valid_from
          )
          AND (
              NEW.valid_until IS NULL
              OR existing.valid_from < NEW.valid_until
          )
    ) THEN
        RAISE EXCEPTION 'overlapping CompanyAccountPolicy'
            USING ERRCODE = '23505';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_eos_company_account_overlap
    ON eos_company_account_policy;

CREATE TRIGGER trg_eos_company_account_overlap
BEFORE INSERT OR UPDATE OF company_id, account_id, valid_from, valid_until, state
ON eos_company_account_policy
FOR EACH ROW
EXECUTE FUNCTION eos_reject_company_account_overlap();

-- S1-03 owns runtime activation for this shared, immutable migration boundary.
CREATE TABLE IF NOT EXISTS eos_accounting_period (
    tenant_id VARCHAR(128) NOT NULL,
    company_id UUID NOT NULL,
    period_id UUID NOT NULL,
    fiscal_year INTEGER NOT NULL,
    period_no INTEGER NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    state VARCHAR(16) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    close_proof_ref VARCHAR(71) NULL,
    closed_at TIMESTAMPTZ NULL,
    ledger_cutoff_watermark VARCHAR(128) NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_accounting_period
        PRIMARY KEY (tenant_id, company_id, period_id),
    CONSTRAINT fk_eos_accounting_period_company
        FOREIGN KEY (tenant_id, company_id)
        REFERENCES eos_legal_entity (tenant_id, company_id),
    CONSTRAINT ux_eos_accounting_period_number
        UNIQUE (tenant_id, company_id, fiscal_year, period_no),
    CONSTRAINT ck_eos_accounting_period_dates CHECK (end_date >= start_date),
    CONSTRAINT ck_eos_accounting_period_state CHECK (
        state IN ('OPEN', 'CLOSING', 'CLOSED')
    ),
    CONSTRAINT ck_eos_accounting_period_number CHECK (
        fiscal_year BETWEEN 1900 AND 9999 AND period_no BETWEEN 1 AND 99
    ),
    CONSTRAINT ck_eos_accounting_period_version CHECK (version > 0),
    CONSTRAINT ck_eos_accounting_period_close CHECK (
        close_proof_ref IS NULL
        OR close_proof_ref ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_accounting_period_effective
    ON eos_accounting_period (
        tenant_id, company_id, state, start_date, end_date
    );

CREATE OR REPLACE FUNCTION eos_reject_accounting_period_overlap()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM eos_accounting_period existing
        WHERE existing.tenant_id = NEW.tenant_id
          AND existing.company_id = NEW.company_id
          AND existing.period_id <> NEW.period_id
          AND existing.end_date >= NEW.start_date
          AND existing.start_date <= NEW.end_date
    ) THEN
        RAISE EXCEPTION 'overlapping AccountingPeriod'
            USING ERRCODE = '23505';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_eos_accounting_period_overlap
    ON eos_accounting_period;

CREATE TRIGGER trg_eos_accounting_period_overlap
BEFORE INSERT OR UPDATE OF company_id, start_date, end_date
ON eos_accounting_period
FOR EACH ROW
EXECUTE FUNCTION eos_reject_accounting_period_overlap();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2517_eos_account_catalog_accounting_period',
    'EOS approved account catalog, company policy, PostingRule, and S1-03 period schema foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
