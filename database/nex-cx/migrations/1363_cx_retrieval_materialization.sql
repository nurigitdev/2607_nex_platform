BEGIN;

ALTER TABLE cx_retrieval_packages
    ADD COLUMN IF NOT EXISTS tenant_ref_type TEXT,
    ADD COLUMN IF NOT EXISTS tenant_ref_id TEXT,
    ADD COLUMN IF NOT EXISTS owner_subject_ref_type TEXT,
    ADD COLUMN IF NOT EXISTS owner_subject_ref_id TEXT,
    ADD COLUMN IF NOT EXISTS retrieval_runtime_schema_version TEXT,
    ADD COLUMN IF NOT EXISTS persistence_payload_policy TEXT,
    ADD COLUMN IF NOT EXISTS retrieval_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS permission_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS warnings JSONB NOT NULL DEFAULT '[]'::jsonb;

WITH package_lineage AS (
    SELECT DISTINCT ON (evidence.retrieval_package_id)
           evidence.retrieval_package_id,
           content.tenant_ref_type,
           content.tenant_ref_id,
           content.owner_subject_ref_type,
           content.owner_subject_ref_id
    FROM cx_retrieval_evidence_items AS evidence
    JOIN cx_content_objects AS content
      ON content.content_object_id = evidence.content_object_id
    ORDER BY evidence.retrieval_package_id, evidence.rank
)
UPDATE cx_retrieval_packages AS package
SET tenant_ref_type = lineage.tenant_ref_type,
    tenant_ref_id = lineage.tenant_ref_id,
    owner_subject_ref_type = lineage.owner_subject_ref_type,
    owner_subject_ref_id = lineage.owner_subject_ref_id
FROM package_lineage AS lineage
WHERE package.retrieval_package_id = lineage.retrieval_package_id
  AND package.tenant_ref_id IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_cx_ret_pkg_owner_pair'
    ) THEN
        ALTER TABLE cx_retrieval_packages
            ADD CONSTRAINT ck_cx_ret_pkg_owner_pair CHECK (
                (
                    tenant_ref_type IS NULL
                    AND tenant_ref_id IS NULL
                    AND owner_subject_ref_type IS NULL
                    AND owner_subject_ref_id IS NULL
                )
                OR (
                    tenant_ref_type = 'oa.tenant'
                    AND tenant_ref_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$'
                    AND owner_subject_ref_type = 'oa.user'
                    AND owner_subject_ref_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$'
                )
            );
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_cx_ret_pkg_restore_json'
    ) THEN
        ALTER TABLE cx_retrieval_packages
            ADD CONSTRAINT ck_cx_ret_pkg_restore_json CHECK (
                jsonb_typeof(retrieval_profile) = 'object'
                AND jsonb_typeof(permission_snapshot) = 'object'
                AND jsonb_typeof(warnings) = 'array'
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_cx_ret_pkg_owner_created
    ON cx_retrieval_packages (
        tenant_ref_id,
        owner_subject_ref_id,
        created_at DESC
    )
    WHERE tenant_ref_id IS NOT NULL AND owner_subject_ref_id IS NOT NULL;

INSERT INTO schema_migrations (version, description)
VALUES (
    '1363_cx_retrieval_materialization',
    'CX owner-scoped restart-safe retrieval package materialization metadata'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
