BEGIN;

ALTER TABLE eos_document_signoff_context
    ADD COLUMN IF NOT EXISTS allowed_project_codes JSONB NOT NULL
        DEFAULT '[]'::jsonb;

ALTER TABLE eos_approved_document_envelope
    ADD COLUMN IF NOT EXISTS allowed_project_codes JSONB NOT NULL
        DEFAULT '[]'::jsonb;

ALTER TABLE eos_document_signoff_context
    ADD CONSTRAINT ck_eos_doc_signoff_project_codes CHECK (
        jsonb_typeof(allowed_project_codes) = 'array'
    );

ALTER TABLE eos_approved_document_envelope
    ADD CONSTRAINT ck_eos_approved_doc_project_codes CHECK (
        jsonb_typeof(allowed_project_codes) = 'array'
        AND (
            jsonb_array_length(allowed_project_codes) = 0
            OR jsonb_array_length(allowed_project_codes)
                = jsonb_array_length(allowed_project_ids)
        )
    );

INSERT INTO schema_migrations (version, description)
VALUES (
    '2533_eos_mandatory_project_attribution',
    'Project registration-code lineage for MyBee document and accounting boundaries'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
