BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cx_retrieval_packages (
    retrieval_package_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    retrieval_package_schema_version TEXT NOT NULL DEFAULT 'cx_retrieval_context_package.v1'
        CHECK (retrieval_package_schema_version = 'cx_retrieval_context_package.v1'),
    package_hash TEXT NOT NULL CHECK (package_hash ~ '^[0-9a-f]{64}$'),
    status TEXT NOT NULL CHECK (status IN ('READY', 'LOW_CONFIDENCE', 'NO_ANSWER')),
    trace_id TEXT CHECK (trace_id IS NULL OR trace_id ~ '^[0-9a-f]{32}$'),
    request_id TEXT NOT NULL,
    query_text_sha256 TEXT NOT NULL CHECK (query_text_sha256 ~ '^[0-9a-f]{64}$'),
    query_text_preview TEXT CHECK (query_text_preview IS NULL OR char_length(query_text_preview) <= 240),
    query_embedding_provided BOOLEAN NOT NULL DEFAULT false,
    query_embedding_sha256 TEXT CHECK (query_embedding_sha256 IS NULL OR query_embedding_sha256 ~ '^[0-9a-f]{64}$'),
    query_embedding_dimension INTEGER NOT NULL DEFAULT 0 CHECK (query_embedding_dimension >= 0),
    purpose TEXT NOT NULL CHECK (
        purpose IN (
            'search',
            'grounded_answer',
            'summary',
            'document_generation',
            'confidence_probe'
        )
    ),
    retrieval_policy_id TEXT NOT NULL,
    retrieval_policy_version TEXT,
    retrieval_policy_hash TEXT CHECK (retrieval_policy_hash IS NULL OR retrieval_policy_hash ~ '^[0-9a-f]{64}$'),
    retrieval_policy_source TEXT NOT NULL,
    ranker_mix TEXT NOT NULL,
    rerank_state TEXT NOT NULL CHECK (rerank_state IN ('APPLIED', 'NOT_APPLIED', 'FAILED')),
    permission_snapshot_hash TEXT NOT NULL CHECK (permission_snapshot_hash ~ '^[0-9a-f]{64}$'),
    source_summary JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(source_summary) = 'object'),
    score_summary JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(score_summary) = 'object'),
    warning_count INTEGER NOT NULL DEFAULT 0 CHECK (warning_count >= 0),
    evidence_count INTEGER NOT NULL DEFAULT 0 CHECK (evidence_count >= 0),
    no_answer_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (package_hash),
    CONSTRAINT ck_cx_retrieval_packages_query_embedding_consistent CHECK (
        (
            query_embedding_provided
            AND query_embedding_sha256 IS NOT NULL
            AND query_embedding_dimension > 0
        )
        OR (
            NOT query_embedding_provided
            AND query_embedding_sha256 IS NULL
            AND query_embedding_dimension = 0
        )
    ),
    CONSTRAINT ck_cx_retrieval_packages_evidence_count_status CHECK (
        (status = 'NO_ANSWER' AND evidence_count = 0)
        OR (status <> 'NO_ANSWER' AND evidence_count > 0)
    )
);

CREATE TABLE IF NOT EXISTS cx_retrieval_evidence_items (
    retrieval_package_id UUID NOT NULL REFERENCES cx_retrieval_packages(retrieval_package_id) ON DELETE CASCADE,
    evidence_id UUID NOT NULL,
    rank INTEGER NOT NULL CHECK (rank > 0),
    content_object_id UUID NOT NULL REFERENCES cx_content_objects(content_object_id),
    content_version_id TEXT NOT NULL,
    chunk_id UUID NOT NULL REFERENCES cx_chunks(chunk_id),
    chunk_policy_id TEXT NOT NULL,
    source_anchor JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(source_anchor) = 'object'),
    citation_label TEXT NOT NULL,
    evidence_text_sha256 TEXT NOT NULL CHECK (evidence_text_sha256 ~ '^[0-9a-f]{64}$'),
    evidence_text_preview TEXT NOT NULL CHECK (char_length(evidence_text_preview) <= 240),
    final_score DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (final_score >= 0),
    scores JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(scores) = 'object'),
    matched_terms JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(matched_terms) = 'array'),
    permission_result JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(permission_result) = 'object'),
    neighbor_context JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(neighbor_context) = 'array'),
    quality_flags JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(quality_flags) = 'array'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (retrieval_package_id, evidence_id),
    UNIQUE (retrieval_package_id, rank)
);

CREATE INDEX IF NOT EXISTS idx_cx_retrieval_packages_status_created
    ON cx_retrieval_packages (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_cx_retrieval_packages_trace
    ON cx_retrieval_packages (trace_id);

CREATE INDEX IF NOT EXISTS idx_cx_retrieval_packages_request
    ON cx_retrieval_packages (request_id);

CREATE INDEX IF NOT EXISTS idx_cx_retrieval_packages_policy_created
    ON cx_retrieval_packages (retrieval_policy_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_cx_retrieval_evidence_content
    ON cx_retrieval_evidence_items (content_object_id, rank);

CREATE INDEX IF NOT EXISTS idx_cx_retrieval_evidence_chunk
    ON cx_retrieval_evidence_items (chunk_id);

CREATE INDEX IF NOT EXISTS idx_cx_retrieval_evidence_score
    ON cx_retrieval_evidence_items (retrieval_package_id, final_score DESC);

INSERT INTO schema_migrations (version, description)
VALUES ('0172_cx_retrieval_package_persistence', 'CX retrieval package and evidence metadata persistence')
ON CONFLICT (version) DO NOTHING;

COMMIT;
