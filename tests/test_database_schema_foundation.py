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


def test_service_worker_heartbeat_foundation_exists_for_every_service_database() -> None:
    for service_id in SERVICE_IDS:
        compact = normalized(
            read_migration_named(service_id, "0112_service_worker_heartbeat_foundation.sql")
        )

        assert "create table if not exists service_worker_heartbeats" in compact
        assert "heartbeat_schema_version text not null default 'worker_heartbeat.v1'" in compact
        assert "check (heartbeat_schema_version = 'worker_heartbeat.v1')" in compact
        assert "status text not null check (status in" in compact
        for status in ("starting", "idle", "busy", "stopping", "stopped", "error"):
            assert f"'{status}'" in compact
        for column in (
            "service_id text not null",
            "worker_id text not null",
            "worker_type text not null",
            "active_job_id text",
            "trace_id text",
            "started_at timestamptz not null",
            "last_seen_at timestamptz not null",
            "metadata jsonb not null default '{}'::jsonb",
            "primary key (service_id, worker_id)",
        ):
            assert column in compact
        assert "constraint ck_service_worker_heartbeats_busy_job check" in compact
        assert "constraint ck_service_worker_heartbeats_last_seen_order check" in compact
        assert "ix_service_worker_heartbeats_service_status" in compact
        assert "ix_service_worker_heartbeats_type_status" in compact
        assert "ix_service_worker_heartbeats_last_seen" in compact
        assert "ix_service_worker_heartbeats_active_job" in compact
        assert "0112_service_worker_heartbeat_foundation" in compact


def test_service_log_entries_foundation_exists_for_every_service_database() -> None:
    for service_id in SERVICE_IDS:
        compact = normalized(
            read_migration_named(service_id, "0137_service_log_entries_foundation.sql")
        )

        assert "create table if not exists service_log_entries" in compact
        assert "service_log_schema_version text not null default 'service_log_entry.v1'" in compact
        assert "check (service_log_schema_version = 'service_log_entry.v1')" in compact
        assert "severity text not null check (severity in" in compact
        for severity in ("debug", "info", "warning", "error", "critical"):
            assert f"'{severity}'" in compact
        for column in (
            "service_id text not null",
            "logger_name text not null check (char_length(logger_name) <= 160)",
            "message text not null check (char_length(message) <= 512)",
            "trace_id text",
            "request_id text",
            "job_id text",
            "subject_type text",
            "subject_id text",
            "attributes jsonb not null default '{}'::jsonb",
            "redacted_attribute_keys jsonb not null default '[]'::jsonb",
            "observed_at timestamptz not null",
        ):
            assert column in compact
        assert "ix_service_log_entries_service_observed" in compact
        assert "ix_service_log_entries_severity_observed" in compact
        assert "ix_service_log_entries_logger_observed" in compact
        assert "ix_service_log_entries_trace" in compact
        assert "ix_service_log_entries_request" in compact
        assert "ix_service_log_entries_job" in compact
        assert "ix_service_log_entries_subject" in compact
        assert "0137_service_log_entries_foundation" in compact


def test_oa_subject_registry_foundation_tracks_stable_tenant_and_user_refs() -> None:
    compact = normalized(
        read_migration_named("nex-oa", "0193_oa_subject_registry_foundation.sql")
    )

    assert "create table if not exists oa_tenants" in compact
    assert "tenant_ref_type text not null default 'oa.tenant'" in compact
    assert "check (tenant_ref_type = 'oa.tenant')" in compact
    assert "status text not null default 'active'" in compact
    assert "check (status in ('active', 'disabled', 'deleted'))" in compact
    assert "metadata jsonb not null default '{}'::jsonb" in compact

    assert "create table if not exists oa_subjects" in compact
    assert "tenant_id text not null references oa_tenants(tenant_id)" in compact
    assert "subject_ref_type text not null default 'oa.user'" in compact
    assert "check (subject_ref_type = 'oa.user')" in compact
    assert "primary key (tenant_id, subject_ref_type, subject_id)" in compact
    assert "ix_oa_tenants_status_updated" in compact
    assert "ix_oa_subjects_tenant_status_updated" in compact
    assert "ix_oa_subjects_subject_ref" in compact
    assert "0193_oa_subject_registry_foundation" in compact
    assert "password" not in compact


