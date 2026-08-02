from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE_ROOT = ROOT / "database"


def read_migration(service: str) -> str:
    migrations = sorted((DATABASE_ROOT / service / "migrations").glob("*.sql"))
    assert migrations, f"missing migrations for {service}"
    return "\n".join(path.read_text(encoding="utf-8") for path in migrations)


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


def test_cx_schema_scopes_duplicate_uploads_to_active_owner_documents() -> None:
    compact = normalized(read_migration("nex-cx"))

    assert "create table if not exists cx_source_blobs" in compact
    assert "create table if not exists cx_content_objects" in compact
    assert "unique (source_sha256)" in compact
    assert "ux_cx_content_owner_source_active" in compact
    assert "on cx_content_objects (tenant_id, owner_user_id, source_sha256)" in compact
    assert "where lifecycle_status = 'active'" in compact


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
