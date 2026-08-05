from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE_ROOT = ROOT / "database"
SERVICE_IDS = ("nex-oa", "nex-ag", "nex-ae-api", "nex-cx", "nex-mo")


def read_migration(service: str) -> str:
    migrations = sorted((DATABASE_ROOT / service / "migrations").glob("*.sql"))
    assert migrations, f"missing migrations for {service}"
    return "\n".join(path.read_text(encoding="utf-8") for path in migrations)


def read_migration_named(service: str, name: str) -> str:
    path = DATABASE_ROOT / service / "migrations" / name
    assert path.exists(), f"missing migration {path}"
    return path.read_text(encoding="utf-8")


def normalized(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.lower()).strip()


def test_database_migrations_are_transactional_and_secret_free() -> None:
    for path in sorted(DATABASE_ROOT.glob("*/migrations/*.sql")):
        sql = path.read_text(encoding="utf-8")
        compact = normalized(sql)
        assert compact.startswith("begin;")
        assert compact.endswith("commit;")
        assert "schema_migrations" in compact
        assert re.search(r"nuri\d+", compact) is None


def test_service_job_queue_foundation_exists_for_every_service_database() -> None:
    for service_id in SERVICE_IDS:
        compact = normalized(
            read_migration_named(service_id, "0083_service_job_queue_foundation.sql")
        )

        assert "create table if not exists service_jobs" in compact
        assert "job_schema_version text not null default 'common_job.v1'" in compact
        assert "check (job_schema_version = 'common_job.v1')" in compact
        assert "status text not null check (status in" in compact
        for status in ("queued", "running", "succeeded", "failed", "cancelled"):
            assert f"'{status}'" in compact
        for column in (
            "trace_id text not null",
            "request_id text not null",
            "subject_type text not null",
            "subject_id text not null",
            "idempotency_key text not null",
            "links jsonb not null default '{}'::jsonb",
            "payload jsonb not null default '{}'::jsonb",
            "error jsonb",
            "available_at timestamptz not null default now()",
            "locked_by text",
        ):
            assert column in compact
        assert "constraint ck_service_jobs_attempts check (attempt_count <= max_attempts)" in compact
        assert "constraint ux_service_jobs_idempotency unique (job_type, idempotency_key)" in compact
        assert "ix_service_jobs_status_available" in compact
        assert "ix_service_jobs_type_status" in compact
        assert "ix_service_jobs_trace" in compact
        assert "ix_service_jobs_subject" in compact
        assert "0083_service_job_queue_foundation" in compact


def test_service_operational_event_foundation_exists_for_every_service_database() -> None:
    for service_id in SERVICE_IDS:
        compact = normalized(
            read_migration_named(service_id, "0085_service_operational_events_foundation.sql")
        )

        assert "create table if not exists service_operational_events" in compact
        assert "event_schema_version text not null default 'operational_event.v1'" in compact
        assert "check (event_schema_version = 'operational_event.v1')" in compact
        assert "severity text not null check (severity in" in compact
        for severity in ("debug", "info", "warning", "error", "critical"):
            assert f"'{severity}'" in compact
        for column in (
            "service_id text not null",
            "event_type text not null",
            "trace_id text",
            "request_id text",
            "subject_type text",
            "subject_id text",
            "message text not null check (char_length(message) <= 512)",
            "details jsonb not null default '{}'::jsonb",
        ):
            assert column in compact
        assert "ix_service_operational_events_service_created" in compact
        assert "ix_service_operational_events_severity_created" in compact
        assert "ix_service_operational_events_trace" in compact
        assert "ix_service_operational_events_type" in compact
        assert "0085_service_operational_events_foundation" in compact


def test_cx_schema_scopes_duplicate_uploads_to_active_owner_documents() -> None:
    compact = normalized(read_migration("nex-cx"))
    storage_policy = normalized(
        read_migration_named("nex-cx", "0022_source_file_storage_policy.sql")
    )

    assert "cx_source_files" in compact
    assert "alter table cx_source_blobs rename to cx_source_files" in storage_policy
    assert "rename column source_blob_id to source_file_id" in storage_policy
    assert "create table if not exists cx_content_objects" in compact
    assert "unique (source_sha256)" in compact
    assert "ux_cx_content_owner_source_active" in compact
    assert "on cx_content_objects (tenant_id, owner_user_id, source_sha256)" in compact
    assert "where lifecycle_status = 'active'" in compact
    assert "bytea" not in compact