def test_oa_tenant_membership_foundation_tracks_roles_and_scopes() -> None:
    compact = normalized(
        read_migration_named("nex-oa", "0242_oa_tenant_membership_foundation.sql")
    )

    assert "create table if not exists oa_tenant_memberships" in compact
    assert "subject_ref_type text not null default 'oa.user'" in compact
    assert "membership_schema_version text not null default 'oa_tenant_membership.v1'" in compact
    assert "status text not null default 'active'" in compact
    assert "check (status in ('active', 'disabled'))" in compact
    assert "roles jsonb not null default '[]'::jsonb" in compact
    assert "scopes jsonb not null default '[]'::jsonb" in compact
    assert "metadata jsonb not null default '{}'::jsonb" in compact
    assert "primary key (tenant_id, subject_ref_type, subject_id)" in compact
    assert "references oa_subjects (tenant_id, subject_ref_type, subject_id)" in compact
    assert "ix_oa_tenant_memberships_status_updated" in compact
    assert "ix_oa_tenant_memberships_subject" in compact
    assert "0242_oa_tenant_membership_foundation" in compact
    assert "password" not in compact
    assert "token" not in compact


def test_oa_user_session_foundation_tracks_browser_safe_sessions() -> None:
    compact = normalized(
        read_migration_named("nex-oa", "0243_oa_user_session_foundation.sql")
    )

    assert "create table if not exists oa_user_sessions" in compact
    assert "session_schema_version text not null default 'oa_user_session.v1'" in compact
    assert "status text not null default 'active'" in compact
    assert "check (status in ('active', 'expired', 'revoked'))" in compact
    assert "issuer text not null default 'nex-oa'" in compact
    assert "audience text not null default 'nex-ae-api'" in compact
    assert "token_use text not null default 'user'" in compact
    assert "scopes jsonb not null default '[]'::jsonb" in compact
    assert "roles jsonb not null default '[]'::jsonb" in compact
    assert "metadata jsonb not null default '{}'::jsonb" in compact
    assert "references oa_tenant_memberships (tenant_id, subject_ref_type, subject_id)" in compact
    assert "ck_oa_user_sessions_time_order" in compact
    assert "ck_oa_user_sessions_revoked_at" in compact
    assert "ix_oa_user_sessions_tenant_status_expires" in compact
    assert "ix_oa_user_sessions_subject_issued" in compact
    assert "0243_oa_user_session_foundation" in compact
    assert "access_token" not in compact
    assert "password" not in compact


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


def test_cx_source_ownership_schema_migration_adds_indexable_oa_subject_refs() -> None:
    migration = normalized(
        read_migration_named(
            "nex-cx",
            "0194_cx_source_ownership_schema_migration.sql",
        )
    )

    for column in (
        "add column if not exists tenant_ref_type text",
        "add column if not exists tenant_ref_id text",
        "add column if not exists owner_subject_ref_type text",
        "add column if not exists owner_subject_ref_id text",
        "add column if not exists uploaded_by_subject_ref_type text",
        "add column if not exists uploaded_by_subject_ref_id text",
    ):
        assert column in migration
    assert "tenant_ref_id = coalesce(tenant_ref_id, tenant_id)" in migration
    assert (
        "owner_subject_ref_id = coalesce(owner_subject_ref_id, owner_user_id)"
        in migration
    )
    assert "uploaded_by_subject_ref_id = coalesce(" in migration
    assert "create or replace function cx_apply_content_object_ownership_refs()" in migration
    assert "create trigger tr_cx_content_objects_apply_ownership_refs" in migration
    assert "alter column tenant_ref_id set not null" in migration
    assert "alter column owner_subject_ref_id set not null" in migration

    assert "ux_cx_content_owner_subject_source_active" in migration
    assert (
        "on cx_content_objects ( tenant_ref_type, tenant_ref_id, "
        "owner_subject_ref_type, owner_subject_ref_id, source_sha256 )"
        in migration
    )
    assert "where lifecycle_status = 'active'" in migration
    assert "idx_cx_content_objects_owner_subject_created" in migration
    assert "idx_cx_content_objects_uploaded_by_subject_created" in migration

    for column in (
        "add column if not exists principal_ref_type text",
        "add column if not exists principal_ref_id text",
        "add column if not exists granted_by_subject_ref_type text",
        "add column if not exists granted_by_subject_ref_id text",
    ):
        assert column in migration
    assert "when 'user' then 'oa.user'" in migration
    assert "when 'group' then 'oa.group'" in migration
    assert "create or replace function cx_apply_acl_subject_refs()" in migration
    assert "create trigger tr_cx_content_acl_entries_apply_subject_refs" in migration
    assert "alter column principal_ref_id set not null" in migration
    assert "ux_cx_content_acl_subject_ref_permission" in migration
    assert "idx_cx_content_acl_principal_ref" in migration
    assert "idx_cx_content_acl_granted_by_subject_ref" in migration
    assert "0194_cx_source_ownership_schema_migration" in migration


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


