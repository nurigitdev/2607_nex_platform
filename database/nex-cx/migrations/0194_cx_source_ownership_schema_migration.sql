BEGIN;

ALTER TABLE cx_content_objects
    ADD COLUMN IF NOT EXISTS tenant_ref_type TEXT,
    ADD COLUMN IF NOT EXISTS tenant_ref_id TEXT,
    ADD COLUMN IF NOT EXISTS owner_subject_ref_type TEXT,
    ADD COLUMN IF NOT EXISTS owner_subject_ref_id TEXT,
    ADD COLUMN IF NOT EXISTS uploaded_by_subject_ref_type TEXT,
    ADD COLUMN IF NOT EXISTS uploaded_by_subject_ref_id TEXT;

UPDATE cx_content_objects
SET tenant_ref_type = COALESCE(tenant_ref_type, 'oa.tenant'),
    tenant_ref_id = COALESCE(tenant_ref_id, tenant_id),
    owner_subject_ref_type = COALESCE(owner_subject_ref_type, 'oa.user'),
    owner_subject_ref_id = COALESCE(owner_subject_ref_id, owner_user_id),
    uploaded_by_subject_ref_type = COALESCE(uploaded_by_subject_ref_type, 'oa.user'),
    uploaded_by_subject_ref_id = COALESCE(
        uploaded_by_subject_ref_id,
        owner_subject_ref_id,
        owner_user_id
    );

CREATE OR REPLACE FUNCTION cx_apply_content_object_ownership_refs()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.tenant_ref_type IS NULL THEN
        NEW.tenant_ref_type := 'oa.tenant';
    END IF;
    IF NEW.tenant_ref_id IS NULL THEN
        NEW.tenant_ref_id := NEW.tenant_id;
    END IF;
    IF NEW.owner_subject_ref_type IS NULL THEN
        NEW.owner_subject_ref_type := 'oa.user';
    END IF;
    IF NEW.owner_subject_ref_id IS NULL THEN
        NEW.owner_subject_ref_id := NEW.owner_user_id;
    END IF;
    IF NEW.uploaded_by_subject_ref_type IS NULL THEN
        NEW.uploaded_by_subject_ref_type := 'oa.user';
    END IF;
    IF NEW.uploaded_by_subject_ref_id IS NULL THEN
        NEW.uploaded_by_subject_ref_id := NEW.owner_subject_ref_id;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tr_cx_content_objects_apply_ownership_refs
    ON cx_content_objects;

CREATE TRIGGER tr_cx_content_objects_apply_ownership_refs
    BEFORE INSERT OR UPDATE ON cx_content_objects
    FOR EACH ROW
    EXECUTE FUNCTION cx_apply_content_object_ownership_refs();

