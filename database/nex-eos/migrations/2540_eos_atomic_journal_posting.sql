BEGIN;

ALTER TABLE eos_voucher_candidate
    DROP CONSTRAINT ck_eos_candidate_s3_state;

ALTER TABLE eos_voucher_candidate
    ADD CONSTRAINT ck_eos_candidate_s3_state CHECK (
        state IN (
            'DRAFT',
            'READY_FOR_REVIEW',
            'RETURNED_FOR_CORRECTION',
            'POSTED'
        )
    );

ALTER TABLE eos_outbox
    DROP CONSTRAINT ck_eos_outbox_event_type;

ALTER TABLE eos_outbox
    ADD CONSTRAINT ck_eos_outbox_event_type CHECK (
        event_type ~ '^([A-Z][A-Z0-9_.]{0,127}|[A-Z][A-Z0-9_.]{0,123}v[0-9]{1,3})$'
    );

ALTER TABLE eos_approved_document_consumption
    ADD CONSTRAINT fk_eos_doc_cons_candidate_revision FOREIGN KEY (
        tenant_id, candidate_revision_id
    ) REFERENCES eos_voucher_candidate_revision (
        tenant_id, revision_id
    ) ON DELETE RESTRICT,
    ADD CONSTRAINT fk_eos_doc_cons_journal FOREIGN KEY (
        tenant_id, company_id, posted_journal_id
    ) REFERENCES eos_journal_header (
        tenant_id, company_id, journal_id
    ) DEFERRABLE INITIALLY DEFERRED;

INSERT INTO schema_migrations (version, description)
VALUES (
    '2540_eos_atomic_journal_posting',
    'Atomic Posting candidate state and immutable source lineage constraints'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
