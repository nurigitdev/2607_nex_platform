BEGIN;

CREATE TABLE IF NOT EXISTS eos_approved_document_consumption (
    tenant_id VARCHAR(128) NOT NULL,
    consumption_id UUID NOT NULL,
    company_id UUID NOT NULL,
    envelope_id UUID NOT NULL,
    source_document_line_ref VARCHAR(256) NOT NULL,
    supplier_invoice_ref VARCHAR(256) NULL,
    payroll_period_ref VARCHAR(256) NULL,
    source_identity_hash VARCHAR(71) NOT NULL,
    candidate_revision_id UUID NOT NULL,
    posted_journal_id UUID NOT NULL,
    consumed_amount NUMERIC(20, 4) NOT NULL,
    currency CHAR(3) NOT NULL,
    state VARCHAR(16) NOT NULL,
    operation_id UUID NOT NULL,
    posted_at TIMESTAMPTZ NOT NULL,
    reversed_journal_ref UUID NULL,
    consumption_hash VARCHAR(71) NOT NULL,
    CONSTRAINT pk_eos_doc_cons PRIMARY KEY (tenant_id, consumption_id),
    CONSTRAINT ux_eos_doc_cons_candidate UNIQUE (
        tenant_id, company_id, candidate_revision_id
    ),
    CONSTRAINT ux_eos_doc_cons_source UNIQUE (
        tenant_id, company_id, envelope_id, source_identity_hash
    ),
    CONSTRAINT fk_eos_doc_cons_envelope FOREIGN KEY (
        tenant_id, envelope_id
    ) REFERENCES eos_approved_document_envelope (tenant_id, envelope_id),
    CONSTRAINT fk_eos_doc_cons_operation FOREIGN KEY (
        tenant_id, operation_id
    ) REFERENCES eos_business_operation (tenant_id, business_operation_id),
    CONSTRAINT ck_eos_doc_cons_amount CHECK (consumed_amount > 0),
    CONSTRAINT ck_eos_doc_cons_currency CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT ck_eos_doc_cons_state CHECK (state = 'COMMITTED'),
    CONSTRAINT ck_eos_doc_cons_hashes CHECK (
        source_identity_hash ~ '^sha256:[0-9a-f]{64}$'
        AND consumption_hash ~ '^sha256:[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS ix_eos_doc_cons_envelope
    ON eos_approved_document_consumption (
        tenant_id, envelope_id, state
    );

CREATE OR REPLACE FUNCTION eos_guard_doc_cons_immutable()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'ApprovedDocumentConsumption is immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_eos_doc_cons_immutable
BEFORE UPDATE OR DELETE ON eos_approved_document_consumption
FOR EACH ROW EXECUTE FUNCTION eos_guard_doc_cons_immutable();

INSERT INTO schema_migrations (version, description)
VALUES (
    '2529_eos_approved_document_consumption',
    'Transaction-bound approved document allowance consumption guard'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
