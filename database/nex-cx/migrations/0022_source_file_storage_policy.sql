BEGIN;

DO $$
BEGIN
    IF to_regclass('public.cx_source_blobs') IS NOT NULL
       AND to_regclass('public.cx_source_files') IS NULL THEN
        ALTER TABLE cx_source_blobs RENAME TO cx_source_files;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'cx_source_files'
          AND column_name = 'source_blob_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'cx_source_files'
          AND column_name = 'source_file_id'
    ) THEN
        ALTER TABLE cx_source_files RENAME COLUMN source_blob_id TO source_file_id;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'cx_content_objects'
          AND column_name = 'source_blob_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'cx_content_objects'
          AND column_name = 'source_file_id'
    ) THEN
        ALTER TABLE cx_content_objects RENAME COLUMN source_blob_id TO source_file_id;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'cx_extraction_artifacts'
          AND column_name = 'source_blob_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'cx_extraction_artifacts'
          AND column_name = 'source_file_id'
    ) THEN
        ALTER TABLE cx_extraction_artifacts RENAME COLUMN source_blob_id TO source_file_id;
    END IF;
END $$;

ALTER TABLE cx_source_files
    ADD COLUMN IF NOT EXISTS storage_backend TEXT NOT NULL DEFAULT 'local_filesystem',
    ADD COLUMN IF NOT EXISTS storage_key TEXT,
    ADD COLUMN IF NOT EXISTS stored_filename TEXT,
    ADD COLUMN IF NOT EXISTS stored_extension TEXT,
    ADD COLUMN IF NOT EXISTS checksum_verified_at TIMESTAMPTZ;

UPDATE cx_source_files
SET stored_extension = COALESCE(
        lower(substring(storage_uri from '\.[A-Za-z0-9][A-Za-z0-9._-]{0,31}$')),
        ''
    )
WHERE stored_extension IS NULL;

UPDATE cx_source_files
SET stored_filename = source_file_id::text || stored_extension
WHERE stored_filename IS NULL;

UPDATE cx_source_files
SET storage_key = to_char(created_at AT TIME ZONE 'UTC', 'YYYYMMDD')
    || '/' || substr(source_sha256, 1, 2)
    || '/' || substr(source_sha256, 3, 2)
    || '/' || stored_filename
WHERE storage_key IS NULL;

ALTER TABLE cx_source_files
    ALTER COLUMN storage_key SET NOT NULL,
    ALTER COLUMN stored_filename SET NOT NULL,
    ALTER COLUMN stored_extension SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_cx_source_files_storage_backend'
    ) THEN
        ALTER TABLE cx_source_files
            ADD CONSTRAINT ck_cx_source_files_storage_backend
            CHECK (storage_backend IN ('local_filesystem', 's3', 'minio', 'gcs', 'azure_blob'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_cx_source_files_storage_key_safe'
    ) THEN
        ALTER TABLE cx_source_files
            ADD CONSTRAINT ck_cx_source_files_storage_key_safe
            CHECK (storage_key <> '' AND storage_key !~ '(^/|(^|/)\.\.($|/))');
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_cx_source_files_local_key_shape'
    ) THEN
        ALTER TABLE cx_source_files
            ADD CONSTRAINT ck_cx_source_files_local_key_shape
            CHECK (
                storage_backend <> 'local_filesystem'
                OR storage_key ~ '^[0-9]{8}/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f-]+(\.[A-Za-z0-9][A-Za-z0-9._-]{0,31})?$'
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_cx_source_files_stored_filename'
    ) THEN
        ALTER TABLE cx_source_files
            ADD CONSTRAINT ck_cx_source_files_stored_filename
            CHECK (stored_filename <> '' AND stored_filename !~ '[/\\]');
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_cx_source_files_stored_extension'
    ) THEN
        ALTER TABLE cx_source_files
            ADD CONSTRAINT ck_cx_source_files_stored_extension
            CHECK (stored_extension ~ '^(|\.[A-Za-z0-9][A-Za-z0-9._-]{0,31})$');
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS ux_cx_source_files_storage_backend_key
    ON cx_source_files (storage_backend, storage_key);

INSERT INTO schema_migrations (version, description)
VALUES ('0022_source_file_storage_policy', 'Rename CX source blobs to source files and add local storage key policy')
ON CONFLICT (version) DO NOTHING;

COMMIT;