ALTER TABLE cx_content_objects
    ALTER COLUMN tenant_ref_type SET NOT NULL,
    ALTER COLUMN tenant_ref_id SET NOT NULL,
    ALTER COLUMN owner_subject_ref_type SET NOT NULL,
    ALTER COLUMN owner_subject_ref_id SET NOT NULL,
    ALTER COLUMN uploaded_by_subject_ref_type SET NOT NULL,
    ALTER COLUMN uploaded_by_subject_ref_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_cx_content_objects_tenant_ref_type'
    ) THEN
        ALTER TABLE cx_content_objects
            ADD CONSTRAINT ck_cx_content_objects_tenant_ref_type
            CHECK (tenant_ref_type = 'oa.tenant');
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_cx_content_objects_owner_subject_ref_type'
    ) THEN
        ALTER TABLE cx_content_objects
            ADD CONSTRAINT ck_cx_content_objects_owner_subject_ref_type
            CHECK (owner_subject_ref_type = 'oa.user');
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_cx_content_objects_uploaded_by_subject_ref_type'
    ) THEN
        ALTER TABLE cx_content_objects
            ADD CONSTRAINT ck_cx_content_objects_uploaded_by_subject_ref_type
            CHECK (uploaded_by_subject_ref_type = 'oa.user');
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_cx_content_objects_subject_ref_ids'
    ) THEN
        ALTER TABLE cx_content_objects
            ADD CONSTRAINT ck_cx_content_objects_subject_ref_ids
            CHECK (
                tenant_ref_id <> ''
                AND owner_subject_ref_id <> ''
                AND uploaded_by_subject_ref_id <> ''
                AND char_length(tenant_ref_id) <= 128
                AND char_length(owner_subject_ref_id) <= 128
                AND char_length(uploaded_by_subject_ref_id) <= 128
            );
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS ux_cx_content_owner_subject_source_active
    ON cx_content_objects (
        tenant_ref_type,
        tenant_ref_id,
        owner_subject_ref_type,
        owner_subject_ref_id,
        source_sha256
    )
    WHERE lifecycle_status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_cx_content_objects_owner_subject_created
    ON cx_content_objects (
        tenant_ref_type,
        tenant_ref_id,
        owner_subject_ref_type,
        owner_subject_ref_id,
        created_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_cx_content_objects_uploaded_by_subject_created
    ON cx_content_objects (
        uploaded_by_subject_ref_type,
        uploaded_by_subject_ref_id,
        created_at DESC
    );

ALTER TABLE cx_content_acl_entries
    ADD COLUMN IF NOT EXISTS principal_ref_type TEXT,
    ADD COLUMN IF NOT EXISTS principal_ref_id TEXT,
    ADD COLUMN IF NOT EXISTS granted_by_subject_ref_type TEXT,
    ADD COLUMN IF NOT EXISTS granted_by_subject_ref_id TEXT;

UPDATE cx_content_acl_entries
SET principal_ref_type = COALESCE(
        principal_ref_type,
        CASE principal_type
            WHEN 'user' THEN 'oa.user'
            WHEN 'group' THEN 'oa.group'
            WHEN 'service' THEN 'service'
            ELSE principal_type
        END
    ),
    principal_ref_id = COALESCE(principal_ref_id, principal_id),
    granted_by_subject_ref_type = CASE
        WHEN granted_by_user_id IS NULL THEN granted_by_subject_ref_type
        ELSE COALESCE(granted_by_subject_ref_type, 'oa.user')
    END,
    granted_by_subject_ref_id = COALESCE(granted_by_subject_ref_id, granted_by_user_id);

CREATE OR REPLACE FUNCTION cx_apply_acl_subject_refs()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.principal_ref_type IS NULL THEN
        NEW.principal_ref_type := CASE NEW.principal_type
            WHEN 'user' THEN 'oa.user'
            WHEN 'group' THEN 'oa.group'
            WHEN 'service' THEN 'service'
            ELSE NEW.principal_type
        END;
    END IF;
    IF NEW.principal_ref_id IS NULL THEN
        NEW.principal_ref_id := NEW.principal_id;
    END IF;
    IF NEW.granted_by_user_id IS NOT NULL
       AND NEW.granted_by_subject_ref_type IS NULL THEN
        NEW.granted_by_subject_ref_type := 'oa.user';
    END IF;
    IF NEW.granted_by_subject_ref_id IS NULL THEN
        NEW.granted_by_subject_ref_id := NEW.granted_by_user_id;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tr_cx_content_acl_entries_apply_subject_refs
    ON cx_content_acl_entries;

CREATE TRIGGER tr_cx_content_acl_entries_apply_subject_refs
    BEFORE INSERT OR UPDATE ON cx_content_acl_entries
    FOR EACH ROW
    EXECUTE FUNCTION cx_apply_acl_subject_refs();

ALTER TABLE cx_content_acl_entries
    ALTER COLUMN principal_ref_type SET NOT NULL,
    ALTER COLUMN principal_ref_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_cx_content_acl_entries_principal_ref'
    ) THEN
        ALTER TABLE cx_content_acl_entries
            ADD CONSTRAINT ck_cx_content_acl_entries_principal_ref
            CHECK (
                principal_ref_type IN ('oa.user', 'oa.group', 'service')
                AND principal_ref_id <> ''
                AND char_length(principal_ref_id) <= 128
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_cx_content_acl_entries_granted_by_ref'
    ) THEN
        ALTER TABLE cx_content_acl_entries
            ADD CONSTRAINT ck_cx_content_acl_entries_granted_by_ref
            CHECK (
                (
                    granted_by_subject_ref_type IS NULL
                    AND granted_by_subject_ref_id IS NULL
                )
                OR (
                    granted_by_subject_ref_type = 'oa.user'
                    AND granted_by_subject_ref_id <> ''
                    AND char_length(granted_by_subject_ref_id) <= 128
                )
            );
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS ux_cx_content_acl_subject_ref_permission
    ON cx_content_acl_entries (
        content_object_id,
        principal_ref_type,
        principal_ref_id,
        permission
    );

CREATE INDEX IF NOT EXISTS idx_cx_content_acl_principal_ref
    ON cx_content_acl_entries (principal_ref_type, principal_ref_id, permission);

CREATE INDEX IF NOT EXISTS idx_cx_content_acl_granted_by_subject_ref
    ON cx_content_acl_entries (
        granted_by_subject_ref_type,
        granted_by_subject_ref_id,
        created_at DESC
    )
    WHERE granted_by_subject_ref_id IS NOT NULL;

INSERT INTO schema_migrations (version, description)
VALUES ('0194_cx_source_ownership_schema_migration', 'CX source ownership OA subject reference schema migration')
ON CONFLICT (version) DO NOTHING;

COMMIT;
