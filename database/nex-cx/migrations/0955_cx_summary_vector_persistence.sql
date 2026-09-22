BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = 'vector'
    ) THEN
        RAISE EXCEPTION 'pgvector extension must be provisioned by a database administrator'
            USING ERRCODE = '55000';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS cx_summary_vectors (
    summary_vector_id UUID PRIMARY KEY,
    summary_embedding_id UUID NOT NULL UNIQUE
        REFERENCES cx_document_summary_embeddings(summary_embedding_id)
        ON DELETE CASCADE,
    document_summary_id UUID NOT NULL
        REFERENCES cx_document_summaries(document_summary_id)
        ON DELETE CASCADE,
    content_object_id UUID NOT NULL
        REFERENCES cx_content_objects(content_object_id)
        ON DELETE CASCADE,
    tenant_ref_type TEXT NOT NULL DEFAULT 'oa.tenant'
        CHECK (tenant_ref_type = 'oa.tenant'),
    tenant_ref_id TEXT NOT NULL CHECK (
        tenant_ref_id <> '' AND char_length(tenant_ref_id) <= 128
    ),
    owner_subject_ref_type TEXT NOT NULL DEFAULT 'oa.user'
        CHECK (owner_subject_ref_type = 'oa.user'),
    owner_subject_ref_id TEXT NOT NULL CHECK (
        owner_subject_ref_id <> '' AND char_length(owner_subject_ref_id) <= 128
    ),
    summary_text_sha256 TEXT NOT NULL
        CHECK (summary_text_sha256 ~ '^[0-9a-f]{64}$'),
    provider_alias TEXT NOT NULL CHECK (char_length(provider_alias) <= 160),
    model_profile_id TEXT NOT NULL CHECK (char_length(model_profile_id) <= 160),
    model_revision TEXT NOT NULL CHECK (char_length(model_revision) <= 160),
    deployment_id TEXT NOT NULL CHECK (char_length(deployment_id) <= 160),
    profile_fingerprint TEXT NOT NULL
        CHECK (profile_fingerprint ~ '^[0-9a-f]{64}$'),
    embedding_sha256 TEXT NOT NULL
        CHECK (embedding_sha256 ~ '^[0-9a-f]{64}$'),
    vector_dimension INTEGER NOT NULL CHECK (vector_dimension > 0),
    embedding vector NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_cx_summary_vectors_dimension CHECK (
        vector_dims(embedding) = vector_dimension
    )
);

CREATE OR REPLACE FUNCTION cx_assert_summary_vector_lineage()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    embedding_record RECORD;
    summary_record RECORD;
    content_record RECORD;
BEGIN
    SELECT
        document_summary_id,
        provider_alias,
        model_profile_id,
        model_revision,
        deployment_id,
        vector_dimension,
        embedding_sha256,
        status
    INTO STRICT embedding_record
    FROM cx_document_summary_embeddings
    WHERE summary_embedding_id = NEW.summary_embedding_id;

    SELECT content_object_id, summary_text_sha256, status
    INTO STRICT summary_record
    FROM cx_document_summaries
    WHERE document_summary_id = NEW.document_summary_id;

    SELECT
        tenant_ref_type,
        tenant_ref_id,
        owner_subject_ref_type,
        owner_subject_ref_id,
        lifecycle_status
    INTO STRICT content_record
    FROM cx_content_objects
    WHERE content_object_id = NEW.content_object_id;

    IF embedding_record.document_summary_id <> NEW.document_summary_id
       OR summary_record.content_object_id <> NEW.content_object_id
       OR embedding_record.provider_alias <> NEW.provider_alias
       OR embedding_record.model_profile_id <> NEW.model_profile_id
       OR embedding_record.model_revision <> NEW.model_revision
       OR embedding_record.deployment_id <> NEW.deployment_id
       OR embedding_record.vector_dimension <> NEW.vector_dimension
       OR embedding_record.embedding_sha256 <> NEW.embedding_sha256
       OR summary_record.summary_text_sha256 <> NEW.summary_text_sha256
       OR embedding_record.status <> 'READY'
       OR summary_record.status <> 'READY'
       OR content_record.lifecycle_status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'CX summary vector lineage is not current and ready'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.tenant_ref_type <> content_record.tenant_ref_type
       OR NEW.tenant_ref_id <> content_record.tenant_ref_id
       OR NEW.owner_subject_ref_type <> content_record.owner_subject_ref_type
       OR NEW.owner_subject_ref_id <> content_record.owner_subject_ref_id THEN
        RAISE EXCEPTION 'CX summary vector owner does not match content owner'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tr_cx_summary_vectors_lineage ON cx_summary_vectors;
CREATE TRIGGER tr_cx_summary_vectors_lineage
    BEFORE INSERT OR UPDATE OF
        summary_embedding_id,
        document_summary_id,
        content_object_id,
        tenant_ref_type,
        tenant_ref_id,
        owner_subject_ref_type,
        owner_subject_ref_id,
        summary_text_sha256,
        provider_alias,
        model_profile_id,
        model_revision,
        deployment_id,
        embedding_sha256,
        vector_dimension
    ON cx_summary_vectors
    FOR EACH ROW
    EXECUTE FUNCTION cx_assert_summary_vector_lineage();

CREATE INDEX IF NOT EXISTS ix_cx_summary_vectors_owner
    ON cx_summary_vectors (
        tenant_ref_id,
        owner_subject_ref_id,
        content_object_id,
        document_summary_id
    );

CREATE INDEX IF NOT EXISTS ix_cx_summary_vectors_profile
    ON cx_summary_vectors (
        tenant_ref_id,
        owner_subject_ref_id,
        profile_fingerprint,
        created_at DESC
    );

CREATE INDEX IF NOT EXISTS ix_cx_summary_vectors_hnsw_2560_cosine
    ON cx_summary_vectors
    USING hnsw ((embedding::halfvec(2560)) halfvec_cosine_ops)
    WHERE vector_dimension = 2560;

INSERT INTO schema_migrations (version, description)
VALUES (
    '0955_cx_summary_vector_persistence',
    'CX owner-scoped summary pgvector payload and freshness foundation'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
