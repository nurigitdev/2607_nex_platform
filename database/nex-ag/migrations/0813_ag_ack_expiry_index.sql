BEGIN;

CREATE INDEX IF NOT EXISTS idx_ag_ack_state_expiry
    ON ag_op_review_ack_state (state_status, suppressed_until, ack_state_id);

INSERT INTO schema_migrations (version, description)
VALUES ('0813_ag_ack_expiry_index', 'AG acknowledgement expiry candidate index')
ON CONFLICT (version) DO NOTHING;

COMMIT;
