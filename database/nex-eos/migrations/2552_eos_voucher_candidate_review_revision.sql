BEGIN;

ALTER TABLE eos_voucher_candidate_revision
    ADD COLUMN IF NOT EXISTS recognition_date DATE NULL;

UPDATE eos_voucher_candidate_revision AS revision
SET recognition_date = candidate.recognition_date
FROM eos_voucher_candidate AS candidate
WHERE revision.tenant_id = candidate.tenant_id
  AND revision.candidate_id = candidate.candidate_id
  AND revision.recognition_date IS NULL;

ALTER TABLE eos_voucher_candidate_revision
    ALTER COLUMN recognition_date SET NOT NULL;

CREATE OR REPLACE FUNCTION eos_guard_candidate_identity()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'VoucherCandidate cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF (to_jsonb(NEW) - ARRAY[
        'state', 'current_revision_no', 'version', 'recognition_date', 'updated_at'
    ]) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY[
        'state', 'current_revision_no', 'version', 'recognition_date', 'updated_at'
    ]) THEN
        RAISE EXCEPTION 'VoucherCandidate identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

INSERT INTO schema_migrations (version, description)
VALUES (
    '2552_eos_voucher_candidate_review_revision',
    'Immutable pre-submission VoucherCandidate recognition-date revisions'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
