BEGIN;

ALTER TABLE ae_external_event_inbox
    DROP CONSTRAINT IF EXISTS ck_ae_external_event_type,
    DROP CONSTRAINT IF EXISTS ck_ae_external_event_shape,
    DROP CONSTRAINT IF EXISTS ck_ae_external_event_family;

ALTER TABLE ae_external_event_inbox
    ADD CONSTRAINT ck_ae_external_event_type CHECK (
        event_type IN (
            'WORK_RESULT_SUBMITTED',
            'NSL_APPROVAL_DECIDED',
            'PROPOSAL_REVIEW_SUBMITTED',
            'BUSINESS_APPROVAL_CHANGED',
            'VOUCHER_REVIEW_SUBMITTED',
            'ACCOUNTING_APPROVAL_CHANGED'
        )
    ),
    ADD CONSTRAINT ck_ae_external_event_family CHECK (
        (event_type = 'WORK_RESULT_SUBMITTED' AND event_family = 'WORK_RESULT')
        OR (event_type = 'NSL_APPROVAL_DECIDED' AND event_family = 'NSL_APPROVAL')
        OR (
            event_type IN (
                'PROPOSAL_REVIEW_SUBMITTED',
                'BUSINESS_APPROVAL_CHANGED',
                'VOUCHER_REVIEW_SUBMITTED',
                'ACCOUNTING_APPROVAL_CHANGED'
            )
            AND event_family = 'PRODUCT_PREPARATION'
        )
    ),
    ADD CONSTRAINT ck_ae_external_event_shape CHECK (
        (
            event_type = 'WORK_RESULT_SUBMITTED'
            AND result_id IS NOT NULL
            AND approval_request_id IS NULL
            AND approval_work_item_ref IS NULL
            AND approval_evidence_ref IS NULL
            AND evidence_integrity IS NULL
            AND nsl_execution_id IS NULL
            AND business_operation_id IS NULL
        )
        OR (
            event_type = 'NSL_APPROVAL_DECIDED'
            AND result_id IS NULL
            AND result_contract_ref IS NULL
            AND approval_request_id IS NOT NULL
            AND char_length(approval_request_id) BETWEEN 1 AND 256
            AND external_ref = approval_request_id
            AND approval_work_item_ref IS NOT NULL
            AND char_length(approval_work_item_ref) BETWEEN 1 AND 128
            AND approval_evidence_ref IS NOT NULL
            AND char_length(approval_evidence_ref) BETWEEN 1 AND 512
            AND evidence_integrity ~ '^sha256:[0-9a-f]{64}$'
            AND nsl_execution_id IS NOT NULL
            AND char_length(nsl_execution_id) BETWEEN 1 AND 256
            AND business_operation_id IS NOT NULL
            AND char_length(business_operation_id) BETWEEN 1 AND 256
        )
        OR (
            event_type IN (
                'PROPOSAL_REVIEW_SUBMITTED',
                'BUSINESS_APPROVAL_CHANGED',
                'VOUCHER_REVIEW_SUBMITTED',
                'ACCOUNTING_APPROVAL_CHANGED'
            )
            AND result_id IS NULL
            AND result_contract_ref IS NULL
            AND approval_request_id IS NULL
            AND approval_work_item_ref IS NULL
            AND approval_evidence_ref IS NULL
            AND evidence_integrity IS NULL
            AND nsl_execution_id IS NULL
            AND business_operation_id IS NULL
            AND jsonb_typeof(event_payload) = 'object'
        )
    );

CREATE OR REPLACE FUNCTION ae_fill_event_family_projection()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.event_family IS NULL THEN
        NEW.event_family := CASE NEW.event_type
            WHEN 'WORK_RESULT_SUBMITTED' THEN 'WORK_RESULT'
            WHEN 'NSL_APPROVAL_DECIDED' THEN 'NSL_APPROVAL'
            WHEN 'PROPOSAL_REVIEW_SUBMITTED' THEN 'PRODUCT_PREPARATION'
            WHEN 'BUSINESS_APPROVAL_CHANGED' THEN 'PRODUCT_PREPARATION'
            WHEN 'VOUCHER_REVIEW_SUBMITTED' THEN 'PRODUCT_PREPARATION'
            WHEN 'ACCOUNTING_APPROVAL_CHANGED' THEN 'PRODUCT_PREPARATION'
            ELSE NULL
        END;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

ALTER TABLE ae_product_prep_wait_binding
    DROP CONSTRAINT IF EXISTS ae_product_prep_wait_binding_expected_event_type_check,
    DROP CONSTRAINT IF EXISTS ae_product_prep_wait_binding_authority_kind_check,
    DROP CONSTRAINT IF EXISTS ck_ae_product_prep_wait_authority;

ALTER TABLE ae_product_prep_wait_binding
    ADD CONSTRAINT ae_product_prep_wait_binding_expected_event_type_check CHECK (
        expected_event_type IN (
            'PROPOSAL_REVIEW_SUBMITTED',
            'BUSINESS_APPROVAL_CHANGED',
            'VOUCHER_REVIEW_SUBMITTED',
            'ACCOUNTING_APPROVAL_CHANGED'
        )
    ),
    ADD CONSTRAINT ae_product_prep_wait_binding_authority_kind_check CHECK (
        authority_kind IN (
            'REQUESTER_PROPOSAL_REVIEW',
            'BUSINESS_FORMAL',
            'REQUESTER_VOUCHER_REVIEW',
            'ACCOUNTING_REVIEW'
        )
    ),
    ADD CONSTRAINT ck_ae_product_prep_wait_authority CHECK (
        (authority_kind = 'REQUESTER_PROPOSAL_REVIEW'
            AND expected_event_type = 'PROPOSAL_REVIEW_SUBMITTED')
        OR (authority_kind = 'BUSINESS_FORMAL'
            AND expected_event_type = 'BUSINESS_APPROVAL_CHANGED')
        OR (authority_kind = 'REQUESTER_VOUCHER_REVIEW'
            AND expected_event_type = 'VOUCHER_REVIEW_SUBMITTED')
        OR (authority_kind = 'ACCOUNTING_REVIEW'
            AND expected_event_type = 'ACCOUNTING_APPROVAL_CHANGED')
    );

ALTER TABLE ae_product_prep_event_binding
    DROP CONSTRAINT IF EXISTS ae_product_prep_event_binding_authority_kind_check;

ALTER TABLE ae_product_prep_event_binding
    ADD CONSTRAINT ae_product_prep_event_binding_authority_kind_check CHECK (
        authority_kind IN (
            'REQUESTER_PROPOSAL_REVIEW',
            'BUSINESS_FORMAL',
            'REQUESTER_VOUCHER_REVIEW',
            'ACCOUNTING_REVIEW'
        )
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2518_ae_product_requester_review_resume',
    'Requester proposal and voucher review resume events on generalized Product waits'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