def test_cx_schema_tracks_retrieval_package_metadata_without_raw_text() -> None:
    compact = normalized(read_migration("nex-cx"))
    retrieval = normalized(
        read_migration_named("nex-cx", "0172_cx_retrieval_package_persistence.sql")
    )

    assert "create table if not exists cx_retrieval_packages" in compact
    assert "create table if not exists cx_retrieval_evidence_items" in compact
    for column in (
        "retrieval_package_schema_version text not null default 'cx_retrieval_context_package.v1'",
        "package_hash text not null check",
        "query_text_sha256 text not null check",
        "query_text_preview text check",
        "query_embedding_provided boolean not null default false",
        "query_embedding_sha256 text check",
        "query_embedding_dimension integer not null default 0",
        "retrieval_policy_id text not null",
        "retrieval_policy_hash text check",
        "permission_snapshot_hash text not null check",
        "source_summary jsonb not null default '{}'::jsonb",
        "score_summary jsonb not null default '{}'::jsonb",
        "evidence_text_sha256 text not null check",
        "evidence_text_preview text not null check",
        "final_score double precision not null default 0",
        "scores jsonb not null default '{}'::jsonb",
        "matched_terms jsonb not null default '[]'::jsonb",
        "permission_result jsonb not null default '{}'::jsonb",
    ):
        assert column in retrieval
    assert "primary key (retrieval_package_id, evidence_id)" in retrieval
    assert "unique (retrieval_package_id, rank)" in retrieval
    assert "ck_cx_retrieval_packages_query_embedding_consistent" in retrieval
    assert "ck_cx_retrieval_packages_evidence_count_status" in retrieval
    assert "idx_cx_retrieval_packages_status_created" in retrieval
    assert "idx_cx_retrieval_packages_trace" in retrieval
    assert "idx_cx_retrieval_evidence_score" in retrieval
    assert "0172_cx_retrieval_package_persistence" in retrieval
    assert "query_text text" not in compact
    assert "evidence_text text" not in compact
    assert "raw_query" not in compact
    assert "raw_evidence" not in compact


def test_cx_schema_tracks_processing_run_metadata_without_raw_payloads() -> None:
    compact = normalized(read_migration("nex-cx"))
    processing = normalized(
        read_migration_named("nex-cx", "0182_cx_processing_run_step_persistence.sql")
    )

    assert "create table if not exists cx_document_processing_runs" in compact
    assert "create table if not exists cx_document_processing_steps" in compact
    for column in (
        "pipeline_schema_version text not null default 'cx_document_processing_pipeline.v1'",
        "document_id uuid not null references cx_content_objects(content_object_id)",
        "status text not null check (status in ('queued', 'running', 'succeeded', 'failed', 'cancelled'))",
        "job_subject_ref jsonb not null default '{}'::jsonb",
        "job_links jsonb not null default '{}'::jsonb",
        "step_total integer not null default 0",
        "step_succeeded integer not null default 0",
        "step_skipped integer not null default 0",
        "step_failed integer not null default 0",
        "output_ref_hash text check",
        "error_detail_sha256 text check",
        "primary key (pipeline_run_id, step_order)",
        "unique (pipeline_run_id, step_id)",
    ):
        assert column in processing
    assert "ck_cx_processing_runs_step_total" in processing
    assert "ck_cx_processing_runs_terminal_completed" in processing
    assert "ck_cx_processing_steps_success_output_ref" in processing
    assert "ck_cx_processing_steps_nonfailed_error_hash" in processing
    assert "idx_cx_processing_runs_document_updated" in processing
    assert "idx_cx_processing_runs_status_updated" in processing
    assert "idx_cx_processing_runs_trace" in processing
    assert "idx_cx_processing_steps_output_ref" in processing
    assert "0182_cx_processing_run_step_persistence" in processing
    assert "source_text" not in processing
    assert "chunk_text" not in processing
    assert "summary_text" not in processing
    assert "embedding_raw_vector" not in processing
    assert "error_detail text" not in compact


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
