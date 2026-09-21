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

CREATE TABLE IF NOT EXISTS cx_vector_indexes (
    vector_index_id UUID PRIMARY KEY,
    index_schema_version TEXT NOT NULL DEFAULT 'cx_vector_index.v1'
        CHECK (index_schema_version = 'cx_vector_index.v1'),
    content_object_id UUID NOT NULL REFERENCES cx_content_objects(content_object_id)
        ON DELETE CASCADE,
    chunk_set_id UUID NOT NULL REFERENCES cx_chunk_sets(chunk_set_id)
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
    chunk_policy_id TEXT NOT NULL CHECK (char_length(chunk_policy_id) <= 160),
    source_markdown_sha256 TEXT NOT NULL
        CHECK (source_markdown_sha256 ~ '^[0-9a-f]{64}$'),
    source_fingerprint TEXT NOT NULL
        CHECK (source_fingerprint ~ '^[0-9a-f]{64}$'),
    source_chunk_count INTEGER NOT NULL CHECK (source_chunk_count >= 0),
    provider_alias TEXT NOT NULL CHECK (char_length(provider_alias) <= 160),
    model_profile_id TEXT NOT NULL CHECK (char_length(model_profile_id) <= 160),
    model_revision TEXT NOT NULL CHECK (char_length(model_revision) <= 160),
    deployment_id TEXT NOT NULL CHECK (char_length(deployment_id) <= 160),
    vector_dimension INTEGER NOT NULL CHECK (vector_dimension > 0),
    profile_fingerprint TEXT NOT NULL
        CHECK (profile_fingerprint ~ '^[0-9a-f]{64}$'),
    status TEXT NOT NULL CHECK (
        status IN ('BUILDING', 'READY', 'STALE', 'REBUILD_REQUIRED', 'FAILED')
    ),
    status_reason TEXT,
    payload_count INTEGER NOT NULL DEFAULT 0 CHECK (payload_count >= 0),
    payload_fingerprint TEXT CHECK (
        payload_fingerprint IS NULL
        OR payload_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    checkpoint_version INTEGER NOT NULL DEFAULT 0 CHECK (checkpoint_version >= 0),
    trace_id TEXT NOT NULL CHECK (trace_id <> '' AND char_length(trace_id) <= 160),
    request_id TEXT NOT NULL CHECK (request_id <> '' AND char_length(request_id) <= 160),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    ready_at TIMESTAMPTZ,
    CONSTRAINT ux_cx_vector_indexes_source_profile UNIQUE (
        content_object_id,
        source_fingerprint,
        profile_fingerprint
    ),
    CONSTRAINT ck_cx_vector_indexes_state CHECK (
        (
            status IN ('BUILDING', 'READY')
            AND status_reason IS NULL
        )
        OR (
            status IN ('STALE', 'REBUILD_REQUIRED', 'FAILED')
            AND status_reason IS NOT NULL
            AND status_reason <> ''
        )
    ),
    CONSTRAINT ck_cx_vector_indexes_ready CHECK (
        (
            status = 'READY'
            AND payload_count = source_chunk_count
            AND payload_fingerprint IS NOT NULL
            AND ready_at IS NOT NULL
        )
        OR (
            status <> 'READY'
            AND ready_at IS NULL
        )
    )
);

CREATE OR REPLACE FUNCTION cx_assert_vector_index_lineage()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    content_owner RECORD;
    source_set RECORD;
BEGIN
    SELECT
        tenant_ref_type,
        tenant_ref_id,
        owner_subject_ref_type,
        owner_subject_ref_id
    INTO STRICT content_owner
    FROM cx_content_objects
    WHERE content_object_id = NEW.content_object_id;

    SELECT
        content_object_id,
        chunk_policy_id,
        source_markdown_sha256,
        chunk_count
    INTO STRICT source_set
    FROM cx_chunk_sets
    WHERE chunk_set_id = NEW.chunk_set_id;

    IF source_set.content_object_id <> NEW.content_object_id
       OR source_set.chunk_policy_id <> NEW.chunk_policy_id
       OR source_set.source_markdown_sha256 <> NEW.source_markdown_sha256
       OR source_set.chunk_count <> NEW.source_chunk_count THEN
        RAISE EXCEPTION 'CX vector index source snapshot does not match chunk set'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.tenant_ref_type <> content_owner.tenant_ref_type
       OR NEW.tenant_ref_id <> content_owner.tenant_ref_id
       OR NEW.owner_subject_ref_type <> content_owner.owner_subject_ref_type
       OR NEW.owner_subject_ref_id <> content_owner.owner_subject_ref_id THEN
        RAISE EXCEPTION 'CX vector index owner does not match content owner'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tr_cx_vector_indexes_lineage ON cx_vector_indexes;
CREATE TRIGGER tr_cx_vector_indexes_lineage
    BEFORE INSERT OR UPDATE OF
        content_object_id,
        chunk_set_id,
        tenant_ref_type,
        tenant_ref_id,
        owner_subject_ref_type,
        owner_subject_ref_id,
        chunk_policy_id,
        source_markdown_sha256,
        source_chunk_count
    ON cx_vector_indexes
    FOR EACH ROW
    EXECUTE FUNCTION cx_assert_vector_index_lineage();

CREATE INDEX IF NOT EXISTS ix_cx_vector_indexes_owner_status
    ON cx_vector_indexes (
        tenant_ref_id,
        owner_subject_ref_id,
        status,
        updated_at DESC
    );

CREATE INDEX IF NOT EXISTS ix_cx_vector_indexes_content_profile
    ON cx_vector_indexes (
        content_object_id,
        profile_fingerprint,
        updated_at DESC
    );

CREATE TABLE IF NOT EXISTS cx_vectors (
    vector_id UUID PRIMARY KEY,
    vector_index_id UUID NOT NULL,
    content_object_id UUID NOT NULL,
    chunk_set_id UUID NOT NULL,
    chunk_id UUID NOT NULL,
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
    embedding_sha256 TEXT NOT NULL CHECK (embedding_sha256 ~ '^[0-9a-f]{64}$'),
    vector_dimension INTEGER NOT NULL CHECK (vector_dimension > 0),
    embedding vector NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ux_cx_vectors_index_chunk UNIQUE (vector_index_id, chunk_id),
    CONSTRAINT ck_cx_vectors_dimension CHECK (
        vector_dims(embedding) = vector_dimension
    )
);

CREATE INDEX IF NOT EXISTS ix_cx_vectors_owner_index
    ON cx_vectors (
        tenant_ref_id,
        owner_subject_ref_id,
        vector_index_id,
        chunk_id
    );

CREATE INDEX IF NOT EXISTS ix_cx_vectors_content
    ON cx_vectors (content_object_id, vector_index_id);

CREATE INDEX IF NOT EXISTS ix_cx_vectors_hnsw_2560_cosine
    ON cx_vectors
    USING hnsw ((embedding::halfvec(2560)) halfvec_cosine_ops)
    WHERE vector_dimension = 2560;

INSERT INTO schema_migrations (version, description)
VALUES (
    '0933_cx_vector_index_persistence',
    'CX vector index manifest and pgvector payload persistence'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
