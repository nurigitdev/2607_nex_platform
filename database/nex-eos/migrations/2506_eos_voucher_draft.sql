BEGIN;

CREATE TABLE IF NOT EXISTS eos_voucher_draft (
    tenant_id VARCHAR(128) NOT NULL,
    voucher_id UUID NOT NULL,
    project_id UUID NOT NULL,
    voucher_type VARCHAR(32) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    transaction_date DATE NOT NULL,
    description VARCHAR(2000) NOT NULL,
    requester_ref_type VARCHAR(64) NOT NULL,
    requester_id VARCHAR(128) NOT NULL,
    source_ref_type VARCHAR(64) NOT NULL,
    source_id VARCHAR(128) NOT NULL,
    state VARCHAR(16) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_eos_voucher_draft PRIMARY KEY (tenant_id, voucher_id),
    CONSTRAINT fk_eos_voucher_project
        FOREIGN KEY (tenant_id, project_id)
        REFERENCES eos_project (tenant_id, project_id),
    CONSTRAINT ck_eos_voucher_state CHECK (state = 'DRAFT'),
    CONSTRAINT ck_eos_voucher_version CHECK (version > 0)
);

CREATE TABLE IF NOT EXISTS eos_voucher_draft_line (
    tenant_id VARCHAR(128) NOT NULL,
    voucher_id UUID NOT NULL,
    line_no INTEGER NOT NULL,
    account_id UUID NOT NULL,
    signed_amount NUMERIC(20, 2) NOT NULL,
    economic_category VARCHAR(32) NOT NULL,
    description VARCHAR(1000) NULL,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    CONSTRAINT pk_eos_voucher_line
        PRIMARY KEY (tenant_id, voucher_id, line_no),
    CONSTRAINT fk_eos_voucher_line_draft
        FOREIGN KEY (tenant_id, voucher_id)
        REFERENCES eos_voucher_draft (tenant_id, voucher_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_eos_voucher_line_account
        FOREIGN KEY (tenant_id, account_id)
        REFERENCES eos_account (tenant_id, account_id),
    CONSTRAINT ux_eos_voucher_line_account
        UNIQUE (tenant_id, voucher_id, account_id, line_no),
    CONSTRAINT ck_eos_voucher_line_no CHECK (line_no > 0),
    CONSTRAINT ck_eos_voucher_line_amount CHECK (signed_amount <> 0)
);

INSERT INTO schema_migrations (version, description)
VALUES ('2506_eos_voucher_draft', 'NeX-EOS VoucherDraft aggregate foundation')
ON CONFLICT (version) DO NOTHING;

COMMIT;