def test_cx_source_files_use_local_storage_key_policy() -> None:
    storage_policy = normalized(
        read_migration_named("nex-cx", "0022_source_file_storage_policy.sql")
    )

    assert "storage_backend text not null default 'local_filesystem'" in storage_policy
    assert "storage_key text" in storage_policy
    assert "stored_filename text" in storage_policy
    assert "stored_extension text" in storage_policy
    assert "checksum_verified_at timestamptz" in storage_policy
    assert "ck_cx_source_files_storage_backend" in storage_policy
    assert "ck_cx_source_files_storage_key_safe" in storage_policy
    assert "ck_cx_source_files_local_key_shape" in storage_policy
    assert "^[0-9]{8}/[0-9a-f]{2}/[0-9a-f]{2}/" in storage_policy
    assert "ux_cx_source_files_storage_backend_key" in storage_policy


def test_cx_schema_tracks_markdown_summary_and_summary_embedding_lineage() -> None:
    compact = normalized(read_migration("nex-cx"))

    for table in (
        "cx_extraction_artifacts",
        "cx_chunk_sets",
        "cx_chunks",
        "cx_chunk_embeddings",
        "cx_document_summaries",
        "cx_document_summary_embeddings",
    ):
        assert f"create table if not exists {table}" in compact

    assert "summary_chunk_policy_id text not null default 'summary_1000_0'" in compact
    assert "summary_max_chars integer not null default 900" in compact
    assert "summary_hard_limit_chars integer not null default 1000" in compact
    assert "check (summary_char_count <= summary_hard_limit_chars)" in compact
    assert "summary_hard_limit_chars > 0 and summary_hard_limit_chars <= 1000" in compact
    assert "embedding_sha256" in compact
    assert "vector_dimension integer not null check (vector_dimension > 0)" in compact


def test_prompt_registry_is_service_local_and_versioned() -> None:
    cx = normalized(read_migration("nex-cx"))
    ae = normalized(read_migration("nex-ae-api"))

    for compact, service_id, prefix in (
        (cx, "nex-cx", "cx"),
        (ae, "nex-ae-api", "ae"),
    ):
        assert f"create table if not exists {prefix}_prompt_templates" in compact
        assert f"create table if not exists {prefix}_prompt_template_versions" in compact
        assert f"create table if not exists {prefix}_prompt_bindings" in compact
        assert f"create table if not exists {prefix}_prompt_render_events" in compact
        assert f"service_id text not null default '{service_id}'" in compact
        assert "content_sha256 text not null" in compact
        assert "rendered_prompt_hash text not null" in compact
        assert "raw_prompt" not in compact
        assert "raw_user_message" not in compact


def test_prompt_registry_seed_migrations_define_default_bindings() -> None:
    cx_seed = normalized(read_migration_named("nex-cx", "0029_prompt_registry_seed.sql"))
    ae_seed = normalized(read_migration_named("nex-ae-api", "0029_prompt_registry_seed.sql"))

    assert "cx.document_summary.default" in cx_seed
    assert "default_document_summary_system" in cx_seed
    assert "summary_1000_0" in cx_seed
    assert "summary_max_chars" in cx_seed
    assert "ae.grounded_chat.default" in ae_seed
    assert "default_grounded_chat_system" in ae_seed
    assert "retrieval_required" in ae_seed
    assert "raw_prompt" not in cx_seed
    assert "raw_prompt" not in ae_seed


def test_ae_schema_supports_prompt_analytics_and_recommendations_without_raw_prompt() -> None:
    compact = normalized(read_migration("nex-ae-api"))

    for table in (
        "ae_chat_interactions",
        "ae_prompt_events",
        "ae_prompt_intent_classifications",
        "ae_user_task_profiles",
        "ae_automation_recommendations",
        "ae_recommendation_feedback",
    ):
        assert f"create table if not exists {table}" in compact

    assert "prompt_hash text not null" in compact
    assert "prompt_preview text not null check (char_length(prompt_preview) <= 240)" in compact
    assert "dominant_task_categories jsonb not null default '[]'::jsonb" in compact
    assert "recommendation_type text not null" in compact
    assert "raw_prompt" not in compact
    assert "raw_user_message" not in compact
