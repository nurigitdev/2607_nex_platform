BEGIN;

ALTER TABLE eos_approval_proof
    ADD CONSTRAINT fk_eos_approval_proof_final_decision
    FOREIGN KEY (tenant_id, final_wc_decision_id)
    REFERENCES eos_approval_decision (tenant_id, wc_decision_id)
    ON DELETE RESTRICT;

INSERT INTO schema_migrations (version, description)
VALUES (
    '2512_eos_approval_proof_decision_fk',
    'Bind final approval proof to the exact tenant-qualified EOS decision'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
